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
- **Run-metrics harness (`scripts/run_metrics.py`).** Derives a versioned
  `metrics.json` per run from the durable artifacts — safety/autonomy (escalation
  rate + triggers, autonomy ratio, council OBJECT/SAFETY rates, reversibility mix,
  precedent reuse, fail-closed events), quality (quality-gate first-pass rate and
  refactor iterations, sidecar review counters, split rate, integration-gate
  results, runbook requirement coverage), performance (run wall clock, per-slice
  durations, wave parallelism, escalation answer latency), and opt-in best-effort
  token accounting from Claude Code transcripts (`--transcripts`, with
  `probe-transcripts` for schema-drift visibility). `trend --md` prints a cross-run
  comparison table. Null-honest: underivable metrics are `null`, and legacy runs
  analyze retroactively (timing via `--git` merge-commit dates).
- **Minimal run instrumentation.** `dag.json` gains `created_at` and a
  `remediation` flag; decisions-log lines carry a trailing ` — AT: <ISO-8601>`
  token; escalation blocks gain `Opened:`/`Answered-at:`; the slice status sidecar
  gains optional `started_at`/`finished_at`/`wave`/`counters` (validated
  only-if-present by `council_contracts.py` — legacy sidecars stay valid). The
  controller writes `metrics.json` at wave boundaries and commits the final
  git-enriched snapshot with the runbook.
- **Dashboard metrics view.** The web dashboard serves each run's metrics
  (committed `metrics.json` preferred, live artifact-only recompute otherwise,
  marked `committed`/`live`), headline pills on overview cards, and a full
  `metrics_full` document on the run-detail endpoint; `metrics.json` participates
  in artifact listings and ETag invalidation. `/spec-loop:dashboard` renders a
  Run metrics section from `metrics.json` when present.

- **`/spec-loop --from-plan [path]` — plan-mode handoff.** The loop can now source its
  intent from a Claude Code plan-mode plan instead of a free-text request. With no
  path it reads the most recently modified `*.md` under `~/.claude/plans/` (the
  directory plan mode writes approved plans to); with a path it reads that file. The
  controller treats the plan as authoritative intent — restating its goal, seeding
  decomposition from its structure, and recording it into
  `docs/spec-loop/<run-id>/request.md` — while any prose passed alongside the flag
  layers on as extra focus. `--resume` still wins if both are given; a bare
  `--from-plan` against an empty plans dir stops with a clear message rather than
  treating the flag as the request. This is the supported bridge from plan mode into
  the loop: Claude Code's plan-approval menu cannot be extended with a custom "run via
  spec-loop" item (those options are hardcoded in the harness), so the flag + the
  on-disk plan file are the handoff.
- **Knowledge-graph Obsidian-native UX.** Notes gain an `aliases` frontmatter entry (the
  human title, unioned with user-added aliases) so wikilinks and the quick switcher
  resolve by title; commas are now quoted in frontmatter scalars so titles survive the
  inline-list round-trip. A create-once `spec-loop.base` starter (Obsidian Bases table
  views over Runs/Decisions/Patterns/Domain/Reviews, tag-filtered) is written at Phase 1
  via the batch key `ensure_base` — opt out with `starter_base: false` in the config. The
  `System/<repo>` hub maintains a per-repo home index (runs newest-first, active
  decisions, patterns, domain, reviews) in its managed `kg:index` region, refreshed at
  the existing MOC moments with no new caller step. Each run gets a
  `Runs/<run-id>.canvas` — a JSON Canvas 1.0 wave-layout of the run DAG (longest-path
  layering, risk-tier colors, dep edges), created once at runbook time via the batch key
  `canvas: {dag_file}`, linked from the run MOC, and never overwritten (user
  rearrangements survive). `query` results now carry `repo`/`status`/`created`/`updated`.
- **Peer-review → knowledge graph (doubly opt-in `review` node type).** After
  `/spec-loop:peer-review` publishes its report, it can project the verdict into the
  Obsidian knowledge graph as ONE `Reviews/<review-id>.md` note — `verdict` frontmatter,
  severity counts, and ≤10 P0/P1 finding titles (never P2s, report bodies, evidence, or
  diff text) — linked to the repo `system` hub and already-existing `component` hubs only.
  Requires the graph enabled AND `review` selected in `node_types` (a new, non-default
  fifth option in `/spec-loop:knowledge-graph`), preserving every existing config as
  non-publishing. Written strictly after the verdict prints (can influence nothing), no
  MOC, no MCP enrichment, fail-open — mirroring the runbook's "one sanctioned write
  outside the run directory" carve-out, now stated explicitly in the peer-review security
  boundary. `runs` frontmatter records writer ids (run-ids and review-ids alike); review
  ids are never remap-eligible and never in `known_ids`; `context` returns a repo-scoped
  capped `reviews` list so accumulated review knowledge feeds Phase 0 intake.
- **Knowledge-graph query mode ("ask the graph").** `/spec-loop:knowledge-graph
  <free-text question>` answers from the accumulated graph: bounded retrieval (one ranked
  `context` call + ≤2 `query` calls, keywords passed as separate argv tokens, never
  shell-spliced) plus ≤3 note reads, synthesized with cited titles/paths and staleness —
  and a plain "the graph has nothing on this" when it doesn't. Hard read-only; no args
  still opens the config flow unchanged. `query` results now carry a `one_liner` snippet
  so most questions need zero note reads.
- **Knowledge-graph read-path intelligence.** The `context` subcommand gains request-aware
  relevance ranking (`--term`, repeatable, and `--request-file`: deterministic lexical
  overlap — title ×3, tags ×2, body ×1 — that **reorders but never filters**, so the
  recency floor survives an off-target term list; entries gain a `relevance` field and the
  result echoes the `terms` used) and component-scoped buckets (`--component`, repeatable:
  per-slug decisions/patterns/domain whose managed links region names the component,
  capped 5 per type). The controller passes 5–8 salient request terms at Phase 0 and
  surfaces `relevance > 0` decisions to the Iron Council under a "prior decisions that may
  bear on this request" framing (the helper surfaces candidates; the council judges
  contradiction), and at each wave boundary makes ONE component-scoped `context` call
  (union of the wave's slices' `subsystems`) to inject a small `## Prior knowledge for
  this slice (knowledge graph)` section into each slice's dispatch prompt — slice workers
  still never touch the vault. No terms/components → byte-identical prior output (pinned
  by test); no new config keys; read path stays fail-open and never gates intake.
- **Native PR-review library (pr-review-toolkit decomposed in).** The aspect-based PR
  review the loop ran through the external `pr-review-toolkit` plugin now ships natively,
  with feature parity, as 1 skill + 1 command + 6 agents: the `review-pr` skill (the
  orchestration contract — aspect→agent map, diff-driven aspect auto-selection,
  sequential/parallel modes, aggregation buckets, and the canonical
  Critical/Important/Suggestion → P0/P1/P2 severity mapping, moved here from
  `peer-review-council`), the thin `/spec-loop:review-pr` command wrapper, and agents
  `guideline-reviewer` (the source's `code-reviewer`, renamed to avoid clashing with the
  native plan-alignment `code-reviewer`; confidence-scored ≥80 findings),
  `pr-test-analyzer`, `comment-analyzer`, `silent-failure-hunter` (Anthropic-internal
  logging references generalized to target-repo discovery), `type-design-analyzer`, and
  `code-simplifier` (source project standards demoted to fallbacks behind the target
  repo's own conventions). New `exhaustive` mode (all five review agents forced — not
  `code-simplifier` — parallel, P0–P3 reporting; unproven until it has runtime mileage)
  natively replaces the optional external
  `/exhaustive-pr-review:exhaustive-pr` for Tier 3. The `pr-review-toolkit` preflight
  check and install instructions are removed — spec-loop now has **zero external plugin
  dependencies**. Existing plan headers naming `pr-review-toolkit:review-pr …` are
  executed as the equivalent `spec-loop:review-pr …` on resume. Ported and adapted from
  `pr-review-toolkit` (Anthropic, claude-plugins-official) with per-file provenance
  sections; source `model: opus` pins replaced with `model: inherit`.
- **Native process skill library (superpowers decomposed in).** The development-process
  skills the loop chained from the external `superpowers` plugin now ship natively, with
  feature parity, as 13 skills + 3 agents: `using-spec-loop` (gateway/router),
  `brainstorming` (+ optional zero-dep visual-companion server under
  `skills/brainstorming/scripts/`), `writing-plans` (plans now at `docs/spec-loop/plans/`,
  specs at `docs/spec-loop/specs/`), `subagent-driven-development` (+ bundled
  `sdd-workspace`/`task-brief`/`review-package` scripts, ledger at `.spec-loop/sdd/`),
  `executing-plans`, `test-driven-development` (+ testing-anti-patterns reference),
  `systematic-debugging` (+ technique references and `find-polluter.sh`),
  `verification-before-completion`, `code-review-discipline` (merges the source's
  requesting- and receiving-code-review pair into one home), `finishing-a-development-branch`,
  `using-git-worktrees`, `dispatching-parallel-agents`, `writing-skills` (adapted to this
  repo's CI contract); plus native agents `sdd-implementer`, `sdd-task-reviewer`, and
  `code-reviewer` replacing the source's pasted prompt templates. Ported and adapted from
  `superpowers` v6.1.1 (github.com/obra/superpowers, MIT) with per-skill provenance
  sections. No SessionStart hook is added — skills load on demand.

- **Structured JSON contracts (fail-closed).** Iron Council members now end their replies
  with a fenced ```json verdict block, and slice workers write a machine-readable status
  sidecar (`docs/spec-loop/<run-id>/slice-<id>-status.json`) that the controller — not the
  return text — trusts. New stdlib-only `scripts/council_contracts.py`
  (+ `test_council_contracts.py`) validates member verdicts, executes the aggregation rules
  (majority OBJECT, single-SAFETY veto, reduced councils), and validates sidecars. Fail-closed
  throughout: an invalid member reply becomes a non-SAFETY OBJECT after one re-dispatch; a
  missing/invalid sidecar makes the slice `NEEDS_DECISION`.
- **Deterministic guardrail hooks.** New `hooks/hooks.json` registers a PreToolUse hook
  (`scripts/spec_loop_guard.py` + tests) that, while a run's `.active` marker exists,
  mechanically blocks mid-run `git push` (except `per-slice-pr` mode), broad staging
  (`git add -A`/`--all`/`.`), commits/merges on `main`/`master`, and any edit to
  `~/.claude/spec-loop/quality-gate.json` — with deny reasons that name the compliant
  alternative. Marker lifecycle: `.active` at Phase 1, `.publish-choice` at the publish
  answer, `.active` → `.done` at run end. The guard fails open on its own errors
  (defense-in-depth; the skill prompts remain the primary control). Verified empirically
  that PreToolUse also fires for Bash calls made inside Task subagents, so the guard covers
  slice workers as well as the controller's main-session operations.
- **Deterministic quality-gate measurement.** New stdlib-only `scripts/quality_gate.py`
  (+ `test_quality_gate.py`) measures the slice diff's metrics (cyclomatic/cognitive
  complexity, method lines, parameters, nesting, class lines, CRAP with coverage) via
  installed backends (`lizard` preferred, `radon` for Python) or a built-in stdlib analyzer
  marked `builtin-heuristic` — never installing anything and never fabricating a
  tool-attributed number. The `quality-gate` skill is now script-first; model heuristics
  remain only as fallback when the script itself cannot run.
- **Adversarial review-finding verification.** New `review-finding-verifier` agent: before
  the auto-fix loop, each blocking review finding gets one read-only verifier that tries to
  REFUTE it against the actual code (cap 6/round, highest severity first). REFUTED findings
  are logged with file:line evidence and never burn fix cycles or escalate; CONFIRMED is the
  default and unreadable verdicts fail closed to CONFIRMED.
- **Risk-tier-scaled council composition.** The pre-execution Iron Council now scales with
  the slice's risk tier via `review-depth-map`: Tier 1 convenes a reduced
  `pragmatist,guardian` council, Tier 2 the full five, Tier 3 the full five with an explicit
  high-effort deep-review mandate. The guardian sits on every council so the lone-SAFETY veto
  never loses coverage; intake always convenes the full five. The composition is recorded in
  the plan header (`council="..."`) and pinned at aggregation by the new
  `council_contracts.py aggregate --expect <members>` check — a missing, duplicate, or
  uninvited verdict exits 2 (fail closed) instead of silently shrinking the majority math.
- **One shared context bundle per convening.** The controller's Phase 0 exploration is now
  persisted as `docs/spec-loop/<run-id>/conventions.md` (reusable helpers, patterns,
  conventions, key-file map) and handed to every slice worker and every council convening;
  the convening layer assembles ONE context packet (subject, `conventions.md`,
  `shared_constraints`, run-state path, files the plan names) passed identically to all
  members — same prefix, prompt-cache friendly — instead of five agents re-exploring the
  same files. The previously undocumented `shared_constraints` array in `dag.json` is now
  part of the contract and flows to workers and councils.
- **Cross-run learning.** Prior runs' committed artifacts are now read as precedent: the
  historian enumerates earlier `docs/spec-loop/*/runbook.md`, `decisions-log.md`, and
  `status: ANSWERED` escalation blocks and flags re-litigation of settled decisions (citing
  run-id + escalation title), and `escalation-gate` runs a precedent check before surfacing —
  a squarely-applicable prior human answer resolves autonomously (logged with the precedent),
  a near-match becomes the escalation's recommended default. A question answered in run N is
  not asked again in run N+1.

- **Obsidian knowledge graph (opt-in).** `/spec-loop` can now project a run's decisions,
  architecture patterns, system context, and domain knowledge into an Obsidian vault as
  linked markdown notes (`[[wikilinks]]` + YAML frontmatter) that **accumulate and cross-link
  across every run and repo** — a persistent graph instead of per-run logs.
  - New global, opt-in config at `~/.claude/spec-loop/knowledge-graph.json`, configured by the
    new **`/spec-loop:knowledge-graph`** command (mirrors `/spec-loop:quality-gate`). The
    vault path is **user-supplied with no machine-specific default** — the feature stays inert
    until you provide one, keeping the distributed plugin portable.
  - New **`knowledge-graph`** skill pins the node taxonomy, frontmatter schema, and wikilink
    edges; writes are **MCP-preferred with a direct-file fallback** (works with Obsidian
    closed).
  - New stdlib-only helper `scripts/knowledge_graph.py` (+ `test_knowledge_graph.py`) owns the
    deterministic **idempotent upsert** (frontmatter union, dated observation blocks, wikilink
    dedup, run MOC, path-containment) so nodes are *updated*, never duplicated, on re-runs.
  - **Light touch by design:** only the controller (at phase boundaries) and the end-of-run
    `runbook` write notes — **slice workers never touch the vault**, so the loop's parallel
    execution is unaffected. The runbook records a `knowledge_graph` block in its front-matter
    for traceability.
- **Knowledge graph read path.** The graph is no longer write-only: a new read-only
  `knowledge_graph.py context` subcommand returns a bounded prior-knowledge summary for a
  repo (system hub one-liner, ALL patterns — they are cross-repo by design — plus repo-scoped
  domain notes and non-superseded decisions, and `known_ids` per type), and the controller
  surfaces it at Phase 0 intake as a `## Prior knowledge (knowledge graph)` section of the
  conventions summary handed to every council and slice worker. Complements (never replaces)
  plain-file cross-run learning; one serial call, fail-open, never gates intake.
- **Deterministic secret redaction in the knowledge-graph helper.** `redact_secrets()` scrubs
  well-known token shapes (AWS keys, GitHub PATs, `sk-` keys, Slack tokens, PEM private-key
  blocks, JWTs) and explicit `key=value` assignment forms from every node field before it
  reaches the vault, reporting a `redactions` count — a script-enforced floor beneath the
  skill's model-side redaction guard.
- **Conservative id-drift remap.** A batch upsert of a new `pattern`/`component`/`system`/
  `domain` id that has no existing note is remapped onto the ONE existing note it plainly
  meant (same id modulo a `-<type>` suffix, or slugified-title match); zero or multiple
  candidates create as given — never guess. Same-payload links are rewritten and `remapped`
  pairs are reported for the caller's log. Backstops the "reference before creating" rule so
  id drift can't silently fork accumulation.
- **MCP enrichment budget.** The `knowledge-graph` skill now caps `mcp-preferred` discovery:
  one probe per invocation, ≤3 searches at a wave boundary (skipped entirely for large
  waves), ≤5 at runbook synthesis, always aimed outside the spec-loop subfolder (the helper's
  disk scans already cover the inside).

### Fixed
- **Stale coverage OMIT ranges for `dashboard_server.py`.** The
  `scripts/coverage_omit.txt` ranges (654-659/663-664) had drifted after the file
  grew and were silently omitting mid-file executable lines; re-pinned to the
  actual `serve_forever` tail and `__main__` shim.
- **Knowledge-graph run MOC now genuinely refreshes.** The grouped listing moved into a
  managed `<!-- kg:index -->` region replaced wholesale on every build (previously the body
  was written only on first create, so Phase 5 "finalize the MOC" left the Phase 1 listing
  stale). Pre-region MOC bodies from earlier alpha builds are upgraded in place on the next
  run — no user action needed, no file renames.
- **Knowledge-graph observation blocks are idempotent under retry.** Re-invoking an identical
  batch (controller retry, resumed runbook) no longer appends duplicate dated observation
  blocks; an identical payload now leaves the vault byte-identical.
- **Finalized run MOC includes wave-boundary nodes.** MOC refs are collected by scanning the
  vault for every node whose `runs` include the run-id (`query --run`), so decisions recorded
  at wave boundaries appear in the Phase 5 MOC without being re-upserted.

### Changed
- **Claude 5 context-engineering refactor of the entire prompt surface.** Every
  command, agent, and skill was rewritten for Claude 5-generation models
  (Opus 5-class) per Anthropic's context-engineering guidance: rules→judgment
  (red-flag negation lists, rationalization tables, and ALL-CAPS emphasis
  removed), examples→interface design (embedded worked-example outputs deleted;
  pinned output contracts are the interface), upfront→progressive disclosure
  (a new `references/` layer — `run-state.md`, `spec-loop/phase-5-integration.md`,
  `spec-loop/split-ingestion.md`, `spec-loop/knowledge-graph-steps.md` — loads
  late-phase and opt-in detail only when reached; `code-review-discipline` gains a
  linked `review-communication.md`; `systematic-debugging` now links its three
  technique files), and repetition→single-home (the Iron Council verdict schema
  lives only in `skills/iron-council`, the subagent-nesting rule only in
  `skills/dispatching-parallel-agents`, the dag.json schema/wave rule/marker
  lifecycle only in `references/run-state.md`, COMMIT-SAFETY only in the Phase 5
  reference). Security-critical guards (untrusted-data, read-only rules,
  commit-safety, SAFETY vetoes) are kept, compressed to standard forms. Net:
  always-loaded prompt surface shrinks ~39% (commands 1,293→763 lines, agents
  3,175→2,118, skills 4,783→2,923), with the hot-path controller down 60% and
  the slice worker down 49%. All machine-validated contracts
  (`council_contracts.py`, `quality_gate.py`) are unchanged and prose stays
  semantically identical to them.
- **Model-selection guidance rewritten for the Claude 5 family.**
  `subagent-driven-development` now defaults every dispatch to `model: inherit`
  (the session model, Opus 5-class) and reserves `model: sonnet` for cheap
  mechanical lanes; the haiku tier and `model: opus` pins are gone.
  `review-depth-map`'s Tier 3 rule lifts sonnet-pinned council members to the
  session model. Cost-tiered `model: sonnet` agent pins are retained; veto-holding
  reviewers stay `inherit`.
- **Per-file "Provenance and maintenance" sections consolidated** into a single
  maintainer-facing `PROVENANCE.md` (never loaded into model context), which also
  records the deliberate divergence from the `superpowers` /
  `pr-review-toolkit` upstreams introduced by this refactor.
- **Dependency drop: `superpowers` is no longer required.** The controller preflight,
  slice worker, escalation-gate/quality-gate/review-depth-map skills, dashboard, and
  READMEs now reference the native `spec-loop:*` process skills; the SDD helper scripts
  are located via `${CLAUDE_PLUGIN_ROOT}/skills/subagent-driven-development/scripts/`
  instead of globbing the superpowers plugin cache; slice plans move from
  `docs/superpowers/plans/` to `docs/spec-loop/plans/`.
- **Dependency drop: `pr-review-toolkit` is no longer required.** The controller
  preflight no longer checks for any external plugin; `review-depth-map`,
  `spec-loop-slice`, `peer-review-council`, `peer-review`, `escalation-gate`,
  `code-review-discipline`, `quality-gate`, `runbook`, `peer-review-tests`, and both
  READMEs now reference the native `spec-loop:review-pr` skill/command and
  `spec-loop:*` review agents. Combined with the superpowers drop above, the plugin
  has zero external plugin dependencies.
- `escalation-gate` now lists `quality-gate-block` as its fifth surface trigger — the
  quality-gate skill and slice worker already emitted it; the enum was missing it.
- `validate_marketplace.py` also checks `${CLAUDE_PLUGIN_ROOT}` references inside
  `hooks/*.json` (JSON-decoded, so escaped quotes in hook commands are handled) so an
  unshipped hook script can never reach a release.

## [1.2.1] - 2026-07-06
### Added
- **Stage-aware dashboard.** The run-detail view (both the `/spec-loop:dashboard` terminal
  view and the `/spec-loop:dashboard-serve` web SPA) now presents a run as a **pipeline of
  stages** — Iron Council → Execution → Final Review — with a specific view per stage and a
  persistent **Escalations** panel:
  - **Iron Council** — the council findings parsed from `decisions-log.md` (intake + per-slice
    verdicts: ENDORSE / ENDORSE_WITH_CONCERNS / OBJECT, with scope + summary).
  - **Execution** — the existing per-slice DAG view (waves, slice table now with a per-slice
    report marker, status rollup, recent decisions).
  - **Final Review** — an executive dashboard synthesized from the committed `runbook.md`
    (front-matter chips + the self-contained Executive Readout).
  - **Escalations** — a static, always-shown panel listing **every** escalation (open +
    answered) with its OPEN/ANSWERED status.
  The web SPA marks the run's current derived stage in a clickable pipeline strip and switches
  stage views without a refetch (`#run/<id>/<stage>` routing). Stages, council findings, and
  the runbook are **derived from cold artifacts** — the dashboard stays strictly read-only and
  never claims a slice/council is "running right now." New read-only `/api/runs[/…]` fields:
  `stage`, `council`, `escalations` (all, with status), `runbook`, and `artifacts`.
- `runbook` skill — at the end of a `/spec-loop` run, after the Phase 5 integration gate is
  green and just before the publish prompt, the controller synthesizes one committed
  `docs/spec-loop/<run-id>/runbook.md` from the run's durable artifacts (`dag.json`,
  `decisions-log.md`, `escalations.md`, `slice-*-report.md`): a self-contained **Executive
  Readout** plus What Was Built, Business Logic, Gaps/Deferred, requirement traceability, a
  decisions summary, the integration-gate result, and how-to-verify/operate. The runbook and
  its full run-state audit trail are committed onto the integration branch (staged by an
  explicit single-directory pathspec — never `git add -A` — because the run artifacts are
  untracked-not-ignored) **before** the publish prompt, so they travel with any push/merge;
  the Executive Readout is then printed verbatim as the run's final terminal output, replacing
  the previous ephemeral hand-written summary. The web dashboard's per-run scan now reports a
  read-only `has_runbook` flag.
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

## [1.2.0] - 2026-06-29
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

[Unreleased]: https://github.com/z2297/spec-loop/compare/v1.2.1...HEAD
[1.2.1]: https://github.com/z2297/spec-loop/releases/tag/v1.2.1
[1.2.0]: https://github.com/z2297/spec-loop/releases/tag/v1.2.0
[1.0.0]: https://github.com/z2297/spec-loop/releases/tag/v1.0.0
[0.4.0]: https://github.com/z2297/spec-loop/releases/tag/v0.4.0
[0.3.0]: https://github.com/z2297/spec-loop/releases/tag/v0.3.0
[0.2.0]: https://github.com/z2297/spec-loop/releases/tag/v0.2.0
