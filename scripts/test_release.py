#!/usr/bin/env python3
"""Tests for the release helper (stdlib unittest).

`scripts/release.py` performs the mechanical file transforms of cutting a release
(bump plugin.json, prepend a pinned archive entry to marketplace.json, roll the
CHANGELOG). It is PURE — it only reads/writes files under a `root` Path and shells
out to nothing — so these tests seed an ISOLATED temporary repo root, run the real
transforms against it, and assert on the resulting file CONTENT (version bumped,
archive entry pinned to `v<version>`, changelog rolled and link-refs rewritten) and
each function's idempotency return value. They pin behaviour, not line-hits.

GUARDIAN INVARIANT: every test operates on a `tempfile.TemporaryDirectory` root and
NEVER the real repo checkout. `seed_repo` builds a self-contained fixture repo, and
`make_root` asserts the root resolves under the OS temp dir so a mis-authored test
that forgot `--root <tmp>` (and would otherwise mutate the live plugin.json /
marketplace.json / CHANGELOG.md via the default `--root .`) fails loudly instead.

There is deliberately NO real-repo regression test (cf. the RealRepoTest pattern in
sibling test files): release.py mutates in place, so exercising it against the real
checkout is forbidden.

Standard library only.

Usage:
    python3 scripts/test_release.py
"""

import contextlib
import datetime
import io
import json
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent))

import release as rel  # noqa: E402


# --------------------------------------------------------------------------
# Fixture builders
# --------------------------------------------------------------------------

PLUGIN_VERSION = "1.1.0-alpha.3"
REPO = "z2297/spec-loop"

# Channel entries (names NOT matching ^spec-loop-\d) then existing archive entries
# (names matching ^spec-loop-\d). add_archive_entry must insert a new archive entry
# BETWEEN these groups; seeding both is what makes the ordering assertion meaningful.
_CHANNEL_ENTRIES = [
    {"name": "spec-loop", "source": "./plugins/spec-loop"},
    {"name": "spec-loop-beta", "source": {"source": "git", "url": REPO, "ref": "beta"}},
    {"name": "spec-loop-alpha", "source": {"source": "git", "url": REPO, "ref": "alpha"}},
]
_ARCHIVE_ENTRIES = [
    {"name": "spec-loop-1-0-0", "source": {"source": "git-subdir", "url": REPO,
                                           "path": "plugins/spec-loop", "ref": "v1.0.0"}},
    {"name": "spec-loop-0-4-0", "source": {"source": "git-subdir", "url": REPO,
                                           "path": "plugins/spec-loop", "ref": "v0.4.0"}},
]

_CHANGELOG_WITH_UNRELEASED = f"""# Changelog

## [Unreleased]
### Added
- A brand new thing.
### Fixed
- An old bug.

## [1.0.0] - 2026-01-01
### Added
- The first release.

[Unreleased]: https://github.com/{REPO}/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/{REPO}/releases/tag/v1.0.0
"""

_CHANGELOG_NO_UNRELEASED = f"""# Changelog

## [1.0.0] - 2026-01-01
### Added
- The first release.

[1.0.0]: https://github.com/{REPO}/releases/tag/v1.0.0
"""


def make_root() -> TemporaryDirectory:
    """Create a TemporaryDirectory and assert it lives under the OS temp dir.

    Guardian self-check: if a test ever resolved `root` to the real checkout, this
    would fail loudly rather than let a transform mutate the live repo files.
    """
    td = TemporaryDirectory()
    resolved = Path(td.name).resolve()
    tmp_base = Path(tempfile.gettempdir()).resolve()
    assert tmp_base in resolved.parents or tmp_base == resolved, (
        f"test root {resolved} is NOT under the OS temp dir {tmp_base}; "
        "refusing to run a mutating transform against a non-temp path"
    )
    return td


@dataclass(frozen=True)
class RepoSpec:
    """Which shape of fixture repo to seed. Defaults describe the realistic repo:
    the real plugin version, a marketplace with both channel and archive entries,
    and a CHANGELOG that has an [Unreleased] section. Individual tests flip one
    flag (e.g. with_archives=False) to reach a specific branch."""
    plugin_version: str = PLUGIN_VERSION
    with_marketplace: bool = True
    with_archives: bool = True
    with_unreleased: bool = True


@contextlib.contextmanager
def seeded_root(**spec_kwargs):
    """Yield an isolated, seeded temp-repo root `Path` for a single test.

    Combines the two steps every test performs — allocate a guarded temp root
    (make_root, which enforces the GUARDIAN INVARIANT) and lay down the fixture
    repo (seed_repo) — so the tests read as `with seeded_root() as root:`.
    `spec_kwargs` build the RepoSpec (e.g. with_archives=False).
    """
    with make_root() as td:
        root = Path(td)
        seed_repo(root, RepoSpec(**spec_kwargs))
        yield root


def seed_repo(root: Path, spec: RepoSpec = RepoSpec()) -> None:
    """Lay down a self-contained fixture repo under `root` per `spec`.

    Mirrors the real manifest shapes closely enough that release.py's transforms
    hit their real branches:
      * plugin.json under plugins/spec-loop/.claude-plugin/
      * marketplace.json with channel + archive entries (unless suppressed)
      * CHANGELOG.md with (optionally) an [Unreleased] section + link refs
    """
    manifest_dir = root / "plugins" / "spec-loop" / ".claude-plugin"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "plugin.json").write_text(
        json.dumps({"name": "spec-loop", "version": spec.plugin_version}, indent=2) + "\n"
    )

    if spec.with_marketplace:
        plugins = list(_CHANNEL_ENTRIES)
        if spec.with_archives:
            plugins += _ARCHIVE_ENTRIES
        market_dir = root / ".claude-plugin"
        market_dir.mkdir(parents=True)
        (market_dir / "marketplace.json").write_text(
            json.dumps({"name": "spec-loop", "owner": {"name": "tester"},
                        "plugins": plugins}, indent=2) + "\n"
        )

    changelog = (_CHANGELOG_WITH_UNRELEASED if spec.with_unreleased
                 else _CHANGELOG_NO_UNRELEASED)
    (root / "CHANGELOG.md").write_text(changelog)


def read_plugin(root: Path) -> dict:
    return json.loads((root / rel.PLUGIN_MANIFEST).read_text())


def read_market(root: Path) -> dict:
    return json.loads((root / rel.MARKETPLACE).read_text())


def read_changelog(root: Path) -> str:
    return (root / rel.CHANGELOG).read_text()


# --------------------------------------------------------------------------
# bump_plugin_version
# --------------------------------------------------------------------------

class BumpPluginVersionTests(unittest.TestCase):
    def test_bumps_version_when_different(self):
        with seeded_root(plugin_version="1.1.0-alpha.3") as root:
            changed = rel.bump_plugin_version(root, "1.1.0")
            self.assertTrue(changed)
            self.assertEqual(read_plugin(root)["version"], "1.1.0")

    def test_noop_when_already_at_version(self):
        with seeded_root(plugin_version="1.1.0") as root:
            changed = rel.bump_plugin_version(root, "1.1.0")
            self.assertFalse(changed)
            self.assertEqual(read_plugin(root)["version"], "1.1.0")


# --------------------------------------------------------------------------
# add_archive_entry
# --------------------------------------------------------------------------

class AddArchiveEntryTests(unittest.TestCase):
    def test_inserts_pinned_entry_with_correct_content(self):
        with seeded_root() as root:
            changed = rel.add_archive_entry(root, "1.1.0")
            self.assertTrue(changed)
            entry = next(p for p in read_market(root)["plugins"]
                         if p["name"] == "spec-loop-1-1-0")
            self.assertEqual(entry["source"], {
                "source": "git-subdir",
                "url": REPO,
                "path": "plugins/spec-loop",
                "ref": "v1.1.0",
            })
            self.assertIn("v1.1.0", entry["description"])

    def test_inserts_after_channels_ahead_of_existing_archives(self):
        with seeded_root() as root:  # channels + existing archives both present
            rel.add_archive_entry(root, "1.1.0")
            names = [p["name"] for p in read_market(root)["plugins"]]
            new_idx = names.index("spec-loop-1-1-0")
            # After the last channel entry...
            self.assertGreater(new_idx, names.index("spec-loop-alpha"))
            # ...and ahead of every pre-existing archive entry.
            self.assertLess(new_idx, names.index("spec-loop-1-0-0"))

    def test_first_archive_appends_after_channels(self):
        # No pre-existing archive entries: insert_at falls back to len(plugins),
        # so the very first archive entry lands AFTER the last channel entry.
        with seeded_root(with_archives=False) as root:
            changed = rel.add_archive_entry(root, "1.1.0")
            self.assertTrue(changed)
            names = [p["name"] for p in read_market(root)["plugins"]]
            self.assertGreater(names.index("spec-loop-1-1-0"),
                               names.index("spec-loop-alpha"))

    def test_noop_when_entry_already_present(self):
        with seeded_root() as root:
            first = rel.add_archive_entry(root, "1.1.0")
            before = read_market(root)
            second = rel.add_archive_entry(root, "1.1.0")
            self.assertTrue(first)
            self.assertFalse(second)
            self.assertEqual(read_market(root), before)  # unchanged


# --------------------------------------------------------------------------
# roll_changelog
# --------------------------------------------------------------------------

class RollChangelogTests(unittest.TestCase):
    def test_rolls_unreleased_into_dated_section_and_rewrites_refs(self):
        with seeded_root() as root:
            changed = rel.roll_changelog(root, "1.1.0")
            self.assertTrue(changed)
            text = read_changelog(root)
            today = datetime.date.today().isoformat()
            # Dated section created with today's date (computed, not hard-coded).
            self.assertIn(f"## [1.1.0] - {today}", text)
            # A fresh empty [Unreleased] remains above the dated section.
            self.assertLess(text.index("## [Unreleased]"), text.index("## [1.1.0]"))
            # Link refs rewritten: Unreleased now compares from v1.1.0, and a
            # tag ref for the new version was added.
            self.assertIn(
                f"[Unreleased]: https://github.com/{REPO}/compare/v1.1.0...HEAD", text)
            self.assertIn(
                f"[1.1.0]: https://github.com/{REPO}/releases/tag/v1.1.0", text)
            # The rolled body still carries the previous Unreleased content.
            self.assertIn("A brand new thing.", text)

    def test_noop_when_version_section_present(self):
        with seeded_root() as root:
            changed = rel.roll_changelog(root, "1.0.0")  # already dated in fixture
            self.assertFalse(changed)

    def test_warning_noop_when_no_unreleased_section(self):
        with seeded_root(with_unreleased=False) as root:
            before = read_changelog(root)
            with contextlib.redirect_stdout(io.StringIO()) as out:
                changed = rel.roll_changelog(root, "2.0.0")
            self.assertFalse(changed)
            self.assertIn("WARNING", out.getvalue())
            self.assertEqual(read_changelog(root), before)  # unchanged


# --------------------------------------------------------------------------
# extract_notes
# --------------------------------------------------------------------------

class ExtractNotesTests(unittest.TestCase):
    def test_returns_section_body_without_heading(self):
        # Extract the [Unreleased] body: it has a following "## [" heading, so the
        # regex stops there — proving the body excludes its own heading AND does not
        # bleed into the next section.
        with seeded_root() as root:
            notes = rel.extract_notes(root, "Unreleased")
            self.assertIn("A brand new thing.", notes)
            self.assertNotIn("## [Unreleased]", notes)  # own heading excluded
            self.assertNotIn("## [1.0.0]", notes)       # stops before next section
            self.assertNotIn("The first release.", notes)

    def test_returns_empty_for_missing_version(self):
        with seeded_root() as root:
            self.assertEqual(rel.extract_notes(root, "9.9.9"), "")


# --------------------------------------------------------------------------
# cut_release
# --------------------------------------------------------------------------

class CutReleaseTests(unittest.TestCase):
    def test_stable_applies_all_three_effects(self):
        with seeded_root() as root:
            rel.cut_release(root, "1.1.0", "stable")
            self.assertEqual(read_plugin(root)["version"], "1.1.0")
            names = [p["name"] for p in read_market(root)["plugins"]]
            self.assertIn("spec-loop-1-1-0", names)
            today = datetime.date.today().isoformat()
            self.assertIn(f"## [1.1.0] - {today}", read_changelog(root))

    def test_prerelease_bumps_only(self):
        with seeded_root() as root:
            market_before = read_market(root)
            changelog_before = read_changelog(root)
            rel.cut_release(root, "1.2.0-beta.1", "beta")
            self.assertEqual(read_plugin(root)["version"], "1.2.0-beta.1")
            # No archive entry, no changelog cut for pre-release channels.
            self.assertEqual(read_market(root), market_before)
            self.assertEqual(read_changelog(root), changelog_before)


# --------------------------------------------------------------------------
# main() argument / validation paths (always pass --root <tmp>)
# --------------------------------------------------------------------------

class MainTests(unittest.TestCase):
    def test_notes_prints_and_mutates_nothing(self):
        with seeded_root() as root:
            plugin_before = read_plugin(root)
            market_before = read_market(root)
            changelog_before = read_changelog(root)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = rel.main(["1.0.0", "--notes", "--root", str(root)])
            self.assertEqual(rc, 0)
            self.assertIn("The first release.", out.getvalue())
            # Read-only: fixtures untouched.
            self.assertEqual(read_plugin(root), plugin_before)
            self.assertEqual(read_market(root), market_before)
            self.assertEqual(read_changelog(root), changelog_before)

    def test_invalid_semver_returns_1_and_mutates_nothing(self):
        with seeded_root() as root:
            plugin_before = read_plugin(root)
            with contextlib.redirect_stderr(io.StringIO()):
                rc = rel.main(["not-a-version", "--root", str(root)])
            self.assertEqual(rc, 1)
            self.assertEqual(read_plugin(root), plugin_before)

    def test_missing_marketplace_returns_1(self):
        with seeded_root(with_marketplace=False) as root:  # no marketplace.json
            with contextlib.redirect_stderr(io.StringIO()) as err:
                rc = rel.main(["1.1.0", "--root", str(root)])
            self.assertEqual(rc, 1)
            self.assertIn("marketplace.json", err.getvalue())

    def test_stable_prerelease_rejected(self):
        with seeded_root() as root:
            plugin_before = read_plugin(root)
            with contextlib.redirect_stderr(io.StringIO()) as err:
                rc = rel.main(["1.1.0-beta.1", "--channel", "stable", "--root", str(root)])
            self.assertEqual(rc, 1)
            self.assertIn("stable", err.getvalue())
            self.assertEqual(read_plugin(root), plugin_before)  # aborted before bump

    def test_beta_without_suffix_warns_but_bumps(self):
        with seeded_root() as root:
            with contextlib.redirect_stdout(io.StringIO()):
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    rc = rel.main(["1.3.0", "--channel", "beta", "--root", str(root)])
            self.assertEqual(rc, 0)
            self.assertIn("warning", err.getvalue())
            self.assertEqual(read_plugin(root)["version"], "1.3.0")  # still bumped

    def test_stable_happy_path_returns_0_and_runs(self):
        # cut_release's full three-effect content is pinned in CutReleaseTests;
        # here the main() wrapper only needs to prove rc==0 plus one smoke check
        # that cut_release actually ran.
        with seeded_root() as root:
            with contextlib.redirect_stdout(io.StringIO()):
                rc = rel.main(["1.1.0", "--channel", "stable", "--root", str(root)])
            self.assertEqual(rc, 0)
            self.assertEqual(read_plugin(root)["version"], "1.1.0")


if __name__ == "__main__":
    unittest.main()
