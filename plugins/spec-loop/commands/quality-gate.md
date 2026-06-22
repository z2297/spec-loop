---
description: "View or update the spec-loop code-quality gate — thresholds (cyclomatic complexity, method length, CRAP, …) and custom gates, persisted globally across all runs"
argument-hint: "(no args — interactive)"
allowed-tools: ["Bash", "Read", "Write", "Edit", "AskUserQuestion"]
---

# Spec-Loop Quality Gate — setup & update

Configure the objective code-quality bar that every `/spec-loop` slice must clear
after PR review, before merge. The config is **global** and persists across all runs
and repos at `~/.claude/spec-loop/quality-gate.json`. This command is the **only**
thing that prompts for it — the loop never re-asks once the file exists.

The runtime behavior of the gate is defined by the `quality-gate` skill; this command
just owns the config file.

## Steps

1. **Locate / read current config.** Resolve `~/.claude/spec-loop/quality-gate.json`.
   - If it exists, read and **show the current values** (thresholds, `refactor_attempts`,
     `measurement`, `enabled`, and any `custom_gates`).
   - If it does not exist, say so — this is first-time setup.

2. **Choose a quality level.** Ask via `AskUserQuestion` (single select) which level to
   apply. Present the concrete numbers so the user is validating the actual bar:
   - **Recommended (default)** — `cyclomatic 10, cognitive 15, method_lines 50,
     parameter_count 4, nesting_depth 3, class_lines 300, crap 30`.
   - **Strict** — tighter: `cyclomatic 8, cognitive 12, method_lines 40,
     parameter_count 3, nesting_depth 2, class_lines 250, crap 20`.
   - **Lenient** — looser: `cyclomatic 15, cognitive 20, method_lines 75,
     parameter_count 5, nesting_depth 4, class_lines 400, crap 40`.
   - **Customize** — set individual thresholds.

3. **Customize (only if chosen).** Walk the thresholds in batches via `AskUserQuestion`,
   offering the recommended value first and using the **"Other"** free-text option for
   an exact number. Also ask for `refactor_attempts` (default 3) and `enabled` (default
   true). Keep batches to ≤4 questions per round.

4. **Additional / custom gates.** Ask whether to add any custom gates beyond the
   built-ins. Each is either:
   - a **metric** gate `{ "name", "metric", "threshold" }`, or
   - a **command** gate `{ "name", "command", "pass_when": "exit 0" }` (run against the
     slice's changed files).
   Capture any the user describes (e.g. "no TODO comments", "coverage ≥ 80%").

5. **Write the file.** Ensure the directory exists (`mkdir -p ~/.claude/spec-loop`) and
   `Write` the JSON. Schema:
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

6. **Confirm.** Print the absolute path and the final values, and remind the user this
   applies to **all** future `/spec-loop` runs until they run `/spec-loop:quality-gate`
   again. Do not trigger a loop or any slice work from this command.

## Notes
- `measurement` is `hybrid` (real analyzer when installed, else `refactor-analysis`
  heuristics). `crap_score` needs coverage data; the gate skips it with a note when no
  coverage report is available.
- This command never measures code or refactors — it only edits the config.
