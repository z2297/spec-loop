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
├── plugins/
│   └── spec-loop/           # the plugin
│       ├── .claude-plugin/plugin.json
│       ├── commands/        # /spec-loop controller
│       ├── agents/          # spec-loop-slice worker
│       ├── skills/          # escalation-gate, review-depth-map
│       └── README.md
├── LICENSE
└── README.md
```

## License

[MIT](LICENSE) © Zach McMurry
