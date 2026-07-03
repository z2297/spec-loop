#!/usr/bin/env python3
"""Tests for the read-only provider-agnostic PR resolver (stdlib unittest).

Covers URL parsing + provider detection for all three providers (incl. both
Azure DevOps URL forms), rejection of malformed / unknown-host URLs, pr_id and
path-segment validation (argument-injection defence), READ-ONLY resolution
against mocked CLIs/REST, the actionable failure when a CLI/credential is
absent, that the BITBUCKET_TOKEN never leaks through an error/stdout, and the
no-shell-injection / no-flag-injection guarantees (every subprocess call uses
list-args with shell=False, and user-derived refs are option-terminated).

`scripts/validate_marketplace.py` does NOT lint scripts/*.py, so this is the
sole automated guard on the resolver. Standard library only. No live network/CLI.

Usage:
    python3 scripts/test_pr_resolver.py
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pr_resolver as pr  # noqa: E402


# --------------------------------------------------------------------------
# Provider detection + input validation (pure, no I/O)
# --------------------------------------------------------------------------

class TestProviderDetection(unittest.TestCase):
    def test_github_host(self):
        self.assertEqual(pr.detect_provider("github.com"), "github")

    def test_bitbucket_host(self):
        self.assertEqual(pr.detect_provider("bitbucket.org"), "bitbucket")

    def test_azure_devops_host(self):
        self.assertEqual(pr.detect_provider("dev.azure.com"), "azure")

    def test_azure_visualstudio_host(self):
        self.assertEqual(pr.detect_provider("myorg.visualstudio.com"), "azure")

    def test_host_is_case_insensitive(self):
        self.assertEqual(pr.detect_provider("GitHub.com"), "github")

    def test_unknown_host_rejected(self):
        with self.assertRaises(pr.ResolverError):
            pr.detect_provider("gitlab.com")

    def test_lookalike_host_rejected(self):
        with self.assertRaises(pr.ResolverError):
            pr.detect_provider("github.com.evil.example")


class TestPrIdValidation(unittest.TestCase):
    def test_numeric_ok(self):
        self.assertEqual(pr.validate_pr_id("123"), "123")

    def test_non_numeric_rejected(self):
        for bad in ("12a", "1; rm -rf /", "", "-1", "1 2", "$(id)"):
            with self.assertRaises(pr.ResolverError):
                pr.validate_pr_id(bad)


class TestValidateSegment(unittest.TestCase):
    def test_accepts_normal(self):
        for ok in ("acme", "my-repo", "Proj_1", "a.b", "x~y"):
            self.assertEqual(pr.validate_segment(ok), ok)

    def test_rejects_leading_dash_and_specials(self):
        # leading '-' could be read as a CLI flag (argument injection)
        for bad in ("-X", "--output=x", "a/b", "a b", "", "a;b", "a$b"):
            with self.assertRaises(pr.ResolverError):
                pr.validate_segment(bad)


class TestParsePrUrl(unittest.TestCase):
    def test_github(self):
        rec = pr.parse_pr_url("https://github.com/acme/widgets/pull/42")
        self.assertEqual(rec["provider"], "github")
        self.assertEqual(rec["repo"], "acme/widgets")
        self.assertEqual(rec["pr_id"], "42")
        self.assertEqual(rec["host"], "github.com")
        self.assertEqual(rec["web_url"],
                         "https://github.com/acme/widgets/pull/42")

    def test_bitbucket(self):
        rec = pr.parse_pr_url("https://bitbucket.org/team/repo/pull-requests/7")
        self.assertEqual(rec["provider"], "bitbucket")
        self.assertEqual(rec["repo"], "team/repo")
        self.assertEqual(rec["pr_id"], "7")

    def test_azure_dev_azure(self):
        rec = pr.parse_pr_url(
            "https://dev.azure.com/org/proj/_git/repo/pullrequest/9")
        self.assertEqual(rec["provider"], "azure")
        self.assertEqual(rec["repo"], "org/proj/repo")
        self.assertEqual(rec["pr_id"], "9")

    def test_azure_visualstudio(self):
        rec = pr.parse_pr_url(
            "https://org.visualstudio.com/proj/_git/repo/pullrequest/9")
        self.assertEqual(rec["provider"], "azure")
        self.assertEqual(rec["repo"], "org/proj/repo")
        self.assertEqual(rec["pr_id"], "9")

    def test_malformed_url_rejected(self):
        for bad in (
            "not a url",
            "ftp://github.com/a/b/pull/1",
            "https://github.com/acme/widgets/issues/42",
            "https://gitlab.com/a/b/merge_requests/1",
            "https://github.com/acme/widgets/pull/notanumber",
            "https://github.com/acme/pull/1",          # missing repo segment
            "https://dev.azure.com/org/proj/repo/9",    # no _git/pullrequest
        ):
            with self.assertRaises(pr.ResolverError):
                pr.parse_pr_url(bad)

    def test_bitbucket_wrong_path_segment_rejected(self):
        # A bitbucket.org URL whose 3rd segment is NOT 'pull-requests' is not a
        # PR URL and must raise, naming Bitbucket (pr_resolver.py L132).
        with self.assertRaises(pr.ResolverError) as ctx:
            pr.parse_pr_url("https://bitbucket.org/team/repo/wrong/7")
        self.assertIn("Bitbucket", str(ctx.exception))

    def test_azure_missing_id_after_pullrequest_rejected(self):
        # 'pullrequest' is the last segment, so there is no id after it
        # (pi + 1 >= len(segs)) -> raises, naming Azure DevOps (L153).
        with self.assertRaises(pr.ResolverError) as ctx:
            pr.parse_pr_url(
                "https://dev.azure.com/org/proj/_git/repo/pullrequest")
        self.assertIn("Azure DevOps", str(ctx.exception))

    def test_azure_git_as_first_segment_rejected(self):
        # '_git' is the very first path segment, so gi < 1 -> raises (L153):
        # there is no org/project preceding it. Uses the .visualstudio.com form
        # (org is the SUBDOMAIN, so the dev.azure.com-specific gi < 2 guard at
        # L161 does not apply) -- here gi < 1 is the ONLY guard that can fire, so
        # the test genuinely pins that sub-clause rather than relying on L161.
        with self.assertRaises(pr.ResolverError) as ctx:
            pr.parse_pr_url(
                "https://org.visualstudio.com/_git/repo/pullrequest/9")
        self.assertIn("Azure DevOps", str(ctx.exception))

    def test_azure_dev_azure_missing_org_rejected(self):
        # dev.azure.com needs BOTH an org (first segment) and a project before
        # '_git'. Here gi == 1 (only the project precedes _git, no org), so the
        # dev.azure.com-specific gi < 2 guard raises (pr_resolver.py L161).
        with self.assertRaises(pr.ResolverError) as ctx:
            pr.parse_pr_url(
                "https://dev.azure.com/proj/_git/repo/pullrequest/9")
        self.assertIn("Azure DevOps", str(ctx.exception))

    def test_leading_dash_segment_rejected(self):
        # An owner/repo/org segment beginning with '-' could be read as a flag
        # (argument injection); reject it at parse time (Guardian concern).
        for bad in (
            "https://github.com/-X/widgets/pull/1",
            "https://github.com/acme/-rf/pull/1",
            "https://bitbucket.org/-evil/repo/pull-requests/1",
        ):
            with self.assertRaises(pr.ResolverError):
                pr.parse_pr_url(bad)


# --------------------------------------------------------------------------
# READ-ONLY resolution via CLI / REST (mocked -- no live network/CLI)
# --------------------------------------------------------------------------

class TestRunIsShellFree(unittest.TestCase):
    def test_run_uses_list_args_and_no_shell(self):
        with mock.patch("pr_resolver.subprocess.run") as m:
            m.return_value = mock.Mock(returncode=0, stdout="{}", stderr="")
            pr._run(["gh", "pr", "view", "42"])
        args, kwargs = m.call_args
        self.assertEqual(args[0], ["gh", "pr", "view", "42"])  # list, not str
        self.assertFalse(kwargs.get("shell", False))           # never shell=True

    def test_run_missing_binary_raises_actionable(self):
        with mock.patch("pr_resolver.subprocess.run",
                        side_effect=FileNotFoundError("gh")):
            with self.assertRaises(pr.ResolverError):
                pr._run(["gh", "pr", "view", "1"])

    def test_run_nonzero_exit_raises(self):
        with mock.patch("pr_resolver.subprocess.run") as m:
            m.return_value = mock.Mock(returncode=1, stdout="", stderr="boom")
            with self.assertRaises(pr.ResolverError):
                pr._run(["gh", "pr", "view", "1"])


class TestResolveGithub(unittest.TestCase):
    def test_uses_gh_cli_read_verb_and_normalizes(self):
        payload = json.dumps({
            "baseRefName": "main", "headRefName": "feature",
            "title": "T", "body": "B",
            "baseRefOid": "aaa", "headRefOid": "bbb",
        })
        parsed = pr.parse_pr_url("https://github.com/acme/widgets/pull/42")
        with mock.patch("pr_resolver.shutil.which", return_value="/usr/bin/gh"), \
             mock.patch("pr_resolver._run", return_value=payload) as m:
            rec = pr.resolve(parsed)
        argv = m.call_args.args[0]
        self.assertEqual(argv[:3], ["gh", "pr", "view"])   # READ verb only
        for forbidden in ("merge", "comment", "review", "close", "edit"):
            self.assertNotIn(forbidden, argv)
        self.assertEqual(rec["base_ref"], "main")
        self.assertEqual(rec["base_sha"], "aaa")
        self.assertEqual(rec["head_ref"], "feature")
        self.assertEqual(rec["head_sha"], "bbb")
        self.assertEqual(rec["title"], "T")
        self.assertEqual(rec["description"], "B")
        self.assertEqual(rec["provider"], "github")

    def test_missing_gh_cli_is_actionable(self):
        parsed = pr.parse_pr_url("https://github.com/acme/widgets/pull/42")
        with mock.patch("pr_resolver.shutil.which", return_value=None):
            with self.assertRaises(pr.ResolverError) as ctx:
                pr.resolve(parsed)
        self.assertIn("gh", str(ctx.exception).lower())


class TestResolveAzure(unittest.TestCase):
    def test_uses_az_read_verb(self):
        payload = json.dumps({
            "sourceRefName": "refs/heads/feature",
            "targetRefName": "refs/heads/main",
            "title": "T", "description": "D",
            "lastMergeSourceCommit": {"commitId": "bbb"},
            "lastMergeTargetCommit": {"commitId": "aaa"},
        })
        parsed = pr.parse_pr_url(
            "https://dev.azure.com/org/proj/_git/repo/pullrequest/9")
        with mock.patch("pr_resolver.shutil.which", return_value="/usr/bin/az"), \
             mock.patch("pr_resolver._run", return_value=payload) as m:
            rec = pr.resolve(parsed)
        argv = m.call_args.args[0]
        self.assertEqual(argv[:3], ["az", "repos", "pr"])
        self.assertIn("show", argv)
        for forbidden in ("create", "vote", "update", "set-vote"):
            self.assertNotIn(forbidden, argv)
        self.assertEqual(rec["base_ref"], "main")     # refs/heads/ stripped
        self.assertEqual(rec["head_ref"], "feature")
        self.assertEqual(rec["base_sha"], "aaa")
        self.assertEqual(rec["head_sha"], "bbb")

    def test_visualstudio_org_url(self):
        payload = json.dumps({
            "sourceRefName": "refs/heads/f", "targetRefName": "refs/heads/m",
            "title": "", "description": "",
            "lastMergeSourceCommit": {"commitId": "b"},
            "lastMergeTargetCommit": {"commitId": "a"},
        })
        parsed = pr.parse_pr_url(
            "https://org.visualstudio.com/proj/_git/repo/pullrequest/9")
        with mock.patch("pr_resolver.shutil.which", return_value="/usr/bin/az"), \
             mock.patch("pr_resolver._run", return_value=payload) as m:
            pr.resolve(parsed)
        argv = m.call_args.args[0]
        self.assertIn("https://org.visualstudio.com", argv)

    def test_missing_az_cli_is_actionable(self):
        parsed = pr.parse_pr_url(
            "https://dev.azure.com/org/proj/_git/repo/pullrequest/9")
        with mock.patch("pr_resolver.shutil.which", return_value=None):
            with self.assertRaises(pr.ResolverError) as ctx:
                pr.resolve(parsed)
        self.assertIn("az", str(ctx.exception).lower())


class TestResolveBitbucket(unittest.TestCase):
    def test_uses_http_get_to_fixed_origin(self):
        payload = json.dumps({
            "title": "T", "description": "D",
            "source": {"branch": {"name": "feature"},
                       "commit": {"hash": "bbb"}},
            "destination": {"branch": {"name": "main"},
                            "commit": {"hash": "aaa"}},
        }).encode()
        parsed = pr.parse_pr_url(
            "https://bitbucket.org/team/repo/pull-requests/7")
        with mock.patch.dict(os.environ, {"BITBUCKET_TOKEN": "tok"}), \
             mock.patch("pr_resolver._http_get", return_value=payload) as m:
            rec = pr.resolve(parsed)
        url = m.call_args.args[0]
        self.assertTrue(url.startswith("https://api.bitbucket.org/"))
        self.assertEqual(rec["base_ref"], "main")
        self.assertEqual(rec["head_ref"], "feature")
        self.assertEqual(rec["head_sha"], "bbb")

    def test_missing_token_is_actionable(self):
        parsed = pr.parse_pr_url(
            "https://bitbucket.org/team/repo/pull-requests/7")
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(pr.ResolverError) as ctx:
                pr.resolve(parsed)
        self.assertIn("BITBUCKET_TOKEN", str(ctx.exception))


class TestMalformedPayload(unittest.TestCase):
    def test_non_json_cli_output_raises_actionable(self):
        # A CLI emitting non-JSON (e.g. an auth banner) must fail with an
        # actionable message, not a raw JSONDecodeError traceback.
        parsed = pr.parse_pr_url("https://github.com/acme/widgets/pull/42")
        with mock.patch("pr_resolver.shutil.which", return_value="/usr/bin/gh"), \
             mock.patch("pr_resolver._run", return_value="not json <<<"):
            with self.assertRaises(pr.ResolverError) as ctx:
                pr.resolve(parsed)
        self.assertIn("not valid JSON", str(ctx.exception))


# --------------------------------------------------------------------------
# _http_get success + HTTP-error paths (slice s8)
#
# TestTokenNeverLeaks below already exercises the urllib.error.URLError arm of
# _http_get (via _resolve_bitbucket). These pin the two SIBLING branches it
# never reaches: the resp.read() SUCCESS return, and the urllib.error.HTTPError
# arm. urlopen is mocked, so no real request is ever issued.
# --------------------------------------------------------------------------

class TestHttpGet(unittest.TestCase):
    def _urlopen_cm(self, body: bytes):
        """A context-manager stand-in for urlopen's response whose read()
        yields `body` -- matches _http_get's `with urlopen(...) as resp`."""
        cm = mock.MagicMock()
        cm.__enter__.return_value.read.return_value = body
        return cm

    def test_success_returns_response_bytes_via_get(self):
        body = b'{"ok": true}'
        with mock.patch("pr_resolver.urllib.request.urlopen",
                        return_value=self._urlopen_cm(body)) as m:
            out = pr._http_get("https://api.example.com/x",
                               headers={"Authorization": "Bearer x"})
        self.assertEqual(out, body)               # returns resp.read() verbatim
        req = m.call_args.args[0]                  # the urllib Request object
        self.assertEqual(req.get_method(), "GET")  # READ-only: never mutating

    def _http_error(self, url, code, reason):
        """A closed-on-teardown HTTPError. HTTPError owns an internal file
        object; closing it avoids a ResourceWarning at GC time."""
        err = urllib.error.HTTPError(url, code, reason, {}, None)
        self.addCleanup(err.close)
        return err

    def test_http_error_raises_actionable_with_code_and_url(self):
        url = "https://api.example.com/missing"
        err = self._http_error(url, 404, "Not Found")
        with mock.patch("pr_resolver.urllib.request.urlopen", side_effect=err):
            with self.assertRaises(pr.ResolverError) as ctx:
                pr._http_get(url)
        msg = str(ctx.exception)
        self.assertIn("HTTP 404", msg)
        self.assertIn(url, msg)

    def test_http_error_message_never_leaks_auth_header(self):
        # A secret riding in the Authorization header must never surface in the
        # raised error text, even when the fetch fails with an HTTPError.
        secret = "s3cr3t-bearer-value"
        url = "https://api.example.com/missing"
        err = self._http_error(url, 403, "Forbidden")
        with mock.patch("pr_resolver.urllib.request.urlopen", side_effect=err):
            with self.assertRaises(pr.ResolverError) as ctx:
                pr._http_get(url, headers={"Authorization": f"Bearer {secret}"})
        self.assertNotIn(secret, str(ctx.exception))


class TestTokenNeverLeaks(unittest.TestCase):
    SECRET = "s3cr3t-token-value"

    def test_token_absent_from_http_error_and_streams(self):
        parsed = pr.parse_pr_url(
            "https://bitbucket.org/team/repo/pull-requests/7")
        # Force the network path to raise inside _http_get's urlopen.
        err = urllib.error.URLError("connection refused")
        with mock.patch.dict(os.environ, {"BITBUCKET_TOKEN": self.SECRET}), \
             mock.patch("pr_resolver.urllib.request.urlopen", side_effect=err):
            with self.assertRaises(pr.ResolverError) as ctx:
                pr.resolve(parsed)
        self.assertNotIn(self.SECRET, str(ctx.exception))

    def test_token_absent_from_main_stderr(self):
        argv = ["https://bitbucket.org/team/repo/pull-requests/7"]
        err = urllib.error.URLError("nope")
        captured = {}
        with mock.patch.dict(os.environ, {"BITBUCKET_TOKEN": self.SECRET}), \
             mock.patch("pr_resolver.urllib.request.urlopen", side_effect=err), \
             mock.patch("sys.stderr") as se, mock.patch("sys.stdout") as so:
            rc = pr.main(argv)
            captured["err"] = "".join(
                c.args[0] for c in se.write.call_args_list if c.args)
            captured["out"] = "".join(
                c.args[0] for c in so.write.call_args_list if c.args)
        self.assertNotEqual(rc, 0)
        self.assertNotIn(self.SECRET, captured["err"])
        self.assertNotIn(self.SECRET, captured["out"])


# --------------------------------------------------------------------------
# Local ref-range mode, provider-aware diff materialization, and main()
# --------------------------------------------------------------------------

class TestResolveLocal(unittest.TestCase):
    def test_local_ref_range_uses_git_rev_parse_read_only(self):
        with mock.patch("pr_resolver._run", side_effect=["aaa\n", "bbb\n"]) as m:
            rec = pr.resolve_local("main", "feature", repo_dir="/tmp/x")
        first = m.call_args_list[0].args[0]
        self.assertEqual(first[0], "git")
        self.assertIn("rev-parse", first)
        self.assertEqual(rec["provider"], "local")
        self.assertEqual(rec["base_sha"], "aaa")
        self.assertEqual(rec["head_sha"], "bbb")
        # the untrusted ref is option-terminated so it can never be a flag
        self.assertIn("--end-of-options", first)
        self.assertEqual(first[-1], "main")

    def test_local_leading_dash_ref_is_not_a_flag(self):
        # A malicious --base="--output=/tmp/x" must reach git AFTER
        # --end-of-options, never as a parsed flag.
        with mock.patch("pr_resolver._run", side_effect=["a\n", "b\n"]) as m:
            pr.resolve_local("--output=/tmp/x", "feature", repo_dir="/tmp/x")
        argv = m.call_args_list[0].args[0]
        self.assertIn("--end-of-options", argv)
        self.assertLess(argv.index("--end-of-options"),
                        argv.index("--output=/tmp/x"))


class TestResolveDiff(unittest.TestCase):
    """resolve_diff runs, in order: provider fetches (base, head, PR-ref), then a
    `git rev-parse --verify` reachability check per SHA, then `git diff`. The fake
    _run below routes by verb so tests are not coupled to the exact call count."""

    def _record(self, **over):
        rec = {"provider": "github", "repo": "acme/widgets", "pr_id": "42",
               "base_sha": "aaa", "head_sha": "bbb",
               "base_ref": "main", "head_ref": "feature"}
        rec.update(over)
        return rec

    def _fake_run(self, *, diff="diff --git ...\n", reachable=True,
                  fail_fetch=False):
        """Build a fake _run that records calls and routes by git verb."""
        calls = []

        def run(argv, *, cwd=None):
            calls.append(argv)
            verb = argv[1]
            if verb == "fetch":
                if fail_fetch:
                    raise pr.ResolverError("fetch failed")
                return ""
            if verb == "rev-parse":
                if reachable:
                    return "ok\n"
                raise pr.ResolverError("Needed a single revision")
            if verb == "diff":
                return diff
            return ""
        run.calls = calls
        return run

    def test_github_fetches_base_head_and_pr_ref_then_diffs_read_only(self):
        run = self._fake_run()
        with mock.patch("pr_resolver._run", side_effect=run):
            out = pr.resolve_diff(self._record(), repo_dir="/tmp/x")
        argvs = run.calls
        for argv in argvs:                       # every call is read-only git
            self.assertEqual(argv[0], "git")
            for w in ("push", "commit", "merge", "checkout", "reset", "rebase"):
                self.assertNotIn(w, argv)
        verbs = [a[1] for a in argvs]
        self.assertEqual(verbs[-1], "diff")      # diff is last
        self.assertEqual(verbs.count("fetch"), 3)  # base, head, PR ref
        # base sha, head sha, and the GitHub PR head ref are each fetched
        self.assertTrue(any(a[1] == "fetch" and "aaa" in a for a in argvs))
        self.assertTrue(any(a[1] == "fetch" and "bbb" in a for a in argvs))
        self.assertTrue(any("pull/42/head" in tok for a in argvs for tok in a))
        self.assertIn("diff --git", out)

    def test_diff_argv_terminates_user_shas_as_options(self):
        run = self._fake_run()
        with mock.patch("pr_resolver._run", side_effect=run):
            pr.resolve_diff(self._record(), repo_dir="/tmp/x")
        diff_argv = [a for a in run.calls if a[1] == "diff"][-1]
        self.assertEqual(diff_argv[0:2], ["git", "diff"])
        self.assertIn("--end-of-options", diff_argv)
        idx = diff_argv.index("--end-of-options")
        self.assertEqual(diff_argv[idx + 1], "aaa..bbb")

    def test_azure_fetches_pr_merge_ref(self):
        rec = self._record(provider="azure", repo="org/proj/repo", pr_id="9",
                            base_sha="a1", head_sha="b1")
        run = self._fake_run()
        with mock.patch("pr_resolver._run", side_effect=run):
            pr.resolve_diff(rec, repo_dir="/tmp/x")
        self.assertTrue(any("refs/pull/9/merge" in tok
                            for a in run.calls for tok in a))

    def test_bitbucket_fetches_source_branch(self):
        rec = self._record(provider="bitbucket", repo="team/repo",
                            head_ref="feature")
        run = self._fake_run()
        with mock.patch("pr_resolver._run", side_effect=run):
            pr.resolve_diff(rec, repo_dir="/tmp/x")
        self.assertTrue(any("feature" in tok for a in run.calls for tok in a))

    def test_local_record_uses_plain_fetch(self):
        rec = self._record(provider="local", repo="/tmp/x")
        run = self._fake_run()
        with mock.patch("pr_resolver._run", side_effect=run):
            pr.resolve_diff(rec, repo_dir="/tmp/x")
        fetches = [a for a in run.calls if a[1] == "fetch"]
        self.assertEqual(fetches, [["git", "fetch", "--quiet"]])  # no SHA args

    def test_missing_shas_raise(self):
        with self.assertRaises(pr.ResolverError):
            pr.resolve_diff(self._record(base_sha=""), repo_dir="/tmp/x")

    def test_fetch_failure_is_tolerated_when_commits_reachable(self):
        # Every fetch raises, but the commits are already reachable -> success.
        run = self._fake_run(fail_fetch=True, reachable=True)
        with mock.patch("pr_resolver._run", side_effect=run):
            out = pr.resolve_diff(self._record(), repo_dir="/tmp/x")
        self.assertIn("diff --git", out)

    def test_unreachable_commit_raises_actionable(self):
        # Fetches succeed but rev-parse --verify reports the commit absent.
        run = self._fake_run(reachable=False)
        with mock.patch("pr_resolver._run", side_effect=run):
            with self.assertRaises(pr.ResolverError) as ctx:
                pr.resolve_diff(self._record(), repo_dir="/tmp/x")
        self.assertIn("not reachable", str(ctx.exception))
        # the diff step must never run once reachability fails
        self.assertFalse(any(a[1] == "diff" for a in run.calls))

    def test_empty_diff_for_distinct_shas_raises(self):
        # git diff returns exit 0 + empty output even though base != head:
        # that is a silent half-resolve and must fail loudly.
        run = self._fake_run(diff="   \n")
        with mock.patch("pr_resolver._run", side_effect=run):
            with self.assertRaises(pr.ResolverError) as ctx:
                pr.resolve_diff(self._record(), repo_dir="/tmp/x")
        self.assertIn("empty diff", str(ctx.exception))


# --------------------------------------------------------------------------
# _pr_head_refspec: the provider PR-head refspec (slice s8)
#
# The positive github/azure/bitbucket refspec branches are already exercised
# indirectly by TestResolveDiff (pull/42/head, refs/pull/9/merge, the bitbucket
# source branch). This pins the function directly and, crucially, covers the
# L384 `return None` tail -- a record with no matching provider/pr_id/head_ref.
# --------------------------------------------------------------------------

class TestPrHeadRefspec(unittest.TestCase):
    def test_github_and_azure_and_bitbucket_positive_refspecs(self):
        self.assertEqual(
            pr._pr_head_refspec({"provider": "github", "pr_id": "42"}),
            "pull/42/head")
        self.assertEqual(
            pr._pr_head_refspec({"provider": "azure", "pr_id": "9"}),
            "refs/pull/9/merge")
        self.assertEqual(
            pr._pr_head_refspec(
                {"provider": "bitbucket", "head_ref": "feature"}),
            "feature")

    def test_returns_none_when_no_provider_ref_applies(self):
        # A local record, and remote records missing the field each provider
        # needs, all fall through to the `return None` tail (pr_resolver L384).
        for rec in (
            {"provider": "local"},
            {"provider": "github", "pr_id": ""},        # github needs pr_id
            {"provider": "azure", "pr_id": ""},         # azure needs pr_id
            {"provider": "bitbucket", "head_ref": ""},  # bitbucket needs head_ref
            {},                                          # no provider at all
        ):
            self.assertIsNone(pr._pr_head_refspec(rec))


class TestNormalizedRequiresFields(unittest.TestCase):
    def test_empty_sha_field_raises(self):
        # A provider payload missing a merge commit -> empty base_sha must fail
        # rather than emit a structurally-valid but semantically-empty record.
        payload = json.dumps({
            "baseRefName": "main", "headRefName": "feature",
            "baseRefOid": "", "headRefOid": "bbb",   # empty base sha
            "title": "T", "body": "B",
        })
        parsed = pr.parse_pr_url("https://github.com/acme/widgets/pull/42")
        with mock.patch("pr_resolver.shutil.which", return_value="/usr/bin/gh"), \
             mock.patch("pr_resolver._run", return_value=payload):
            with self.assertRaises(pr.ResolverError) as ctx:
                pr.resolve(parsed)
        self.assertIn("base_sha", str(ctx.exception))


class TestMain(unittest.TestCase):
    def test_emits_json_for_url(self):
        rec = {"provider": "github", "pr_id": "42"}
        with mock.patch("pr_resolver.resolve", return_value=rec), \
             mock.patch("sys.stdout") as out:
            rc = pr.main(["https://github.com/acme/widgets/pull/42"])
        self.assertEqual(rc, 0)
        printed = "".join(c.args[0] for c in out.write.call_args_list if c.args)
        self.assertIn('"provider"', printed)

    def test_diff_flag_prints_diff_after_json(self):
        rec = {"provider": "github", "pr_id": "42",
               "base_sha": "a", "head_sha": "b"}
        with mock.patch("pr_resolver.resolve", return_value=rec), \
             mock.patch("pr_resolver.resolve_diff", return_value="DIFFTEXT"), \
             mock.patch("sys.stdout") as out:
            rc = pr.main(["https://github.com/acme/widgets/pull/42", "--diff"])
        self.assertEqual(rc, 0)
        printed = "".join(c.args[0] for c in out.write.call_args_list if c.args)
        self.assertIn("DIFFTEXT", printed)
        self.assertLess(printed.index('"provider"'), printed.index("DIFFTEXT"))

    def test_local_mode_emits_json(self):
        rec = {"provider": "local", "base_sha": "a", "head_sha": "b"}
        with mock.patch("pr_resolver.resolve_local", return_value=rec), \
             mock.patch("sys.stdout") as out:
            rc = pr.main(["--base", "main", "--head", "feature"])
        self.assertEqual(rc, 0)
        printed = "".join(c.args[0] for c in out.write.call_args_list if c.args)
        self.assertIn('"local"', printed)

    def test_resolver_error_exits_nonzero(self):
        rc = pr.main(["https://gitlab.com/a/b/pull/1"])
        self.assertNotEqual(rc, 0)

    def test_requires_url_or_ref_range(self):
        self.assertNotEqual(pr.main([]), 0)


class TestResolveLocalRealGit(unittest.TestCase):
    """Exercises resolve_local / resolve_diff against a REAL git repo (NO _run
    mock). Regression guard for the bug where `git rev-parse` WITHOUT --verify
    echoes the `--end-of-options` token into the captured SHA (base_sha became
    "--end-of-options\\n<sha>", which then broke resolve_diff's reachability
    check end-to-end for the local --base/--head path). The mocked
    TestResolveLocal above cannot catch this class — it stubs _run and never
    runs git, so it never sees rev-parse's real stdout."""

    _SHA = re.compile(r"^[0-9a-f]{40}$")

    def _git(self, *args):
        subprocess.run(["git", *args], cwd=self._tmp, check=True,
                       capture_output=True, text=True)

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="pr_resolver_realgit_")
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self._git("init", "-q")
        self._git("config", "user.email", "t@example.com")
        self._git("config", "user.name", "Test")
        Path(self._tmp, "f.txt").write_text("base\n")
        self._git("add", "f.txt")
        self._git("commit", "-q", "-m", "base")
        Path(self._tmp, "f.txt").write_text("head\n")
        self._git("commit", "-q", "-am", "head")

    def test_resolve_local_yields_clean_shas(self):
        rec = pr.resolve_local("HEAD~1", "HEAD", repo_dir=self._tmp)
        # base_sha/head_sha must be bare 40-hex, never carrying the echoed
        # `--end-of-options` token or an embedded newline.
        self.assertRegex(rec["base_sha"], self._SHA)
        self.assertRegex(rec["head_sha"], self._SHA)
        self.assertNotIn("--end-of-options", rec["base_sha"])
        self.assertNotIn("--end-of-options", rec["head_sha"])

    def test_resolve_diff_returns_nonempty_local_diff(self):
        rec = pr.resolve_local("HEAD~1", "HEAD", repo_dir=self._tmp)
        diff = pr.resolve_diff(rec, repo_dir=self._tmp)
        self.assertTrue(diff.strip(), "local ref-range diff must be non-empty")
        self.assertIn("f.txt", diff)


if __name__ == "__main__":
    unittest.main()
