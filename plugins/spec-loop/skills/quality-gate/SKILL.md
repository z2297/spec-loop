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

## Step 2 — Measure (hybrid: real tools first, heuristics otherwise)

Measure **only the slice's changed code** (the diff's added/modified
methods/files), not the whole repo.

1. **Detect language + available tooling**, then prefer a real analyzer when one is
   installed (gives authoritative numbers). Examples (use what exists; do not
   install anything):
   - JS/TS → `eslint` with `complexity`/`max-depth`/`max-lines-per-function` rules,
     or `npx eslintcc`.
   - Python → `radon cc`/`radon mi`, `flake8` complexity.
   - Many languages → `lizard` (CCN, length, parameter count).
   - C#/.NET → Roslyn analyzers / `dotnet build` analyzer output, or an installed
     metrics tool. (No universal CLI — fall back to heuristics if none present.)
   - Coverage for **CRAP**: read an existing coverage report (lcov, cobertura,
     `coverage.xml`, etc.) produced by the slice's test run. If none exists, **skip
     CRAP** and note it; do not fabricate a coverage number.
2. **Fallback — no tool for this language:** invoke the `refactor-analysis` skill
   (or apply its checklists directly) to estimate the same metrics by reading the
   changed code. Mark these results as **heuristic** in the log.
3. **Record** each measured metric with its value, the threshold, pass/fail, and the
   source (tool name + version, or `heuristic`). Quote real tool output as evidence.

## Step 3 — Evaluate custom gates

For each entry in `custom_gates`:
- **Metric form** (`{name, metric, threshold}`) — evaluate like a built-in threshold.
- **Command form** (`{name, command, pass_when}`) — run the command scoped to the
  changed files; pass when it matches `pass_when` (e.g. `exit 0`). Treat a missing
  interpreter/tool as a skip-with-note, not a failure.

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
3. **Re-measure** the failing items (Step 2). Stop early once all pass.

If the budget is exhausted with any item still failing:
- Consult `escalation-gate` with trigger **`quality-gate-block`**.
- Append an escalation entry to `escalations.md` (include the failing metric(s),
  measured vs threshold, what was tried, and why it can't be met without changing
  behavior).
- Return `NEEDS_DECISION`. Do **not** merge, and do **not** weaken thresholds or
  edit the config to force a pass.

## Step 5 — Evidence

Always log to `decisions-log.md`: the metrics table (value vs threshold, source),
PASS/FAIL, refactor passes used, and before→after deltas for anything refactored.
The slice report's `Quality:` line summarizes this.

## Red flags (never)
- Weakening thresholds or editing `quality-gate.json` to make a slice pass.
- Changing observable behavior, public APIs, or test expectations during a gate
  refactor (it is implementation-only).
- Fabricating a metric or coverage number when no tool/coverage is available — skip
  and note instead.
- Looping refactors past `refactor_attempts` instead of escalating.
- Measuring the whole repo instead of just the slice's changed code.
