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
- **Auto-decompose** one request into independently shippable slices.
- **Dynamic decomposition** — the initial cut can be coarse: a slice that turns out
  to be two-or-more shippable changes **splits itself** back into the DAG mid-run
  (autonomous, depth-capped), so large or fuzzy requests don't need a perfect
  fine-grained plan before any code exists.
- **Dependency-aware scheduling** — independent slices run in parallel worktrees;
  dependent slices serialize.
- **Integration gate** — once every slice lands, a final pass verifies the *assembled
  whole* (full suite on the integration base + a cross-slice review of the cumulative
  diff), catching contract drift and same-wave merge incompatibilities that a
  per-slice review structurally can't see. Failures are remediated by a normal slice.
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

**Channels & previous versions** — one marketplace serves stable plus pre-release
channels and a pinned archive of every past release:
```
/plugin install spec-loop-beta@spec-loop      # beta  — release candidates
/plugin install spec-loop-alpha@spec-loop     # alpha — bleeding edge
/plugin install spec-loop-0-3-0@spec-loop     # pin/roll back to v0.3.0 (dashes, not dots)
```
See the [CHANGELOG](../../CHANGELOG.md) for the full version history and channel table.

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

## Usage examples

Three scenarios at increasing complexity. The commands are **illustrative** — not
specific to this repo — and show how decomposition, the **Iron Council**, and the
autonomy contract behave at different scales.

### Simple — a single low-risk slice (fully autonomous)

```
/spec-loop "Add a --version flag to the CLI that prints the package version"
```

What happens:
- Decomposes to **one slice**, classified **Tier 1** (isolated, no behavioral surface).
- The Iron Council convenes at **intake** (verdict: ENDORSE) and again on the **plan**
  (ENDORSE) — the work is sound, so it stays silent.
- The slice runs end-to-end in its own worktree: plan → execute (TDD) → light
  `review-pr code` → quality gate → merge.
- **No interruptions.** You get a final summary with the branch/PR. This is the happy
  path: when the request and plan are clean, the council never bothers you.

### Mid — a multi-slice feature in parallel (a council concern folded in)

```
/spec-loop "Add CSV export to the reports page — a backend endpoint and a frontend download button"
```

What happens:
- Decomposes into **~2 independent slices** (export endpoint, download button) that run
  in **parallel worktrees**, each **Tier 2**.
- On one slice's plan, the **Historian** returns `ENDORSE_WITH_CONCERNS` — e.g. *"reuse
  the existing `serializeRows()` helper instead of writing a new CSV formatter."*
- Because it's a minority, non-safety concern, it is **folded into the plan and logged**
  to `decisions-log.md` — **you are not interrupted**.
- Both slices pass review + quality gate and merge. Illustrates dependency-aware
  parallel scheduling plus autonomy-preserving "fold the concern, keep moving."

### Advanced — high-risk, flags, a council objection, and resume

```
/spec-loop "Migrate auth from session cookies to JWT with refresh tokens, keeping existing sessions valid during rollout" --risk-floor 2 --max-parallel 3
```

What happens:
- High-risk surface (auth/security) → slices are **Tier 3**; `--risk-floor 2` forbids any
  Tier 1 review and `--max-parallel 3` caps concurrency.
- At **intake**, the **Guardian** raises a `SAFETY` OBJECT — e.g. the rollout could
  **invalidate live sessions** or leave refresh tokens unrevocable. A single safety
  objection is enough to **halt**: it's lifted to you via `escalation-gate`'s
  `council-objection` trigger as **one batched `AskUserQuestion`**.
- You answer (e.g. "dual-validate cookie + JWT during a 2-week overlap"); the controller
  injects the decision and proceeds — **without re-convening the council on a question
  you've already settled.**
- Tier 3 slices run the deepest review (`review-pr all parallel`, or
  `/exhaustive-pr-review:exhaustive-pr` if installed). Any further escalations batch at
  **wave boundaries**, never one-at-a-time.
- Interrupted? `--resume <run-id>` skips completed slices and continues. Illustrates the
  full machinery: flags, tiered review, the council's hard stop, batched escalation, and
  resume.

### Large — a coarse request that splits itself, then an integration gate

```
/spec-loop "Add a billing module: usage metering, monthly invoice generation, and a customer billing dashboard"
```

What happens:
- Decomposes into a **coarse** first cut — say three slices (metering, invoicing,
  dashboard) — without over-thinking the fine boundaries.
- When the **invoicing** slice plans its work, the **Pragmatist** flags it as two
  independently shippable changes (invoice *data model + generation* vs. *PDF/email
  delivery*). The slice returns **`SPLIT`**; the controller grafts the two children
  into the DAG, rewires the dashboard's dependency onto both, and schedules them — all
  **autonomously**, logged to `decisions-log.md`, **no interruption**.
- After the final wave merges, the **integration gate** (Phase 5) runs the full suite
  on the integration base and a cross-slice review of the cumulative diff. It catches
  that the dashboard calls an invoice field the split renamed; the loop opens a small
  **remediation slice**, fixes it, and re-verifies — still no human contact.
- You get a summary noting the split parent, its children, and the integration result.
  Illustrates **longer autonomous runs on larger work**: coarse-in, self-refining,
  whole verified — with the escalation bar unchanged.

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
| command | `spec-loop`       | Controller — decompose, schedule waves, ingest splits, run the integration gate, surface batched escalations |
| command | `quality-gate`    | View/update the global code-quality gate config (`/spec-loop:quality-gate`) |
| command | `dashboard`       | Read-only terminal-markdown view of a run — DAG, derived waves, slice status, escalations, decisions (`/spec-loop:dashboard [run-id]`) |
| agent   | `spec-loop-slice` | Per-slice worker — creates a clean dedicated worktree up front, then plan→council→(split if too big)→execute→review→quality-gate→merge inside it |
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
- **Dynamic decomposition is depth-capped:** a slice may split at most twice
  (`MAX_SPLIT_DEPTH = 2`). A slice still oversized at the cap stops splitting and
  falls back to the normal escalation path — splits never become a new way to
  interrupt you.
- **Integration gate runs on the merge base.** If slices opened PRs instead of
  merging, it verifies on a throwaway integration branch and reports, leaving the PRs
  for you to merge.

## License

[MIT](../../LICENSE) © Zach McMurry
