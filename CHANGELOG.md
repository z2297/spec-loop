# Changelog

All notable changes to the **spec-loop** plugin are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Versioning & channels

Releases are published through three channels from one marketplace
(`/plugin marketplace add z2297/spec-loop`):

| Channel | Install target              | Source         | Stability                          |
| ------- | --------------------------- | -------------- | ---------------------------------- |
| stable  | `spec-loop@spec-loop`       | `main`         | recommended, release-quality       |
| beta    | `spec-loop-beta@spec-loop`  | `beta` branch  | release candidates ahead of stable |
| alpha   | `spec-loop-alpha@spec-loop` | `alpha` branch | bleeding edge, may be unstable     |

Every stable release is also pinned, immutably, as a version-suffixed entry — the
version with dashes instead of dots, since plugin names are kebab-case
(e.g. v0.3.0 → `spec-loop-0-3-0@spec-loop`) — so a consumer can roll back to any
prior build. Pinned entries map to git tags `v<version>`.

## [Unreleased]
### Added
- `/spec-loop:dashboard` — a read-only slash command that renders a terminal-markdown
  dashboard of a spec-loop run (DAG, derived waves, per-slice status, open escalations,
  recent decisions) from the durable artifacts under `docs/spec-loop/<run-id>/`. Mutates
  nothing and triggers no slice work.
- Web dashboard — a read-only, modern dark-theme single-page web UI (zero-dependency,
  served by a stdlib `http.server`) that renders the same run view in a browser: an
  all-runs overview and a single-run drill-down (DAG/waves, slice table, status rollup,
  open escalations, recent decisions), with near-real-time auto-refresh (~2.5s polling +
  ETag/304) and a freshness indicator. Strictly read-only (`GET`/`HEAD` only, `127.0.0.1`
  bind, no mutation endpoints). Launch it with the new `/spec-loop:dashboard-serve`
  command, which starts the plugin-bundled `dashboard_launcher.py` (Docker-preferred,
  Python-fallback) and prints the local URL.
- `/spec-loop:peer-review` — a strictly **read-only** multi-provider peer-review loop. It
  resolves a real pull request (GitHub / Azure DevOps / Bitbucket URL, or an explicit local
  `--base/--head` ref-range) and materializes its diff read-only via the plugin-bundled `pr_resolver.py`,
  then convenes five `peer-review-*` reviewers (`peer-review-conformance`, `-correctness`,
  `-design`, `-risk`, `-tests`) plus a report-only `pr-review-toolkit:review-pr` pass through
  the new `peer-review-council` skill, and publishes **one** pinned-schema report at
  `docs/pr-review/<review-id>/review-report.md`. It changes no implementation — there is no
  auto-fix loop, no `simplify` pass, no quality-gate, and no provider write-back (commenting /
  approving / merging is a deliberate future follow-on). The command's read-only contract is
  now machine-enforced: `scripts/validate_marketplace.py` asserts that any command marked
  read-only (including this one and the two dashboard commands) does not grant `Edit` in its
  `allowed-tools`.
- **The dashboard and peer-review runtime now ships inside the plugin**, so
  `/spec-loop:dashboard-serve` and `/spec-loop:peer-review` work on a marketplace install
  (previously they invoked repo-root `scripts/…` by a relative path that did not exist for
  installed users). The bundled `dashboard_launcher.py`, `dashboard_server.py`,
  `pr_resolver.py`, `dashboard_assets/`, and `Dockerfile` live under
  `plugins/spec-loop/scripts/` (and `plugins/spec-loop/Dockerfile`); the commands invoke
  them by their absolute `${CLAUDE_PLUGIN_ROOT}` path, so they run from any working
  directory. `scripts/validate_marketplace.py` now guards against regressions: it fails if a
  command/skill/agent references a `${CLAUDE_PLUGIN_ROOT}/<path>` that is not shipped, or if
  the plugin `Dockerfile` `COPY`s a source missing from the build context.

### Changed
- **Single-branch integration is now the default and is hardened.** Every slice merges into
  ONE dedicated local integration branch (cut from `main` by default, named meaningfully after
  the work — never containing `spec-loop`), instead of each slice being free to open its own PR
  or leave its own branch. Slices no longer self-merge: they finish as verified, committed
  branches and the **controller** merges each into the integration branch **serially** at the
  wave boundary (eliminating the race where two same-wave slices checked out and merged into the
  shared branch concurrently), then deletes the per-slice worktree branch. Per-slice worktree
  branches are now explicitly an ephemeral isolation detail, not a deliverable.
- **The run ends by prompting how to publish** the integration branch — push it as a feature
  branch (optionally opening a PR) or merge it onto `main` — and never pushes or touches `main`
  without that explicit choice.
- Added flags `--branch <name>` (integration branch name), `--base-branch <name>` (branch it is
  cut from; default `main`/`master`), and `--per-slice-pr` (opt into a branch/PR per slice — the
  only way, alongside an explicit request in the prose, to get the old per-slice behavior).
- `dag.json` now records `base_branch` and `merge_mode`, and `--resume` restores and checks out
  the integration branch.
- **Per-role model selection for the advisory reviewers (token optimization).** The ten
  read-only council agents used to run on `model: inherit`, so an Opus session spent Opus on
  every one — including bursts of five at intake, per slice plan, and per peer-review. The seven
  judgment/scope reviewers now default to `model: sonnet` (`iron-council-skeptic`, `-architect`,
  `-pragmatist`, `-historian`; `peer-review-conformance`, `-design`, `-tests`), while the three
  roles that can block on their own stay on `inherit` at full session strength
  (`iron-council-guardian` and `peer-review-risk` — a lone `SAFETY` objection halts the loop — and
  `peer-review-correctness` — bug/logic finding, mirroring pr-review-toolkit pinning
  `code-reviewer` to opus). The `spec-loop-slice` implementer stays `inherit` so it keeps cascading
  the session model to superpowers implementers. This changes only spec-loop's own agent
  frontmatter — it injects no `model:` into any `superpowers` or `pr-review-toolkit` dispatch, so
  their own model choices (e.g. `code-reviewer`/`code-simplifier` pinned to opus) remain honored.

## [1.0.0] - 2026-06-25
### Added
- Stable / beta / alpha release channels and a pinned version archive, all served
  from the single `z2297/spec-loop` marketplace.
- `scripts/release.py` and a `workflow_dispatch` `release` GitHub Action to cut
  releases and publish GitHub Releases.

## [0.4.0]

### Added
- Dynamic decomposition: a slice that turns out too large splits itself back into
  the plan mid-run.
- Integration gate: once every slice lands, the assembled whole is verified before
  the run is called complete.

## [0.3.0]

### Added
- The Iron Council — an adversarial review layer of five agents that challenges the
  request and every slice plan, surfacing genuinely unworthy work to the human and
  folding lesser concerns in.

## [0.2.0]

### Added
- Post-review code-quality gate: an objective complexity/length/CRAP metric gate
  with a bounded, behavior-preserving refactor loop before merge.

[Unreleased]: https://github.com/z2297/spec-loop/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/z2297/spec-loop/releases/tag/v1.0.0
[0.4.0]: https://github.com/z2297/spec-loop/releases/tag/v0.4.0
[0.3.0]: https://github.com/z2297/spec-loop/releases/tag/v0.3.0
[0.2.0]: https://github.com/z2297/spec-loop/releases/tag/v0.2.0
