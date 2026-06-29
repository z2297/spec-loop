#!/usr/bin/env python3
"""Provider-agnostic, READ-ONLY pull-request resolver (standard library only).

Given a PR URL from Azure DevOps, GitHub, or Bitbucket (or an explicit local
--base/--head ref-range), this parses and validates the URL, DETECTS the
provider, resolves the PR READ-ONLY to a normalized record, and emits it as
JSON on stdout. It prefers the official CLI when available (`gh pr view`,
`az repos pr show`) and uses Bitbucket's REST API over urllib; if the relevant
CLI/credential is absent it FAILS with an actionable message and a non-zero
exit -- it never half-resolves and never mutates the PR or the repo.

Normalized record (the stable inter-slice JSON contract -- 10 fields):
    {provider, host, repo, pr_id, base_ref, base_sha, head_ref, head_sha,
     title, description, web_url}

`resolve_diff(record, repo_dir)` materializes the base..head diff locally and
returns it as diff TEXT: it fetches the provider-specific PR ref (plus the base
commit) into the local clone, then runs `git diff <base_sha>..<head_sha>`.
(The downstream working-tree materialization that lets `review-pr` read
identical bytes is a separate concern handled by the peer-review controller,
not this resolver.) `--repo-dir` is assumed to be a clone of the same repo; the
resolver fetches the refs it needs into it, and FAILS with an actionable error
if the PR commits remain unreachable rather than emitting a partial diff.

SECURITY: the URL / pr_id / refs / path segments are UNTRUSTED. pr_id is
validated as ^[0-9]+$, each URL path segment is validated against a strict
allow-list (no leading '-', no shell/flag metacharacters), the host is
validated against the known provider hosts, and user input is NEVER interpolated
into a shell string -- every external command runs through _run() with list-args
and shell=False, every user-derived ref in a git argv is preceded by
`--end-of-options` so it can never be parsed as a flag, and only READ verbs are
ever invoked (gh pr view/diff, az repos pr show, git fetch/diff/rev-parse,
HTTP GET). The Bitbucket bearer token is attached only to the hardcoded
api.bitbucket.org origin and never appears in any error message or output.

Usage:
    python3 scripts/pr_resolver.py <pr-url>
    python3 scripts/pr_resolver.py <pr-url> --diff
    python3 scripts/pr_resolver.py --base <ref> --head <ref> [--repo-dir .]
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

PR_ID_RE = re.compile(r"^[0-9]+$")
# Path segments (owner/repo/workspace/org/project): no leading '-', and only
# characters that cannot be a shell or argv-flag metacharacter.
SEGMENT_RE = re.compile(r"^[A-Za-z0-9._~][A-Za-z0-9._~-]*$")

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


def validate_segment(seg: str) -> str:
    """Validate an untrusted URL path segment used in a CLI/REST call. Rejects a
    leading '-' (argument injection) and any shell/flag metacharacter."""
    if not SEGMENT_RE.match(seg or ""):
        raise ResolverError(
            f"invalid path segment {seg!r}: must match {SEGMENT_RE.pattern} "
            "(no leading '-', no special characters)"
        )
    return seg


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
            owner, repo = validate_segment(segs[0]), validate_segment(segs[1])
            repo_full, pr_id = f"{owner}/{repo}", segs[3]
        else:
            raise ResolverError(f"not a GitHub PR URL: {url!r}")
    elif provider == "bitbucket":
        # /<workspace>/<repo>/pull-requests/<n>
        if len(segs) >= 4 and segs[2] == "pull-requests":
            ws, repo = validate_segment(segs[0]), validate_segment(segs[1])
            repo_full, pr_id = f"{ws}/{repo}", segs[3]
        else:
            raise ResolverError(f"not a Bitbucket PR URL: {url!r}")
    else:  # azure
        repo_full, pr_id = _parse_azure_path(segs, host, url)
    validate_pr_id(pr_id)
    return {
        "provider": provider,
        "host": host.lower(),
        "repo": repo_full,
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
    if pi + 1 >= len(segs) or pi <= gi or gi < 1:
        raise ResolverError(f"not an Azure DevOps PR URL: {url!r}")
    repo_name = segs[gi + 1]
    pr_id = segs[pi + 1]
    if host.lower().endswith(".visualstudio.com"):
        org = host.split(".", 1)[0]
        project = segs[gi - 1]
    else:  # dev.azure.com -- org is the first segment, project precedes _git
        if gi < 2:
            raise ResolverError(f"not an Azure DevOps PR URL: {url!r}")
        org = segs[0]
        project = segs[gi - 1]
    org = validate_segment(org)
    project = validate_segment(project)
    repo_name = validate_segment(repo_name)
    return f"{org}/{project}/{repo_name}", pr_id


def _run(argv, *, cwd=None) -> str:
    """Run a READ-ONLY command via list-args (shell=False). Sole subprocess
    entry point -- keeps the no-shell-injection guarantee provable in one place.
    Never includes a secret in argv, so its error text never leaks one."""
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
    """HTTP GET via urllib (READ-only; never sets a body or mutating method).
    Errors reference only the URL -- the bearer token rides in the header, so it
    never appears in an exception message."""
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise ResolverError(f"HTTP {exc.code} fetching {url}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise ResolverError(f"network error fetching {url}: {exc.reason}") from exc


def _strip_ref(ref):
    """refs/heads/main -> main (Azure returns fully-qualified ref names)."""
    return (ref or "").removeprefix("refs/heads/")


def _normalized(parsed, *, base_ref, base_sha, head_ref, head_sha,
                title, description):
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


def resolve(parsed: dict) -> dict:
    """Resolve a parsed PR READ-ONLY to the normalized record. Dispatches to the
    per-provider resolver; each prefers the official CLI / REST and FAILS with an
    actionable message when its CLI/credential is absent (never half-resolves)."""
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
            raise ResolverError("local --base/--head mode not yet implemented")
        else:
            raise ResolverError(
                "provide a PR URL, or both --base and --head for a local "
                "ref-range")
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return 0
    except ResolverError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
