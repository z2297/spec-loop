---
name: quality-gate
description: Use when a spec-loop slice has passed PR review and the code-simplifier polish pass and needs a final, objective code-quality gate before merge — measures complexity/length/CRAP metrics against the user's persisted thresholds and drives a bounded, behavior-preserving refactor loop until compliant or escalation.
---

# Quality Gate — the final, objective bar before a slice merges

## Overview

PR review catches correctness and reviewer-judgment issues; this gate enforces
**objective, measurable** code quality. It runs **after** review + auto-fix + the
code-simplifier polish pass and **before** verification/merge. If the slice's changed
code exceeds any configured threshold, the gate runs a **bounded, behavior-preserving
refactor loop** until the metrics pass — or escalates.

It is language-agnostic and config-driven: the same thresholds apply to every tier and
every run, and that configured bar is separate from the review severity bar in
`review-depth-map`.

## Step 1 — Load config

Read the global config at `~/.claude/spec-loop/quality-gate.json` (expand `~`), created
once by the controller's first-run setup or the `/spec-loop:quality-gate` command.

- If `enabled` is `false`, **skip the gate entirely** — log one line to
  `decisions-log.md` and return.
- If the file is **missing** (a slice somehow ran before setup), fall back to the
  **default thresholds** below, and log a note that defaults were used.

### Default thresholds (per changed method/function unless noted) — single home

This table is the declared home of the defaults; the constants in
`scripts/quality_gate.py` are its executable mirror. Change both together.

| Metric                  | Default | Notes |
|-------------------------|---------|-------|
| `cyclomatic_complexity` | 10      | branches: each `if/else if/case/catch/&&/\|\|/?:` |
| `cognitive_complexity`  | 15      | nesting-weighted complexity |
| `method_lines`          | 50      | executable lines in a method/function |
| `parameter_count`       | 4       | parameters per method/function |
| `nesting_depth`         | 3       | max block-nesting depth |
| `class_lines`           | 300     | per class/module/file (language-adjusted) |
| `crap_score`            | 30      | needs coverage data; skipped + noted if absent |

The `refactor-analysis` skill uses the same numbers, so the heuristic fallback (Step 2)
and any custom config stay consistent. `custom_gates` from the config are also
evaluated (see Step 3).

## Step 2 — Measure (run the bundled script; it is the measurement of record)

Measure **only the slice's changed code** (the diff's added/modified
methods/files), not the whole repo.

1. **Run the gate script from the slice worktree** — this is the measurement of
   record, not an eyeballed estimate:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/quality_gate.py" \
     --config <config-path> --base <base_sha> [--head HEAD] [--repo-dir .] \
     [--coverage <report>]
   ```

   It discovers the changed line ranges from `git diff`, measures only the
   changed functions/files, and emits a single JSON report on stdout:
   `{version, backends, base, head, config, findings:[{file, function, metric,
   value, threshold, pass, source}], skipped:[…], summary:{pass, failures}}`.
   Its exit code is `0` (all thresholds pass), `1` (one or more fail), or `2`
   (usage/git/config error).

   The script prefers an installed analyzer (`lizard`, or `radon cc` for Python)
   and never installs anything; every finding carries the `source` it came from
   (tool name, or `builtin-heuristic` for the stdlib fallback). It computes CRAP
   only when a coverage report is found and otherwise lists it in `skipped` —
   it never fabricates a coverage number. Metric-form custom gates are evaluated
   in-script; command-form gates land in `skipped` for Step 3.
2. **Read the JSON report** — the `findings`/`summary` are the authoritative
   metrics. Do not re-measure by hand when the script ran.
3. **Fallback — only when the script itself cannot run** (exit `2`, or `python3`
   missing): invoke the `refactor-analysis` skill to estimate the same metrics by
   reading the changed code against the default thresholds above. Mark these results
   explicitly as heuristic in the log and note *why* the script did not run.
4. **Record** each measured metric with its value, threshold, pass/fail, and
   `source`, quoting the script's JSON summary as evidence.

## Step 3 — Evaluate custom gates

Metric-form gates (`{name, metric, threshold}`) are already in the Step 2 report,
tagged with their `gate` name — do not re-evaluate them by hand. Command-form gates
(`{name, command, pass_when}`) arrive in `skipped`: run each here, scoped to the
changed files, passing when it matches `pass_when`. A missing interpreter or tool is a
skip-with-note, not a failure.

## Step 4 — Bounded, behavior-preserving refactor loop

If every metric and custom gate passes → record PASS in `decisions-log.md` and
return; the slice proceeds to verification.

Otherwise, for each failing item, run a refactor pass (budget =
`refactor_attempts`, default **3**):

1. **Refactor implementation only.** Apply the smallest transformation that lowers
   the metric — extract method, guard clauses, polymorphism over conditionals,
   parameter object, split a god class. Never change observable behavior, public
   signatures, contracts, or outputs.
2. **Keep tests green.** The existing tests must stay green through every pass. Re-run
   the slice's tests after each refactor; if a change reddens them or alters behavior,
   revert it and try a different transformation.
3. **Re-measure** by re-running the gate script (Step 2) against the current worktree;
   its fresh report is the authoritative check. Stop early once all items pass.

If the budget is exhausted with any item still failing: consult `escalation-gate` with
trigger **`quality-gate-block`**, append an escalation entry to `escalations.md` (the
failing metrics, measured vs threshold, what was tried, why it can't be met without
changing behavior), and return `NEEDS_DECISION`. Do not merge.

## Step 5 — Evidence

Log to `decisions-log.md`: the gate script's JSON `summary` (plus relevant
`findings`/`skipped`) quoted verbatim as the metrics of record, PASS/FAIL, refactor
passes used, and before→after deltas for anything refactored. The slice report's
`Quality:` line summarizes this.

## Hard prohibitions
- **Never weaken a threshold or edit `quality-gate.json` to make a slice pass.**
  Escalate instead — the config is the user's bar, not the loop's.
- **Gate refactors are behavior-preserving only.** Never change observable behavior,
  public APIs, or test expectations to move a metric.
