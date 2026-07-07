# Request

Add a / command for the highest level orchestrator to see a dashboard of the dag, plans, etc

## Resolved up-front (Phase 0)

- **Render form:** Terminal markdown (read-only text in the CLI), per the human's
  answer to the one up-front question. A richer HTML/visual dashboard is explicitly a
  separable follow-on, not part of this run.
- **Command name:** `/spec-loop:dashboard` (literal reading of "dashboard"; PROCEED+log).
- **"highest level orchestrator"** = a human invoking the slash command to inspect a
  run (NOT the controller-agent calling it mid-run — that hits the nesting rule and the
  controller already holds DAG state in-context).
