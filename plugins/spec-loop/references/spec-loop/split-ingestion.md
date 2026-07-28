# Ingesting a SPLIT (dynamic decomposition)

Loaded by the controller when a slice returns `SPLIT`. Read the proposal at
`docs/spec-loop/<run-id>/slice-<id>-split.json` (shape: `references/run-state.md`)
and graft the children into `dag.json`:

1. Insert each child as a `pending` slice with id `<parent-id>.1`, `<parent-id>.2`, …,
   `depth = parent.depth + 1`, `parent = <parent-id>`. Carry `goal`/`files`/
   `subsystems` from the proposal; assign each child a `risk_tier` via
   `review-depth-map` heuristics (never below `--risk-floor`).
2. **deps:** children inherit the parent's external `deps`; translate each child's
   `internal_deps` indices into the sibling child ids and add them.
3. **Rewrite dependents:** every slice that listed the parent in its `deps` now
   depends on **all** of the parent's children (replace the parent id with the
   full child-id set).
4. Mark the parent `status:"split"` (terminal — not counted as incomplete).
5. Re-run the DAG sanity check (no cycles, every `deps` id exists), then append one
   line to `decisions-log.md` recording the graft.

The children schedule in later waves like any `pending` slice — no special wave
logic.
