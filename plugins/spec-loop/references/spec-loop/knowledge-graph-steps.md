# Controller knowledge-graph steps (opt-in)

Loaded only when `~/.claude/spec-loop/knowledge-graph.json` has `enabled:true`
and a `vault_path`. Otherwise every step below is skipped silently. All calls are
serial, main-session, and non-gating: on any error, log one line and continue —
never delay intake or a wave. Slice workers never invoke the knowledge-graph
skill or helper; the controller pre-fetches for them.

## Intake — prior knowledge (Phase 0, during exploration)

Run one read-only helper call:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/knowledge_graph.py" context --vault <vault_path> --subfolder <subfolder> --repo <repo-slug> --term <t> ...
```

passing 5–8 salient terms from the request (domain nouns, subsystem names; the
helper ranks by lexical overlap and reorders, never filters). Append a short
`## Prior knowledge (knowledge graph)` section to the conventions summary: the
system hub one-liner, existing cross-repo patterns with one-liners, active
decisions and domain notes for this repo, and the `known_ids` lists with an
instruction to reuse those exact ids in later graph writes. List any decision
with `relevance > 0` under **Prior decisions that may bear on this request**,
with the instruction that the Iron Council must verify the request against them
and flag contradictions — the graph surfaces candidates; it does not judge
conflict.

## Run seed (Phase 1, after run state is written)

Invoke the `knowledge-graph` skill once to upsert the `system/<repo>` hub
(create-or-touch adding this `run-id`) and create the `run/<run-id>` MOC.
Include `"ensure_base": true` unless the config sets `starter_base: false` —
the helper create-onces the vault's starter Base view and refreshes the hub's
home index as side effects.

## Wave pre-fetch (Phase 2, before dispatching a wave)

Run ONE read-only helper call for the whole wave:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/knowledge_graph.py" context --vault <vault_path> --subfolder <subfolder> --repo <repo-slug> --request-file docs/spec-loop/<run-id>/request.md --component <s> ...
```

with the union of the wave's slices' `subsystems` (slugified) as repeated
`--component` flags. From the returned `components` map, inject into each
slice's dispatch prompt a `## Prior knowledge for this slice (knowledge graph)`
section covering only the components that slice touches — **≤ ~120 words /
~10 lines**, ids + one-liners only. Slices whose components all have empty
buckets get no section.

## Wave decisions (Phase 3, at the wave boundary)

Invoke the `knowledge-graph` skill once per wave to upsert `decision` nodes for
the *material* decisions / council verdicts logged during the wave, plus one
`decision` node per human-answered escalation — each linking to the `run`, the
repo `system`, and the `component` hubs it touched (hubs are created on
reference). The helper is idempotent under retry; its result reports
`redactions` and `remapped` counts — include them in the one-line digest logged
to `decisions-log.md`.
