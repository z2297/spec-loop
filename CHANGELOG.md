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
  command, which starts `scripts/dashboard_server.py` and prints the local URL.
- `/spec-loop:peer-review` — a strictly **read-only** multi-provider peer-review loop. It
  resolves a real pull request (GitHub / Azure DevOps / Bitbucket URL, or an explicit local
  `--base/--head` ref-range) and materializes its diff read-only via `scripts/pr_resolver.py`,
  then convenes five `peer-review-*` reviewers (`peer-review-conformance`, `-correctness`,
  `-design`, `-risk`, `-tests`) plus a report-only `pr-review-toolkit:review-pr` pass through
  the new `peer-review-council` skill, and publishes **one** pinned-schema report at
  `docs/pr-review/<review-id>/review-report.md`. It changes no implementation — there is no
  auto-fix loop, no `simplify` pass, no quality-gate, and no provider write-back (commenting /
  approving / merging is a deliberate future follow-on). The command's read-only contract is
  now machine-enforced: `scripts/validate_marketplace.py` asserts that any command marked
  read-only (including this one and the two dashboard commands) does not grant `Edit` in its
  `allowed-tools`.

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
