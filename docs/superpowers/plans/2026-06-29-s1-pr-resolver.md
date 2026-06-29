<!-- spec-loop: risk-tier=2 review="pr-review-toolkit:review-pr" simplify="pr-review-toolkit:review-pr simplify" blocking-bar="P0,P1" surface="scripts/pr_resolver.py, scripts/test_pr_resolver.py — subsystems: pr-resolver, scripts, provider-integration (security-sensitive: untrusted-URL parsing + subprocess CLI invocation; escalate review to Tier 3 if the diff warrants)" -->

# PR Resolver (provider-agnostic, READ-ONLY) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a stdlib-only Python module `scripts/pr_resolver.py` that parses a PR URL from Azure DevOps / GitHub / Bitbucket (or an explicit local `--base/--head` ref-range), detects the provider, resolves the PR READ-ONLY to a normalized JSON record via the official CLI or REST, and can materialize the base..head diff locally — with a full stdlib `unittest` suite that mocks all network/CLI.

**Architecture:** One self-contained module matching the idiom of `scripts/release.py` / `scripts/validate_marketplace.py` (module docstring, pure helpers, `main() -> int`, `__main__` guard, `json.dumps(ensure_ascii=False)`). Provider detection is a pure function over a parsed `urllib.parse.urlsplit` host. Resolution is split per provider, each returning the same `NormalizedRecord` shape; all external calls go through a single `_run(argv)` subprocess wrapper (list-args, `shell=False`) and a single `_http_get(url, headers)` urllib wrapper, so the no-shell-injection guarantee is provable in one place. Missing CLI/credentials raise a typed `ResolverError` with an actionable message and map to a non-zero exit. `resolve_diff(record)` fetches refs and produces a local `git diff base_sha..head_sha`.

**Tech Stack:** Python 3 standard library only — `argparse`, `urllib.parse`, `urllib.request`, `json`, `subprocess`, `shutil.which`, `os`, `re`, `sys`. Tests: `unittest` + `unittest.mock`.

## Global Constraints

- Standard library ONLY — zero third-party dependencies.
- Module idiom: module docstring; `main() -> int`; `if __name__ == "__main__": sys.exit(main())`; `json.dumps(..., ensure_ascii=False)` for output.
- READ-ONLY: only ever invoke read verbs (`gh pr view`/`gh pr diff`, `az repos pr show`, `git fetch`/`diff`/`log`/`show`, HTTP GET). NEVER `gh pr merge|comment|review|close|edit`, `az ... create|vote`, `git push|commit|merge`, or any mutating POST.
- SECURITY: treat URL / PR-id / refs as UNTRUSTED. Validate `pr_id` as `^[0-9]+$`; validate host against the known provider host set; NEVER interpolate raw user input into a shell string — `subprocess` list-args only, never `shell=True`.
- Stay strictly within `scripts/pr_resolver.py` and `scripts/test_pr_resolver.py`. Do NOT touch command/agent/skill/release files (other slices).
- `scripts/validate_marketplace.py` does NOT lint `scripts/*.py`; the unittest file is the sole automated guard. No live network/CLI in tests.

---

### Task 1: URL parsing + provider detection (pure, no I/O)

**Files:**
- Create: `scripts/pr_resolver.py`
- Test: `scripts/test_pr_resolver.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `ResolverError(Exception)` — carries an actionable message.
  - `PROVIDER_HOSTS` — mapping used for detection.
  - `detect_provider(host: str) -> str` — returns `"azure" | "github" | "bitbucket"`; raises `ResolverError` for unknown hosts. `host` is lowercased; `*.visualstudio.com` and `dev.azure.com` -> `"azure"`; `github.com`/`www.github.com` -> `"github"`; `bitbucket.org`/`www.bitbucket.org` -> `"bitbucket"`.
  - `validate_pr_id(pr_id: str) -> str` — returns `pr_id` if it matches `^[0-9]+$`, else raises `ResolverError`.
  - `parse_pr_url(url: str) -> dict` — returns `{"provider", "host", "repo", "pr_id", "web_url"}`. Raises `ResolverError` on malformed URL, non-http(s) scheme, unknown host, or un-extractable pr_id. Supported forms:
    - GitHub: `https://github.com/<owner>/<repo>/pull/<n>` -> repo=`<owner>/<repo>`, pr_id=`<n>`.
    - Bitbucket: `https://bitbucket.org/<workspace>/<repo>/pull-requests/<n>` -> repo=`<workspace>/<repo>`, pr_id=`<n>`.
    - Azure (dev.azure.com): `https://dev.azure.com/<org>/<project>/_git/<repo>/pullrequest/<n>` -> repo=`<org>/<project>/<repo>`, pr_id=`<n>`.
    - Azure (visualstudio.com): `https://<org>.visualstudio.com/<project>/_git/<repo>/pullrequest/<n>` -> repo=`<org>/<project>/<repo>`, pr_id=`<n>`.

- [ ] **Step 1: Write the failing tests**

```python
#!/usr/bin/env python3
"""Tests for the read-only provider-agnostic PR resolver (stdlib unittest).

Covers URL parsing + provider detection for all three providers (incl. both
Azure DevOps URL forms), rejection of malformed / unknown-host URLs, pr_id
validation, READ-ONLY resolution against mocked CLIs/REST, the actionable
failure when a CLI/credential is absent, and the no-shell-injection guarantee
(every subprocess call uses list-args with shell=False).

`scripts/validate_marketplace.py` does NOT lint scripts/*.py, so this is the
sole automated guard on the resolver. Standard library only. No live network/CLI.

Usage:
    python3 scripts/test_pr_resolver.py
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pr_resolver as pr  # noqa: E402


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


class TestParsePrUrl(unittest.TestCase):
    def test_github(self):
        rec = pr.parse_pr_url("https://github.com/acme/widgets/pull/42")
        self.assertEqual(rec["provider"], "github")
        self.assertEqual(rec["repo"], "acme/widgets")
        self.assertEqual(rec["pr_id"], "42")

    def test_bitbucket(self):
        rec = pr.parse_pr_url(
            "https://bitbucket.org/team/repo/pull-requests/7")
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
        ):
            with self.assertRaises(pr.ResolverError):
                pr.parse_pr_url(bad)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 scripts/test_pr_resolver.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'pr_resolver'` (or AttributeError once the file exists but functions are missing).

- [ ] **Step 3: Write minimal implementation**

```python
#!/usr/bin/env python3
"""Provider-agnostic, READ-ONLY pull-request resolver (standard library only).

Given a PR URL from Azure DevOps, GitHub, or Bitbucket (or an explicit local
--base/--head ref-range), this parses and validates the URL, DETECTS the
provider, resolves the PR READ-ONLY to a normalized record, and emits it as
JSON on stdout. It prefers the official CLI when available (`gh pr view`,
`az repos pr show`) and uses Bitbucket's REST API over urllib; if the relevant
CLI/credential is absent it FAILS with an actionable message and a non-zero
exit — it never half-resolves and never mutates the PR or the repo.

SECURITY: the URL / pr_id / refs are UNTRUSTED. pr_id is validated as ^[0-9]+$,
the host is validated against the known provider hosts, and user input is NEVER
interpolated into a shell string — every external command runs through _run()
with list-args and shell=False, and only READ verbs are ever invoked.

Usage:
    python3 scripts/pr_resolver.py <pr-url>
    python3 scripts/pr_resolver.py <pr-url> --diff
    python3 scripts/pr_resolver.py --base <ref> --head <ref> [--repo-dir .]
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

PR_ID_RE = re.compile(r"^[0-9]+$")

# Known provider hosts. visualstudio.com is matched by suffix (per-org subdomain).
PROVIDER_HOSTS = {
    "github.com": "github",
    "www.github.com": "github",
    "bitbucket.org": "bitbucket",
    "www.bitbucket.org": "bitbucket",
    "dev.azure.com": "azure",
}


class ResolverError(Exception):
    """Raised for any unrecoverable resolver condition (bad input, missing
    CLI/credential, failed read). Carries an actionable, user-facing message."""


def detect_provider(host: str) -> str:
    h = (host or "").strip().lower()
    if h in PROVIDER_HOSTS:
        return PROVIDER_HOSTS[h]
    if h.endswith(".visualstudio.com"):
        return "azure"
    raise ResolverError(
        f"unsupported host {host!r}: expected one of github.com, bitbucket.org, "
        "dev.azure.com, or <org>.visualstudio.com"
    )


def validate_pr_id(pr_id: str) -> str:
    if not PR_ID_RE.match(pr_id or ""):
        raise ResolverError(
            f"invalid pull-request id {pr_id!r}: must match ^[0-9]+$"
        )
    return pr_id


def parse_pr_url(url: str) -> dict:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ResolverError(f"not an http(s) URL: {url!r}")
    host = parts.hostname or ""
    provider = detect_provider(host)
    segs = [s for s in parts.path.split("/") if s]
    if provider == "github":
        # /<owner>/<repo>/pull/<n>
        if len(segs) >= 4 and segs[2] == "pull":
            repo, pr_id = f"{segs[0]}/{segs[1]}", segs[3]
        else:
            raise ResolverError(f"not a GitHub PR URL: {url!r}")
    elif provider == "bitbucket":
        # /<workspace>/<repo>/pull-requests/<n>
        if len(segs) >= 4 and segs[2] == "pull-requests":
            repo, pr_id = f"{segs[0]}/{segs[1]}", segs[3]
        else:
            raise ResolverError(f"not a Bitbucket PR URL: {url!r}")
    else:  # azure
        repo, pr_id = _parse_azure_path(segs, host, url)
    validate_pr_id(pr_id)
    return {
        "provider": provider,
        "host": host.lower(),
        "repo": repo,
        "pr_id": pr_id,
        "web_url": url,
    }


def _parse_azure_path(segs: list, host: str, url: str):
    # dev.azure.com:  /<org>/<project>/_git/<repo>/pullrequest/<n>
    # visualstudio:   /<project>/_git/<repo>/pullrequest/<n>  (org is subdomain)
    if "_git" not in segs or "pullrequest" not in segs:
        raise ResolverError(f"not an Azure DevOps PR URL: {url!r}")
    gi = segs.index("_git")
    pi = segs.index("pullrequest")
    if pi + 1 >= len(segs) or pi <= gi:
        raise ResolverError(f"not an Azure DevOps PR URL: {url!r}")
    repo_name = segs[gi + 1]
    pr_id = segs[pi + 1]
    if host.lower().endswith(".visualstudio.com"):
        org = host.split(".", 1)[0]
        project = segs[gi - 1] if gi >= 1 else ""
    else:  # dev.azure.com
        org = segs[0] if gi >= 2 else ""
        project = segs[gi - 1] if gi >= 1 else ""
    if not org or not project:
        raise ResolverError(f"not an Azure DevOps PR URL: {url!r}")
    return f"{org}/{project}/{repo_name}", pr_id
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 scripts/test_pr_resolver.py`
Expected: PASS (all parsing/detection/validation tests green).

- [ ] **Step 5: Commit**

```bash
git add scripts/pr_resolver.py scripts/test_pr_resolver.py
git commit -m "feat(pr-resolver): URL parsing + provider detection (read-only, stdlib)"
```

---

### Task 2: READ-ONLY resolution via CLI/REST + missing-credential failure

**Files:**
- Modify: `scripts/pr_resolver.py`
- Test: `scripts/test_pr_resolver.py`

**Interfaces:**
- Consumes: `parse_pr_url`, `ResolverError` from Task 1.
- Produces:
  - `_run(argv: list, *, cwd=None) -> str` — runs `argv` via `subprocess.run(argv, shell=False, ...)`, returns stdout, raises `ResolverError` on non-zero exit / missing binary. The ONLY subprocess entry point.
  - `_http_get(url: str, headers: dict | None = None) -> bytes` — GET via `urllib.request` (method defaults to GET; never sets a mutating method/body). The ONLY network entry point.
  - `resolve(parsed: dict) -> dict` — dispatches to the per-provider resolver; returns the normalized record `{provider, host, repo, pr_id, base_ref, base_sha, head_ref, head_sha, title, description, web_url}`.
  - `_resolve_github(parsed)`, `_resolve_azure(parsed)`, `_resolve_bitbucket(parsed)` — each returns the normalized record; each raises `ResolverError` with an actionable message (e.g. `gh auth login`, `az login`, named env var) when the CLI/credential is absent.

- [ ] **Step 1: Write the failing tests**

```python
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
        self.assertNotIn("merge", argv)
        self.assertNotIn("comment", argv)
        self.assertEqual(rec["base_ref"], "main")
        self.assertEqual(rec["head_sha"], "bbb")
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
        self.assertNotIn("vote", argv)
        self.assertNotIn("create", argv)
        self.assertEqual(rec["base_ref"], "main")
        self.assertEqual(rec["head_ref"], "feature")

    def test_missing_az_cli_is_actionable(self):
        parsed = pr.parse_pr_url(
            "https://dev.azure.com/org/proj/_git/repo/pullrequest/9")
        with mock.patch("pr_resolver.shutil.which", return_value=None):
            with self.assertRaises(pr.ResolverError) as ctx:
                pr.resolve(parsed)
        self.assertIn("az", str(ctx.exception).lower())


class TestResolveBitbucket(unittest.TestCase):
    def test_uses_http_get(self):
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
        self.assertIn("api.bitbucket.org", url)
        self.assertEqual(rec["base_ref"], "main")
        self.assertEqual(rec["head_sha"], "bbb")

    def test_missing_token_is_actionable(self):
        parsed = pr.parse_pr_url(
            "https://bitbucket.org/team/repo/pull-requests/7")
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(pr.ResolverError) as ctx:
                pr.resolve(parsed)
        self.assertIn("BITBUCKET_TOKEN", str(ctx.exception))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 scripts/test_pr_resolver.py`
Expected: FAIL with `AttributeError`/`ResolverError` mismatch — `_run`, `_http_get`, `resolve` not yet defined.

- [ ] **Step 3: Write minimal implementation**

Add `import shutil` to the imports, then append:

```python
def _run(argv, *, cwd=None) -> str:
    """Run a READ-ONLY command via list-args (shell=False). Sole subprocess
    entry point — keeps the no-shell-injection guarantee provable in one place."""
    try:
        proc = subprocess.run(
            argv, cwd=cwd, shell=False,
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError as exc:
        raise ResolverError(
            f"required command not found: {argv[0]!r} ({exc})"
        ) from exc
    if proc.returncode != 0:
        raise ResolverError(
            f"command failed ({argv[0]} exit {proc.returncode}): "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc.stdout


def _http_get(url, headers=None) -> bytes:
    """HTTP GET via urllib (READ-only; never sets a body or mutating method)."""
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise ResolverError(f"HTTP {exc.code} fetching {url}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise ResolverError(f"network error fetching {url}: {exc.reason}") from exc


def _normalized(parsed, *, base_ref, base_sha, head_ref, head_sha, title, description):
    return {
        "provider": parsed["provider"],
        "host": parsed["host"],
        "repo": parsed["repo"],
        "pr_id": parsed["pr_id"],
        "base_ref": base_ref,
        "base_sha": base_sha,
        "head_ref": head_ref,
        "head_sha": head_sha,
        "title": title,
        "description": description,
        "web_url": parsed["web_url"],
    }


def _strip_ref(ref):
    """refs/heads/main -> main (Azure returns fully-qualified ref names)."""
    return (ref or "").removeprefix("refs/heads/")


def resolve(parsed: dict) -> dict:
    return {
        "github": _resolve_github,
        "azure": _resolve_azure,
        "bitbucket": _resolve_bitbucket,
    }[parsed["provider"]](parsed)


def _resolve_github(parsed: dict) -> dict:
    if not shutil.which("gh"):
        raise ResolverError(
            "GitHub CLI 'gh' not found. Install it and run `gh auth login`."
        )
    fields = "baseRefName,headRefName,baseRefOid,headRefOid,title,body"
    out = _run([
        "gh", "pr", "view", validate_pr_id(parsed["pr_id"]),
        "--repo", parsed["repo"], "--json", fields,
    ])
    d = json.loads(out)
    return _normalized(
        parsed,
        base_ref=d.get("baseRefName", ""), base_sha=d.get("baseRefOid", ""),
        head_ref=d.get("headRefName", ""), head_sha=d.get("headRefOid", ""),
        title=d.get("title", ""), description=d.get("body", ""),
    )


def _resolve_azure(parsed: dict) -> dict:
    if not shutil.which("az"):
        raise ResolverError(
            "Azure CLI 'az' not found. Install it (with the azure-devops "
            "extension) and run `az login`."
        )
    org, project, repo = parsed["repo"].split("/", 2)
    org_url = (f"https://{org}.visualstudio.com"
               if parsed["host"].endswith(".visualstudio.com")
               else f"https://dev.azure.com/{org}")
    out = _run([
        "az", "repos", "pr", "show",
        "--id", validate_pr_id(parsed["pr_id"]),
        "--org", org_url, "--output", "json",
    ])
    d = json.loads(out)
    return _normalized(
        parsed,
        base_ref=_strip_ref(d.get("targetRefName")),
        base_sha=(d.get("lastMergeTargetCommit") or {}).get("commitId", ""),
        head_ref=_strip_ref(d.get("sourceRefName")),
        head_sha=(d.get("lastMergeSourceCommit") or {}).get("commitId", ""),
        title=d.get("title", ""), description=d.get("description", ""),
    )


def _resolve_bitbucket(parsed: dict) -> dict:
    token = os.environ.get("BITBUCKET_TOKEN")
    if not token:
        raise ResolverError(
            "Bitbucket access requires the BITBUCKET_TOKEN environment "
            "variable (an app password / access token with PR read scope)."
        )
    api = (
        f"https://api.bitbucket.org/2.0/repositories/{parsed['repo']}"
        f"/pullrequests/{validate_pr_id(parsed['pr_id'])}"
    )
    raw = _http_get(api, headers={"Authorization": f"Bearer {token}"})
    d = json.loads(raw.decode("utf-8"))
    src, dst = d.get("source") or {}, d.get("destination") or {}
    return _normalized(
        parsed,
        base_ref=(dst.get("branch") or {}).get("name", ""),
        base_sha=(dst.get("commit") or {}).get("hash", ""),
        head_ref=(src.get("branch") or {}).get("name", ""),
        head_sha=(src.get("commit") or {}).get("hash", ""),
        title=d.get("title", ""), description=d.get("description", ""),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 scripts/test_pr_resolver.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/pr_resolver.py scripts/test_pr_resolver.py
git commit -m "feat(pr-resolver): read-only CLI/REST resolution with actionable missing-credential errors"
```

---

### Task 3: Local ref-range mode, resolve_diff, and main()/CLI

**Files:**
- Modify: `scripts/pr_resolver.py`
- Test: `scripts/test_pr_resolver.py`

**Interfaces:**
- Consumes: `_run`, `resolve`, `parse_pr_url`, `_normalized`, `ResolverError`.
- Produces:
  - `resolve_local(base, head, repo_dir=".") -> dict` — normalized record for an explicit local `--base/--head` ref-range; provider `"local"`. Resolves SHAs via `git rev-parse` (READ verb).
  - `resolve_diff(record, repo_dir=".") -> str` — `git fetch` (read) then return `git diff <base_sha>..<head_sha>` text. Uses `_run` (list-args) only.
  - `main() -> int` — argparse: positional optional `url`; `--base`, `--head`, `--repo-dir`, `--diff`. Emits the record as `json.dumps(record, ensure_ascii=False, indent=2)` on stdout; if `--diff`, prints the diff after. Maps `ResolverError` to stderr + exit 2. Mutually requires either a URL or both `--base`/`--head`.
  - `if __name__ == "__main__": sys.exit(main())`.

- [ ] **Step 1: Write the failing tests**

```python
class TestResolveLocal(unittest.TestCase):
    def test_local_ref_range_uses_git_rev_parse(self):
        with mock.patch("pr_resolver._run", side_effect=["aaa\n", "bbb\n"]) as m:
            rec = pr.resolve_local("main", "feature", repo_dir="/tmp/x")
        first = m.call_args_list[0].args[0]
        self.assertEqual(first[0], "git")
        self.assertIn("rev-parse", first)
        self.assertEqual(rec["provider"], "local")
        self.assertEqual(rec["base_sha"], "aaa")
        self.assertEqual(rec["head_sha"], "bbb")


class TestResolveDiff(unittest.TestCase):
    def test_fetch_then_diff_read_only(self):
        rec = {"base_sha": "aaa", "head_sha": "bbb",
               "base_ref": "main", "head_ref": "feature"}
        with mock.patch("pr_resolver._run",
                        side_effect=["", "diff --git ...\n"]) as m:
            out = pr.resolve_diff(rec, repo_dir="/tmp/x")
        verbs = [c.args[0][1] for c in m.call_args_list]  # git <verb> ...
        self.assertEqual(verbs, ["fetch", "diff"])         # read verbs only
        for c in m.call_args_list:
            argv = c.args[0]
            self.assertEqual(argv[0], "git")
            for w in ("push", "commit", "merge", "checkout"):
                self.assertNotIn(w, argv)
        self.assertIn("diff --git", out)


class TestMain(unittest.TestCase):
    def test_emits_json_for_url(self):
        rec = {"provider": "github", "pr_id": "42"}
        with mock.patch("pr_resolver.resolve", return_value=rec), \
             mock.patch("sys.stdout") as out:
            rc = pr.main(["https://github.com/acme/widgets/pull/42"])
        self.assertEqual(rc, 0)
        printed = "".join(c.args[0] for c in out.write.call_args_list)
        self.assertIn('"provider"', printed)

    def test_resolver_error_exits_nonzero(self):
        rc = pr.main(["https://gitlab.com/a/b/pull/1"])
        self.assertNotEqual(rc, 0)

    def test_requires_url_or_ref_range(self):
        self.assertNotEqual(pr.main([]), 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 scripts/test_pr_resolver.py`
Expected: FAIL — `resolve_local`, `resolve_diff`, `main(argv)` not yet defined / `main` not accepting argv.

- [ ] **Step 3: Write minimal implementation**

Append:

```python
def resolve_local(base, head, repo_dir=".") -> dict:
    base_sha = _run(["git", "rev-parse", base], cwd=repo_dir).strip()
    head_sha = _run(["git", "rev-parse", head], cwd=repo_dir).strip()
    return {
        "provider": "local", "host": "", "repo": repo_dir,
        "pr_id": "", "base_ref": base, "base_sha": base_sha,
        "head_ref": head, "head_sha": head_sha,
        "title": "", "description": "", "web_url": "",
    }


def resolve_diff(record, repo_dir=".") -> str:
    """Materialize base..head as a local unified diff so downstream reviewers
    see identical bytes. READ verbs only: git fetch (read) then git diff."""
    base, head = record["base_sha"], record["head_sha"]
    if not base or not head:
        raise ResolverError("record is missing base_sha/head_sha; cannot diff")
    _run(["git", "fetch", "--quiet"], cwd=repo_dir)
    return _run(["git", "diff", f"{base}..{head}"], cwd=repo_dir)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Read-only PR resolver (Azure DevOps / GitHub / Bitbucket).")
    ap.add_argument("url", nargs="?", help="pull-request URL")
    ap.add_argument("--base", help="base ref for an explicit local ref-range")
    ap.add_argument("--head", help="head ref for an explicit local ref-range")
    ap.add_argument("--repo-dir", default=".", help="local repo for diff/refs")
    ap.add_argument("--diff", action="store_true",
                    help="also emit the local base..head diff")
    args = ap.parse_args(argv)

    try:
        if args.url:
            record = resolve(parse_pr_url(args.url))
        elif args.base and args.head:
            record = resolve_local(args.base, args.head, repo_dir=args.repo_dir)
        else:
            raise ResolverError(
                "provide a PR URL, or both --base and --head for a local "
                "ref-range")
        print(json.dumps(record, ensure_ascii=False, indent=2))
        if args.diff:
            print(resolve_diff(record, repo_dir=args.repo_dir))
        return 0
    except ResolverError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the full suite + validator**

Run: `python3 scripts/test_pr_resolver.py`
Expected: PASS (all classes).
Run: `python3 scripts/validate_marketplace.py`
Expected: exit 0.
Run: `python3 scripts/pr_resolver.py https://github.com/acme/widgets/pull/42 2>&1 || true` and `python3 scripts/pr_resolver.py --help` — demonstrate parse path + usage with no network.

- [ ] **Step 5: Commit**

```bash
git add scripts/pr_resolver.py scripts/test_pr_resolver.py
git commit -m "feat(pr-resolver): local ref-range mode, resolve_diff, and CLI main()"
```

---

## Self-Review

**Spec coverage:**
- stdlib-only idiom (docstring/main/guard/ensure_ascii) — Tasks 1–3. ✓
- parse + validate URL with urllib.parse + provider detection (azure/github/bitbucket, both ADO forms) — Task 1. ✓
- normalized record with all 10 fields — Task 2 `_normalized`. ✓
- prefer official CLI (gh / az) + Bitbucket REST over urllib — Task 2. ✓
- absent CLI/credential -> actionable message + non-zero exit, never half-resolve — Task 2 + `main` exit 2. ✓
- emit JSON on stdout — Task 3 `main`. ✓
- security: pr_id `^[0-9]+$`, host allow-list, no shell=True, list-args, READ verbs only — Tasks 1–3 + dedicated tests. ✓
- resolve_diff materializes base..head locally via git fetch + git diff (throwaway-branch idiom acknowledged; git diff is the primary, simplest read path) — Task 3. ✓
- tests cover all three providers, malformed/unknown-host rejection, pr_id validation, no-shell assertion, mocked network/CLI — Tasks 1–3. ✓

**Placeholder scan:** none — every code step is complete.

**Type consistency:** `_normalized`, `resolve`, `parse_pr_url`, `_run`, `_http_get`, `resolve_local`, `resolve_diff`, `main(argv=None)` names/signatures consistent across tasks and tests.

---

## Iron Council amendments (folded — ENDORSE_WITH_CONCERNS, 2 non-safety OBJECTs)

These are binding refinements to the tasks above, folded in before execution:

1. **`validate_segment(s)` (new pure helper, Task 1).** `^[A-Za-z0-9._~][A-Za-z0-9._~-]*$` — rejects empty, leading `-`, `/`, whitespace, and shell/flag metacharacters. Applied to every untrusted URL path segment (owner/repo/workspace/org/project) inside `parse_pr_url`, alongside `validate_pr_id`. Tests: reject `https://github.com/-X/widgets/pull/1` etc., and unit-test `validate_segment` directly. (Guardian)

2. **`resolve_diff(record, repo_dir=".")` becomes provider-aware (Task 3).** Plain `git fetch` leaves a remote/fork PR's commits unreachable, so `git diff base_sha..head_sha` would fail with "bad revision". Instead fetch the provider-specific PR ref + base into local refs, then diff the fetched SHAs, and raise an actionable `ResolverError` if the commits remain unreachable (never half-resolve). Fetch map: GitHub -> `pull/<pr_id>/head`; Azure -> the source ref `pull/<pr_id>/merge` fallback to head_sha; Bitbucket -> the source branch `head_ref`. Always also fetch `base_sha`. Every user-derived ref/SHA in a git argv is preceded by `--end-of-options` (and `git diff ... --` terminates options) so a leading-dash value can never be parsed as a flag (`git diff --output=<file>` write side-effect is thereby unreachable). Test asserts the provider-specific fetch argv (e.g. a GitHub record fetches `pull/<id>/head`) AND that `--end-of-options`/`--` guards precede user refs. (Architect + Guardian)

3. **Module docstring states the contracts (Task 2/3):** `resolve_diff` returns diff TEXT (the Phase-5 working-tree materialization for `review-pr` stays with s4, NOT this slice); the 10-field normalized record is the stable inter-slice JSON contract; `--repo-dir` is assumed to be a clone of the same repo and the resolver fetches the needed refs into it. (Skeptic + Historian)

4. **Token-leak guard (Task 2):** a test forces the HTTP/`_run` error paths and asserts the `BITBUCKET_TOKEN` value never appears in any `ResolverError` message, stdout, or stderr; the bearer header is only ever attached to the hardcoded `api.bitbucket.org` origin, never to the user-supplied `web_url`. (Guardian)

5. **Kept (DEFERRED-REJECTED):** `resolve_local` / `--base`/`--head` local ref-range — the verbatim slice goal lists it explicitly, so it is in scope, not YAGNI. (Pragmatist concern noted and logged.)
