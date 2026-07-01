#!/usr/bin/env python3
"""Tests for the marketplace validator (stdlib unittest).

Focuses on the read-only contract check added by slice s5: a command whose
frontmatter/prose marks it read-only must NOT grant `Edit` in its `allowed-tools`.
The check is best-effort keyword detection (it does not sandbox anything); these
tests pin its semantics — it FAILS a read-only command that lists `Edit`, PASSES
one that does not, leaves non-read-only commands free to grant `Edit`, and does
not false-positive when `Edit` merely appears in a read-only command's *prose*.

`scripts/validate_marketplace.py` does NOT lint scripts/*.py (and CI only runs the
validator itself), so this file is the sole automated guard on the validator's
behaviour. Standard library only.

Usage:
    python3 scripts/test_validate_marketplace.py
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent))

import validate_marketplace as vm  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------
# Fixture builders
# --------------------------------------------------------------------------

def write_plugin(root: Path, command_md: str) -> None:
    """Lay down a minimal but structurally-valid marketplace + plugin so the
    validator reaches validate_frontmatter_files for the single command we plant."""
    plugin_dir = root / "plugins" / "demo"
    (plugin_dir / ".claude-plugin").mkdir(parents=True)
    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "demo", "version": "0.0.1"}) + "\n"
    )
    cmds = plugin_dir / "commands"
    cmds.mkdir()
    (cmds / "thecmd.md").write_text(command_md)

    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({
            "name": "demo-market",
            "owner": {"name": "tester"},
            "plugins": [{"name": "demo", "source": "./plugins/demo"}],
        }) + "\n"
    )


def run_on_command(command_md: str):
    """Validate a repo containing exactly one command file; return (ok, errors)."""
    with TemporaryDirectory() as td:
        root = Path(td)
        write_plugin(root, command_md)
        v = vm.Validator(root)
        ok = v.run()
        return ok, v.errors


def cmd(*, description: str, allowed_tools: list[str], body: str = "") -> str:
    """Build a command .md with frontmatter + optional prose body."""
    tools = ", ".join(f'"{t}"' for t in allowed_tools)
    return (
        "---\n"
        f"description: \"{description}\"\n"
        f"allowed-tools: [{tools}]\n"
        "---\n\n"
        f"# A command\n\n{body}\n"
    )


# --------------------------------------------------------------------------
# Frontmatter-value fixtures (for the YAML colon-space heuristic, slice s7)
#
# These reuse write_plugin's marketplace+plugin layout but generalize it to the
# agent and skill kinds and let a test supply a `description:` line VERBATIM, so
# we can plant any quoting/colon variant the heuristic must accept or reject.
# --------------------------------------------------------------------------

def write_frontmatter_plugin(root: Path, kind: str, frontmatter: str) -> None:
    """Lay down a minimal valid marketplace + plugin carrying one frontmatter file
    of `kind` ('command' | 'agent' | 'skill') so the validator reaches
    validate_frontmatter_files for it. Mirrors write_plugin but covers the
    agents/*.md and skills/<name>/SKILL.md locations too."""
    plugin_dir = root / "plugins" / "demo"
    (plugin_dir / ".claude-plugin").mkdir(parents=True)
    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "demo", "version": "0.0.1"}) + "\n"
    )

    if kind == "command":
        target = plugin_dir / "commands" / "thecmd.md"
    elif kind == "agent":
        target = plugin_dir / "agents" / "theagent.md"
    elif kind == "skill":
        target = plugin_dir / "skills" / "theskill" / "SKILL.md"
    else:  # pragma: no cover - guards against a test typo
        raise ValueError(f"unknown frontmatter kind: {kind}")
    target.parent.mkdir(parents=True)
    target.write_text(frontmatter)

    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({
            "name": "demo-market",
            "owner": {"name": "tester"},
            "plugins": [{"name": "demo", "source": "./plugins/demo"}],
        }) + "\n"
    )


def run_on_frontmatter(kind: str, frontmatter: str):
    """Validate a repo whose single `kind` file carries `frontmatter`; return
    (ok, errors)."""
    with TemporaryDirectory() as td:
        root = Path(td)
        write_frontmatter_plugin(root, kind, frontmatter)
        v = vm.Validator(root)
        ok = v.run()
        return ok, v.errors


def command_fm(description_line: str, *, allowed_tools: str = '["Read"]') -> str:
    """A command .md whose `description` line is supplied VERBATIM, plus a valid
    allowed-tools line (commands require only `description`)."""
    return (
        "---\n"
        f"{description_line}\n"
        f"allowed-tools: {allowed_tools}\n"
        "---\n\n# A command\n"
    )


def agent_fm(description_line: str) -> str:
    """An agent .md (requires name + description) with a verbatim description line."""
    return "---\nname: theagent\n" + description_line + "\n---\n\n# An agent\n"


def skill_fm(description_line: str) -> str:
    """A SKILL.md (requires name matching its dir 'theskill' + description) with a
    verbatim description line."""
    return "---\nname: theskill\n" + description_line + "\n---\n\n# A skill\n"


# --------------------------------------------------------------------------
# Marketplace/plugin structural fixtures (for the error-path coverage added by
# slice s3). These generalize write_plugin to let a test supply arbitrary
# marketplace.json / plugin.json content and choose whether to lay down the
# plugin directory at all, so every validation-failure arm can be driven from a
# real input rather than by calling an internal method. Everything is written
# under a caller-provided TemporaryDirectory root; nothing touches the checkout.
# --------------------------------------------------------------------------

def run_on_root(build) -> tuple:
    """Run the validator against a fresh tmp root that `build(root)` populates.
    Returns (ok, errors). The root is asserted to live under the system temp dir
    so a mis-authored fixture fails loudly instead of mutating the live checkout."""
    with TemporaryDirectory() as td:
        root = Path(td)
        assert str(root).startswith(tempfile.gettempdir()), (
            f"fixture root {root} escaped the temp dir"
        )
        build(root)
        v = vm.Validator(root)
        return v.run(), v.errors


def write_marketplace(root: Path, marketplace) -> None:
    """Write .claude-plugin/marketplace.json. `marketplace` may be a dict (dumped
    as JSON) or a raw str (written verbatim, e.g. to plant malformed JSON)."""
    (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    body = marketplace if isinstance(marketplace, str) else json.dumps(marketplace)
    (root / ".claude-plugin" / "marketplace.json").write_text(body + "\n")


def write_plugin_dir(root: Path, source: str, plugin_json) -> Path:
    """Lay down a plugin directory at `root/source` carrying plugin.json.
    `plugin_json` may be a dict (dumped) or a raw str (verbatim, for malformed
    JSON). Returns the plugin directory path."""
    plugin_dir = root / source
    (plugin_dir / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    body = plugin_json if isinstance(plugin_json, str) else json.dumps(plugin_json)
    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(body + "\n")
    return plugin_dir


def single_entry_marketplace(entry, *, metadata=None) -> dict:
    """A minimal valid marketplace shell carrying exactly one plugins[] entry."""
    m = {"name": "demo-market", "owner": {"name": "tester"}, "plugins": [entry]}
    if metadata is not None:
        m["metadata"] = metadata
    return m


# --------------------------------------------------------------------------
# Read-only contract: read-only commands must not grant Edit
# --------------------------------------------------------------------------

class ReadOnlyContractTest(unittest.TestCase):
    def test_readonly_command_listing_edit_fails(self):
        ok, errors = run_on_command(cmd(
            description="A read-only inspector that mutates nothing.",
            allowed_tools=["Bash", "Read", "Edit"],
        ))
        self.assertFalse(ok, "read-only command granting Edit must fail validation")
        self.assertTrue(
            any("Edit" in e and "thecmd.md" in e for e in errors),
            f"error should name the command and Edit; got: {errors}",
        )

    def test_readonly_command_without_edit_passes(self):
        ok, errors = run_on_command(cmd(
            description="A read-only inspector.",
            allowed_tools=["Bash", "Glob", "Grep", "Read"],
        ))
        self.assertTrue(ok, f"read-only command without Edit should pass; got: {errors}")

    def test_non_readonly_command_may_grant_edit(self):
        # No read-only marker anywhere -> Edit is legitimate (cf. quality-gate.md).
        ok, errors = run_on_command(cmd(
            description="Mutates config and applies refactors.",
            allowed_tools=["Bash", "Read", "Edit", "Write"],
            body="This command edits files freely.",
        ))
        self.assertTrue(ok, f"non-read-only command may grant Edit; got: {errors}")

    def test_edit_in_prose_only_does_not_false_positive(self):
        # Real peer-review.md prose literally says its allowed-tools "excludes Edit".
        # The Edit-membership check must read the frontmatter value, NOT the prose.
        ok, errors = run_on_command(cmd(
            description="A read-only loop; never edits anything.",
            allowed_tools=["Bash", "Read", "Task", "Write"],
            body="This command is read-only and its `allowed-tools` excludes `Edit`.",
        ))
        self.assertTrue(
            ok,
            f"Edit appearing only in prose must not trip the check; got: {errors}",
        )

    def test_edit_token_is_matched_exactly_not_substring(self):
        # A future tool whose name merely contains "Edit" must not trip the gate.
        ok, errors = run_on_command(cmd(
            description="A read-only inspector.",
            allowed_tools=["Bash", "Read", "MultiEdit"],
        ))
        self.assertTrue(
            ok,
            f"'MultiEdit' must not be treated as 'Edit'; got: {errors}",
        )


# --------------------------------------------------------------------------
# Frontmatter YAML colon-space heuristic (slice s7)
#
# read_frontmatter() was a regex key-PRESENCE parser: it captured `key: value`
# and never asked whether the value was something real YAML rejects. An UNQUOTED
# top-level scalar containing ': ' (colon-space) is read by YAML as a nested
# mapping and rejected in scalar position — exactly the construct that passed the
# local gate but FAILED CI's authoritative `claude plugin validate`. These tests
# pin the targeted heuristic that closes that class: an unquoted value containing
# ': ' is flagged (naming file + key); a properly quoted value is safe even when
# it contains ': '; a colon-WITHOUT-space (e.g. a URL) is never falsely flagged.
# This is a heuristic, NOT a YAML parser — CI remains the authoritative gate.
# --------------------------------------------------------------------------

class FrontmatterColonSpaceTest(unittest.TestCase):
    def test_unquoted_colon_space_description_fails_command(self):
        ok, errors = run_on_frontmatter("command", command_fm(
            "description: Do this thing: then that other thing"
        ))
        self.assertFalse(ok, "unquoted colon-space description must fail validation")
        self.assertTrue(
            any("description" in e and "thecmd.md" in e and "': '" in e
                for e in errors),
            f"error should name the file + key and cite ': '; got: {errors}",
        )

    def test_quoted_colon_space_description_passes_double(self):
        ok, errors = run_on_frontmatter("command", command_fm(
            'description: "Do this thing: then that other thing"'
        ))
        self.assertTrue(
            ok,
            f"double-quoted value containing ': ' must pass; got: {errors}",
        )

    def test_quoted_colon_space_description_passes_single(self):
        ok, errors = run_on_frontmatter("command", command_fm(
            "description: 'Do this thing: then that other thing'"
        ))
        self.assertTrue(
            ok,
            f"single-quoted value containing ': ' must pass; got: {errors}",
        )

    def test_quoted_value_with_trailing_spaces_passes(self):
        # The regex consumes leading whitespace; the check must trailing-strip so
        # extra spaces after the closing quote do not break the quote detection.
        ok, errors = run_on_frontmatter("command", command_fm(
            'description:    "Do this: then that"   '
        ))
        self.assertTrue(
            ok,
            f"quoted value with surrounding spaces must pass; got: {errors}",
        )

    def test_quoted_value_with_trailing_cr_passes(self):
        # A CRLF-checked-out file leaves a trailing \r after the closing quote;
        # a naive endswith(quote) would false-positive. Trailing-strip fixes it.
        ok, errors = run_on_frontmatter("command", command_fm(
            'description: "Do this: then that"\r'
        ))
        self.assertTrue(
            ok,
            f"quoted value with a trailing CR must pass; got: {errors}",
        )

    def test_colon_without_space_url_not_flagged(self):
        # A colon with NO following space (a URL) is legal in an unquoted scalar.
        ok, errors = run_on_frontmatter("command", command_fm(
            "description: see https://example.com/docs for details"
        ))
        self.assertTrue(
            ok,
            f"colon-without-space (URL) must not be flagged; got: {errors}",
        )

    def test_unquoted_colon_space_description_fails_agent(self):
        # The rule lives in shared read_frontmatter, so it applies to agents too.
        ok, errors = run_on_frontmatter("agent", agent_fm(
            "description: An agent that does X: and also Y"
        ))
        self.assertFalse(ok, "unquoted colon-space agent description must fail")
        self.assertTrue(
            any("description" in e and "theagent.md" in e for e in errors),
            f"error should name the agent file + key; got: {errors}",
        )

    def test_quoted_colon_space_description_passes_skill(self):
        # Guardian's load-bearing case: real SKILL.md descriptions are quoted and
        # contain ': ' (e.g. peer-review-council). Rule 1 (quote-aware, first) must
        # let them through unflagged.
        ok, errors = run_on_frontmatter("skill", skill_fm(
            'description: "Use when X happens: convene the council and report"'
        ))
        self.assertTrue(
            ok,
            f"quoted SKILL description containing ': ' must pass; got: {errors}",
        )

    def test_bracket_leading_value_not_flagged(self):
        # allowed-tools is an unquoted flow sequence starting with '['. The heuristic
        # must NOT flag leading YAML-indicator chars (no such rule) or every real
        # command file would false-positive.
        ok, errors = run_on_frontmatter("command", command_fm(
            'description: "A plain description"',
            allowed_tools='["Bash", "Read"]',
        ))
        self.assertTrue(
            ok,
            f"a '['-leading allowed-tools value must not be flagged; got: {errors}",
        )

    def test_helper_is_pure_and_quote_aware(self):
        # Direct unit test of the heuristic in isolation (it needs no Validator
        # instance — a pure (key, value) -> str|None function).
        err = vm.Validator._frontmatter_value_error
        self.assertIsNone(err("description", '"safe: quoted"'))
        self.assertIsNone(err("description", "'safe: quoted'"))
        self.assertIsNone(err("description", "no colon space here"))
        self.assertIsNone(err("description", "https://x:y"))  # colon, no space
        self.assertIsNone(err("description", ""))  # empty -> presence check's job
        bad = err("description", "unquoted: mapping-like")
        self.assertIsInstance(bad, str)
        self.assertIn("description", bad)
        self.assertIn("': '", bad)


# --------------------------------------------------------------------------
# main() CLI: exit codes and reported output (slice s3)
#
# main(argv=None) resolves argv[0] (or "." when empty) and returns 0 on a valid
# marketplace, 1 on a bad path or any validation error, printing OK:/FAILED:/error
# accordingly. These pin the observable CLI contract without spawning a process or
# mutating sys.argv; the default-arg case runs against an isolated tmp cwd, never
# the live checkout.
# --------------------------------------------------------------------------

class MainCliTest(unittest.TestCase):
    def _run_main(self, argv):
        """Call vm.main(argv), capturing (rc, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = vm.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_not_a_directory_arg_exits_1(self):
        with TemporaryDirectory() as td:
            missing = str(Path(td) / "does-not-exist")
            rc, out, err = self._run_main([missing])
        self.assertEqual(rc, 1)
        self.assertIn("error: not a directory", err)

    def test_valid_repo_exits_0_and_prints_ok(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            write_plugin(root, cmd(
                description="A read-only inspector.",
                allowed_tools=["Read"],
            ))
            rc, out, err = self._run_main([str(root)])
        self.assertEqual(rc, 0, f"valid repo must exit 0; stderr: {err}")
        self.assertIn("OK:", out)

    def test_invalid_repo_exits_1_and_prints_failed_with_errors(self):
        # A root with no marketplace.json fails; FAILED: header + the error list
        # must reach stderr.
        with TemporaryDirectory() as td:
            rc, out, err = self._run_main([str(Path(td))])
        self.assertEqual(rc, 1)
        self.assertIn("FAILED:", err)
        self.assertIn("missing required file", err)

    def test_default_arg_runs_against_cwd_without_raising(self):
        # argv=[] resolves to "." (the process cwd). Guardian/historian INVARIANT:
        # this must NOT run against the live checkout, and its exit code is
        # environment-dependent, so assert only that it returns an int and does not
        # raise. chdir into an isolated tmp dir, restored via addCleanup.
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        td = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(td, ignore_errors=True))
        os.chdir(td)
        rc, out, err = self._run_main([])
        self.assertIsInstance(rc, int)


# --------------------------------------------------------------------------
# Marketplace-level structural failures (slice s3)
# --------------------------------------------------------------------------

class MarketplaceStructureTest(unittest.TestCase):
    def test_missing_marketplace_json_reported(self):
        ok, errors = run_on_root(lambda root: None)  # empty root, no manifest
        self.assertFalse(ok)
        self.assertTrue(
            any("missing required file" in e and "marketplace.json" in e
                for e in errors),
            f"missing marketplace.json must be reported; got: {errors}",
        )

    def test_invalid_json_marketplace_reported(self):
        ok, errors = run_on_root(
            lambda root: write_marketplace(root, "{ not valid json")
        )
        self.assertFalse(ok)
        self.assertTrue(
            any("invalid JSON" in e and "marketplace.json" in e for e in errors),
            f"malformed marketplace.json must be reported; got: {errors}",
        )

    def test_non_kebab_marketplace_name_fails(self):
        ok, errors = run_on_root(lambda root: write_marketplace(root, {
            "name": "Not Kebab",
            "owner": {"name": "tester"},
            "plugins": [{"name": "demo", "source": "./plugins/demo"}],
        }))
        self.assertFalse(ok)
        self.assertTrue(
            any("'name' must be a kebab-case string" in e for e in errors),
            f"non-kebab marketplace name must fail; got: {errors}",
        )

    def test_missing_owner_name_fails(self):
        ok, errors = run_on_root(lambda root: write_marketplace(root, {
            "name": "demo-market",
            "owner": {},
            "plugins": [{"name": "demo", "source": "./plugins/demo"}],
        }))
        self.assertFalse(ok)
        self.assertTrue(
            any("'owner.name' is required" in e for e in errors),
            f"missing owner.name must fail; got: {errors}",
        )

    def test_empty_plugins_array_fails(self):
        ok, errors = run_on_root(lambda root: write_marketplace(root, {
            "name": "demo-market",
            "owner": {"name": "tester"},
            "plugins": [],
        }))
        self.assertFalse(ok)
        self.assertTrue(
            any("'plugins' must be a non-empty array" in e for e in errors),
            f"empty plugins array must fail; got: {errors}",
        )

    def test_plugins_not_a_list_fails(self):
        ok, errors = run_on_root(lambda root: write_marketplace(root, {
            "name": "demo-market",
            "owner": {"name": "tester"},
            "plugins": "not-a-list",
        }))
        self.assertFalse(ok)
        self.assertTrue(
            any("'plugins' must be a non-empty array" in e for e in errors),
            f"non-list plugins must fail; got: {errors}",
        )

    def test_plugin_root_prefixing_resolves_bare_name_source(self):
        # A BARE-name source (no './' prefix) must be resolved under
        # metadata.pluginRoot. Lay the plugin down there and confirm it passes.
        def build(root):
            write_plugin_dir(root, "plugins/demo", {"name": "demo", "version": "0.0.1"})
            write_marketplace(root, single_entry_marketplace(
                {"name": "demo", "source": "demo"},
                metadata={"pluginRoot": "plugins"},
            ))
        ok, errors = run_on_root(build)
        self.assertTrue(
            ok, f"bare-name source under pluginRoot must resolve; got: {errors}"
        )


# --------------------------------------------------------------------------
# Plugin-entry structural failures (slice s3)
# --------------------------------------------------------------------------

class PluginEntryTest(unittest.TestCase):
    def test_entry_not_an_object_fails(self):
        ok, errors = run_on_root(lambda root: write_marketplace(root, {
            "name": "demo-market",
            "owner": {"name": "tester"},
            "plugins": ["not-an-object"],
        }))
        self.assertFalse(ok)
        self.assertTrue(
            any("must be an object" in e for e in errors),
            f"non-object entry must fail; got: {errors}",
        )

    def test_non_kebab_entry_name_fails(self):
        ok, errors = run_on_root(lambda root: write_marketplace(
            root, single_entry_marketplace({"name": "Bad Name", "source": "./x"})
        ))
        self.assertFalse(ok)
        self.assertTrue(
            any("'name' must be a kebab-case string" in e for e in errors),
            f"non-kebab entry name must fail; got: {errors}",
        )

    def test_duplicate_plugin_name_fails(self):
        ok, errors = run_on_root(lambda root: write_marketplace(root, {
            "name": "demo-market",
            "owner": {"name": "tester"},
            "plugins": [
                {"name": "demo", "source": "./plugins/demo"},
                {"name": "demo", "source": "./plugins/other"},
            ],
        }))
        self.assertFalse(ok)
        self.assertTrue(
            any("duplicate plugin name" in e for e in errors),
            f"duplicate plugin name must fail; got: {errors}",
        )

    def test_missing_string_source_fails(self):
        ok, errors = run_on_root(lambda root: write_marketplace(
            root, single_entry_marketplace({"name": "demo"})  # no source
        ))
        self.assertFalse(ok)
        self.assertTrue(
            any("'source' (relative path) is required" in e for e in errors),
            f"missing string source must fail; got: {errors}",
        )

    def test_source_path_traversal_fails(self):
        ok, errors = run_on_root(lambda root: write_marketplace(
            root, single_entry_marketplace({"name": "demo", "source": "../escape"})
        ))
        self.assertFalse(ok)
        self.assertTrue(
            any("path traversal" in e for e in errors),
            f"'..' in source must fail; got: {errors}",
        )

    def test_source_not_a_directory_fails(self):
        ok, errors = run_on_root(lambda root: write_marketplace(
            root, single_entry_marketplace(
                {"name": "demo", "source": "./nonexistent"}
            )
        ))
        self.assertFalse(ok)
        self.assertTrue(
            any("does not resolve to a directory" in e for e in errors),
            f"non-directory source must fail; got: {errors}",
        )

    def test_missing_plugin_json_fails(self):
        def build(root):
            (root / "plugins" / "demo").mkdir(parents=True)  # dir but no plugin.json
            write_marketplace(root, single_entry_marketplace(
                {"name": "demo", "source": "./plugins/demo"}
            ))
        ok, errors = run_on_root(build)
        self.assertFalse(ok)
        self.assertTrue(
            any("missing" in e and "plugin.json" in e for e in errors),
            f"missing plugin.json must fail; got: {errors}",
        )


# --------------------------------------------------------------------------
# Object-source validation (slice s3)
# --------------------------------------------------------------------------

class SourceObjectTest(unittest.TestCase):
    def _run_source(self, source_obj):
        return run_on_root(lambda root: write_marketplace(
            root, single_entry_marketplace({"name": "demo", "source": source_obj})
        ))

    def test_unknown_source_kind_fails(self):
        ok, errors = self._run_source({"source": "svn", "repo": "x"})
        self.assertFalse(ok)
        self.assertTrue(
            any("must be one of" in e for e in errors),
            f"unknown source kind must fail; got: {errors}",
        )

    def test_missing_required_key_fails(self):
        ok, errors = self._run_source({"source": "github"})  # github requires 'repo'
        self.assertFalse(ok)
        self.assertTrue(
            any("github source requires string 'repo'" in e for e in errors),
            f"github without repo must fail; got: {errors}",
        )

    def test_git_subdir_missing_one_of_multiple_keys_fails(self):
        # git-subdir requires BOTH 'url' and 'path'; supplying only 'url' must fail
        # on the missing 'path' — exercises the multi-key required-key loop.
        ok, errors = self._run_source(
            {"source": "git-subdir", "url": "https://example.com/repo.git"}
        )
        self.assertFalse(ok)
        self.assertTrue(
            any("git-subdir source requires string 'path'" in e for e in errors),
            f"git-subdir without path must fail; got: {errors}",
        )

    def test_empty_ref_fails(self):
        ok, errors = self._run_source(
            {"source": "github", "repo": "o/r", "ref": ""}
        )
        self.assertFalse(ok)
        self.assertTrue(
            any("'source.ref' must be a non-empty string" in e for e in errors),
            f"empty ref must fail; got: {errors}",
        )

    def test_bad_sha_fails(self):
        ok, errors = self._run_source(
            {"source": "github", "repo": "o/r", "sha": "deadbeef"}  # not 40 hex
        )
        self.assertFalse(ok)
        self.assertTrue(
            any("must be a 40-char commit SHA" in e for e in errors),
            f"non-40-char sha must fail; got: {errors}",
        )

    def test_valid_object_source_passes(self):
        ok, errors = self._run_source({
            "source": "github",
            "repo": "owner/repo",
            "ref": "main",
            "sha": "a" * 40,
        })
        self.assertTrue(
            ok, f"a well-formed github object source must pass; got: {errors}"
        )


# --------------------------------------------------------------------------
# Plugin manifest + frontmatter failures (slice s3)
# --------------------------------------------------------------------------

class PluginManifestTest(unittest.TestCase):
    def _run_with_manifest(self, manifest, *, entry_extra=None):
        entry = {"name": "demo", "source": "./plugins/demo"}
        if entry_extra:
            entry.update(entry_extra)

        def build(root):
            write_plugin_dir(root, "plugins/demo", manifest)
            write_marketplace(root, single_entry_marketplace(entry))
        return run_on_root(build)

    def test_manifest_name_non_kebab_fails(self):
        ok, errors = self._run_with_manifest({"name": "Bad Name", "version": "0.0.1"})
        self.assertFalse(ok)
        self.assertTrue(
            any("'name' must be a kebab-case string" in e for e in errors),
            f"non-kebab manifest name must fail; got: {errors}",
        )

    def test_manifest_name_mismatch_fails(self):
        ok, errors = self._run_with_manifest({"name": "other", "version": "0.0.1"})
        self.assertFalse(ok)
        self.assertTrue(
            any("does not match marketplace entry" in e for e in errors),
            f"manifest/entry name mismatch must fail; got: {errors}",
        )

    def test_version_mismatch_fails(self):
        ok, errors = self._run_with_manifest(
            {"name": "demo", "version": "9.9.9"},
            entry_extra={"version": "0.0.1"},
        )
        self.assertFalse(ok)
        self.assertTrue(
            any("version mismatch" in e for e in errors),
            f"version mismatch must fail; got: {errors}",
        )

    def test_malformed_plugin_json_reported(self):
        # A plugin.json that is present but not valid JSON: load_json records an
        # 'invalid JSON' error and returns None, so validate_plugin bails early.
        ok, errors = self._run_with_manifest("{ not valid json")
        self.assertFalse(ok)
        self.assertTrue(
            any("invalid JSON" in e and "plugin.json" in e for e in errors),
            f"malformed plugin.json must be reported; got: {errors}",
        )

    def test_command_without_allowed_tools_passes(self):
        # A read-only command whose frontmatter OMITS allowed-tools entirely must
        # pass: _allowed_tools returns an empty set for a missing/non-string value,
        # so there is no Edit to flag.
        command_md = (
            "---\n"
            'description: "A read-only inspector that mutates nothing."\n'
            "---\n\n# A command\n"
        )

        def build(root):
            plugin_dir = write_plugin_dir(
                root, "plugins/demo", {"name": "demo", "version": "0.0.1"}
            )
            (plugin_dir / "commands").mkdir()
            (plugin_dir / "commands" / "thecmd.md").write_text(command_md)
            write_marketplace(root, single_entry_marketplace(
                {"name": "demo", "source": "./plugins/demo"}
            ))
        ok, errors = run_on_root(build)
        self.assertTrue(
            ok,
            f"a read-only command with no allowed-tools must pass; got: {errors}",
        )

    def test_skill_name_dir_mismatch_fails(self):
        # SKILL.md declaring a name that differs from its directory must fail.
        skill_md = (
            "---\nname: wrongname\n"
            'description: "A skill."\n---\n\n# A skill\n'
        )

        def build(root):
            plugin_dir = write_plugin_dir(
                root, "plugins/demo", {"name": "demo", "version": "0.0.1"}
            )
            skill_dir = plugin_dir / "skills" / "theskill"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(skill_md)
            write_marketplace(root, single_entry_marketplace(
                {"name": "demo", "source": "./plugins/demo"}
            ))
        ok, errors = run_on_root(build)
        self.assertFalse(ok)
        self.assertTrue(
            any("does not match its directory" in e for e in errors),
            f"skill name/dir mismatch must fail; got: {errors}",
        )

    def test_agent_missing_required_key_fails(self):
        # An agent frontmatter missing 'name' must be reported by require_keys.
        ok, errors = run_on_frontmatter(
            "agent", "---\ndescription: \"An agent.\"\n---\n\n# An agent\n"
        )
        self.assertFalse(ok)
        self.assertTrue(
            any("missing required 'name'" in e and "theagent.md" in e
                for e in errors),
            f"agent missing name must fail; got: {errors}",
        )

    def test_missing_frontmatter_block_fails(self):
        # A command file with no leading '---' block.
        ok, errors = run_on_frontmatter(
            "command", "# Just a heading, no frontmatter\n"
        )
        self.assertFalse(ok)
        self.assertTrue(
            any("missing YAML frontmatter" in e and "thecmd.md" in e
                for e in errors),
            f"missing frontmatter block must fail; got: {errors}",
        )

    def test_unterminated_frontmatter_block_fails(self):
        # A leading '---' with no closing '---'.
        ok, errors = run_on_frontmatter(
            "command", "---\ndescription: \"x\"\n(no closing fence)\n"
        )
        self.assertFalse(ok)
        self.assertTrue(
            any("unterminated frontmatter block" in e and "thecmd.md" in e
                for e in errors),
            f"unterminated frontmatter must fail; got: {errors}",
        )


# --------------------------------------------------------------------------
# Regression: the real repository still validates cleanly
# --------------------------------------------------------------------------

class RealRepoTest(unittest.TestCase):
    def test_real_repo_validates(self):
        v = vm.Validator(REPO_ROOT)
        ok = v.run()
        self.assertTrue(ok, f"real repo must validate; errors: {v.errors}")


if __name__ == "__main__":
    unittest.main()
