---
description: "Spec-driven autonomous loop: decompose a request into small slices, then plan→execute→review→fix each in parallel worktrees, surfacing only genuine decisions"
argument-hint: "<feature request> [--branch <name>] [--base-branch <name>] [--max-parallel N] [--risk-floor 1|2|3] [--per-slice-pr] [--resume <run-id>]"
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
  to the human ONLY on (1) genuine ambiguity, (2) a material assumption, (3) a
  review BLOCK that survived the auto-fix loop, (4) an Iron Council objection, or
  (5) a quality-gate block that survived the refactor loop — `escalation-gate` is
  authoritative on all five triggers.
- **REQUIRED SUB-SKILL:** `review-depth-map` decides how far each slice's review
  goes, based on the slice's risk tier.
- **REQUIRED SUB-SKILL:** `iron-council` convenes an adversarial council that
  challenges the work before effort is spent on it — once on the **user request**
  at intake with the full five members (you run this), and once on **every slice
  plan** before execution with a composition scaled to the slice's risk tier
  (the slice worker runs this; Tier 1 convenes only pragmatist + guardian). The council surfaces discrepancies and
  returns opinionated verdicts; a majority OBJECT (or any single `SAFETY` OBJECT)
  means the work is **unworthy as proposed** and is lifted to you (the orchestrator)
  to prompt the human — via `escalation-gate`'s `council-objection` trigger. Lesser
  concerns are folded into the decomposition/plan and logged, never surfaced.
- **REQUIRED SUB-SKILL:** `quality-gate` is the objective, post-review bar each
  slice must clear before merge. Its thresholds live in the global config at
  `~/.claude/spec-loop/quality-gate.json`; you ensure that config exists (Phase 0)
  and pass its path to every slice.
- **REQUIRED SUB-SKILL:** `runbook` runs once at the end of Phase 5 — after the
  integration gate is green and **before** the publish prompt. It synthesizes one
  `docs/spec-loop/<run-id>/runbook.md` from the run's durable artifacts (which you then
  commit) and returns the **Executive Readout** that becomes the run's final terminal
  output.
- **OPTIONAL SUB-SKILL:** `knowledge-graph` projects the run's decisions, architecture
  patterns, system context, and domain knowledge into the user's Obsidian vault as linked
  markdown notes that accumulate across runs. It is **opt-in** — active only when
  `~/.claude/spec-loop/knowledge-graph.json` has `enabled:true` and a `vault_path`; otherwise
  it no-ops. It is **light touch**: you (the controller) invoke it at phase boundaries
  (Phase 1 start, each wave boundary) and `runbook` invokes it at end of run — **never** a
  slice worker, so it does not touch the parallel hot path. Ensure its config exists in Phase 0
  (batched with the quality-gate first-run setup); if disabled, say nothing and skip every
  knowledge-graph step below.
- This loop **intentionally overrides** the human gates in `spec-loop:brainstorming`
  and `spec-loop:subagent-driven-development`. It does NOT override
  `spec-loop:verification-before-completion`.
- Slice workers run in the **background** so the terminal is never blocked.
- **Single-branch integration (default).** Every slice merges into ONE dedicated
  local **integration branch** — never `main`/`master` directly, and never as its
  own surviving branch or PR. A slice's worktree branch
  (`spec-loop/<run-id>/<slice-id>`) is an ephemeral *isolation* detail, not a
  deliverable: the **controller** — not the slice — merges it into the integration
  branch (serially, at the wave boundary) and then deletes it. The loop **never
  pushes** during the run and **never opens a PR or leaves a branch per slice**. The
  sole exception is `--per-slice-pr` mode (Phase 0), set by the flag or an explicit
  request in the prose, in which each slice opens its own PR instead.
- Never let any slice work on `main` — every slice gets its own worktree, branched
  off the integration branch.
- **The run ends by prompting you how to publish** the integration branch — push it
  as a feature branch (optionally opening a PR) or merge it onto `main` (Phase 5).
  The loop does not push or touch `main` until you choose.

## Preflight — self-contained

The plugin is fully self-contained: the development-process skills the loop chains
(writing-plans, subagent-driven-development, executing-plans, using-git-worktrees,
code-review-discipline, verification-before-completion,
finishing-a-development-branch) AND the PR-review library (the `spec-loop:review-pr`
skill and its six review agents) all ship **inside this plugin** — no external
plugin dependency exists, and no preflight plugin check is needed.

## Phase 0 — Intake & decompose

1. If `--resume <run-id>` is present, skip to **Resume** below.
2. Parse flags: `--max-parallel` (default 5), `--risk-floor` (default 1),
   `--branch <name>` (integration branch name; default = a meaningful slug derived
   from the request), `--base-branch <name>` (branch the integration branch is cut
   from; default `main`, else `master`), and `--per-slice-pr` (opt into per-slice
   PRs). Enter **`per-slice-pr` mode** only when that flag is present **or** the
   request prose explicitly asks for a branch/PR per slice; otherwise the run is
   **single-branch** — all slices merge into one integration branch. Never infer
   per-slice branches from anything less than an explicit request.
3. **Global config (one-time).** Check whether
   `~/.claude/spec-loop/quality-gate.json` exists. If it does **not**, run the
   first-run setup once now — follow the `/spec-loop:quality-gate` command's routine
   to prompt the human (validate the quality level + any custom gates) and write the
   file. If the file already exists, say nothing and proceed — never re-prompt.
   - **Knowledge graph (also one-time, optional).** Check whether
     `~/.claude/spec-loop/knowledge-graph.json` exists. If it does **not**, add a single
     **opt-in offer** to the same batched round ("record this run's decisions / patterns /
     context into an Obsidian vault? if so, give the vault path") per the
     `/spec-loop:knowledge-graph` command's routine, and write the file (default `disabled`
     with `vault_path:null` if the human declines or gives no path — never assume a path).
     If it already exists, say nothing.
   - **Batch both of these with the Phase 0 step 8 `escalation-gate` round** so the human
     sees a single up-front interaction.
4. Restate the request in your own words (per the user's global CLAUDE.md).
5. Explore the codebase to find reusable functions, patterns, and conventions —
   launch up to 3 `Explore` agents in parallel. Prefer reuse over new code.
   **Distill their findings into a conventions summary** (reusable helpers and
   functions with paths, established patterns, naming/testing/layout conventions,
   a key-file map): hold it now, pass it to the intake council in step 6, and
   persist it as `docs/spec-loop/<run-id>/conventions.md` in Phase 1.3 — every
   slice worker and council convening reads it instead of re-exploring.
   - **Prior knowledge (only if the knowledge graph is enabled).** If
     `~/.claude/spec-loop/knowledge-graph.json` is `enabled` with a `vault_path`, run one
     read-only helper call —
     `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/knowledge_graph.py" context --vault <vault_path> --subfolder <subfolder> --repo <repo-slug> --term <t> ...`
     — passing 5–8 salient terms distilled from the request (domain nouns, subsystem
     names; the helper ranks by deterministic lexical overlap and **reorders, never
     filters**). Append a short `## Prior knowledge (knowledge graph)` section to the
     conventions summary: the system hub one-liner, existing patterns (cross-repo) with
     their one-liners, active decisions and domain notes for this repo, and the
     `known_ids` lists with an instruction to reuse those exact ids in any later graph
     writes. Keep the section the same size as before — ranking changes order, not caps.
     List any decision returned with `relevance > 0` under a sub-heading
     **Prior decisions that may bear on this request** with the instruction: the Iron
     Council must verify the request against these and flag contradictions — the graph
     only surfaces candidates, it does not judge conflict. If the call fails or the graph
     is disabled, omit the section silently — this never gates intake.
6. **Convene the Iron Council on the request (intake).** Intake always convenes
   the full five — tier-scaled composition applies only at pre-execution (there is
   no tier before decomposition). Before decomposing, invoke the `iron-council`
   skill and dispatch all five members (`iron-council-skeptic`, `-architect`,
   `-pragmatist`, `-guardian`, `-historian`) in a single message so they
   deliberate concurrently, passing every member the **same context packet** —
   the verbatim user request plus the step 5 conventions summary, placed
   identically at the start of each member's prompt (identical prefixes earn
   prompt-cache hits). Validate and aggregate mechanically per the skill —
   pipe each member's reply through
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/council_contracts.py" validate-member`
   (invalid → re-dispatch that member once → still invalid → synthesize a
   non-SAFETY OBJECT for it), then pipe the normalized array through
   `... council_contracts.py aggregate --expect skeptic,architect,pragmatist,guardian,historian`
   (a missing or duplicate verdict fails closed). Act on the returned council verdict:
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
2. **Establish the singular integration branch.** All slices merge into this ONE
   local branch. It must not be `main`/`master`, must not contain `spec-loop` in its
   name, and should be meaningful to the work.
   - **Name:** `--branch <name>` if given, else a short, human-meaningful slug of the
     request (e.g. "Add CSV export to the reports page" → `csv-export`). No date, no
     `spec-loop` prefix. If a local branch by that name already exists, append `-2`,
     `-3`, ….
   - **Base:** `--base-branch <name>` if given, else `main` (else `master`). If the
     base has an upstream, refresh it first (`git fetch` then fast-forward), then cut
     the integration branch from its tip and **check it out** so the controller sits
     on it for the whole run: `git checkout -b <integration-branch> <base-branch>`.
   - **Clean tree required.** If the working tree has uncommitted changes, do NOT
     switch branches — run `escalation-gate` (material assumption / cannot proceed
     safely) and ask the human to commit or stash first.
   - Record `base_ref` = `<integration-branch>` and `base_sha` = `git rev-parse HEAD`
     (its creation point). This is the branch each worker's clean worktree is cut
     from, and the branch the controller merges every slice into. (Ensure
     `.worktrees/` is gitignored — the using-git-worktrees skill verifies and adds
     it, but check.)
   - Record the run's **merge mode** (`single-branch` default, or `per-slice-pr`) to
     pass to every slice.
3. Create `docs/spec-loop/<run-id>/` and write:
   - `.active` — the run marker (one line: ISO timestamp + run-id). While this file
     exists, the plugin's bundled PreToolUse hook (`spec_loop_guard.py`)
     deterministically blocks mid-run pushes, broad staging, main-branch
     commits/merges, and quality-gate config edits. It is deleted (renamed `.done`)
     when the run ends and is **never committed**.
   - `request.md` — the original request, verbatim.
   - `dag.json` — `{ base_ref, base_sha, base_branch, merge_mode, shared_constraints: [...], slices: [...] }` where `base_ref` is the integration branch, `base_branch` is what it was cut from, `merge_mode` is `"single-branch"` or `"per-slice-pr"`, `shared_constraints` is the run-wide list of must-not-regress constraints distilled from intake (council concerns folded in, human answers, invariants every slice must preserve — `[]` if none), and each slice is `{id, goal, files, subsystems, deps:[ids], risk_tier:1|2|3, depth:0, parent:null, status:"pending"}`. Apply `--risk-floor` as the minimum tier. Assign tiers using `review-depth-map` heuristics. `depth` tracks split generation (intake slices = `0`); `parent` links a split child to the slice it came from. `status` may also become the terminal value `"split"` (Phase 3) when a slice is replaced by its children.
   - `conventions.md` — the Phase 0 exploration summary from step 5 (reusable
     helpers with paths, established patterns, conventions, key-file map). Written
     once here; read by every slice worker and every council convening for the
     rest of the run instead of re-exploring.
   - `escalations.md` — start empty (header only).
   - `decisions-log.md` — start empty (header only).
4. Sanity-check the DAG: no cycles, every `deps` id exists. If a cycle exists, that is a decomposition error — fix it yourself (collapse the cyclic slices into one) and log it.
5. **Seed the knowledge graph (only if enabled).** If `~/.claude/spec-loop/knowledge-graph.json`
   is `enabled` with a `vault_path`, invoke the `knowledge-graph` skill once to upsert the
   `system/<repo>` hub (a create-or-touch that adds this `run-id` to a note persisting across
   runs, with a one-line summary of the system) and create the `run/<run-id>` MOC. Include
   `"ensure_base": true` in the batch unless the config sets `starter_base: false` — the
   helper create-onces the vault's `spec-loop.base` starter view and refreshes the hub's
   home index as side effects of the MOC batch. If disabled, skip silently. This is a
   single serial helper call in the main session — it does not gate or delay wave
   scheduling.

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
   path to `docs/spec-loop/<run-id>/`, its risk tier, `base_ref` (the integration
   branch), the run's `merge_mode` (`single-branch` | `per-slice-pr`), the
   absolute path to the quality-gate config (`~/.claude/spec-loop/quality-gate.json`),
   the absolute path to `docs/spec-loop/<run-id>/conventions.md`, and the run's
   `shared_constraints` from `dag.json`.
   The worker's first action is to create a clean dedicated worktree from the current
   tip of `base_ref` under `.worktrees/spec-loop/<run-id>/<slice-id>` — before any
   other work. In `single-branch` mode the worker does **not** merge or push; it
   finishes as a verified, committed branch and the controller integrates it (Phase 3).
   - **Component-scoped prior knowledge (only if the knowledge graph is enabled).**
     Before dispatching the wave, run ONE read-only helper call for the whole wave —
     `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/knowledge_graph.py" context --vault <vault_path> --subfolder <subfolder> --repo <repo-slug> --request-file docs/spec-loop/<run-id>/request.md --component <s> ...`
     — with the **union of the wave's slices' `subsystems`** (slugified) as repeated
     `--component` flags. From the returned `components` map, inject into each slice's
     dispatch prompt a `## Prior knowledge for this slice (knowledge graph)` section
     covering only the components that slice touches — **≤ ~120 words / ~10 lines**,
     ids + one-liners only. Slices whose components all have empty buckets get no
     section. This is a controller pre-fetch: **slice workers still never invoke the
     knowledge-graph skill or helper.** On any error, dispatch without the section —
     never delay a wave.
   - **Fallback:** if a background dispatch is rejected because you are yourself a
     subagent (e.g. `/spec-loop` was invoked from within another agent), re-dispatch
     the wave's slices **synchronously** (`run_in_background: false`) instead. The
     loop still works correctly; it just runs the slices one at a time and blocks
     until each returns. Note this in your summary so the user knows parallelism
     was unavailable.
3. If a wave has more slices than `--max-parallel`, dispatch in batches; start the
   next batch as background slots free up.

## Phase 3 — Collect & gate (wave boundary)

1. When the wave's background agents report, read each slice's **status sidecar**
   `docs/spec-loop/<run-id>/slice-<id>-status.json` — the sidecar, not the agent's
   return text (which is only a human-readable summary), is the source of truth.
   Validate it first:
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/council_contracts.py" validate-slice-status --file <path>`.
   **Missing or invalid sidecar → treat the slice as `NEEDS_DECISION`** (fail
   closed — same bar as the "DONE without evidence" rule in step 2). Then route by
   its `status`:
   - `DONE` → set the slice `status:"complete"` in `dag.json`.
   - `SPLIT` → the slice is two-or-more shippable changes; ingest its children (step 3).
   - `NEEDS_DECISION` → leave it `pending`; its escalation is in `escalations.md`.
   - `BLOCKED` → leave it `pending`; treat its blocker as an escalation too.
2. Verify each `DONE` claim independently before trusting it
   (`spec-loop:verification-before-completion`): check the worktree's git log /
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
4. **Integrate the wave onto the singular branch, then check it.**
   - **(a) Controller-owned serial merge (single-branch mode).** The controller — not
     the slices — merges, so every slice lands on ONE branch race-free. Sitting on
     `base_ref` in the main worktree, take each verified `DONE` slice **one at a time,
     never concurrently** and merge its branch:
     `git merge --no-ff spec-loop/<run-id>/<slice-id>`. After a clean merge, remove
     the slice's worktree and delete its branch (`spec-loop:using-git-worktrees`
     cleanup, i.e. `git worktree remove` then `git branch -d`). A merge **conflict**
     is an integration failure → do not force it; open a **remediation slice**
     (Phase 5's procedure) scoped to reconciling the two slices, and leave the
     unmerged slice branch in place for it. *(In `per-slice-pr` mode the slices have
     already opened their own PRs — there is nothing for the controller to merge;
     skip (a) and defer verification to Phase 5.4's throwaway integration branch.)*
   - **(b) Per-wave integration check (lightweight).** With the wave merged, run the
     project's full test/build **fresh on `base_ref`** and read the output
     (`spec-loop:verification-before-completion` discipline). This catches same-wave
     merge incompatibilities and cross-slice drift *early*, while remediation is cheap
     — two slices in one wave both branched from the same tip and merged blind to each
     other. Green → continue. Red → open a **remediation slice** (Phase 5's procedure)
     for the failure and schedule it; do not advance as if the wave were clean.
5. Collect ALL `OPEN` entries from `escalations.md` and surface them as ONE
   batched `AskUserQuestion` round (one question per escalation, with the
   recommended default first). Do not ask one-at-a-time across waves.
6. Write the human's answers back into `escalations.md` (set `status: ANSWERED`)
   and re-dispatch each answered slice via a fresh `spec-loop-slice` agent with
   the answer injected into its prompt.
7. **Record wave decisions in the knowledge graph (only if enabled).** If the
   knowledge graph is enabled, invoke the `knowledge-graph` skill once for this wave to
   upsert `decision` nodes for the material decisions / council verdicts appended to
   `decisions-log.md` during the wave, plus one `decision` node per **human-answered
   escalation** from step 6 — each linking to the `run`, the repo `system`, and the
   `component` hubs it touched (the helper creates those hubs on reference). Keep it to the
   *material* decisions, not every logged line. This is one serial helper call in the main
   session at the wave boundary; if disabled, skip silently. The helper is idempotent under
   retry (re-invoking the same batch after an interruption leaves the vault unchanged); its
   result reports `redactions` and `remapped` counts — include them in the one-line digest
   logged to `decisions-log.md`.

## Phase 4 — Loop

Repeat Phases 2–3 until every slice in `dag.json` is terminal — `complete` or
`split` (a split parent is replaced by its children, which must themselves reach
`complete`). Slices left `pending` because of an open escalation block the run until
answered. Once every slice is terminal, proceed to Phase 5.

## Phase 5 — Integration gate (verify the assembled whole)

Each slice was merged onto the integration branch (by the controller, at its wave
boundary) after passing *its own* tests in *its own* worktree — but nothing has yet
verified the slices **together**. This phase does, before the run is called complete.
(Analogous to a cross-phase integration check.)

1. **Full test/build on `base_ref`.** Run the project's complete test and build
   suite fresh on `base_ref` (which now contains every merged slice) and read the
   output. This is the assembled whole, not any single slice's worktree.
2. **Cross-slice integration review.** Run ONE synchronous `spec-loop:review-pr`
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
     review → quality-gate → verify loop with the same bounded auto-fix, and the
     controller integrates its branch onto `base_ref` (Phase 3.4) when it returns.
   - Re-run Phase 5 after the remediation slice merges.
   - Only if a remediation slice itself exhausts its bounded loop and returns
     `NEEDS_DECISION` does this reach the human — through the **existing**
     `escalation-gate` (`review-block`) at the next wave boundary. No new trigger;
     the bar is exactly the per-slice bar applied to the whole.
4. **`per-slice-pr` variant.** In `--per-slice-pr` mode each slice opened its own PR,
   so there is no single merged branch to test. Build a **throwaway integration
   branch** off `base_sha`, merge every completed slice branch into it, run steps 1–2
   there, report the integration status, then delete the branch — leaving the PRs
   untouched for the human to merge. (Single-branch merge is the primary path; this
   is only for the explicitly-requested per-slice-PR mode.)

5. **Generate and commit the RUNBOOK (before publishing).** Steps 1–3 are green and
   every slice sits on `base_ref`. Before asking how to publish, invoke the `runbook`
   skill, passing it: the `run-id`, the absolute path to `docs/spec-loop/<run-id>/`, the
   resolved `base_ref`/`base_sha`/`base_branch`/`merge_mode`, and the Phase 5 result
   (suite command + outcome, cross-slice `review-pr` verdict + tier, and the ids of any
   remediation slices). It writes `docs/spec-loop/<run-id>/runbook.md` and **returns the
   Executive Readout** for you to print at the very end. Then commit the **whole run-state
   directory** onto the integration branch so the runbook and its audit trail travel with
   any push/merge:

   ```
   git add -- docs/spec-loop/<run-id>/ ':(exclude)docs/spec-loop/<run-id>/.active' ':(exclude)docs/spec-loop/<run-id>/.publish-choice' ':(exclude)docs/spec-loop/<run-id>/.done'
   git status --short        # verify ONLY docs/spec-loop/<run-id>/ is staged (and no marker files)
   git commit -m "docs(spec-loop): runbook + run state for <run-id>"
   ```

   **COMMIT-SAFETY (critical).** The run-state artifacts (`dag.json`, `decisions-log.md`,
   `escalations.md`, `slice-*.md`, `runbook.md`) are **untracked but NOT gitignored**.
   **Never** use `git add -A`, `git add .`, or a broader pathspec here — any of those would
   sweep unrelated working-tree changes into this commit. Stage **only** the run directory
   by its explicit pathspec (`git add -- docs/spec-loop/<run-id>/`), then confirm with
   `git status --short` that nothing outside that directory is staged. If anything
   unexpected is staged, run `escalation-gate` (material assumption / cannot proceed safely)
   rather than forcing the commit. Rationale for committing **before** the publish prompt:
   the runbook + audit trail then ride along with whatever the human chooses in step 6 — a
   post-publish commit would strand them on a local-only commit for the push case, or need a
   second `main` commit for the merge case.

   *(In `per-slice-pr` mode there is no single integration branch. Generate the runbook the
   same way — its source artifacts are complete regardless of merge mode — and commit the
   run directory onto the **current** branch (the `base_branch` checked out in Phase 0),
   with the same single-pathspec add. Set the runbook's `publish` field to `per-slice-prs`
   and record the throwaway-integration-branch result + the PR list in §6. Never commit the
   run directory into an individual slice's PR branch.)*

6. **Publish prompt (single-branch mode) — the run's final interaction.** With the runbook
   committed, all the work sits on the singular local integration branch, unpushed, with
   `main`/`master` untouched. Ask the human via **one `AskUserQuestion`** how to publish it
   (recommended option first):
   1. **Push as a feature branch** — push the integration branch to the remote,
      optionally opening a PR.
   2. **Merge onto `main`** — locally `git checkout main && git merge --no-ff
      <integration-branch>`; offer to push `main` afterward.
   3. **Leave it local** — do nothing; the branch stays for the human to handle.
   **Immediately after the human answers and before performing the action**, write
   `docs/spec-loop/<run-id>/.publish-choice` (one line: the chosen option) — the
   bundled guard hook blocks pushes and main-branch merges until this marker
   exists. Perform the chosen action and nothing more — never push or touch `main`
   without an explicit choice. **After the action completes**, rename `.active` →
   `.done` (`mv docs/spec-loop/<run-id>/.active docs/spec-loop/<run-id>/.done`) so
   the guard disengages. *(In `per-slice-pr` mode the PRs are already open: skip
   this prompt, just report the PR list, and rename `.active` → `.done` at that
   point.)*

When Phase 5 is green, the runbook committed (step 5), and the publish choice handled
(step 6), the run's **final terminal output IS the Executive Readout** returned by the
`runbook` skill — print it **verbatim**, then append one line stating how the branch was
published (pushed as a feature branch / merged onto `main` / left local / PR list). Do not
compose a separate hand-written summary: the committed `docs/spec-loop/<run-id>/runbook.md`
is the single source of truth, and its Executive Readout is the self-contained top section;
the full detail (What Was Built, Business Logic, Gaps, requirement traceability, decisions,
integration-gate result) lives in that file.

## Resume

For `--resume <run-id>`: read `docs/spec-loop/<run-id>/dag.json`, recover `base_ref`
(the integration branch) and `merge_mode`, recreate the `.active` marker if it is
absent (the guard hook must cover the resumed run), and **check out `base_ref`** so
the controller resumes on the singular branch (clean-tree guard as in Phase 1). Skip all
terminal slices (`complete` and `split` parents), drain any `ANSWERED` escalations
into re-dispatches, and continue from the first wave that has runnable slices. If
every slice is already terminal, go straight to the Phase 5 integration gate — which
generates + commits the runbook (step 5) then ends with the publish prompt — before
declaring the run done. On resume, step 5 still applies: if `runbook.md` already exists
for this run-id (an earlier interrupted finish), **regenerate** it (the artifacts are the
source of truth) and re-stage the run directory; if `git status --short` shows nothing to
commit (content unchanged), skip the empty commit and proceed to the publish prompt.

## Guardrails
- Never dispatch two implementer-level agents that touch the same files
  concurrently — that is what the dependency DAG and per-slice worktrees prevent.
- Never surface an escalation that `escalation-gate` would resolve as proceed-and-log.
- Never claim the run is complete without verifying each slice's evidence.
- Never let a slice self-merge or push, and never create a branch or PR per slice,
  unless `--per-slice-pr` (flag or explicit request) is set — the controller owns the
  single-branch integration and merges slice branches serially.
- Never push the integration branch or merge onto `main` without the human's explicit
  publish choice (Phase 5, step 6).
- Never stage the runbook commit with `git add -A`/`git add .`/a broad pathspec — the
  run-state artifacts are untracked-not-ignored, so stage ONLY the run directory
  (`git add -- docs/spec-loop/<run-id>/`, excluding the marker files) and verify with
  `git status --short` (Phase 5, step 5).
- The marker lifecycle is part of the contract: `.active` at Phase 1, `.publish-choice`
  at the Phase 5.6 answer, `.active` → `.done` at run end, `.active` recreated on
  resume. While `.active` exists, the plugin's bundled PreToolUse hook
  (`spec_loop_guard.py`) enforces the push/staging/main-branch/config-edit rules
  deterministically — markers are never committed and never deleted to dodge a
  denial (a denial means the run has not earned that operation yet).
