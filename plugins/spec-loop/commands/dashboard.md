---
description: "Render a read-only terminal-markdown dashboard of a spec-loop run (DAG, waves, slice status, escalations, decisions) from its durable artifacts under docs/spec-loop/<run-id>/"
argument-hint: "[run-id]"
allowed-tools: ["Bash", "Glob", "Grep", "Read"]
---

# Spec-Loop Dashboard — read-only run view

Render a human-readable snapshot of a `/spec-loop` run from the durable artifacts under
`docs/spec-loop/<run-id>/`, answering "where is this run, and what can run next?" between
waves or after a pause.

This command is **strictly read-only**: it writes no file, creates no cache, and triggers,
resumes, or mutates no slice work. Read artifacts through `Read`, `Glob`, and `Grep`; `Bash`
is for read-only inspection only (listing directories, reading mtimes), never to write, move,
or delete, and never with the `<run-id>` — or anything derived from it — interpolated into a
command string. There is no `Write`, `Edit`, `Task`, or `AskUserQuestion` here; the authored
frontmatter is what enforces that, since the CI gate only checks `description`.

The run-state contract (dag.json schema, wave derivation, marker lifecycle) is pinned in
`${CLAUDE_PLUGIN_ROOT}/references/run-state.md` — read it first.

## Steps

1. **Select the run (path-traversal-safe).** The `<run-id>` argument is optional.
   - `Glob` `docs/spec-loop/*/dag.json` and take each match's parent directory name as the
     set of known run-ids. Resolve a supplied `<run-id>` **only** by exact-equality match
     against that set — never build a path from the raw argument. That is the path-traversal
     guard: `../../etc` can never match an enumerated basename.
   - No match → print `no spec-loop run matching <run-id>` and stop. Do not fall back to the
     newest run; that would misrepresent which run is shown.
   - Omitted → default to the run whose `dag.json` has the newest mtime. Run-ids are
     `<date>-<slug>` with `-2`/`-3` duplicate suffixes and do not sort chronologically, so
     never rely on glob order or lexical sort.
   - No runs at all → print `no spec-loop runs found` and stop. Normal output, not an error.

2. **Read the artifacts** from the resolved directory: `dag.json` (the sole authority for
   slice ids, `deps`, `depth`, `parent`, and therefore waves), `request.md` (a short excerpt
   for context), `escalations.md`, `decisions-log.md`, and — present only after a run reaches
   Phase 5 — `runbook.md`, whose front-matter carries `integration_gate`, `slice_counts`,
   `gap_counts`, `publish` and whose `## Executive Readout` is self-contained. Per slice,
   optionally `slice-<id>-report.md` and `slice-<id>-split.json`. A split.json is **advisory
   only**: a not-yet-ingested proposal with no `id`/`depth`/`parent`, so never read DAG
   structure out of it — surface it at most as a footnote ("parent proposed N children, not
   yet grafted"). Once ingested, the children appear as real slices in `dag.json`.

3. **Derive the waves** by the rule in `references/run-state.md` — they are computed, never
   stored. For the listing, assign each pending slice to the first wave at which its `deps`
   would be satisfied. Split children, read from `dag.json`, follow the id convention
   `<parent-id>.1`, `<parent-id>.2`, … with `depth = parent.depth + 1`.

4. **Label each slice with an honest, derived status.** On-disk statuses are only
   `pending | complete | split`; a slice running in the background is still `pending`, so
   **never claim a slice is "running now"** — cold artifacts cannot tell you that. Label each
   as exactly one of:
   - **complete** — `status:"complete"`.
   - **split** — `status:"split"` (replaced by children; terminal).
   - **awaiting-human** — `pending` with an OPEN escalation (Step 6), no answer filled in.
   - **redispatch-pending** — `pending` with an ANSWERED escalation: the human has unblocked
     it and it awaits re-dispatch. Keeping this distinct from awaiting-human is what stops the
     rollup showing a human blocking an already-unblocked run.
   - **runnable-pending** — `pending`, no open escalation, all `deps` complete.
   - **blocked-pending** — `pending`, no open escalation, some `dep` not complete.

5. **Plans vs. reports (the "plans" trap).** Per-slice plans live at
   `docs/spec-loop/plans/<date>-<slice-id>.md` **inside the slice's worktree**, which is
   deleted on merge — so a completed slice's plan is gone. Surface the durable
   `slice-<id>-report.md` instead, and attempt a live plan only while
   `.worktrees/spec-loop/<run-id>/<slice-id>` exists. Never claim to show a plan you cannot
   read; if there is neither report nor live plan, say so plainly.

6. **Read escalations (both marker forms).** Headers come as escalation-gate's
   `## [<slice-id>] <short title>   (status: OPEN)` or iron-council's
   `## [<id-or-`intake`>] Iron Council objects: …   (status: OPEN)`. An entry is OPEN when its
   header says `(status: OPEN)` and its `Answer:` line is empty, ANSWERED when
   `status: ANSWERED` / `Answer:` is filled in. The bracket token is usually a slice id, but
   the iron-council form may use **`intake`** — render an intake-scoped escalation in the
   escalations block even though it joins to no slice row.

7. **Derive the run's stage** from cold artifacts, matching
   `scripts/dashboard_server.py::_derive_stage` exactly; furthest-progressed wins:
   - **final-review** — every slice terminal (`complete`/`split`).
   - **execution** — work started (any slice terminal, or any `slice-<id>-report.md` exists)
     but not all slices terminal.
   - **iron-council** — `dag.json` has slices, no slice work started.
   - **preflight** — nothing decomposed yet; a run isn't listed until `dag.json` exists, so
     this is essentially never seen here.

   The stage is an honest artifact signal, never a claim that the council or a slice is
   executing at this instant.

8. **Parse council findings and the runbook.** Scan `decisions-log.md` for
   `[<scope>] COUNCIL…` / `[<scope>] IRON COUNCIL…` lines (tolerating a leading `-`/`#`);
   each yields a scope (slice id or `intake`) and the verdict named in the line (`ENDORSE` /
   `ENDORSE_WITH_CONCERNS` / `OBJECT`) — the intake council vets the request, per-slice
   councils vet each plan. If `runbook.md` exists, take its front-matter and its
   `## Executive Readout` text verbatim up to the next `## ` heading.

9. **Render the dashboard (terminal markdown), in order:**
   - **Header** — run-id, `base_ref@base_sha`, derived stage, one-line `request.md` excerpt.
   - **Iron Council findings** — the Step 8 entries as `[scope] VERDICT — summary`, or "no
     council verdicts recorded".
   - **Execution — DAG / wave listing** — `Wave 0`, `Wave 1`, … each with its slices and their
     Step 4 labels.
   - **Slice table** — id, goal (truncated), tier, depth, parent, deps, derived status, report
     (✓ when `slice-<id>-report.md` exists).
   - **Status rollup** — counts by derived status, plus explicit lists of which slices are
     runnable now and which are awaiting-human.
   - **Final review — Executive Readout** — when `runbook.md` exists, its front-matter chips
     and readout text; otherwise "run not finished — no runbook yet".
   - **Run metrics** — from `metrics.json` when present: escalations open/answered, autonomy
     ratio, council OBJECT rate, quality-gate first-pass rate, split rate, integration gate,
     wall clock, and tokens when present, rendering `null` as `—`. Absent or malformed, print
     `no metrics computed — run: python3 ${CLAUDE_PLUGIN_ROOT}/scripts/run_metrics.py compute docs/spec-loop/<run-id> --git --write`
     rather than computing them here: this command may not write, and the run-id must never
     reach a Bash string.
   - **Escalations** — every entry, both marker forms, intake-scoped included, each with its
     OPEN/ANSWERED status. Always shown.
   - **Recent decisions** — the tail of `decisions-log.md`.

10. **Robustness (never invent or crash).** `dag.json` is rewritten in place at each wave
   boundary with no atomic-write discipline, so a read can catch it half-written. If it fails
   to parse, print `run in progress — state momentarily unreadable` and stop rather than
   erroring or inventing slice state. Skip a malformed `slice-<id>-split.json` with a note,
   and treat any missing optional artifact as simply absent — render the rest.

## Notes

- **Non-goals.** No live-watch or auto-refresh, no TUI, no web server, no HTML artifact (that
  is `/spec-loop:dashboard-serve`), no writes, no slice work triggered or resumed.
- **Read-only contract.** `allowed-tools` stays `Bash`/`Glob`/`Grep`/`Read` — that set is the
  security boundary.
