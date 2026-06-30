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

import json
import sys
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
# Regression: the real repository still validates cleanly
# --------------------------------------------------------------------------

class RealRepoTest(unittest.TestCase):
    def test_real_repo_validates(self):
        v = vm.Validator(REPO_ROOT)
        ok = v.run()
        self.assertTrue(ok, f"real repo must validate; errors: {v.errors}")


if __name__ == "__main__":
    unittest.main()
