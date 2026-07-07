# spec-loop Optimization Roadmap

Optimizations to enhance the spec-loop plugin, grounded in a review of the current
architecture (`commands/spec-loop.md`, `agents/spec-loop-slice.md`, the iron-council /
quality-gate / review-depth-map skills, and agent frontmatter). Ranked by leverage.

**TLDR:** The biggest wins are (1) replacing free-text agent contracts with
schema-validated structured output, (2) moving the "never do X" guardrails from prompt
exhortation into deterministic PreToolUse hooks, and (3) scripting the quality-gate
measurement instead of prompting it. Below those are cost/latency optimizations
(risk-tiered councils, shared context bundles) and a genuine architectural option
(the Workflow tool as the wave scheduler).

---

## High leverage — reliability

### 1. Schema-validated structured output instead of parsed text blocks

✅ **Implemented 2026-07-07** (`council_contracts.py`, JSON verdict contracts, status sidecars — see CHANGELOG [Unreleased])

🟢 HIGH CONFIDENCE

The loop's correctness hinges on prompt-enforced text contracts: council members
"MUST end their reply with exactly this block" (`skills/iron-council/SKILL.md:65-75`),
and slice workers return a 9-line status block the controller parses
(`agents/spec-loop-slice.md:246-255`). A member that drifts from the format — omits
`BLOCKER:`, writes "Object" instead of "OBJECT" — silently corrupts the aggregation,
and a mis-parsed verdict is exactly the failure mode that matters most (a missed
SAFETY OBJECT).

**Plan:**
- Have each council member write its verdict as a JSON file
  (`docs/spec-loop/<run-id>/council/<slice>-<member>.json`).
- Give the convening layer a validation step: malformed verdict → re-dispatch that
  member once → still malformed → treat as OBJECT (**fail-closed, not fail-open**).
- Same for slice status: a JSON sidecar next to the report file.
- Files are also more durable than return-text for `--resume`.
- (If/when adopting the Workflow tool — item 8 — its `schema` option enforces this
  natively with retry-on-mismatch.)

### 2. Deterministic guardrails via plugin hooks

✅ **Implemented 2026-07-07** (`hooks/hooks.json` + `spec_loop_guard.py`; verified PreToolUse also fires in Task subagents)

🟢 HIGH CONFIDENCE

The plugin ships zero hooks — every safety property is prompt-enforced: never
`git push` during a run, never `git add -A`/`git add .` for the runbook commit
(`commands/spec-loop.md:336-346`), never work on `main`, never edit
`quality-gate.json` to force a pass (`agents/spec-loop-slice.md:277-279`). These are
exactly the invariants long-context autonomous agents eventually violate, and they
are all mechanically checkable.

**Plan:**
- Add `hooks/hooks.json` with a PreToolUse Bash hook, active when a run-marker file
  exists (e.g. `docs/spec-loop/<run-id>/.active`), that blocks:
  - `git push` (unless a publish-decision marker exists)
  - `git add -A` / `git add .`
  - checkout/commit on `main`/`master`
  - any write touching `~/.claude/spec-loop/quality-gate.json`
- This converts the longest "Red flags (never)" lists from hopes into invariants,
  and allows shortening the prompts — which are themselves a context cost on every
  dispatch.
- Biggest gap between the plugin and current agent-safety practice; moves further
  up the list if the plugin is headed for wider distribution.

### 3. Script the quality-gate measurement

✅ **Implemented 2026-07-07** (`quality_gate.py` — lizard/radon backends + built-in stdlib analyzer; skill is script-first)

🟢 HIGH CONFIDENCE

`skills/quality-gate/SKILL.md` Step 2 asks the model to detect the language, pick an
analyzer (radon/lizard/eslint), run it, parse output, and fall back to *heuristically
estimating* cyclomatic complexity by reading code. That is deterministic work being
done probabilistically — heuristic complexity estimates vary run-to-run, so the same
code can pass one slice and block another.

**Plan:**
- Follow the existing pattern in the repo (`scripts/pr_resolver.py`,
  `dashboard_launcher.py`): ship a `quality_gate.py` that takes a diff range +
  config path and emits JSON `{metric, value, threshold, pass, source}`.
- Bundle `lizard` (pip-installable, ~15 languages) as the preferred backend.
- The model's job shrinks to the part it is good at — the behavior-preserving
  refactor loop — and every gate decision becomes reproducible and cheap.

### 4. Adversarial verification of review findings before the auto-fix loop

✅ **Implemented 2026-07-07** (`review-finding-verifier` agent + slice Step 3b, cap 6/round, CONFIRMED-by-default)

🟡 MEDIUM CONFIDENCE

Step 4 of the slice worker applies any at/above-bar finding through 2 fix attempts,
then escalates (`agents/spec-loop-slice.md:190-194`). A hallucinated or context-blind
P1 therefore costs two full fix-and-re-review cycles and can end in a human
escalation for a non-issue. `receiving-code-review` discipline ("verify each
suggestion") helps, but the verifier is the same agent that must act on it.

**Plan:**
- Add a dedicated cheap refuter pass: for each blocking finding, dispatch one
  skeptic whose only mandate is to *disprove* the finding against the actual code.
- Only confirmed findings enter the fix loop; refuted ones are logged.
- This extends the council's adversarial philosophy post-review, where false
  positives are the dominant failure mode of automated review.

---

## Medium leverage — cost and latency

### 5. Risk-tier-scaled council and effort

✅ **Implemented 2026-07-07** (`review-depth-map` tier → council composition, `council="..."` plan-header field, `council_contracts.py aggregate --expect` fail-closed completeness check)

🟢 HIGH CONFIDENCE

Member-level model tiering is already partially done (skeptic/architect/pragmatist/
historian are `model: sonnet`; guardian and the risk/correctness reviewers are
`inherit`). But the council convenes all five members on **every** slice plan
regardless of the slice's risk tier — a Tier 1 docs/config slice gets the same
five-agent deliberation as a Tier 3 auth migration. The aggregation rules already
support a reduced council ("for a reduced council of N members, strictly more than
half", `skills/iron-council/SKILL.md:94`).

**Plan:**
- Let `review-depth-map` also map tier → council composition:
  - **Tier 1** → pragmatist + guardian (guardian stays everywhere so the SAFETY
    veto never loses coverage)
  - **Tier 2** → full five
  - **Tier 3** → full five at high effort
- On a 10-slice run that is ~20 fewer agent dispatches with no loss on the paths
  that matter.

### 6. One shared context bundle per convening

✅ **Implemented 2026-07-07** (`conventions.md` run artifact from Phase 0 exploration, shared context packet in the iron-council convening protocol, `shared_constraints` documented in the dag.json contract and passed to workers/councils)

🟡 MEDIUM CONFIDENCE

Each of the five members independently explores the codebase read-only to evaluate
the same plan — five agents re-reading the same files.

**Plan:**
- Have the convening layer assemble one context packet (plan text, slice object,
  the diff of files the plan names, plus the Phase 0 exploration summary) and pass
  it identically to all five. Identical long prompt prefixes also get prompt-cache
  hits when dispatched in a single message.
- Persist Phase 0 exploration: the controller already runs up to 3 Explore agents
  (`commands/spec-loop.md:115-116`) but their findings aren't saved — write them to
  `docs/spec-loop/<run-id>/conventions.md` and hand that to every slice worker and
  historian, instead of each rediscovering conventions per slice.

### 7. Cross-run learning

✅ **Implemented 2026-07-07** (historian reads prior runs' runbooks/decision logs/ANSWERED escalations as precedent; escalation-gate precedent check resolves already-adjudicated questions autonomously)

🟡 MEDIUM CONFIDENCE

Every run commits `decisions-log.md`, `escalations.md` (with human adjudications),
and a runbook — but nothing ever reads prior runs.

**Plan:**
- The historian's mandate is "prior decisions," so point it there explicitly: index
  `docs/spec-loop/*/runbook.md` and answered escalations as precedent.
- A human answer like "yes, we always prefer X over Y here" should prevent the same
  escalation in run N+1.
- Works with plain files — no Obsidian opt-in required — and makes the
  knowledge-graph feature valuable to the loop itself rather than write-only.

---

## Architectural option

### 8. The Workflow tool as the wave scheduler

🔴 LOW CONFIDENCE — evaluate, don't rush

The controller hand-implements a DAG scheduler in prompt-space: wave computation,
`--max-parallel` batching, split grafting, resume logic (`commands/spec-loop.md`
Phases 2–4). Claude Code's Workflow tool now does exactly this deterministically in
JavaScript — `pipeline()`/`parallel()` with a concurrency cap, `schema`-validated
agent returns, `agentType` support (so
`agent(prompt, {agentType: 'spec-loop:spec-loop-slice'})` works), and journaled
resume where completed slices return cached instantly.

**Would eliminate:** the "model mis-scheduled the wave" and "resume re-did completed
work" failure classes, and most of the background-nesting workaround section.

**Tradeoffs to verify before committing:**
- Workflow availability across users' surfaces.
- Whether the interactive touchpoints (batched `AskUserQuestion` rounds, publish
  prompt) sequence cleanly around workflow invocations (they would stay in the
  controller between per-wave workflow calls).
- Per-invocation opt-in semantics.

⚠️ VERIFICATION REQUIRED: test on a real multi-wave run before restructuring — a
hybrid (controller stays interactive, each *wave* becomes one Workflow call) is the
low-risk shape.

---

## Where to start

Items 1–3 are cheap, independent, and attack correctness rather than cost:

1. JSON verdict files with fail-closed validation (item 1)
2. `hooks/hooks.json` enforcing the git invariants (item 2)
3. `quality_gate.py` (item 3)

Item 5 is the quickest token win. Item 8 is worth a spike on a branch once item 1 is
done (structured contracts are a prerequisite for it anyway).

**Assumption to confirm:** this ordering optimizes for solo/small-team usage where
token cost and escalation noise matter more than multi-user hardening. If the plugin
is headed for wider distribution, item 2 (hooks) moves further up — prompt-only
guardrails in other people's repos is the reputational risk.
