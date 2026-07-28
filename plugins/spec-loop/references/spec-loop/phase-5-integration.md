# Phase 5 — Integration gate, runbook, and publish

Loaded by the controller when every slice in `dag.json` is terminal. Each slice
passed its own tests in its own worktree; nothing has yet verified the slices
**together**. This phase does, before the run is called complete.

## 1. Full test/build on `base_ref`

Run the project's complete test and build suite fresh on `base_ref` (which now
contains every merged slice) and read the output — the assembled whole, not any
single slice's worktree.

## 2. Cross-slice integration review

Run ONE synchronous `spec-loop:review-pr` over the cumulative diff
`base_sha..HEAD` of `base_ref`, at the run's highest slice risk tier (via
`review-depth-map`). Scope it to integration concerns: contract consistency
across slices, wiring, and end-to-end flows that span slices — the failures a
per-slice review structurally cannot see.

## 3. Remediate (bar unchanged)

If steps 1–2 surface failures, create a **remediation slice** — a normal
`pending` slice in `dag.json` (`depth:0`, `parent:null`, `remediation:true`,
risk tier = run max, `deps` = all completed slices) whose goal is the specific
integration failure — and dispatch it through a fresh `spec-loop-slice` like any
other slice. The controller integrates its branch as usual, then re-runs Phase 5.
Only if a remediation slice exhausts its bounded loop and returns
`NEEDS_DECISION` does this reach the human, through the existing
`escalation-gate` (`review-block`) at the next wave boundary — the per-slice bar
applied to the whole, no new trigger.

The same procedure handles **wave-boundary failures** (Phase 3.4): a merge
conflict or a red per-wave integration check opens a remediation slice scoped to
that failure; for a conflict, leave the unmerged slice branch in place for it.

## 4. Runbook + final metrics (before publishing)

Invoke the `runbook` skill, passing: the `run-id`, the absolute run-state path,
the resolved `base_ref`/`base_sha`/`base_branch`/`merge_mode`, and the Phase 5
result (suite command + outcome, cross-slice review verdict + tier, remediation
slice ids). It writes `docs/spec-loop/<run-id>/runbook.md` and returns the
**Executive Readout** — the run's final terminal output.

Then compute the final metrics snapshot (non-gating; on error log one line and
continue):

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/run_metrics.py" compute "docs/spec-loop/<run-id>" --git --write
```

## 5. Commit the run state — COMMIT-SAFETY

Commit the whole run-state directory onto the integration branch so the runbook
and audit trail travel with whatever publish choice follows:

```
git add -- docs/spec-loop/<run-id>/ ':(exclude)docs/spec-loop/<run-id>/.active' ':(exclude)docs/spec-loop/<run-id>/.publish-choice' ':(exclude)docs/spec-loop/<run-id>/.done'
git status --short        # verify ONLY docs/spec-loop/<run-id>/ is staged, no marker files
git commit -m "docs(spec-loop): runbook + run state for <run-id>"
```

**COMMIT-SAFETY.** The run-state artifacts are untracked but NOT gitignored.
Never use `git add -A`, `git add .`, or any broader pathspec here — stage only
the run directory by its explicit pathspec and confirm with `git status --short`.
If anything unexpected is staged, run `escalation-gate` rather than forcing the
commit. (While `.active` exists, `spec_loop_guard.py` also blocks broad staging
deterministically.) Committing *before* the publish prompt is deliberate: the
audit trail rides along with either publish choice.

## 6. Publish prompt — the run's final interaction

All work sits on the singular local integration branch, unpushed, `main`
untouched. Ask the human via ONE `AskUserQuestion` (recommended option first):

1. **Push as a feature branch** — push the integration branch, optionally opening a PR.
2. **Merge onto `main`** — `git checkout main && git merge --no-ff <integration-branch>`; offer to push `main` afterward.
3. **Leave it local** — the branch stays for the human to handle.

Immediately after the human answers and **before performing the action**, write
`docs/spec-loop/<run-id>/.publish-choice` (one line: the chosen option) — the
guard hook blocks pushes and main-merges until it exists. Perform the chosen
action and nothing more. After it completes, rename `.active` → `.done` so the
guard disengages.

## Closing output

Print the runbook's Executive Readout **verbatim**, then one line stating how the
branch was published. Do not compose a separate hand-written summary — the
committed `runbook.md` is the single source of truth.

## `per-slice-pr` variant

When the run is in `per-slice-pr` mode (flag or explicit request only):

- Slices opened their own PRs; there is no single merged branch. Skip the
  controller's wave-boundary merge entirely.
- For steps 1–2, build a **throwaway integration branch** off `base_sha`, merge
  every completed slice branch into it, run the suite + cross-slice review there,
  report the result, then delete the branch — leaving the PRs untouched for the
  human to merge.
- Generate the runbook the same way (its source artifacts are complete regardless
  of merge mode); set its `publish` field to `per-slice-prs` and record the
  throwaway-branch result + PR list. Commit the run directory onto the **current**
  branch (the `base_branch` checked out at run start) with the same
  single-pathspec add — never into an individual slice's PR branch.
- Skip the publish prompt: report the PR list and rename `.active` → `.done`.
