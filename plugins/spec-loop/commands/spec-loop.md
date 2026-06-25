---
description: "Spec-driven autonomous loop: decompose a request into small slices, then plan→execute→review→fix each in parallel worktrees, surfacing only genuine decisions"
argument-hint: "<feature request> [--max-parallel N] [--risk-floor 1|2|3] [--resume <run-id>]"
allowed-tools: ["Bash", "Glob", "Grep", "Read", "Task", "AskUserQuestion"]
---

# Spec-Loop — autonomous spec-driven development loop

You are the **controller** for a spec-driven loop. You take one feature request,
decompose it into targeted slices, and drive each slice through
plan → execute → scoped review → auto-fix → merge — running independent slices
in parallel git worktrees as background agents. Slices that turn out too big
**split** themselves back into the DAG (dynamic decomposition), so your initial cut
can be coarse; once every slice lands, an **integration gate** (Phase 5) verifies the
assembled whole before the run is called complete. You run in the **main session**
because you are the only layer that can interactively ask the human anything.

**Request / arguments:** "$ARGUMENTS"

## Operating contract (read first)

- **REQUIRED SUB-SKILL:** `escalation-gate` governs every decision to stop or ask
  the human. Invoke it and follow it exactly. Default is proceed-and-log; surface
  to the human ONLY on (1) genuine ambiguity, (2) a material assumption, or
  (3) a review BLOCK that survived the auto-fix loop.
- **REQUIRED SUB-SKILL:** `review-depth-map` decides how far each slice's review
  goes, based on the slice's risk tier.
- **REQUIRED SUB-SKILL:** `iron-council` convenes a five-member adversarial council
  that challenges the work before effort is spent on it — once on the **user
  request** at intake (you run this), and once on **every slice plan** before
  execution (the slice worker runs this). The council surfaces discrepancies and
  returns opinionated verdicts; a majority OBJECT (or any single `SAFETY` OBJECT)
  means the work is **unworthy as proposed** and is lifted to you (the orchestrator)
  to prompt the human — via `escalation-gate`'s `council-objection` trigger. Lesser
  concerns are folded into the decomposition/plan and logged, never surfaced.
- **REQUIRED SUB-SKILL:** `quality-gate` is the objective, post-review bar each
  slice must clear before merge. Its thresholds live in the global config at
  `~/.claude/spec-loop/quality-gate.json`; you ensure that config exists (Phase 0)
  and pass its path to every slice.
- This loop **intentionally overrides** the human gates in `brainstorming` and
  `subagent-driven-development`. It does NOT override
  `superpowers:verification-before-completion`.
- Slice workers run in the **background** so the terminal is never blocked.
- Never let any slice work on `main` — every slice gets its own worktree.

## Preflight — required plugins

This loop chains skills from two other plugins. Before doing anything, confirm
both are installed and enabled (e.g. `claude plugin list`):
- `superpowers` (provides writing-plans, subagent-driven-development,
  executing-plans, using-git-worktrees, receiving-code-review,
  verification-before-completion, finishing-a-development-branch).
- `pr-review-toolkit` (provides review-pr). `exhaustive-pr-review` is optional,
  used only for Tier 3.

If either is missing, STOP and tell the human exactly what to install
(`/plugin marketplace add anthropics/claude-plugins-official` then
`/plugin install superpowers@claude-plugins-official` and
`/plugin install pr-review-toolkit@claude-plugins-official`). Do not try to
proceed without them.

## Phase 0 — Intake & decompose

1. If `--resume <run-id>` is present, skip to **Resume** below.
2. Parse flags: `--max-parallel` (default 5), `--risk-floor` (default 1).
3. **Quality-gate config (one-time).** Check whether
   `~/.claude/spec-loop/quality-gate.json` exists. If it does **not**, run the
   first-run setup once now — follow the `/spec-loop:quality-gate` command's routine
   to prompt the human (validate the quality level + any custom gates) and write the
   file. **Batch this with the Phase 0 step 6 `escalation-gate` round** so the human
   sees a single up-front interaction. If the file already exists, say nothing and
   proceed — never re-prompt.
4. Restate the request in your own words (per the user's global CLAUDE.md).
5. Explore the codebase to find reusable functions, patterns, and conventions —
   launch up to 3 `Explore` agents in parallel. Prefer reuse over new code.
6. **Convene the Iron Council on the request (intake).** Before decomposing,
   invoke the `iron-council` skill and dispatch all five members
   (`iron-council-skeptic`, `-architect`, `-pragmatist`, `-guardian`,
   `-historian`) on the **verbatim user request**, in a single message so they
   deliberate concurrently. Aggregate their verdicts per the skill:
   - **Council OBJECT** (majority object, or any `SAFETY` OBJECT) → the request is
     unworthy as posed. Run `escalation-gate` (trigger: `council-objection`) and add
     the objection to the **up-front batched question round** in step 8 — do not
     decompose or schedule until the human resolves it.
   - **ENDORSE_WITH_CONCERNS** → fold the concrete concerns into how you decompose
     (split/merge slices, drop gold-plating, reuse existing code, harden risky
     paths) and log them to `decisions-log.md`.
   - **ENDORSE** → proceed; log one line.
7. Decompose the request into independent slices, incorporating the council's intake
   feedback. A correct slice boundary passes the subagent-driven-development test:
   *a reviewer could meaningfully reject one slice while approving its neighbor.* Each
   slice should be a vertical, independently shippable change.
   - **You do not have to find the finest cut up front.** Slice workers refine their
     own slices via dynamic decomposition (slice Step 1.6): a slice that turns out to
     be two-or-more shippable changes returns `SPLIT` with a sub-decomposition you
     ingest in Phase 3. For large or fuzzy requests, prefer cutting at the first
     boundaries you are *confident* are independent and let the workers split deeper —
     this is cheaper and more accurate than guessing a fine-grained DAG before any
     code exists. Reserve aggressive upfront splitting for boundaries you are sure of.
8. Run `escalation-gate` on the request itself. If the request is genuinely
   ambiguous, forces a material assumption about scope, **or the Iron Council
   objected in step 6**, batch those now and ask via `AskUserQuestion` **before**
   spawning any work — together with any first-run quality-gate setup from step 3.
   (This is the one expected up-front interaction; everything after aims to be
   autonomous.)

## Phase 1 — Build the DAG and run state

1. Generate a `run-id` (e.g. `git log -1 --format=%cd --date=format:%Y%m%d`-`<short-slug>`; if that yields a duplicate, append `-2`, `-3`).
2. Record the integration base: `base_ref` = `git branch --show-current` and
   `base_sha` = `git rev-parse HEAD`. This is the branch each worker's clean
   worktree is created from. (Ensure `.worktrees/` is gitignored — the
   using-git-worktrees skill verifies and adds it, but check.)
3. Create `docs/spec-loop/<run-id>/` and write:
   - `request.md` — the original request, verbatim.
   - `dag.json` — `{ base_ref, base_sha, slices: [...] }` where each slice is `{id, goal, files, subsystems, deps:[ids], risk_tier:1|2|3, depth:0, parent:null, status:"pending"}`. Apply `--risk-floor` as the minimum tier. Assign tiers using `review-depth-map` heuristics. `depth` tracks split generation (intake slices = `0`); `parent` links a split child to the slice it came from. `status` may also become the terminal value `"split"` (Phase 3) when a slice is replaced by its children.
   - `escalations.md` — start empty (header only).
   - `decisions-log.md` — start empty (header only).
4. Sanity-check the DAG: no cycles, every `deps` id exists. If a cycle exists, that is a decomposition error — fix it yourself (collapse the cyclic slices into one) and log it.

## Phase 2 — Schedule waves

**Nesting rule (read first):** only the top-level session can run agents in the
background. A subagent ("in-process teammate") that tries to spawn a background
agent fails with "In-process teammates cannot spawn background agents." You (the
controller) are normally the top-level session, so you background the slice
workers. The slice workers are subagents and therefore dispatch all of THEIR
sub-agents synchronously (this is enforced inside `spec-loop-slice`). Never expect
background dispatch to work below depth 1.

1. A **wave** = every slice whose status is `pending` and whose `deps` are all `complete`.
2. For the current wave, dispatch up to `--max-parallel` `spec-loop-slice` agents.
   **Dispatch them in a single message, each `run_in_background: true`**, so they
   run concurrently without blocking the terminal (per the user's saved
   preference). Pass each agent: its slice object, the `run-id`, the absolute
   path to `docs/spec-loop/<run-id>/`, its risk tier, `base_ref`, and the absolute
   path to the quality-gate config (`~/.claude/spec-loop/quality-gate.json`). The worker's
   first action is to create a clean dedicated worktree from the current tip of
   `base_ref` under `.worktrees/spec-loop/<run-id>/<slice-id>` — before any other
   work.
   - **Fallback:** if a background dispatch is rejected because you are yourself a
     subagent (e.g. `/spec-loop` was invoked from within another agent), re-dispatch
     the wave's slices **synchronously** (`run_in_background: false`) instead. The
     loop still works correctly; it just runs the slices one at a time and blocks
     until each returns. Note this in your summary so the user knows parallelism
     was unavailable.
3. If a wave has more slices than `--max-parallel`, dispatch in batches; start the
   next batch as background slots free up.

## Phase 3 — Collect & gate (wave boundary)

1. When the wave's background agents report, read each slice's returned status:
   - `DONE` → set the slice `status:"complete"` in `dag.json`.
   - `SPLIT` → the slice is two-or-more shippable changes; ingest its children (step 3).
   - `NEEDS_DECISION` → leave it `pending`; its escalation is in `escalations.md`.
   - `BLOCKED` → leave it `pending`; treat its blocker as an escalation too.
2. Verify each `DONE` claim independently before trusting it
   (`superpowers:verification-before-completion`): check the worktree's git log /
   diff and test evidence in the slice's report. If a slice claims DONE without
   evidence, treat it as `NEEDS_DECISION`.
3. **Ingest splits (dynamic decomposition).** For each slice that returned `SPLIT`,
   read its proposed sub-decomposition at `docs/spec-loop/<run-id>/slice-<id>-split.json`
   and graft the children into `dag.json`:
   - Insert each child as a `pending` slice with id `<parent-id>.1`, `<parent-id>.2`, …,
     `depth = parent.depth + 1`, `parent = <parent-id>`. Carry the child's
     `files`/`subsystems`/`goal` from the proposal; assign each child a `risk_tier`
     via `review-depth-map` heuristics (never below `--risk-floor`).
   - **deps:** children inherit the parent's external `deps`. Translate each child's
     `internal_deps` indices into the sibling child ids and add them.
   - **Rewrite dependents:** every other slice that listed the parent in its `deps`
     now depends on **all** of the parent's children instead (replace the parent id
     with the full set of child ids).
   - Mark the parent `status:"split"` (terminal — not counted as incomplete).
   - Re-run the Phase 1 sanity check (no cycles, every `deps` id exists), then append
     one line to `decisions-log.md` recording the graft. The children schedule in
     later waves like any `pending` slice — no special wave logic.
4. **Per-wave integration check (lightweight).** After this wave's `DONE` slices have
   merged into `base_ref` (their Step 5 `finishing-a-development-branch`), run the
   project's full test/build **fresh on `base_ref`** and read the output
   (`superpowers:verification-before-completion` discipline). This catches same-wave
   merge incompatibilities and cross-slice drift *early*, while remediation is cheap —
   two slices in one wave both branched from the same tip and merged blind to each
   other. Green → continue. Red → open a **remediation slice** (Phase 5's procedure)
   for the failure and schedule it; do not advance as if the wave were clean.
5. Collect ALL `OPEN` entries from `escalations.md` and surface them as ONE
   batched `AskUserQuestion` round (one question per escalation, with the
   recommended default first). Do not ask one-at-a-time across waves.
6. Write the human's answers back into `escalations.md` (set `status: ANSWERED`)
   and re-dispatch each answered slice via a fresh `spec-loop-slice` agent with
   the answer injected into its prompt.

## Phase 4 — Loop

Repeat Phases 2–3 until every slice in `dag.json` is terminal — `complete` or
`split` (a split parent is replaced by its children, which must themselves reach
`complete`). Slices left `pending` because of an open escalation block the run until
answered. Once every slice is terminal, proceed to Phase 5.

## Phase 5 — Integration gate (verify the assembled whole)

Each slice merged after passing *its own* tests in *its own* worktree — but nothing
has yet verified the slices **together**. This phase does, before the run is called
complete. (Analogous to a cross-phase integration check.)

1. **Full test/build on `base_ref`.** Run the project's complete test and build
   suite fresh on `base_ref` (which now contains every merged slice) and read the
   output. This is the assembled whole, not any single slice's worktree.
2. **Cross-slice integration review.** Run ONE synchronous `pr-review-toolkit:review-pr`
   over the **cumulative diff** `base_sha..HEAD` of `base_ref`, at the run's **highest
   slice risk tier** (via `review-depth-map`). Scope it to integration concerns:
   contract consistency across slices (a signature one slice changed and another
   calls), wiring, and end-to-end flows that span slices — the failures a per-slice
   review structurally cannot see.
3. **Remediate (bar unchanged).** If steps 1–2 surface failures:
   - Create a **remediation slice** — a normal `pending` slice in `dag.json`
     (`depth:0`, `parent:null`, risk tier = run max, `deps` = all completed slices)
     whose goal is to fix the specific integration failure — and dispatch it through
     a fresh `spec-loop-slice` like any other slice. It runs the same plan → execute →
     review → quality-gate → verify → merge loop with the same bounded auto-fix.
   - Re-run Phase 5 after the remediation slice merges.
   - Only if a remediation slice itself exhausts its bounded loop and returns
     `NEEDS_DECISION` does this reach the human — through the **existing**
     `escalation-gate` (`review-block`) at the next wave boundary. No new trigger;
     the bar is exactly the per-slice bar applied to the whole.
4. **PR-mode variant.** If slices opened PRs instead of merging to `base_ref`
   (their `finishing-a-development-branch` chose PR), there is no merged base to test.
   Build a **throwaway integration branch** off `base_sha`, merge every completed
   slice branch into it, run steps 1–2 there, report the integration status, then
   delete the branch — leaving the PRs untouched for the human to merge. (Merge-to-
   `base_ref` is the primary path; this is the fallback.)

When Phase 5 is green, produce the **final summary**:
- Slices completed, with branch/PR for each (note any `split` parents and their children).
- The `decisions-log.md` (auto-decisions made on the human's behalf, including splits).
- Integration gate result (suite + cross-slice review; any remediation slices added).
- Any slices that remain blocked and why.

## Resume

For `--resume <run-id>`: read `docs/spec-loop/<run-id>/dag.json`, skip all terminal
slices (`complete` and `split` parents), drain any `ANSWERED` escalations into
re-dispatches, and continue from the first wave that has runnable slices. If every
slice is already terminal, go straight to the Phase 5 integration gate before
declaring the run done.

## Guardrails
- Never dispatch two implementer-level agents that touch the same files
  concurrently — that is what the dependency DAG and per-slice worktrees prevent.
- Never surface an escalation that `escalation-gate` would resolve as proceed-and-log.
- Never claim the run is complete without verifying each slice's evidence.
