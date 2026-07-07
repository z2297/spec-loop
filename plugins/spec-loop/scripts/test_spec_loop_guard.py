"""Tests for spec_loop_guard.py.

Standard library only; no live git required (current_branch is patched).
Builds throwaway run-state directories with tempfile and drives evaluate()
plus the CLI entry with fixture hook payloads.
"""

import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import spec_loop_guard as guard


class GuardTestCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        env = mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.root})
        env.start()
        self.addCleanup(env.stop)
        # Default: no git subprocess in tests; feature branch unless overridden.
        branch = mock.patch.object(guard, "current_branch", return_value="csv-export")
        self.branch_mock = branch.start()
        self.addCleanup(branch.stop)

    def make_run(self, run_id="20260707-demo", active=True, publish_choice=False,
                 merge_mode="single-branch", base_ref="csv-export"):
        run_dir = os.path.join(self.root, "docs", "spec-loop", run_id)
        os.makedirs(run_dir, exist_ok=True)
        if active:
            with open(os.path.join(run_dir, ".active"), "w") as fh:
                fh.write("2026-07-07T00:00:00 " + run_id)
        if publish_choice:
            with open(os.path.join(run_dir, ".publish-choice"), "w") as fh:
                fh.write("push-feature-branch")
        with open(os.path.join(run_dir, "dag.json"), "w") as fh:
            json.dump({"base_ref": base_ref, "merge_mode": merge_mode, "slices": []}, fh)
        return run_dir

    @staticmethod
    def bash(command, cwd="/tmp/wt"):
        return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd}

    @staticmethod
    def write(file_path):
        return {"tool_name": "Write", "tool_input": {"file_path": file_path}, "cwd": "/tmp"}


class NoActiveRunTests(GuardTestCase):
    def test_everything_allowed_without_marker(self):
        self.make_run(active=False)
        self.assertIsNone(guard.evaluate(self.bash("git push")))
        self.assertIsNone(guard.evaluate(self.bash("git add -A")))
        self.assertIsNone(
            guard.evaluate(self.write(os.path.expanduser(guard.QUALITY_GATE_CONFIG)))
        )


class PushRuleTests(GuardTestCase):
    def test_bare_push_denied(self):
        self.make_run()
        reason = guard.evaluate(self.bash("git push"))
        self.assertIn("publish prompt", reason)
        self.assertIn("--resume 20260707-demo", reason)

    def test_push_of_integration_branch_denied(self):
        self.make_run(base_ref="csv-export")
        self.assertIsNotNone(guard.evaluate(self.bash("git push origin csv-export")))

    def test_push_of_spec_loop_branch_denied(self):
        self.make_run()
        self.assertIsNotNone(
            guard.evaluate(self.bash("git push origin spec-loop/20260707-demo/s1"))
        )

    def test_push_of_unrelated_branch_allowed(self):
        self.make_run(base_ref="csv-export")
        self.assertIsNone(guard.evaluate(self.bash("git push origin hotfix-typo")))

    def test_push_allowed_after_publish_choice(self):
        self.make_run(publish_choice=True)
        self.assertIsNone(guard.evaluate(self.bash("git push")))

    def test_push_allowed_in_per_slice_pr_mode(self):
        self.make_run(merge_mode="per-slice-pr")
        self.assertIsNone(guard.evaluate(self.bash("git push -u origin spec-loop/20260707-demo/s1")))

    def test_push_denied_when_any_run_blocks(self):
        self.make_run("run-a", merge_mode="per-slice-pr")
        self.make_run("run-b")
        self.assertIsNotNone(guard.evaluate(self.bash("git push")))

    def test_git_dash_c_push_denied(self):
        self.make_run()
        self.assertIsNotNone(guard.evaluate(self.bash("git -C /some/dir push")))


class BroadStagingTests(GuardTestCase):
    def test_add_all_variants_denied(self):
        self.make_run()
        for cmd in ("git add -A", "git add --all", "git add .", "git add . && git commit -m x"):
            reason = guard.evaluate(self.bash(cmd))
            self.assertIsNotNone(reason, cmd)
            self.assertIn("git add -- docs/spec-loop/20260707-demo/", reason)

    def test_scoped_add_allowed(self):
        self.make_run()
        self.assertIsNone(
            guard.evaluate(self.bash("git add -- docs/spec-loop/20260707-demo/"))
        )
        self.assertIsNone(guard.evaluate(self.bash("git add src/app.py")))

    def test_broad_add_denied_even_after_publish_choice(self):
        # Publish choice covers push/main, not sloppy staging.
        self.make_run(publish_choice=True)
        self.assertIsNotNone(guard.evaluate(self.bash("git add -A")))


class MainBranchTests(GuardTestCase):
    def test_commit_on_main_denied(self):
        self.make_run()
        self.branch_mock.return_value = "main"
        reason = guard.evaluate(self.bash("git commit -m 'oops'"))
        self.assertIn("main/master", reason)

    def test_merge_on_master_denied(self):
        self.make_run()
        self.branch_mock.return_value = "master"
        self.assertIsNotNone(guard.evaluate(self.bash("git merge --no-ff csv-export")))

    def test_commit_on_feature_branch_allowed(self):
        self.make_run()
        self.assertIsNone(guard.evaluate(self.bash("git commit -m 'slice work'")))

    def test_compound_checkout_main_and_merge_denied(self):
        self.make_run()
        self.assertIsNotNone(
            guard.evaluate(self.bash("git checkout main && git merge --no-ff csv-export"))
        )

    def test_compound_switch_master_and_push_denied(self):
        self.make_run()
        self.assertIsNotNone(guard.evaluate(self.bash("git switch master && git push")))

    def test_checkout_main_alone_allowed(self):
        self.make_run()
        self.assertIsNone(guard.evaluate(self.bash("git checkout main")))

    def test_publish_choice_unlocks_main(self):
        self.make_run(publish_choice=True)
        self.branch_mock.return_value = "main"
        self.assertIsNone(
            guard.evaluate(self.bash("git checkout main && git merge --no-ff csv-export"))
        )


class QualityGateConfigTests(GuardTestCase):
    def test_bash_overwrite_denied(self):
        self.make_run()
        for cmd in (
            "echo '{}' > ~/.claude/spec-loop/quality-gate.json",
            "sed -i '' 's/10/99/' ~/.claude/spec-loop/quality-gate.json",
            "cp /tmp/x ~/.claude/spec-loop/quality-gate.json",
        ):
            self.assertIsNotNone(guard.evaluate(self.bash(cmd)), cmd)

    def test_bash_read_allowed(self):
        self.make_run()
        self.assertIsNone(
            guard.evaluate(self.bash("cat ~/.claude/spec-loop/quality-gate.json"))
        )

    def test_write_tool_denied(self):
        self.make_run()
        reason = guard.evaluate(self.write("~/.claude/spec-loop/quality-gate.json"))
        self.assertIn("quality-gate.json", reason)

    def test_write_tool_other_files_allowed(self):
        self.make_run()
        self.assertIsNone(guard.evaluate(self.write("/tmp/notes.md")))


class RobustnessTests(GuardTestCase):
    def test_missing_dag_json_still_guards(self):
        run_dir = self.make_run()
        os.unlink(os.path.join(run_dir, "dag.json"))
        self.assertIsNotNone(guard.evaluate(self.bash("git push")))

    def test_other_tools_ignored(self):
        self.make_run()
        self.assertIsNone(
            guard.evaluate({"tool_name": "Read", "tool_input": {"file_path": "x"}, "cwd": "/"})
        )

    def test_main_fail_open_on_garbage_stdin(self):
        with mock.patch("sys.stdin", io.StringIO("not json")):
            with mock.patch("sys.stdout", io.StringIO()) as out:
                self.assertEqual(guard.main(), 0)
        self.assertEqual(out.getvalue(), "")

    def test_main_emits_deny_json(self):
        self.make_run()
        payload = json.dumps(self.bash("git push"))
        with mock.patch("sys.stdin", io.StringIO(payload)):
            with mock.patch("sys.stdout", io.StringIO()) as out:
                self.assertEqual(guard.main(), 0)
        decision = json.loads(out.getvalue())["hookSpecificOutput"]
        self.assertEqual(decision["permissionDecision"], "deny")
        self.assertIn("publish prompt", decision["permissionDecisionReason"])

    def test_main_silent_allow(self):
        self.make_run(active=False)
        payload = json.dumps(self.bash("git push"))
        with mock.patch("sys.stdin", io.StringIO(payload)):
            with mock.patch("sys.stdout", io.StringIO()) as out:
                self.assertEqual(guard.main(), 0)
        self.assertEqual(out.getvalue(), "")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
