---
name: quality-gate
description: Use when a spec-loop slice has passed PR review and the code-simplifier polish pass and needs a final, objective code-quality gate before merge — measures complexity/length/CRAP metrics against the user's persisted thresholds and drives a bounded, behavior-preserving refactor loop until compliant or escalation.
---

# Quality Gate — the final, objective bar before a slice merges

## Overview

PR review catches correctness and reviewer-judgment issues; this gate enforces
**objective, measurable** code quality. It runs **after** review + auto-fix +
the code-simplifier polish pass and **before** verification/merge. If the slice's
changed code exceeds any configured threshold, the gate runs a **bounded,
behavior-preserving refactor loop** until the metrics pass — or escalates.

This gate is **language-agnostic** and **config-driven**: the same thresholds apply
to every tier and every run. The blocking bar here is the configured thresholds —
separate from the review severity bar in `review-depth-map`.

## Step 1 — Load config

Read the global config at `~/.claude/spec-loop/quality-gate.json` (expand `~` to the
user's home). It is created once by the controller's first-run setup (or the
`/spec-loop:quality-gate` command) and persists across all runs.

- If `enabled` is `false`, **skip the gate entirely** — log one line to
  `decisions-log.md` and return.
- If the file is **missing** (a slice somehow ran before setup), fall back to the
  **default thresholds** below, and log a note that defaults were used.

### Default thresholds (per changed method/function unless noted)

| Metric                  | Default | Notes |
|-------------------------|---------|-------|
| `cyclomatic_complexity` | 10      | branches: each `if/else if/case/catch/&&/\|\|/?:` |
| `cognitive_complexity`  | 15      | nesting-weighted complexity |
| `method_lines`          | 50      | executable lines in a method/function |
| `parameter_count`       | 4       | parameters per method/function |
| `nesting_depth`         | 3       | max block-nesting depth |
| `class_lines`           | 300     | per class/module/file (language-adjusted) |
| `crap_score`            | 30      | needs coverage data; skipped + noted if absent |

These mirror the `refactor-analysis` skill's thresholds so the heuristic fallback
(Step 2) and any custom config stay consistent. `custom_gates` from the config are
also evaluated (see Step 3).

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
   (usage/git/config error). The script itself:
   - prefers a real analyzer when installed (`lizard` for many languages;
     `radon cc` for Python when lizard is absent) and **never installs
     anything** — every finding carries a `source` (the tool name, or
     `builtin-heuristic` for the transparent stdlib fallback used per-file when
     no tool covers it). `cognitive_complexity` is always heuristic (or listed
     in `skipped`) and is never attributed to a tool.
   - computes **CRAP** only when a coverage report is found (`--coverage`, else
     it probes the repo root for `coverage.xml` / `lcov.info` / `cobertura*.xml`);
     otherwise it lists CRAP in `skipped` with reason `"no coverage report"`. It
     never fabricates a coverage number.
   - evaluates **metric-form** custom gates directly; **command-form** gates are
     listed in `skipped` for the skill to run (Step 3).
2. **Read the JSON report** — the `findings`/`summary` are the authoritative
   metrics. Do not re-measure by hand when the script ran.
3. **Fallback — only when the script itself cannot run** (exit `2`, or `python3`
   missing): invoke the `refactor-analysis` skill (or apply its checklists
   directly) to estimate the same metrics by reading the changed code, using the
   default thresholds table above. Mark these results **explicitly as heuristic**
   in the log and note *why* the script did not run. This tool-menu / by-reading
   path is a fallback, not the primary measurement.
4. **Record** each measured metric with its value, threshold, pass/fail, and
   `source` from the report (tool name or `builtin-heuristic`; `heuristic` for
   the Step-2.3 fallback). Quote the script's JSON summary as evidence.

## Step 3 — Evaluate custom gates

- **Metric form** (`{name, metric, threshold}`) — **already evaluated by the
  script** in Step 2; its pass/fail findings are in the report (each tagged with
  its `gate` name). Do not re-evaluate these by hand.
- **Command form** (`{name, command, pass_when}`) — the script does **not** run
  these (it lists them in `skipped` with reason `command-form gate — evaluated
  by the skill`). Run each command here, scoped to the changed files; pass when
  it matches `pass_when` (e.g. `exit 0`). Treat a missing interpreter/tool as a
  skip-with-note, not a failure.

## Step 4 — Bounded, behavior-preserving refactor loop

If every metric and custom gate passes → record PASS in `decisions-log.md` and
return; the slice proceeds to verification.

Otherwise, for each failing item, run a refactor pass (budget =
`refactor_attempts`, default **3**):

1. **Refactor implementation only.** Apply the smallest transformation that lowers
   the metric — lean on `code-simplifier` and the `refactor-analysis` /
   user-CLAUDE.md patterns: extract method, reduce nesting (guard clauses / early
   return), replace conditional with polymorphism, introduce parameter object, split
   a god class. **Never change observable behavior, public signatures, contracts, or
   outputs** — implementation detail only.
2. **Keep tests green.** Follow `superpowers:test-driven-development` refactor
   discipline: the existing tests must stay green through every pass. Re-run the
   slice's tests after each refactor; if a change reddens them or alters behavior,
   **revert that change** and try a different transformation.
3. **Re-measure** by **re-running the gate script** (Step 2) against the current
   worktree; its fresh report is the authoritative check. Stop early once all
   items pass.

If the budget is exhausted with any item still failing:
- Consult `escalation-gate` with trigger **`quality-gate-block`**.
- Append an escalation entry to `escalations.md` (include the failing metric(s),
  measured vs threshold, what was tried, and why it can't be met without changing
  behavior).
- Return `NEEDS_DECISION`. Do **not** merge, and do **not** weaken thresholds or
  edit the config to force a pass.

## Step 5 — Evidence

Always log to `decisions-log.md`: the gate script's JSON `summary` (and the
relevant `findings`/`skipped`) quoted verbatim as the metrics of record, PASS/FAIL,
refactor passes used, and before→after deltas for anything refactored. The slice
report's `Quality:` line summarizes this.

## Red flags (never)
- Weakening thresholds or editing `quality-gate.json` to make a slice pass.
- Changing observable behavior, public APIs, or test expectations during a gate
  refactor (it is implementation-only).
- Fabricating a metric or coverage number when no tool/coverage is available — skip
  and note instead.
- Looping refactors past `refactor_attempts` instead of escalating.
- Measuring the whole repo instead of just the slice's changed code.
- Eyeballing metrics by hand when the gate script ran successfully — its JSON
  report is the measurement of record; the by-reading path is only for when the
  script itself cannot run (exit 2, `python3` missing).
