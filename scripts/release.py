#!/usr/bin/env python3
"""Release helper for the spec-loop plugin marketplace.

Performs the mechanical parts of cutting a release so they are identical whether
run locally or from CI (`.github/workflows/release.yml`). Standard library only.

Two modes:

    # Cut a release (mutates files in place):
    python3 scripts/release.py <version> [--channel stable|beta|alpha] [--root .]

    # Print the CHANGELOG section for a version (for GitHub Release notes):
    python3 scripts/release.py --notes <version> [--root .]

A STABLE release (default channel):
  * bumps plugins/spec-loop/.claude-plugin/plugin.json `version`,
  * prepends a pinned `spec-loop-<version>` archive entry to marketplace.json
    (source pinned to git tag `v<version>`),
  * rolls the CHANGELOG `[Unreleased]` section into a dated `[<version>]` section
    and updates the link references.

A BETA / ALPHA release only bumps plugin.json (no archive entry, no changelog cut),
because pre-release builds are served from the `beta` / `alpha` branches, not tags.

The operation is idempotent: re-running for the same version is a no-op for the
archive entry and changelog (it detects work already done and skips it).
"""

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

SEMVER = re.compile(
    r"^\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+)?$"
)
PLUGIN_MANIFEST = "plugins/spec-loop/.claude-plugin/plugin.json"
MARKETPLACE = ".claude-plugin/marketplace.json"
CHANGELOG = "CHANGELOG.md"
REPO = "z2297/spec-loop"
PLUGIN_PATH = "plugins/spec-loop"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _write_json(path: Path, data: dict) -> None:
    # 2-space indent + preserved unicode matches the hand-authored manifests.
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def bump_plugin_version(root: Path, version: str) -> bool:
    path = root / PLUGIN_MANIFEST
    manifest = _read_json(path)
    if manifest.get("version") == version:
        print(f"  plugin.json already at {version}")
        return False
    old = manifest.get("version")
    manifest["version"] = version
    _write_json(path, manifest)
    print(f"  plugin.json version {old} -> {version}")
    return True


def add_archive_entry(root: Path, version: str) -> bool:
    path = root / MARKETPLACE
    market = _read_json(path)
    # Plugin names must be kebab-case (no dots), so 0.4.0 -> 0-4-0.
    name = f"spec-loop-{version.replace('.', '-')}"
    plugins = market.setdefault("plugins", [])
    if any(p.get("name") == name for p in plugins):
        print(f"  archive entry {name} already present")
        return False
    entry = {
        "name": name,
        "source": {
            "source": "git-subdir",
            "url": REPO,
            "path": PLUGIN_PATH,
            "ref": f"v{version}",
        },
        "description": (
            f"ARCHIVE — spec-loop v{version}, pinned. "
            "Install to roll back to this exact release."
        ),
    }
    # Newest archive first: insert after the channel entries (stable/beta/alpha),
    # i.e. ahead of any existing spec-loop-<x.y.z> archive entries.
    insert_at = next(
        (i for i, p in enumerate(plugins)
         if re.match(r"^spec-loop-\d", str(p.get("name", "")))),
        len(plugins),
    )
    plugins.insert(insert_at, entry)
    _write_json(path, market)
    print(f"  added archive entry {name} (ref v{version})")
    return True


def roll_changelog(root: Path, version: str) -> bool:
    path = root / CHANGELOG
    text = path.read_text()
    if re.search(rf"^## \[{re.escape(version)}\]", text, re.M):
        print(f"  CHANGELOG already has a [{version}] section")
        return False
    today = datetime.date.today().isoformat()
    # Rename the Unreleased heading to the release, then add a fresh empty
    # Unreleased above it so its body becomes this release's notes.
    new_text, n = re.subn(
        r"^## \[Unreleased\]\s*\n",
        f"## [Unreleased]\n\n## [{version}] - {today}\n",
        text,
        count=1,
        flags=re.M,
    )
    if n == 0:
        print("  WARNING: no [Unreleased] section found; CHANGELOG not rolled")
        return False
    # Update link references at the bottom.
    new_text = re.sub(
        r"^\[Unreleased\]:.*$",
        f"[Unreleased]: https://github.com/{REPO}/compare/v{version}...HEAD\n"
        f"[{version}]: https://github.com/{REPO}/releases/tag/v{version}",
        new_text,
        count=1,
        flags=re.M,
    )
    path.write_text(new_text)
    print(f"  rolled CHANGELOG [Unreleased] -> [{version}] - {today}")
    return True


def extract_notes(root: Path, version: str) -> str:
    """Return the CHANGELOG body for a version (without the heading)."""
    text = (root / CHANGELOG).read_text()
    m = re.search(
        rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)",
        text,
        re.M | re.S,
    )
    return m.group(1).strip() if m else ""


def cut_release(root: Path, version: str, channel: str) -> None:
    print(f"Cutting {channel} release {version} in {root}")
    bump_plugin_version(root, version)
    if channel == "stable":
        add_archive_entry(root, version)
        roll_changelog(root, version)
    else:
        print(f"  ({channel} pre-release: no archive entry / changelog cut)")
    print("Done.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="spec-loop release helper")
    ap.add_argument("version", help="semver, e.g. 0.5.0 or 0.5.0-beta.1")
    ap.add_argument("--channel", choices=["stable", "beta", "alpha"],
                    default="stable")
    ap.add_argument("--root", default=".", help="repo root (default: cwd)")
    ap.add_argument("--notes", action="store_true",
                    help="print the CHANGELOG section for <version> and exit")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    if not (root / MARKETPLACE).is_file():
        print(f"error: {MARKETPLACE} not found under {root}", file=sys.stderr)
        return 1
    if not SEMVER.match(args.version):
        print(f"error: '{args.version}' is not a valid version", file=sys.stderr)
        return 1

    if args.notes:
        print(extract_notes(root, args.version))
        return 0

    is_prerelease = "-" in args.version
    if args.channel == "stable" and is_prerelease:
        print("error: stable releases must not be pre-release versions",
              file=sys.stderr)
        return 1
    if args.channel in ("beta", "alpha") and not is_prerelease:
        print(f"warning: {args.channel} version '{args.version}' has no "
              f"pre-release suffix (expected e.g. {args.version}-{args.channel}.1)",
              file=sys.stderr)

    cut_release(root, args.version, args.channel)
    return 0


if __name__ == "__main__":
    sys.exit(main())
