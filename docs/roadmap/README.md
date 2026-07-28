# spec-loop Self-Audit Roadmap — Making the Loop Improve Itself

## Context

**Audit verdict.** spec-loop is already a state-of-the-art autonomous dev loop for the forward-deployed-engineer (FDE) profile: an FDE lands in an unfamiliar client codebase and must ship autonomously while leaving a defensible evidence trail. The plugin's architecture maps onto that need almost exactly — adversarial intake (Iron Council), risk-tiered review depth, fail-closed machine-verifiable contracts (`council_contracts.py`), deterministic guard hooks, an escalation gate that batches only genuine human decisions, and a committed runbook with requirement traceability that doubles as client handoff documentation. The multi-repo read-only dashboard and zero-third-party-dependency posture make it deployable inside locked-down client environments.

**The gap.** The plugin *measures* itself (the in-flight `run_metrics.py` produces null-honest, versioned `metrics.json` per run, plus a cross-run `trend` CLI) but nothing *interprets* those measurements or closes the loop. Concretely (verified against the code):

- **D1** — Metrics are descriptive only; nothing reads them to conclude "escalation rate regressed" or propose what to change.
- **D2** — Cross-run precedent only covers human-ANSWERED escalations; the far larger proceed-and-log auto-decision population is never revisited.
- **D3** — Council OBJECT rates and verifier REFUTE decisions are counted but never scored against outcomes (no calibration).
- **D4** — Quality-gate thresholds are global/static; no per-repo baseline adaptation.
- **D5/D6** — Integration-gate failures and split causes are rediscovered every run; nothing seeds `shared_constraints` from history. No cross-run dashboard surface exists (`/api/runs` only).

**The eight improvements** (each independently shippable):

1. **`/spec-loop:self-audit`** (flagship) — deterministic rule engine (`self_audit.py`) over cross-run metrics → versioned improvement-vector findings → LLM proposal layer emitting `--from-plan`-consumable plans. Makes the plugin literally self-auditing.
2. **Calibration scoring** — instrument human adjudications and finding↔failure joins; new `calibration` metrics section (council override rate, verifier refute-suspect rate, concerns materialization). Descriptive only.
3. **Auto-decision retrospective sampling** — `spotcheck` selects highest-stakes auto-decisions into runbook §5a; `/spec-loop:decisions review` records ENDORSED/OVERTURNED verdicts that become precedent/anti-precedent.
4. **Per-repo adaptive quality-gate baseline** — `quality_gate.py baseline` proposes repo-scoped thresholds (tightening-only by default) into a repo overlay.
5. **Decomposition-lesson feedback** — `run_metrics.py lessons` harvests prior integration failures/split hotspots; Phase 0 seeds `shared_constraints` from them.
6. **Cross-run dashboard surface** — `/api/trend` + `/api/audits` endpoints + trend/audit UI; knowledge-graph `audit` node type.
7. **Domain lexicon (ubiquitous language)** — a user-curated controlled vocabulary in the knowledge graph's existing `domain` channel (`<repo>-lexicon` note): canonical term → definition → forbidden synonyms → domain rule. Rendered into `conventions.md` so it guides naming and domain rules in every slice; the loop *proposes* candidate terms at runbook, the user approves via `/spec-loop:knowledge-graph`. Advisory (Historian-enforced), never a hard gate.
8. **Controller-lane enforcement** — deterministic, hook-enforced insurance that the orchestrator (main session) never does executor work: while a run is `.active`, `spec_loop_guard.py` denies any main-session source write/edit (or code-mutating Bash) outside a spec-loop worktree and the run-state allowlist. Closes a real-incident gap where the controller began implementing a "prerequisite" itself instead of dispatching a slice.

**Execution model:** dogfood — each phase below is written as a plan file under `docs/roadmap/` and executed via `/spec-loop --from-plan docs/roadmap/<nn>-<name>.md`. Each dogfood run generates fresh instrumented run artifacts that the final self-audit (Phase 6) analyzes — proving the loop end-to-end.

**Reconciled design decisions:**
- Human adjudication grammar: ONE token — the escalation body field `- Resolution: <override | sustain | redirect>` written by the controller at answer write-back. `run_metrics.py` derives `safety.escalations.objection_outcomes {upheld: sustain, overridden: override}` from it; self-audit's `council-objection-calibration` rule consumes that.
- All metrics changes are **additive keys under `SCHEMA_VERSION = 1`** (documented discipline: bump only on breaking change). Quality-gate *report* `version` bumps 1→2 in Phase 4 (its `config` field changes type).
- Reversibility vocabulary is `trivial|moderate|high|n/a` — "highest-stakes" = `high`.
- Domain lexicon is a **user-owned** `domain` node (`<repo>-lexicon`), never machine-written: the runbook *proposes* candidate terms into `docs/spec-loop/<run-id>/lexicon-candidates.md`; only `/spec-loop:knowledge-graph` (human approval) merges approved terms into the authoritative note. Enforcement is **advisory** — surfaced via `conventions.md`, checked by the Iron Council Historian (Tier 2/3), with `writing-plans` Global Constraints + `dag.json shared_constraints` covering Tier-1 slices where the Historian is absent.

---

## Phase 0 — Land the in-flight run-metrics slice (direct, prerequisite)

The working tree has 16 modified + 2 new files: `run_metrics.py`, `test_run_metrics.py`, instrumentation threading through `commands/spec-loop.md`, `agents/spec-loop-slice.md`, `skills/escalation-gate/SKILL.md`, `skills/runbook/SKILL.md`, dashboard metrics view, contracts, Dockerfile, coverage floors. Everything below depends on it.

- Run the full validation suite (`python3 -m unittest discover`, `scripts/measure_coverage.py`, node dashboard tests, `validate_marketplace.py`) and commit on `alpha` as the run-metrics feature.
- Also commit `docs/roadmap/` phase-plan files authored per this roadmap (Phases 1–5 below each get one plan file with Context / Approach / Files to Change / Verification sections, shaped for `--from-plan`).

## Phase 1 — Calibration instrumentation + metrics substrate (`docs/roadmap/01-calibration.md`)

The shared grammar every later phase joins on. **Files:**
- `skills/escalation-gate/SKILL.md` — optional `- Resolution:` body field (semantics: override = human proceeded as loop proposed; sustain = human upheld the objection/block; redirect = neither).
- `commands/spec-loop.md` — Phase 3.6 answer write-back writes `Resolution:`; Phase 3.4b/5.3 integration failures logged as pinned `INTEGRATION CHECK|GATE: FAIL — CLASS: <contract-drift|merge-conflict|test-collision|missing-wiring|env-setup|other> — FILES: <paths> — AT: <ISO>`; remediation slices in `dag.json` gain structured `"cause": {class, files, phase}`.
- `agents/review-finding-verifier.md` — output JSON gains optional `files: [...]`; `agents/spec-loop-slice.md` — Step 3b REFUTED line gains `— FILES:` token; Step 4c quality-gate line gains `BREACHES: <metric>×<n>, …`.
- `skills/quality-gate/SKILL.md` — BREACHES token in the decisions-log line contract; `skills/iron-council/SKILL.md` — one sentence noting Resolution records adjudication.
- `scripts/run_metrics.py` — new regexes (RESOLUTION/CLASS/FILES/BREACHES, all optional; legacy lines stay valid); `parse_sidecar` reads existing `council.verdict`; `parse_dag` reads `remediation_causes`; new additive `calibration` section (`council.override_rate`, `verifier.refuted_suspect` via FILES∩integration-FAIL join, `concerns.materialization_rate` — every rate null when denominator is 0); `quality.quality_gate.breaches_by_metric`; `safety.escalations.objection_outcomes`; extract public `collect_full_metrics(root)` from `trend_rows` (lines ~1040–1048) for Phase 2 reuse; `summary_row` gains `council_override_rate`, `refute_suspect_rate` (tolerant `.get`).
- Tests: `test_run_metrics.py` legacy-fixtures-stay-null + modern-fixtures-join cases; `test_council_contracts.py` regression that a sidecar carrying `council` still validates.

## Phase 2 — Self-audit engine (`docs/roadmap/02-self-audit.md`)

**New `plugins/spec-loop/scripts/self_audit.py`** (stdlib-only, pure-core/thin-shell mirroring `run_metrics.py`): consumes only metrics documents via `run_metrics.collect_full_metrics` (never raw prose), applies a fixed rule catalog over run windows (recent-vs-prior-median, default window 3), emits `AUDIT_SCHEMA_VERSION = 1` report.

- **Rule catalog** (~15 rules, three families): *regression* (`autonomy-regression`, `first-pass-regression`, `wall-clock-per-slice-growth`, `token-per-slice-growth`, `escalation-rate-regression`), *calibration* (`council-objection-calibration` — reads Phase 1's `objection_outcomes`; `review-refute-rate-high`; `escalation-trigger-concentration`; `split-rate-high`; `integration-remediation-recurrence`), *threshold-fit* (`quality-gate-metric-dominance` via `breaches_by_metric`; `quality-gate-never-exercised`; `fail-closed-recurrence`; `precedent-reuse-absent`), plus meta-rule `insufficient-history`. Each rule declares min sample; insufficient data → `status: insufficient_sample` with exact required-vs-actual counts, never a fabricated finding.
- **Findings**: `{id (rule_id + sha256-prefix, byte-stable), category, severity, source: "script", evidence {metric, medians, delta, runs, basis}, suggested_vector {kind, targets, direction}, confidence (deterministic from channel precision + sample), verification {metric, expected_direction, horizon_runs}}`.
- **Report location**: `docs/spec-loop/self-audit/<audit-id>/{audit.json, audit.md}` — invisible to run discovery (no `dag.json`), inside the dashboard trust boundary, colocated with evidence. Multi-repo via repeated `--root` with namespaced evidence ids.
- **CLI**: `compute [--root]... [--window N] [--config] [--md] [--write]` and `rules [--md]` (self-documenting catalog). Optional config `~/.claude/spec-loop/self-audit.json` (fail-soft, provenance recorded).
- **New `commands/self-audit.md`** — LLM layer: optionally refresh missing `metrics.json`, run the script (never edits its output), Read each finding's `suggested_vector.targets`, draft `proposals/<finding-id>.md` — self-contained plan-mode-shaped files (frontmatter `source: llm-proposal` + finding id; Context quotes script evidence verbatim; Verification quotes the finding's `verification` block) — and print ready-to-paste `/spec-loop --from-plan <proposal>` lines. Provenance separation mirrors `quality_gate.py` source labels.
- Tests `test_self_audit.py`: per-rule triggered/ok/insufficient triads, determinism, null-honesty, schema pin, renderer, shell write atomicity, multi-root. Add to `measure_coverage.py` `TARGET_FILES` + `PER_FILE_FLOORS` + omit entry for `__main__` shim.

## Phase 3 — Retrospective sampling + decomposition lessons (`docs/roadmap/03-retrospective-lessons.md`)

Two independent slice groups, one run:

**A. Auto-decision spot-check.** `run_metrics.py spotcheck <run-dir>` (deterministic: all `REVERSIBILITY: high` decisions, then `moderate` gated by material-keyword regex, cap 10); runbook §5a "Auto-decisions for human spot-check" table + front-matter `decision_spotcheck`; new `commands/decisions.md` (`/spec-loop:decisions review [run-id]`, batched AskUserQuestion, appends `[<slice>] REVIEWED: ENDORSED|OVERTURNED — DECISION: <≤120-char prefix> — … — AT: <ISO>` to new durable `docs/spec-loop/<run-id>/decision-reviews.md`, single-pathspec commit offer, optional KG observation + `status: superseded` on OVERTURNED); `skills/escalation-gate/SKILL.md` precedent check extended — ENDORSED = precedent, OVERTURNED = **anti-precedent** (repeating it MUST surface); `run_metrics.py` gains `parse_decision_reviews` + additive `safety.decision_reviews {reviewed, endorsed, overturned, overturn_rate}`.

**B. Decomposition lessons.** `run_metrics.py lessons <repo-root>` — bounded, newest-first JSON of `integration_failures` (Phase 1's CLASS/FILES lines), `remediations` (dag `cause`), `split_hotspots`, runbook §3 `gap_lines`; `commands/spec-loop.md` Phase 0 step 5 appends a "Decomposition lessons (prior runs)" section to the conventions summary and seeds `dag.json shared_constraints` from recurring failure classes (fail-soft: any error → omit silently); `skills/iron-council/SKILL.md` historian mandate note.

## Phase 4 — Per-repo quality-gate baseline (`docs/roadmap/04-repo-baseline.md`)

- `scripts/quality_gate.py`: `load_config` → `resolve_config(global, repo_overlay)` with tightening-only merge (weaker overlay keys ignored + reported unless `allow_weaker: true` + `ack` block, written only by the interactive command); overlay auto-discovered at `<repo>/.claude/spec-loop/quality-gate.json` (same basename ⇒ existing guard Bash rule already denies mid-run shell edits); new `baseline` subcommand (measure existing codebase via `git ls-files` + `measure()`, propose p90 clamped to [Strict-preset floor, global ceiling], print-only by default, `--write` refuses while any `docs/spec-loop/*/.active` exists); report `version` 1→2 (`config` → `sources` object — update the skill's report-shape prose).
- `scripts/spec_loop_guard.py`: `check_write` denies the repo overlay realpath while active; `check_bash` denies `quality_gate.py … baseline … --write` while active.
- `commands/quality-gate.md` "Repo baseline" section (side-by-side proposal, explicit ack question for weaker keys); `skills/quality-gate/SKILL.md` resolution-order note + red flag; controller/slice-agent pass `--repo-config` through.
- Tests: resolution matrix, p90/clamp/requires_ack math, `.active` refusal, guard denials (incl. nonexistent-overlay realpath case).

## Phase 5 — Cross-run surfaces (`docs/roadmap/05-surfaces.md`)

- `dashboard_server.py`: `/api/trend` (per-root `run_metrics.trend_rows`, namespaced, ETag'd, null-honest degrade when run_metrics absent); `/api/audits` + `/api/audits/<id>` (glob `self-audit/*/audit.json`, `resolve_within`-contained, malformed-tolerant, capped); `index.html` `#/trend` route with trend table + latest-audit findings panel grouped by severity; both JS + Python test suites extended.
- `knowledge_graph.py` + skill/command docs: new opt-in `audit` node type (mirrors the `review` type precedent) — one node per audit, dated observations per finding, wikilinks to evidence `run` nodes; wire optional projection step into `commands/self-audit.md`.

## Phase 6 — Close the loop (direct)

Run `/spec-loop:self-audit` against the accumulated runs from Phases 1–5 (all instrumented with the new grammar). Verify it produces an honest report — findings where signals exist, `insufficient_sample` where they don't — and that its `proposals/*.md` are valid `--from-plan` inputs. **The audit's findings become the next roadmap.** Update `README.md` + `CHANGELOG.md` with the self-audit story.

## Phase 7 — Domain lexicon: knowledge graph as ubiquitous-language reference (`docs/roadmap/07-domain-lexicon.md`)

Turn the knowledge graph into an authoritative, user-owned **domain-specific lexicon** that guides naming and domain rules in generated code — unambiguous, user-provided, and evolving (curated) each run. **Reuses the existing `domain` node channel** — no new node type, no `node_types` config change. Independent of Phases 1–6: depends only on the already-shipped knowledge-graph feature, so it can ship on its own track.

**Seed & curate (user-provided).**
- `commands/knowledge-graph.md` — new **lexicon mode**: import terms from a file or interactive entry; each term = `{canonical, definition, forbidden: [synonyms], rule?}`. Writes/updates the ONE per-repo `domain` note `Domain/<repo>-lexicon.md`.
- `scripts/knowledge_graph.py` — new managed body region `<!-- kg:lexicon --> … <!-- /kg:lexicon -->` (replace-wholesale, mirroring the existing `kg:index` region): a deterministic term table the command owns; a `lexicon` subcommand (`add`/`list`/`approve`) + a `lexicon-render` that emits the `## Domain lexicon` block for `conventions.md`. Idempotent; human prose above the region is never touched.

**Guide implementation (read path).**
- `commands/spec-loop.md` Phase 0 step 5 — when the graph is enabled, render the repo's lexicon into a dedicated `## Domain lexicon` section of `conventions.md` (alongside `## Prior knowledge (knowledge graph)`), and seed `dag.json shared_constraints` with the lexicon's domain **rules** so Tier-1 slices (which skip the Historian) still carry them. Fail-soft: any error → omit silently. No hot-path change — per-wave component context already flows to slices.
- `skills/writing-plans/SKILL.md` — Global Constraints note: the lexicon's canonical terms and forbidden synonyms are implicit naming rules for every task.
- `agents/spec-loop-slice.md` Step 1 — one line: prefer the lexicon's canonical terms when naming.

**Enforce (advisory).**
- `skills/iron-council/SKILL.md` + `agents/iron-council-historian.md` — Historian mandate extended: flag identifiers/domain nouns that use a forbidden synonym or an undefined ambiguous term instead of the lexicon's canonical name (ENDORSE_WITH_CONCERNS normally; OBJECT on material drift). Tier 2/3 only — Tier-1 coverage is the `conventions.md` / `shared_constraints` / `writing-plans` path above.

**Evolve (curated, propose→approve).**
- `skills/runbook/SKILL.md` Phase 5 — after synthesis, harvest candidate terms (domain nouns from decisions / §2 Business Logic + any forbidden-synonym usages the review surfaced) into `docs/spec-loop/<run-id>/lexicon-candidates.md`; record a `lexicon` block in runbook front-matter (`proposed`, `already_known`). **The loop never writes the authoritative note.**
- `commands/knowledge-graph.md` lexicon mode — an **approve** step: read a run's `lexicon-candidates.md`, batched `AskUserQuestion`, merge approved terms into `Domain/<repo>-lexicon.md`, offer a single-pathspec commit.

**Tests:** `test_knowledge_graph.py` — `kg:lexicon` region idempotency + wholesale replace, `lexicon` subcommand `add`/`list`/`approve`, `lexicon-render` byte-stability, forbidden-synonym dedup, legacy-note-without-region stays valid. Add any new `knowledge_graph.py` lines to `measure_coverage.py` floors.

## Phase 8 — Controller-lane enforcement: the orchestrator never does executor work (`docs/roadmap/08-controller-lane.md`)

**Motivation (real incident).** During a live run, while three slice workers ran in the background, the **controller** (main session) began implementing a "prerequisite" itself in a sibling repo — *"Concurrently, I'll do the LIB prerequisite myself in the sibling repo… a TDD change to `PaymentsClient`."* — escaping its coordination lane. The controller/executor separation was **prose-only**; nothing mechanically stopped a main-session source edit. This phase adds belt-and-suspenders insurance. Reuses the existing PreToolUse guard (`spec_loop_guard.py`); independent of Phases 1–7.

**Invariant (belt — prose).**
- `commands/spec-loop.md` role header + a new **Guardrail**: the controller **NEVER** implements, writes, or edits source, tests, or config to satisfy the request — including "prerequisite"/"setup"/"just this one" work, and including in **sibling/other repos**. ALL code changes flow through a slice worker (an existing slice, a newly grafted slice, or a remediation slice). A discovered prerequisite becomes its own slice (with a dep edge) or a batched escalation — never controller-authored code. The controller's only writes are run-state artifacts under `docs/spec-loop/<run-id>/`, the serial integration merge, and the runbook commit.
- `agents/spec-loop-slice.md` — reaffirm the mirror invariant: executors implement and never assume orchestration duties.
- `skills/iron-council/SKILL.md` — intake/Historian note: a request that tempts the controller to "just do the prereq" is a **decomposition signal**, not a controller task — split it into a slice.

**Enforcement (suspenders — deterministic hook).**
- `scripts/spec_loop_guard.py` — while any `.active` marker exists, deny a `Write`/`Edit`/`MultiEdit` (or a source-mutating `Bash`: `>`/`>>`/`tee`/`sed -i`/`mv`/`cp`/code here-docs) whose realpath is **outside** a spec-loop worktree (`<root>/.worktrees/spec-loop/…`) **and** outside the controller allowlist (the run-state dir `docs/spec-loop/<run-id>/`, `docs/spec-loop/plans/`). The deny reason names the compliant path ("dispatch or graft a slice — the controller does not implement"). **Slice workers are unaffected** — their target/cwd is inside their worktree. Uses the `cwd` + absolute `file_path` already in the payload and the same `realpath` containment `check_write` already performs; **covers sibling-repo edits** because a sibling source file is neither in a worktree nor in the allowlist. Fail-open on internal error, matching the module's existing defense-in-depth stance.
- Preserve legitimate **Phase 6 "direct" edits** (README/CHANGELOG): those run after `.active` → `.done`, so they fall outside the active window — verify and document this ordering so the guard never fights a legitimate direct phase.

**Tests:** `test_spec_loop_guard.py` — main-session source edit while active → **DENY**; the identical edit under `.worktrees/spec-loop/<run>/<slice>/` → **ALLOW**; run-state write under `docs/spec-loop/<run>/…` → **ALLOW**; sibling-repo source edit (absolute path outside the root) while active → **DENY**; source-mutating Bash (`sed -i`, redirect) outside a worktree → **DENY**; no active run → **ALLOW** (fail-open baseline). Regression: the existing push/broad-staging/main-branch/config-edit cases still pass.

---

## Build order & dependencies

```
Phase 0 (direct commit)
  └─ Phase 1 (calibration grammar — the substrate)
       ├─ Phase 2 (self-audit engine — consumes objection_outcomes, breaches_by_metric, collect_full_metrics)
       │    └─ Phase 5 (audit dashboard/KG surfaces)   } 3/4/5 parallel-safe
       ├─ Phase 3 (spotcheck + lessons — consumes CLASS/FILES/cause)
       └─ Phase 4 (repo baseline — independent; only merge-conflict coupling on quality_gate.py)
  └─ Phase 6 (direct: run the self-audit, harvest next vectors)

Phase 7 (domain lexicon — independent; builds on the shipped knowledge-graph feature, not the self-audit chain)
Phase 8 (controller-lane enforcement — independent; builds on the shipped spec_loop_guard.py hook, not the self-audit chain)
```

Each dogfood phase = one `/spec-loop --from-plan docs/roadmap/<nn>-<name>.md` invocation on a fresh integration branch from `alpha`.

## Verification

- **Per phase (enforced by the loop itself):** slice-level TDD, PR review, quality gate, integration gate; plus the repo's CI suite — `python3 -m unittest discover` over both script dirs, `scripts/measure_coverage.py` floors (new files added to `TARGET_FILES` with floors set at measured-max − 5), `node --test` dashboard suite, `validate_marketplace.py`, `claude plugin validate`.
- **Backward compatibility:** every parser change tested against the LEGACY fixtures (committed `docs/spec-loop/20260630-full-coverage` run) — legacy artifacts must yield nulls, never errors or fabricated values.
- **End-to-end (Phase 6):** `python3 plugins/spec-loop/scripts/self_audit.py compute --md` over the repo's real run history returns a deterministic report; re-running byte-stable modulo timestamps; `run_metrics.py trend --md` shows the dogfood runs; dashboard `#/trend` renders them; one proposal file round-trips through `/spec-loop --from-plan` intake without escalating on format.
- **Domain lexicon (Phase 7):** `knowledge_graph.py lexicon add`/`list` round-trips a term; `lexicon-render` output is byte-stable; a seeded lexicon appears as a `## Domain lexicon` section in a run's `conventions.md`; a run emits `docs/spec-loop/<run-id>/lexicon-candidates.md`; `/spec-loop:knowledge-graph` approve merges an approved term idempotently (re-approve = no-op).
- **Controller-lane enforcement (Phase 8):** with a `.active` marker present, `spec_loop_guard.py` denies a main-session (outside-worktree) source Write/Edit and a code-mutating Bash, while allowing the same operation inside a `.worktrees/spec-loop/…` slice worktree and allowing run-state writes under `docs/spec-loop/<run-id>/`; with no active marker every case allows (fail-open). Assert both the deny reason text and the worktree/allowlist carve-outs.

## Key files

New: `plugins/spec-loop/scripts/self_audit.py` + `test_self_audit.py`, `commands/self-audit.md`, `commands/decisions.md`, `docs/roadmap/01–05-*.md`, `docs/roadmap/07-domain-lexicon.md`, `docs/roadmap/08-controller-lane.md`.
Modified (hot spots): `scripts/run_metrics.py` (calibration/spotcheck/lessons/collect_full_metrics), `commands/spec-loop.md` (Resolution write-back, failure tokens, Phase 0 lessons, Phase 7 lexicon render, Phase 8 controller-lane guardrail), `commands/knowledge-graph.md` (lexicon mode), `skills/escalation-gate/SKILL.md`, `agents/spec-loop-slice.md`, `agents/review-finding-verifier.md`, `agents/iron-council-historian.md`, `scripts/quality_gate.py` + `spec_loop_guard.py` (+ `test_spec_loop_guard.py`, controller-lane deny), `scripts/dashboard_server.py` + assets, `scripts/knowledge_graph.py` (+ `test_knowledge_graph.py`, `kg:lexicon` region), `scripts/measure_coverage.py`, `skills/{writing-plans,runbook,quality-gate,iron-council,knowledge-graph}/SKILL.md`, `README.md`, `CHANGELOG.md`.
