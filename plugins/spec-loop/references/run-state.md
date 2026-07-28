# Spec-loop run-state contract

Single home of the on-disk run-state contract. Everything lives under
`docs/spec-loop/<run-id>/` in the repo the run operates on.

## `dag.json` — the sole authority on run structure

Rewritten in place by the controller as slices complete or split.

```jsonc
{
  "base_ref": "<integration branch>",        // the ONE branch every slice merges into
  "base_sha": "<sha at its creation point>",
  "base_branch": "<branch it was cut from>", // usually main or master
  "merge_mode": "single-branch | per-slice-pr",
  "created_at": "<ISO-8601 UTC>",            // feeds run_metrics.py wall-clock timing
  "shared_constraints": ["<run-wide must-not-regress constraints; [] if none>"],
  "slices": [
    {
      "id": "s1",
      "goal": "<one shippable change>",
      "files": ["..."], "subsystems": ["..."],
      "deps": ["<slice ids>"],
      "risk_tier": 1,                        // 1|2|3, per review-depth-map; --risk-floor is the minimum
      "depth": 0,                            // split generation; intake slices = 0
      "parent": null,                        // split children point at the slice they came from
      "status": "pending",                   // pending | complete | split (terminal)
      "remediation": true                    // present only on Phase 5 remediation slices
    }
  ]
}
```

## Wave derivation

A **wave** = every slice whose `status` is `pending` and whose `deps` are all
`complete`. A `split` parent is terminal: it never schedules and never blocks —
its children (which replaced it in every dependent's `deps`) do.
This rule must stay in sync with `scripts/dashboard_server.py`, which implements
the same derivation in code.

## `slice-<id>-split.json` — split proposal

Written by a slice worker returning `SPLIT`; ingested by the controller
(`references/spec-loop/split-ingestion.md`). A JSON array of children, each
`{goal, files, subsystems, internal_deps}`, where `internal_deps` lists the
**1-based indices** of sibling children that must complete first (`[]` if none).

## `slice-<id>-status.json` — slice status sidecar

The machine-readable slice result; authoritative over the agent's return text.
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/council_contracts.py" validate-slice-status --file <path>`
is the schema of record — a missing or invalid sidecar fails closed to
`NEEDS_DECISION`.

## Other artifacts

| File | Written by | Purpose |
|---|---|---|
| `request.md` | controller | verbatim request (or plan-file content under `--from-plan`) |
| `conventions.md` | controller | Phase 0 exploration summary; read by every slice and council instead of re-exploring |
| `escalations.md` | slices append, controller answers | open questions for the human; `escalation-gate` entry format |
| `decisions-log.md` | everyone, append-only | one-line decisions, each ending ` — AT: <ISO-8601 UTC>` for `run_metrics.py` |
| `slice-<id>-report.md` | slice worker | human-readable slice report |
| `metrics.json` | `run_metrics.py` | run metrics snapshot (atomic write) |
| `runbook.md` | `runbook` skill | end-of-run synthesis; committed with the run state |

## Marker lifecycle (guard-hook contract)

- `.active` — created at Phase 1 (one line: ISO timestamp + run-id), recreated on
  resume, **never committed**. While it exists, the bundled PreToolUse hook
  (`spec_loop_guard.py`) deterministically blocks mid-run pushes, broad staging,
  main-branch commits/merges, and quality-gate config edits.
- `.publish-choice` — written the moment the human answers the Phase 5 publish
  prompt, before the action is performed; the hook blocks pushes/main-merges until
  it exists.
- `.done` — `.active` is renamed to `.done` when the run ends, disengaging the hook.
  A hook denial means the run has not earned that operation yet — never delete a
  marker to dodge one.
