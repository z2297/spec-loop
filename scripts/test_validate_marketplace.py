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
# Regression: the real repository still validates cleanly
# --------------------------------------------------------------------------

class RealRepoTest(unittest.TestCase):
    def test_real_repo_validates(self):
        v = vm.Validator(REPO_ROOT)
        ok = v.run()
        self.assertTrue(ok, f"real repo must validate; errors: {v.errors}")


if __name__ == "__main__":
    unittest.main()
