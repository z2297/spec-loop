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
import sys
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


if __name__ == "__main__":
    unittest.main()
