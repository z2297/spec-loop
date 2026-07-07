#!/usr/bin/env python3
"""PreToolUse guard: deterministic enforcement of spec-loop's git invariants.

Registered by the plugin's hooks/hooks.json for Bash and Write|Edit tool calls.
While a spec-loop run is active (a `docs/spec-loop/<run-id>/.active` marker
exists under the project root), this hook mechanically blocks the operations
the loop's prompts forbid:

- `git push` before the human's publish choice (`.publish-choice` marker) —
  except in `per-slice-pr` merge mode, where slices legitimately push.
  Only pushes that plausibly belong to the run are denied: bare `git push`,
  pushes naming the run's integration branch (`base_ref`), or `spec-loop/`
  worktree branches.
- `git add -A` / `--all` / `git add .` — the runbook commit must stage only
  the run directory by explicit pathspec.
- `git commit` / `git merge` while sitting on `main`/`master` (or a compound
  command that checks out main and commits/merges/pushes) before the publish
  choice.
- Any write to the global quality-gate config (`~/.claude/spec-loop/
  quality-gate.json`) — thresholds must never be weakened mid-run.

Design decisions:
- **Fail-open on internal errors.** This hook is defense-in-depth; the skill
  prompts remain the primary control. A crashed guard must not deny every
  tool call in the session, so any unexpected exception allows the action.
- Denials **fail closed** with a reason that names the compliant alternative
  and the stale-marker remediation (`/spec-loop --resume <run-id>` or clearing
  the `.active` marker).
- Subagent coverage: verified empirically (2026-07-07, instrumented hook +
  headless `claude -p` probe) that PreToolUse fires for Bash calls made inside
  Task subagents as well as the main session — so this guard also covers slice
  workers. The platform docs don't state this explicitly, so it is worth
  re-probing after major Claude Code upgrades; every controller-owned operation
  (integration merge, runbook commit, publish push) runs in the main session
  regardless.

Standard library only. Reads the hook payload from stdin; a denial is exit 0
plus a permissionDecision JSON on stdout; an allow is exit 0 with no output.
"""

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys

QUALITY_GATE_CONFIG = os.path.join("~", ".claude", "spec-loop", "quality-gate.json")

GIT_PUSH = re.compile(r"\bgit\b(?:\s+-\S+|\s+-C\s+\S+)*\s+push\b")
GIT_ADD_BROAD = re.compile(
    r"\bgit\b(?:\s+-\S+|\s+-C\s+\S+)*\s+add\s+(?:[^;|&]*\s)?(?:-A\b|--all\b|\.(?:\s|$|;))"
)
GIT_COMMIT_OR_MERGE = re.compile(r"\bgit\b(?:\s+-\S+|\s+-C\s+\S+)*\s+(?:commit|merge)\b")
CHECKOUT_MAIN = re.compile(r"\bgit\b[^;|&]*\b(?:checkout|switch)\s+(?:main|master)\b")
COMMIT_MERGE_PUSH_WORD = re.compile(r"\b(?:commit|merge|push)\b")
WRITE_INDICATORS = re.compile(r"(?:>>?|\btee\b|\bsed\s+-i\b|\bmv\b|\bcp\b)")


def find_active_runs(project_root):
    """Return info for every run with an `.active` marker under project_root."""
    runs = []
    for marker in sorted(glob.glob(os.path.join(project_root, "docs", "spec-loop", "*", ".active"))):
        run_dir = os.path.dirname(marker)
        info = {
            "run_id": os.path.basename(run_dir),
            "dir": run_dir,
            "publish_choice": os.path.exists(os.path.join(run_dir, ".publish-choice")),
            "merge_mode": "single-branch",
            "base_ref": None,
        }
        try:
            with open(os.path.join(run_dir, "dag.json"), "r", encoding="utf-8") as fh:
                dag = json.load(fh)
            info["merge_mode"] = dag.get("merge_mode", "single-branch")
            info["base_ref"] = dag.get("base_ref")
        except (OSError, ValueError):
            pass  # missing/unreadable dag.json: keep restrictive defaults
        runs.append(info)
    return runs


def current_branch(cwd):
    """The checked-out branch in cwd, or None if git is unavailable."""
    try:
        out = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=cwd or None,
            capture_output=True,
            text=True,
            timeout=3,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _remediation(run):
    return (
        "If run %s is stale, resume it (/spec-loop --resume %s) or clear "
        "docs/spec-loop/%s/.active." % (run["run_id"], run["run_id"], run["run_id"])
    )


def _push_targets_run(command, run):
    """Does this push plausibly belong to the run? Bare pushes count."""
    for segment in re.split(r"(?:&&|\|\||[;|])", command):
        if not GIT_PUSH.search(segment):
            continue
        tail = segment[GIT_PUSH.search(segment).end():]
        args = [a for a in tail.split() if not a.startswith("-")]
        if len(args) <= 1:  # bare `git push` or remote-only
            return True
        if "spec-loop/" in tail:
            return True
        if run["base_ref"] and re.search(r"\b%s\b" % re.escape(run["base_ref"]), tail):
            return True
    return False


def check_bash(command, cwd, runs):
    """Return a deny reason for this Bash command, or None to allow."""
    blocking = [r for r in runs if not r["publish_choice"]]

    if GIT_ADD_BROAD.search(command):
        run = runs[0]
        return (
            "spec-loop run %s is active: broad staging (`git add -A`/`--all`/`.`) would sweep "
            "unrelated changes into the commit. Stage only the run directory by explicit "
            "pathspec: git add -- docs/spec-loop/%s/. %s"
            % (run["run_id"], run["run_id"], _remediation(run))
        )

    if "quality-gate.json" in command and WRITE_INDICATORS.search(command):
        run = runs[0]
        return (
            "spec-loop run %s is active: the quality-gate config must not be modified "
            "mid-run (thresholds are never weakened to force a pass). Adjust it after the "
            "run via /spec-loop:quality-gate. %s" % (run["run_id"], _remediation(run))
        )

    if blocking and GIT_PUSH.search(command):
        push_blockers = [
            r for r in blocking
            if r["merge_mode"] != "per-slice-pr" and _push_targets_run(command, r)
        ]
        if push_blockers:
            run = push_blockers[0]
            return (
                "spec-loop run %s is active and has not reached the publish prompt "
                "(Phase 5): the loop never pushes until the human chooses how to publish. %s"
                % (run["run_id"], _remediation(run))
            )

    if blocking:
        compound = CHECKOUT_MAIN.search(command) and COMMIT_MERGE_PUSH_WORD.search(
            CHECKOUT_MAIN.sub("", command)
        )
        on_main = GIT_COMMIT_OR_MERGE.search(command) and current_branch(cwd) in ("main", "master")
        if compound or on_main:
            run = blocking[0]
            return (
                "spec-loop run %s is active: commits/merges on main/master are reserved for "
                "the human's publish choice (Phase 5). Work happens on the integration "
                "branch%s. %s"
                % (
                    run["run_id"],
                    " (%s)" % run["base_ref"] if run["base_ref"] else "",
                    _remediation(run),
                )
            )

    return None


def check_write(file_path, runs):
    """Return a deny reason for this Write/Edit target, or None to allow."""
    if not file_path:
        return None
    target = os.path.realpath(os.path.expanduser(file_path))
    protected = os.path.realpath(os.path.expanduser(QUALITY_GATE_CONFIG))
    if target == protected:
        run = runs[0]
        return (
            "spec-loop run %s is active: never edit ~/.claude/spec-loop/quality-gate.json "
            "mid-run — weakening thresholds to force a pass is forbidden. Adjust it after "
            "the run via /spec-loop:quality-gate. %s" % (run["run_id"], _remediation(run))
        )
    return None


def evaluate(payload):
    """Return a deny reason for this hook payload, or None to allow."""
    project_root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    runs = find_active_runs(project_root)
    if not runs:
        return None

    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}
    if tool == "Bash":
        return check_bash(tool_input.get("command", ""), payload.get("cwd"), runs)
    if tool in ("Write", "Edit", "MultiEdit"):
        return check_write(tool_input.get("file_path"), runs)
    return None


def main(argv=None):
    try:
        payload = json.load(sys.stdin)
        reason = evaluate(payload)
    except Exception:  # noqa: BLE001 — deliberate fail-open (see module docstring)
        return 0
    if reason:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": reason,
                    }
                }
            )
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
