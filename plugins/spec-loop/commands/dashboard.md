---
description: "Render a read-only terminal-markdown dashboard of a spec-loop run (DAG, waves, slice status, escalations, decisions) from its durable artifacts under docs/spec-loop/<run-id>/"
argument-hint: "[run-id]"
allowed-tools: ["Bash", "Glob", "Grep", "Read"]
---

# Spec-Loop Dashboard — read-only run view

Render a human-readable snapshot of a `/spec-loop` run from the durable artifacts it
leaves under `docs/spec-loop/<run-id>/`. This command is **strictly READ-ONLY**: it
reads existing files and prints a terminal-markdown dashboard. It triggers, resumes, and
mutates **NO** slice work, writes **no** files, and creates **no** new state or cache —
exactly like `/spec-loop:quality-gate` "does not trigger a loop or any slice work." Use it
to check "where is this run, and what can run next?" between waves or after a pause.

Because it is read-only, do every artifact read through the `Read`, `Glob`, and `Grep`
tools. `Bash` is permitted only for read-only inspection (e.g. listing directories,
reading file mtimes for recency); **never** interpolate the raw `<run-id>` argument — or
any value derived from it — into a `Bash` command string, and never use `Bash` to write,
move, or delete anything. There is no `Write`, `Edit`, `Task`, or `AskUserQuestion`
capability here, and that is the security boundary: keep it intact.

## Steps

1. **Select the run (path-traversal-safe).** The `<run-id>` argument is optional.
   - **Enumerate** the actual run directories: `Glob` `docs/spec-loop/*/dag.json` and take
     each match's parent directory name as the set of known run-ids. Resolve a supplied
     `<run-id>` ONLY by exact-equality match against a basename in that enumerated set —
     **never** build a path by interpolating the raw argument (this is the path-traversal
     guard; a value like `../../etc` can never match an enumerated basename).
   - If `<run-id>` is supplied but matches no enumerated run, print
     `no spec-loop run matching <run-id>` and stop. Do **not** silently fall back to the
     newest run — that would misrepresent which run is shown.
   - If `<run-id>` is omitted, default to the **most recent** run, determined
     **deterministically** by the modification time of each run's `dag.json` (newest mtime
     wins). Do not rely on glob order or lexical sort of the directory name — run-ids are
     `<date>-<slug>` with `-2`/`-3` duplicate suffixes and do not sort chronologically.
   - If no runs exist at all (`docs/spec-loop/` absent or no `dag.json` under it), print
     `no spec-loop runs found` and stop. This is normal output, not an error.

2. **Read the artifacts (pure read; introduce no new file).** From the resolved
   `docs/spec-loop/<run-id>/`, `Read`:
   - `dag.json` — the authoritative run state. Schema (per the controller,
     `commands/spec-loop.md`): `{ base_ref, base_sha, slices: [ {id, goal, files,
     subsystems, deps:[ids], risk_tier, depth, parent, status} ] }`, where `status` is one
     of `pending | complete | split`. **`dag.json` is the SOLE authority** for slice ids,
     `deps`, `depth`, `parent`, and therefore for waves.
   - `request.md` — the original request (show a short excerpt for context).
   - `escalations.md` and `decisions-log.md` — siblings of `dag.json`.
   - Per slice, optionally `slice-<id>-report.md` (durable) and `slice-<id>-split.json`.
   - A `slice-<id>-split.json` is **advisory only** — a not-yet-ingested split *proposal*
     holding `{goal, files, subsystems, internal_deps}` (with 1-based sibling indices); it
     has **no** `id`/`depth`/`parent`. Never read DAG structure out of it. Once a split is
     ingested, the children appear as real slices in `dag.json`; surface split.json at most
     as a footnote ("parent proposed N children, not yet grafted").

3. **Derive the waves (do NOT read them from disk — they are not stored).** Compute waves
   exactly as the controller does (`commands/spec-loop.md`): **a wave is every slice whose
   status is `pending` and whose `deps` are all `complete`.** Iterate: wave 0 = pending
   slices with all deps complete; for the listing, assign each later pending slice to the
   first wave at which its deps would be satisfied. Treat a slice with `status:"split"` as
   **terminal** — it has been replaced by its children and does NOT block dependents
   (dependents were rewritten onto the children). Honor the split-child id convention:
   children are `<parent-id>.1`, `<parent-id>.2`, … with `depth = parent.depth + 1` and
   `parent = <parent-id>` — all read from `dag.json`.

4. **Label each slice with an HONEST, derived status.** The only statuses persisted on disk
   are `pending | complete | split`; a slice running in the background is still `pending` on
   disk. **Do NOT claim a slice is "running now"** — you cannot know that from cold
   artifacts. Derive and label each slice as exactly one of:
   - **complete** — `status:"complete"`.
   - **split** — `status:"split"` (replaced by children; terminal).
   - **awaiting-human** — `pending` AND this slice has an **OPEN** escalation (see Step 6)
     with no filled-in answer.
   - **redispatch-pending** — `pending` AND its escalation has been **ANSWERED** (the
     `Answer:` line is filled in / `status: ANSWERED`): the human has unblocked it and it is
     waiting to be re-dispatched. Distinguish this from awaiting-human so the rollup never
     shows a human blocking an already-unblocked run.
   - **runnable-pending** — `pending`, no open escalation, and all `deps` are `complete`.
   - **blocked-pending** — `pending`, no open escalation, and at least one `dep` is not yet
     `complete`.

5. **Plans vs. reports (the "plans" trap).** Per-slice plans live at
   `docs/superpowers/plans/<date>-<slice-id>.md` **inside each slice's worktree**, which is
   **deleted when the slice merges** — so for a completed slice the plan is gone. Surface the
   **durable** `slice-<id>-report.md` from the run-state dir instead. Only attempt to show a
   live plan when the slice's worktree `.worktrees/spec-loop/<run-id>/<slice-id>` still
   exists (an in-progress or paused slice). **Never claim to show a plan you cannot read** —
   if neither a report nor a live worktree plan is available, say so plainly.

6. **Read OPEN escalations (tolerate both marker forms).** Scan `escalations.md` for open
   entries. Two header forms exist:
   - escalation-gate: `## [<slice-id>] <short title>   (status: OPEN)`
   - iron-council: `## [<id-or-`intake`>] Iron Council objects: …   (status: OPEN)`
   An entry is OPEN when its header carries `(status: OPEN)` and its `Answer:` line is empty;
   it is ANSWERED when `status: ANSWERED` / the `Answer:` line is filled in. The bracket
   token is usually a slice id, but the iron-council form may use **`intake`**, which is not
   a slice — render such an intake-scoped OPEN escalation in the escalations block even though
   it joins to no slice row.

7. **Render the dashboard (terminal markdown).** Print, in order:
   - **Header** — run-id and `base_ref@base_sha` (from `dag.json`), plus a one-line excerpt
     of `request.md`.
   - **DAG / wave listing** — `Wave 0`, `Wave 1`, … each listing its slices with the derived
     readiness label from Step 4.
   - **Slice table** — columns: id, goal (truncated), tier, depth, parent, deps, status
     (derived label).
   - **Status rollup** — counts by derived status, and an explicit list of which slices are
     **runnable now** (runnable-pending) and which are awaiting-human.
   - **Open escalations** — the OPEN entries from Step 6 (both forms; include intake-scoped).
   - **Recent decisions** — the tail of `decisions-log.md` (last several entries).

8. **Robustness (never invent or crash).** There is no atomic-write discipline for
   `dag.json` (the controller rewrites it in place each wave boundary), so a read can catch a
   half-written file. If `dag.json` fails to parse as JSON, print
   `run in progress — state momentarily unreadable` for that run and stop, rather than
   erroring out or inventing slice state. Apply the same tolerance to a malformed
   `slice-<id>-split.json` (skip it with a note). Treat any individually missing optional
   artifact (`request.md`, a report, `decisions-log.md`) as simply absent — render the rest.

## Notes
- **Non-goals (explicit).** This command does **not**: run a live-watch / auto-refresh loop;
  render a TUI; start a web server; emit an HTML artifact; write, move, or delete any file;
  or trigger / resume / mutate any slice work. A richer HTML dashboard is a deliberate
  **future follow-on**, intentionally out of scope here.
- **Cold artifacts.** On-disk statuses are `pending | complete | split` only — there is no
  live "running" state. Every readiness label (runnable-pending, blocked-pending,
  awaiting-human, redispatch-pending) is **derived** here, not stored. Waves are derived too
  (the controller never persists them); `dag.json` is the single source of run truth and this
  command introduces no second one.
- **Read-only contract.** `allowed-tools` is restricted to `Bash`/`Glob`/`Grep`/`Read` — no
  `Write`/`Edit`/`Task`/`AskUserQuestion`. The project CI gate
  (`scripts/validate_marketplace.py`) only checks that `description` is present, so this
  read-only boundary is enforced by the authored frontmatter itself: keep it exact.
- **Path-traversal guard.** Run-id resolution is by exact match against the enumerated
  `docs/spec-loop/*/` directory basenames — the raw argument is never interpolated into a
  path or a shell command.
