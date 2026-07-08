---
description: "View or update the spec-loop Obsidian knowledge graph config — vault location, node types, and write mode, persisted globally across all runs"
argument-hint: "(no args — interactive)"
allowed-tools: ["Bash", "Read", "Write", "Edit", "AskUserQuestion"]
---

# Spec-Loop Knowledge Graph — setup & update

Configure the optional Obsidian **knowledge graph** that `/spec-loop` accumulates across
runs — one markdown note per decision, architecture pattern, system-context hub, and
domain-knowledge item, linked with `[[wikilinks]]` so the graph grows and cross-links over
time. The config is **global** and persists across all runs and repos at
`~/.claude/spec-loop/knowledge-graph.json`. This command is the **only** thing that prompts
for it — the loop never re-asks once the file exists.

The runtime behavior is defined by the `knowledge-graph` skill; this command just owns the
config file. **This feature is opt-in and inert until you supply your own vault path** — this
is a distributed plugin, so no vault location is ever assumed.

## Steps

1. **Locate / read current config.** Resolve `~/.claude/spec-loop/knowledge-graph.json`.
   - If it exists, read and **show the current values** (`enabled`, `vault_path`,
     `subfolder`, `write_mode`, `node_types`).
   - If it does not exist, say so — this is first-time setup.

2. **Enable?** Ask via `AskUserQuestion` whether to enable the knowledge graph. If the user
   declines, write a config with `"enabled": false` (leaving `vault_path` as-is or `null`)
   and go to step 6. When disabled, `/spec-loop` does no vault work at all.

3. **Vault path (required — no default).** If enabling, ask for the **absolute path to their
   Obsidian vault root** using the free-text **"Other"** option (there is no sensible default
   to offer — every user's vault lives somewhere different). Then:
   - **Validate** it: expand `~`, confirm the directory **exists and is writable**
     (`test -d "<path>" && test -w "<path>"`). If it does not exist or is not writable, say so
     and re-ask — never silently create a vault in an assumed location, and never enable with
     an unwritable path.
   - Ask for the `subfolder` within the vault (default `spec-loop`; `""` writes at the vault
     root). Notes land under `<vault_path>/<subfolder>/`.

4. **Node types & write mode.** Ask (batched, ≤4 per round):
   - **Which node types** to emit — any of `decision`, `pattern`, `system`, `domain`
     (default: all four). `component` and `run` index notes are structural glue and are
     always written when any content type is enabled.
   - **`write_mode`** — `mcp-preferred` (default: use the Obsidian MCP when reachable for
     live indexing + cross-vault link discovery, else write files directly) or `direct`
     (always write files straight to disk; works with Obsidian closed).

5. **Write the file.** Ensure the directory exists (`mkdir -p ~/.claude/spec-loop`) and
   `Write` the JSON. Schema:
   ```json
   {
     "version": 1,
     "enabled": true,
     "vault_path": "/absolute/path/to/vault",
     "subfolder": "spec-loop",
     "write_mode": "mcp-preferred",
     "node_types": ["decision", "pattern", "system", "domain"]
   }
   ```
   When disabled, write `"enabled": false` and `"vault_path": null` (unless a valid one was
   previously set — then preserve it).

6. **Confirm.** Print the absolute config path and the final values, and remind the user this
   applies to **all** future `/spec-loop` runs until they run `/spec-loop:knowledge-graph`
   again. Do not trigger a loop or any vault write from this command.

## Notes
- **No machine-specific defaults.** `vault_path` has no assumed value; the feature stays
  inert until the user provides one. This keeps the distributed plugin portable across users.
- **Enabling implies read + write.** Besides recording notes, the loop surfaces prior
  knowledge from the vault at run intake (existing patterns, active decisions, domain notes)
  into the run's conventions summary — one `context` helper call that only reads the vault
  and never blocks. There is no separate toggle.
- The graph is plain markdown + `[[wikilinks]]` + YAML frontmatter — Obsidian derives the
  graph view from the links; nothing needs Obsidian running to *write* the notes (it indexes
  them on next open). `mcp-preferred` only changes *how* notes are written, not the result.
- This command never writes to the vault or measures anything — it only edits the config.
- Emission itself is deliberately **light touch**: only the `/spec-loop` controller (main
  session, at phase boundaries) and the end-of-run `runbook` write notes. Slice workers never
  touch the vault, so enabling this does not affect the loop's parallel execution.
