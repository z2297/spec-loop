---
description: "View or update the spec-loop code-quality gate — thresholds (cyclomatic complexity, method length, CRAP, …) and custom gates, persisted globally across all runs"
argument-hint: "(no args — interactive)"
allowed-tools: ["Bash", "Read", "Write", "Edit", "AskUserQuestion"]
---

# Spec-Loop Quality Gate — setup & update

Configure the objective code-quality bar every `/spec-loop` slice must clear
after PR review, before merge. The config is global
(`~/.claude/spec-loop/quality-gate.json`) and this command is the only thing
that prompts for it — the loop never re-asks once the file exists. Runtime
behavior (measurement via the bundled `scripts/quality_gate.py`, the bounded
refactor loop) is defined by the `quality-gate` skill; this command only edits
the config and never measures code or triggers slice work.

## Steps

1. **Locate / read current config.** If `~/.claude/spec-loop/quality-gate.json`
   exists, show the current values (thresholds, `refactor_attempts`,
   `measurement`, `enabled`, `custom_gates`); if not, this is first-time setup.
2. **Choose a quality level** via `AskUserQuestion` (single select), presenting
   the concrete numbers so the user validates the actual bar:
   - **Recommended (default)** — `cyclomatic 10, cognitive 15, method_lines 50, parameter_count 4, nesting_depth 3, class_lines 300, crap 30`
   - **Strict** — `cyclomatic 8, cognitive 12, method_lines 40, parameter_count 3, nesting_depth 2, class_lines 250, crap 20`
   - **Lenient** — `cyclomatic 15, cognitive 20, method_lines 75, parameter_count 5, nesting_depth 4, class_lines 400, crap 40`
   - **Customize** — walk the thresholds in batches (≤4 questions per round),
     recommended value first, "Other" for exact numbers; also ask
     `refactor_attempts` (default 3) and `enabled` (default true).
3. **Custom gates.** Ask whether to add gates beyond the built-ins: a metric
   gate `{ "name", "metric", "threshold" }` or a command gate
   `{ "name", "command", "pass_when": "exit 0" }` run against the slice's
   changed files.
4. **Write the file** (`mkdir -p ~/.claude/spec-loop` first). Schema:
   ```json
   {
     "version": 1,
     "enabled": true,
     "measurement": "hybrid",
     "refactor_attempts": 3,
     "thresholds": {
       "cyclomatic_complexity": 10,
       "cognitive_complexity": 15,
       "method_lines": 50,
       "parameter_count": 4,
       "nesting_depth": 3,
       "class_lines": 300,
       "crap_score": 30
     },
     "custom_gates": []
   }
   ```
   `measurement: "hybrid"` = real analyzer when installed, else heuristics;
   `crap_score` is skipped with a note when no coverage report exists.
5. **Confirm.** Print the absolute path and final values; this applies to all
   future runs until this command is run again.
