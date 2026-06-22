# spec-loop

A spec-driven **autonomous development loop** for Claude Code. Give it one feature
request; it decomposes the work into small targeted slices, then drives each slice
through **plan → execute → scoped review → auto-fix → merge** — running independent
slices in parallel git worktrees as background agents. It surfaces to you **only**
when it genuinely cannot decide.

## What it does

- **Auto-decompose** one request into the smallest independently shippable slices.
- **Dependency-aware scheduling** — independent slices run in parallel worktrees;
  dependent slices serialize.
- **Per slice:** `superpowers:writing-plans` → `superpowers:subagent-driven-development`
  (falls back to `executing-plans` if nested subagents aren't available) →
  `pr-review-toolkit:review-pr` scoped to the plan's risk tier → a bounded auto-fix
  loop → `superpowers:verification-before-completion` → `finishing-a-development-branch`.
- **Autonomy contract** (`escalation-gate`): proceed-and-log by default; interrupt
  you only on (1) genuine ambiguity, (2) a material assumption, or (3) a review
  BLOCK that survives the auto-fix loop. Escalations are batched at wave boundaries
  so background work never blocks your terminal.

## Requirements (install these first)

This plugin **depends on two other plugins** — Claude Code does not auto-install
them, so the consumer must add them:

```
/plugin marketplace add anthropics/claude-plugins-official
/plugin install superpowers@claude-plugins-official
/plugin install pr-review-toolkit@claude-plugins-official
```

Optional, used only for high-risk (Tier 3) reviews: a plugin providing
`/exhaustive-pr-review:exhaustive-pr`. If absent, the loop uses
`pr-review-toolkit:review-pr all parallel` instead.

## Install

**From a marketplace (recommended):**
```
/plugin marketplace add z2297/spec-loop
/plugin install spec-loop@spec-loop
```

**Quick / offline (no marketplace):**
```
claude --plugin-dir /path/to/spec-loop
# or a zipped copy:
claude --plugin-dir /path/to/spec-loop.zip
```

After installing, start a new session (or run `/reload-plugins`).

## Usage

```
/spec-loop "Add rate limiting to the public API with per-key quotas"
```

Flags:
- `--max-parallel N` — max concurrent slices (default 5).
- `--risk-floor 1|2|3` — minimum review tier for the whole run (default 1).
- `--resume <run-id>` — continue a previous run.

Run state is written under `docs/spec-loop/<run-id>/` (request, slice DAG, open
escalations, and an audit log of auto-decisions).

## Components

| Type    | Name              | Role |
|---------|-------------------|------|
| command | `spec-loop`       | Controller — decompose, schedule waves, surface batched escalations |
| agent   | `spec-loop-slice` | Per-slice worker — creates a clean dedicated worktree up front, then plan→execute→review→fix→merge inside it |
| skill   | `escalation-gate` | The autonomy contract |
| skill   | `review-depth-map`| Maps a plan's risk tier to how far `review-pr` goes |

## Notes & limitations

- **Clean dedicated worktrees:** each worker's first action is to create a clean,
  dedicated worktree under `.worktrees/spec-loop/<run-id>/<slice-id>` (branch
  `spec-loop/<run-id>/<slice-id>`), branched from the current tip of the
  integration base, with a verified clean baseline. Stale worktrees from aborted
  runs are removed and recreated; a worktree is reused only when resuming a paused
  slice that has committed progress. `.worktrees/` must be gitignored (the
  using-git-worktrees skill handles this).
- **Agent nesting / background rule:** only the top-level session can run agents
  in the background. The controller backgrounds the slice workers; each slice
  worker is a subagent and therefore dispatches its own implementer/reviewer
  agents **synchronously** (`run_in_background: false`) — required by the platform
  and correct for subagent-driven-development, which is sequential. If `/spec-loop`
  itself is invoked from inside another agent, the controller falls back to running
  slices synchronously (no cross-slice parallelism).
- If nested subagent dispatch is unsupported entirely in your environment, the
  slice worker falls back to inline `superpowers:executing-plans`.
- Background agents cannot prompt you directly; that's why escalations are
  file-based and surfaced by the controller at wave boundaries.
- This loop intentionally overrides the human approval gates in `brainstorming`
  and `subagent-driven-development`. `verification-before-completion` is kept as a
  hard, no-human gate.

## License

[MIT](../../LICENSE) © Zach McMurry
