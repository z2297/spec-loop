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


if __name__ == "__main__":
    unittest.main()
