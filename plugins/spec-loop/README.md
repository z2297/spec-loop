# spec-loop

A spec-driven **autonomous development loop** for Claude Code. Give it one feature
request; it decomposes the work into small targeted slices, then drives each slice
through **plan → execute → scoped review → auto-fix → merge** — running independent
slices in parallel git worktrees as background agents. It surfaces to you **only**
when it genuinely cannot decide.

## What it does

- **The Iron Council** (`iron-council`) — a five-member adversarial review body that
  *challenges* the work before effort is spent on it. It convenes on the **user
  request** at intake and on **every slice plan** before execution, surfacing
  discrepancies and opinionated feedback. A majority objection (or any single safety
  objection) deems the work *unworthy* and is lifted to you to decide.
- **Auto-decompose** one request into the smallest independently shippable slices.
- **Dependency-aware scheduling** — independent slices run in parallel worktrees;
  dependent slices serialize.
- **Per slice:** `superpowers:writing-plans` → **Iron Council plan review**
  (`iron-council`) → `superpowers:subagent-driven-development`
  (falls back to `executing-plans` if nested subagents aren't available) →
  `pr-review-toolkit:review-pr` scoped to the plan's risk tier → a bounded auto-fix
  loop → `superpowers:verification-before-completion` → `finishing-a-development-branch`.
- **Autonomy contract** (`escalation-gate`): proceed-and-log by default; interrupt
  you only on (1) genuine ambiguity, (2) a material assumption, (3) a review
  BLOCK that survives the auto-fix loop, or (4) an Iron Council objection.
  Escalations are batched at wave boundaries so background work never blocks your
  terminal.

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

## The Iron Council

The loop's adversarial review body. Its job is not to agree — it is to **challenge
the work before effort is spent on it**, surface discrepancies, and give
constructive-but-opinionated feedback. It convenes at two moments:

- **Intake** — on the **raw user request**, before decomposition (controller).
- **Pre-execution** — on **every slice plan**, after planning and before any code
  runs (slice Step 1.5).

Each member is its own agent with a distinct mandate:

| Member | Challenges |
|--------|-----------|
| `iron-council-skeptic`    | The **premise** — right problem? unstated requirements, ambiguity, XY-problems, undefined success criteria |
| `iron-council-architect`  | The **design** — soundness, coupling, abstraction fit, error/edge paths, whether the plan's steps reach the goal |
| `iron-council-pragmatist` | The **scope** — over-engineering, YAGNI, gold-plating, right-sizing, the simpler path |
| `iron-council-guardian`   | The **risk** — security, secrets/PII, data integrity, migrations, breaking contracts, irreversibility, test coverage |
| `iron-council-historian`  | **Consistency** — existing patterns, conventions, prior decisions, reuse-over-new |

Each member returns `ENDORSE`, `ENDORSE_WITH_CONCERNS`, or `OBJECT`. The verdicts
aggregate:

- **Majority OBJECT (≥3/5)** — or **any single `SAFETY` OBJECT** (irreversible data
  loss, security hole, broken public contract) — deems the work **unworthy**. It is
  lifted to the orchestrator via `escalation-gate`'s `council-objection` trigger and
  surfaced to **you** (batched at intake, or at the wave boundary for a plan).
- **Lesser concerns** (`ENDORSE_WITH_CONCERNS`, minority non-safety objections) are
  **folded into** the decomposition/plan and logged to `decisions-log.md` — they do
  **not** interrupt you. This keeps autonomy-by-default while still lifting genuinely
  unworthy work to a human.

The council is **advisory and read-only** — members never edit code; they route
every halt through the same batched-escalation machinery as the rest of the loop, so
background work is never blocked.

## Quality gate

After PR review and the code-simplifier polish pass — before a slice merges — each
slice must clear an **objective code-quality gate** (slice Step 4c). It measures the
changed code against configurable thresholds:

| Metric | Default |
|--------|---------|
| Cyclomatic complexity (per method) | ≤ 10 |
| Cognitive complexity (per method) | ≤ 15 |
| Method/function length | ≤ 50 lines |
| Parameter count | ≤ 4 |
| Nesting depth | ≤ 3 |
| Class/file length | ≤ 300 lines |
| CRAP score | ≤ 30 *(needs coverage; skipped + noted if unavailable)* |

Plus any **custom gates** you add (a metric threshold, or a shell command that must
pass against the changed files).

- **Measurement is hybrid:** a real analyzer is used when one is installed for the
  project's language (e.g. `eslint` complexity, `radon`, `lizard`); otherwise the
  language-agnostic `refactor-analysis` heuristics estimate the same metrics.
- **On failure, the slice refactors itself** — a bounded (default 3), **behavior-
  preserving** loop that changes implementation only and keeps tests green. If it
  still can't comply, the slice escalates (`NEEDS_DECISION`) rather than merging.

**Configure once, persists everywhere.** On the first `/spec-loop` run you're prompted
to validate the quality level and add any custom gates; the result is saved globally
to `~/.claude/spec-loop/quality-gate.json` and reused by every future run. You're never
re-prompted — update it anytime with:

```
/spec-loop:quality-gate
```

## Components

| Type    | Name              | Role |
|---------|-------------------|------|
| command | `spec-loop`       | Controller — decompose, schedule waves, surface batched escalations |
| command | `quality-gate`    | View/update the global code-quality gate config (`/spec-loop:quality-gate`) |
| agent   | `spec-loop-slice` | Per-slice worker — creates a clean dedicated worktree up front, then plan→council→execute→review→quality-gate→merge inside it |
| agent   | `iron-council-skeptic`    | Council member — challenges the premise |
| agent   | `iron-council-architect`  | Council member — challenges the design |
| agent   | `iron-council-pragmatist` | Council member — challenges the scope |
| agent   | `iron-council-guardian`   | Council member — challenges the risk |
| agent   | `iron-council-historian`  | Council member — challenges consistency with the codebase |
| skill   | `iron-council`    | Convenes the council, aggregates verdicts, routes objections to `escalation-gate` |
| skill   | `escalation-gate` | The autonomy contract |
| skill   | `review-depth-map`| Maps a plan's risk tier to how far `review-pr` goes |
| skill   | `quality-gate`    | Measures changed code vs thresholds; drives the behavior-preserving refactor loop |

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
