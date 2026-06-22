# spec-loop

A Claude Code **plugin marketplace** hosting the **spec-loop** plugin — a spec-driven
**autonomous development loop**. Give it one feature request; it decomposes the work
into small targeted slices, then drives each slice through
**plan → execute → scoped review → auto-fix → merge**, running independent slices in
parallel git worktrees as background agents, and surfaces to you **only** when it
genuinely cannot decide.

## Install

```
/plugin marketplace add z2297/spec-loop
/plugin install spec-loop@spec-loop
```

Then start a new session (or run `/reload-plugins`).

### Required dependencies

`spec-loop` orchestrates two other plugins. Claude Code does **not** auto-install
them, so add them too:

```
/plugin marketplace add anthropics/claude-plugins-official
/plugin install superpowers@claude-plugins-official
/plugin install pr-review-toolkit@claude-plugins-official
```

> Optional: a plugin providing `/exhaustive-pr-review:exhaustive-pr` is used only for
> high-risk (Tier 3) reviews. If absent, the loop falls back to
> `pr-review-toolkit:review-pr all parallel`.

## Usage

```
/spec-loop "Add rate limiting to the public API with per-key quotas"
```

See [`plugins/spec-loop/README.md`](plugins/spec-loop/README.md) for flags, the
autonomy contract, components, and limitations.

## What's in this repo

```
.
├── .claude-plugin/
│   └── marketplace.json     # marketplace manifest (name: spec-loop)
├── .github/workflows/
│   └── validate.yml         # CI gate (runs on PRs + pushes to main)
├── scripts/
│   └── validate_marketplace.py  # self-contained manifest validator
├── plugins/
│   └── spec-loop/           # the plugin
│       ├── .claude-plugin/plugin.json
│       ├── commands/        # /spec-loop controller, /spec-loop:quality-gate config
│       ├── agents/          # spec-loop-slice worker
│       ├── skills/          # escalation-gate, review-depth-map, quality-gate
│       └── README.md
├── LICENSE
└── README.md
```

## Development / CI

Every PR and push to `main` runs the **`validate`** check
(`.github/workflows/validate.yml`), which fails if the marketplace or any plugin is
structurally broken — so nothing invalid can be merged or deployed. It runs two layers,
and passes only if **both** succeed:

1. **`scripts/validate_marketplace.py`** (Python stdlib, no deps) — confirms every
   manifest parses, required fields exist, each `source` resolves to a real plugin dir,
   plugin names are unique and consistent with their `plugin.json`, and every
   skill/command/agent has the required YAML frontmatter keys.
2. **`claude plugin validate`** — the official Claude Code validator (schema + frontmatter).

Run the fast layer locally before pushing:

```
python3 scripts/validate_marketplace.py .
```

**Make it a blocking gate** (one-time, GitHub UI): repo **Settings → Branches → Add
branch ruleset** for `main` → enable **Require status checks to pass before merging** and
add the **`validate`** check (also recommended: **Require a pull request before merging**).
After that, a red `validate` check blocks the merge.

## License

[MIT](LICENSE) © Zach McMurry
