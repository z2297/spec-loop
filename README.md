# spec-loop

A Claude Code **plugin marketplace** hosting the **spec-loop** plugin — a spec-driven
**autonomous development loop**. Give it one feature request; it decomposes the work
into targeted slices, then drives each slice through
**plan → execute → scoped review → auto-fix → merge**, running independent slices in
parallel git worktrees as background agents, and surfaces to you **only** when it
genuinely cannot decide.

Before any work begins, an adversarial **Iron Council** of five agents challenges the
request and every slice plan — surfacing discrepancies and lifting genuinely unworthy
work to you, while folding lesser concerns in and continuing.

Built for **larger work items**: the initial decomposition can be coarse because any
slice that turns out too big **splits itself** back into the plan mid-run (dynamic
decomposition), and once every slice lands an **integration gate** verifies the
assembled whole before the run is called complete — both fully autonomous.

## Install

```
/plugin marketplace add z2297/spec-loop
/plugin install spec-loop@spec-loop
```

Then start a new session (or run `/reload-plugins`).

### Channels & previous versions

One marketplace serves three channels plus a pinned archive of every past release —
add it once, then install whichever build you want:

```
/plugin install spec-loop@spec-loop          # stable  — recommended (tracks main)
/plugin install spec-loop-beta@spec-loop      # beta    — release candidates
/plugin install spec-loop-alpha@spec-loop     # alpha   — bleeding edge

# Roll back to / pin an exact previous release (version with dashes, not dots):
/plugin install spec-loop-0-3-0@spec-loop     # v0.3.0
/plugin install spec-loop-0-2-0@spec-loop     # v0.2.0
```

If a new build is buggy, install the version-pinned entry for the last release that
worked for you. See [`CHANGELOG.md`](CHANGELOG.md) for what changed in each version
and the full channel reference.

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

See the plugin README for worked **simple / mid / advanced**
[usage examples](plugins/spec-loop/README.md#usage-examples), plus flags, the
autonomy contract, the Iron Council, components, and limitations.

## What's in this repo

```
.
├── .claude-plugin/
│   └── marketplace.json     # marketplace manifest (stable + beta/alpha + archive)
├── .github/workflows/
│   ├── validate.yml         # CI gate (runs on PRs + pushes to main/beta/alpha)
│   └── release.yml          # one-button release (workflow_dispatch)
├── scripts/
│   ├── validate_marketplace.py  # self-contained manifest validator
│   └── release.py               # release helper (bump + archive + changelog)
├── CHANGELOG.md             # version history + channel reference
├── plugins/
│   └── spec-loop/           # the plugin
│       ├── .claude-plugin/plugin.json
│       ├── commands/        # /spec-loop controller, /spec-loop:quality-gate config, /spec-loop:dashboard view
│       ├── agents/          # spec-loop-slice worker + 5 iron-council members
│       ├── skills/          # iron-council, escalation-gate, review-depth-map, quality-gate
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
   manifest parses, required fields exist, each relative-path `source` resolves to a
   real plugin dir (and object `git-subdir`/`github` sources are structurally valid),
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

## Channels & release model

| Channel | Install target              | Backed by      | Meaning                          |
| ------- | --------------------------- | -------------- | -------------------------------- |
| stable  | `spec-loop@spec-loop`       | `main` branch  | recommended, release-quality     |
| beta    | `spec-loop-beta@spec-loop`  | `beta` branch  | release candidates ahead of stable |
| alpha   | `spec-loop-alpha@spec-loop` | `alpha` branch | bleeding edge, may be unstable   |
| archive | `spec-loop-<x-y-z>@spec-loop` | tag `vX.Y.Z` | a pinned, immutable past release |

All channels live in the single `.claude-plugin/marketplace.json`. The stable entry
uses a relative `source`, so it serves whatever is on the branch the consumer added
(default `main`). The beta/alpha and archive entries use `git-subdir` sources pinned
to a `ref` (the `beta`/`alpha` branch, or a `vX.Y.Z` tag).

## Releasing

Releases are cut with **Actions → release** (`.github/workflows/release.yml`,
`workflow_dispatch`): choose a `version` and `channel`. The workflow validates, runs
`scripts/release.py`, commits to the channel's branch, and — for stable — tags
`vX.Y.Z`, adds the pinned archive entry, and publishes a GitHub Release from the
`CHANGELOG.md` section.

The same logic runs locally (e.g. to prepare a release PR):

```
python3 scripts/release.py 0.5.0                  # stable: bump + archive + changelog
python3 scripts/release.py 0.6.0-beta.1 --channel beta   # pre-release: bump only
python3 scripts/release.py --notes 0.5.0          # print a version's release notes
```

> Stable publishing commits to `main` from CI, which needs `contents: write` (granted
> in the workflow). If a branch ruleset blocks the bot, run `release.py` locally, open
> a PR, then push the `vX.Y.Z` tag after merge.

## License

[MIT](LICENSE) © Zach McMurry
