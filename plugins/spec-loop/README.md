# spec-loop

A spec-driven **autonomous development loop** for Claude Code. Give it one feature
request; it decomposes the work into small targeted slices, then drives each slice
through **plan → execute → scoped review → auto-fix → merge** — running independent
slices in parallel git worktrees as background agents. It surfaces to you **only**
when it genuinely cannot decide.

## What it does

- **The Iron Council** (`iron-council`) — an adversarial review body that
  *challenges* the work before effort is spent on it. It convenes on the **user
  request** at intake (always the full five members) and on **every slice plan**
  before execution (composition scaled to the slice's risk tier — a low-risk slice
  convenes just pragmatist + guardian), surfacing discrepancies and opinionated
  feedback. A majority objection (or any single safety objection) deems the work
  *unworthy* and is lifted to you to decide.
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
- **Per slice:** `spec-loop:writing-plans` → **Iron Council plan review**
  (`iron-council`) → `spec-loop:subagent-driven-development`
  (falls back to `executing-plans` if nested subagents aren't available) →
  `spec-loop:review-pr` scoped to the plan's risk tier → **adversarial
  verification of every blocking finding** (a `review-finding-verifier` tries to
  refute each one against the actual code, so hallucinated findings never burn fix
  cycles) → a bounded auto-fix loop → `spec-loop:verification-before-completion` →
  hand the verified branch back to the controller.
- **Deterministic guardrails** — a bundled PreToolUse hook (`spec_loop_guard.py`)
  mechanically enforces the loop's git invariants while a run is active: no mid-run
  pushes before your publish choice, no broad staging (`git add -A`), no
  commits/merges on `main`, no quality-gate config edits. The prompts state the
  rules; the hook makes them non-negotiable.
- **Machine-validated contracts** — council members return JSON verdicts and slice
  workers write JSON status sidecars, validated and aggregated fail-closed by a
  bundled script (`council_contracts.py`) — a garbled verdict can never be
  mistaken for an endorsement, a missing member's verdict fails the convening
  (`aggregate --expect`), and a slice without a valid sidecar is never trusted
  as done.
- **Explore once, share everywhere** — the controller's Phase 0 codebase
  exploration is persisted as `docs/spec-loop/<run-id>/conventions.md` and handed
  (with the run's `shared_constraints`) to every slice worker and every council
  convening as one identical context packet, instead of each agent re-discovering
  the same conventions.
- **Cross-run learning** — prior runs' committed artifacts are precedent: the
  historian reads earlier runbooks, decision logs, and human-answered escalations
  and flags re-litigation, and `escalation-gate` checks them before surfacing — a
  question you answered in run N is not asked again in run N+1.
- **Single-branch integration** — every slice merges into **one** dedicated local
  integration branch. Slices never self-merge or open their own PRs; the controller
  merges each verified slice branch **serially** (race-free) and deletes it. The run
  ends by prompting you to push the branch as a feature branch or merge it onto
  `main`. A branch/PR *per slice* happens only with `--per-slice-pr` or an explicit
  request — never by default.
- **Autonomy contract** (`escalation-gate`): proceed-and-log by default; interrupt
  you only on (1) genuine ambiguity, (2) a material assumption, (3) a review
  BLOCK that survives the auto-fix loop, (4) an Iron Council objection, or (5) a
  quality-gate block that survives the refactor loop.
  Escalations are batched at wave boundaries so background work never blocks your
  terminal.

## Requirements

The plugin has **zero external plugin dependencies**. Both the development-process
skill library the loop chains (planning, TDD execution, verification, code-review
discipline, worktrees, branch finishing) and the PR-review library (the
`spec-loop:review-pr` skill, its `/spec-loop:review-pr` command, and six review
agents) ship **natively inside this plugin** — see
[Process skill library](#process-skill-library) below. High-risk (Tier 3) reviews
use the native `spec-loop:review-pr exhaustive` mode.

**Runtime tooling for the auxiliary commands** (the core loop needs none of this —
its worktrees run on the host). These scripts ship *inside* the plugin and are
invoked by their `${CLAUDE_PLUGIN_ROOT}` path, so they work from any repo:

- `/spec-loop:dashboard-serve` needs **Python 3**. **Docker** is optional — with a
  daemon it runs a detached, read-only, loopback-only singleton container built from
  the bundled `Dockerfile`; without one it falls back to a foreground Python server.
- `/spec-loop:peer-review` needs **Python 3** plus the provider CLI for the PR host
  you point it at — `gh` (GitHub), `az` (Azure DevOps), or `git` for a local
  `--base/--head` ref-range.

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
- `--branch <name>` — name of the singular integration branch every slice merges
  into (default: a meaningful slug of the request; never contains `spec-loop`).
- `--base-branch <name>` — branch the integration branch is cut from (default `main`,
  else `master`).
- `--per-slice-pr` — opt into a branch/PR **per slice** instead of the default
  single-branch merge (also triggered by explicitly asking for it in the request).
- `--resume <run-id>` — continue a previous run.

**Branch model.** By default all slices merge into **one** dedicated local
integration branch (cut from `main`), and the run ends by asking whether to push it
as a feature branch or merge it onto `main` — nothing is pushed and `main` is never
touched until you choose. Per-slice branches/PRs happen **only** with `--per-slice-pr`
or an explicit request.

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
  `review-pr code` → quality gate → verified branch; the controller merges it into the
  single integration branch.
- **One up-front-free run, one closing prompt.** The council never bothers you when
  the request and plan are clean; at the end you're asked once whether to push the
  integration branch as a feature branch or merge it onto `main`.

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
- Tier 3 slices run the deepest review (`spec-loop:review-pr exhaustive` — all
  review agents forced, P0–P3 reporting). Any further escalations batch at
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
- With everything merged onto the one integration branch and verified, you're asked
  once how to publish it (feature branch or onto `main`), then get a summary noting the
  split parent, its children, and the integration result. Illustrates **longer
  autonomous runs on larger work**: coarse-in, self-refining, whole verified — with the
  escalation bar unchanged.

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

- **Measurement is script-first and deterministic:** the bundled
  `scripts/quality_gate.py` measures the slice diff — via an installed analyzer
  when available (`lizard` preferred, `radon` for Python) or its built-in stdlib
  analyzer (marked `builtin-heuristic`) otherwise — and emits one JSON report of
  record. Model-driven heuristics remain only as a fallback when the script itself
  cannot run.
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

## Knowledge graph (optional)

`/spec-loop` can accumulate what each run *learned* into a persistent **Obsidian knowledge
graph** — one markdown note per **decision**, **architecture pattern**, **system-context** hub,
and **domain-knowledge** item, linked with `[[wikilinks]]` and tagged via YAML frontmatter.
Unlike the per-run artifacts under `docs/spec-loop/<run-id>/`, these notes **accumulate and
cross-link across every run and repo**: a repo's system hub and shared patterns grow over time
(re-runs *update* a node — appending a dated observation and the new run-id — rather than
duplicating it), so Obsidian's graph view becomes a navigable map of your codebase's decisions.

- **Opt-in and portable.** Disabled by default. Enable it — and give **your own** vault path
  (there is no assumed default; this is a distributed plugin) — with:
  ```
  /spec-loop:knowledge-graph
  ```
  The config persists globally at `~/.claude/spec-loop/knowledge-graph.json` and is never
  re-prompted. Notes are written under `<vault>/<subfolder>/` (default subfolder `spec-loop`).
- **Light touch — does not affect the loop.** Only the controller (at phase boundaries) and the
  end-of-run `runbook` write notes; **slice workers never touch the vault**, so parallel
  execution is unchanged. A vault/MCP hiccup is logged and never blocks a run.
- **Writes are MCP-preferred with a direct-file fallback.** With the Obsidian app + Local REST
  API MCP reachable, it uses it (live indexing + cross-vault link discovery); otherwise it
  writes the markdown straight to disk (Obsidian indexes it on next open). Requires an Obsidian
  vault; the Obsidian app is **not** required for writes.
- **The graph feeds the loop back.** At run intake the controller pulls a bounded
  prior-knowledge summary from the vault (existing patterns — including ones learned in
  *other* repos — plus this repo's active decisions and domain notes) into the run's
  conventions summary, so councils and slice workers see what earlier runs established.
  Notes are scrubbed by a deterministic secret-redaction floor before they ever reach the
  vault.

## Components

| Type    | Name              | Role |
|---------|-------------------|------|
| command | `spec-loop`       | Controller — decompose, schedule waves, ingest splits, run the integration gate, surface batched escalations |
| command | `quality-gate`    | View/update the global code-quality gate config (`/spec-loop:quality-gate`) |
| command | `knowledge-graph` | View/update the global Obsidian knowledge-graph config — vault path, node types, write mode (`/spec-loop:knowledge-graph`) |
| command | `dashboard`       | Read-only terminal-markdown view of a run — **stage-aware** (Iron Council findings, per-slice execution DAG, final-review Executive Readout) with a static all-status escalations section (`/spec-loop:dashboard [run-id]`) |
| command | `dashboard-serve` | Start a local read-only **web** dashboard — a dark-theme single-page UI whose run detail is a **stage pipeline** (Iron Council → Execution → Final Review) with a specific view per stage and a pinned escalations panel, over the same run artifacts (`/spec-loop:dashboard-serve [--port N] [--root PATH]`) |
| command | `peer-review`     | Strictly read-only multi-provider peer-review loop — resolve a real PR (GitHub/Azure DevOps/Bitbucket URL or local `--base/--head`), convene the five `peer-review-*` reviewers + a report-only `spec-loop:review-pr` pass via `peer-review-council`, and publish one report under `docs/pr-review/<review-id>/`; never edits, merges, or posts (`/spec-loop:peer-review <requirements> --pr <url>`) |
| command | `review-pr`       | Aspect-based PR review over a diff using the native review agents — thin wrapper over the `review-pr` skill (`/spec-loop:review-pr [aspects] [parallel|exhaustive]`) |
| agent   | `spec-loop-slice` | Per-slice worker — creates a clean dedicated worktree up front, then plan→council→(split if too big)→execute→review→quality-gate→verify, and hands the committed branch back to the controller to integrate (opens its own PR only in `--per-slice-pr` mode) |
| agent   | `peer-review-conformance` | Peer-review reviewer — judges the diff against the supplied business requirements |
| agent   | `peer-review-correctness` | Peer-review reviewer — hunts logic errors and bugs in the diff |
| agent   | `peer-review-design`      | Peer-review reviewer — judges design, abstraction, and structure |
| agent   | `peer-review-risk`        | Peer-review reviewer — flags security, data, and irreversibility risk |
| agent   | `peer-review-tests`       | Peer-review reviewer — judges test coverage of the changed behavior |
| agent   | `iron-council-skeptic`    | Council member — challenges the premise |
| agent   | `iron-council-architect`  | Council member — challenges the design |
| agent   | `iron-council-pragmatist` | Council member — challenges the scope |
| agent   | `iron-council-guardian`   | Council member — challenges the risk |
| agent   | `iron-council-historian`  | Council member — challenges consistency with the codebase |
| agent   | `review-finding-verifier` | Adversarially verifies one blocking review finding against the actual code before the auto-fix loop — refutes with file:line evidence or confirms (confirm is the default) |
| skill   | `iron-council`    | Convenes the council, aggregates verdicts, routes objections to `escalation-gate` |
| skill   | `escalation-gate` | The autonomy contract |
| skill   | `review-depth-map`| Maps a plan's risk tier to how far `review-pr` goes |
| skill   | `quality-gate`    | Measures changed code vs thresholds; drives the behavior-preserving refactor loop |
| skill   | `knowledge-graph` | Projects a run's decisions/patterns/context/domain into the user's Obsidian vault as linked notes that accumulate across runs (opt-in; controller + runbook only; MCP-preferred with direct-file fallback) |
| skill   | `peer-review-council` | Convenes the five `peer-review-*` reviewers + a report-only `spec-loop:review-pr` pass and aggregates them into one pinned-schema, report-only review (no fixes, no write-back) |
| skill   | `review-pr`       | The aspect-based PR-review orchestration contract — aspect→agent map, sequential/parallel/exhaustive modes, aggregation and the canonical Critical/Important/Suggestion → P0/P1/P2 severity mapping |
| skill   | `runbook`         | At the end of Phase 5 (gate green, before publishing) synthesizes and commits one `docs/spec-loop/<run-id>/runbook.md` from the run's durable artifacts — a self-contained Executive Readout + What Was Built, Business Logic, Gaps, requirement traceability, decisions summary, integration-gate result, and how-to-verify — and returns the Executive Readout as the run's final terminal output |

### Process skill library

The loop's development-process discipline ships natively (ported and adapted from
[`superpowers`](https://github.com/obra/superpowers) v6.1.1, MIT). These skills are
also usable interactively, outside a run:

> **Deliberate divergence from superpowers:** the source plugin auto-injects its
> skill router into every session via a `SessionStart` hook. spec-loop registers
> no `SessionStart` hook by design — the framework stays dormant until relevant,
> and the `spec-loop:using-spec-loop` router loads on demand via its description.
> This keeps the plugin non-intrusive in repos where you aren't running the loop,
> and avoids double-injection if superpowers is installed alongside. If you want
> always-on skill-check enforcement, invoke `spec-loop:using-spec-loop` explicitly
> at session start or add your own `SessionStart` hook that injects it.

| Type  | Name | Role |
|-------|------|------|
| skill | `using-spec-loop` | Gateway/router — find and invoke the right skill before any response or action |
| skill | `brainstorming` | Design exploration before any creative work — requirements, approaches, an approved spec (`docs/spec-loop/specs/`); optional zero-dep visual-companion web server |
| skill | `writing-plans` | Turn a spec into a bite-sized, TDD-stepped implementation plan (`docs/spec-loop/plans/`) with the executor header |
| skill | `subagent-driven-development` | Execute a plan task-by-task via fresh `sdd-implementer`/`sdd-task-reviewer` dispatches, review packages, and a durable progress ledger (`.spec-loop/sdd/`) |
| skill | `executing-plans` | Inline, sequential plan execution — the sanctioned fallback when subagent dispatch is unavailable |
| skill | `test-driven-development` | The Iron Law: no production code without a failing test first; red-green-refactor with mandatory verify gates |
| skill | `systematic-debugging` | No fixes without root-cause investigation — four gated phases plus escalation after repeated failed fixes |
| skill | `verification-before-completion` | No completion claims without fresh verification evidence — the loop's one never-overridden gate |
| skill | `code-review-discipline` | Both directions of review behavior: requesting (dispatch `code-reviewer` with crafted context) and receiving (verify-then-apply, no performative agreement) |
| skill | `finishing-a-development-branch` | Structured end-of-branch options (merge/PR/keep/discard) with safe worktree cleanup |
| skill | `using-git-worktrees` | Isolated workspaces: native-tool preference, `.worktrees/` fallback with gitignore safety, clean-baseline verification |
| skill | `dispatching-parallel-agents` | Fan out 2+ genuinely independent tasks to isolated-context agents in one response |
| skill | `writing-skills` | Meta-skill: author/test skills with TDD discipline, trigger-first descriptions, and this repo's CI contract |
| agent | `sdd-implementer` | Implements exactly ONE plan task with TDD, commits, self-reviews, reports to a file (dispatched by subagent-driven-development) |
| agent | `sdd-task-reviewer` | Reviews ONE implemented task against its brief — spec compliance + code quality, "do not trust the report" (dispatched by subagent-driven-development) |
| agent | `code-reviewer` | Whole-branch/diff reviewer against plan or requirements — used ad-hoc via code-review-discipline and as SDD's final review gate |

### PR-review library

The aspect-based PR review the loop runs at slice Step 3, the Phase 5 integration
gate, and peer-review corroboration ships natively (ported and adapted from
Anthropic's `pr-review-toolkit`, claude-plugins-official). Orchestrated by the
`review-pr` skill / `/spec-loop:review-pr` command listed above:

| Type  | Name | Role |
|-------|------|------|
| agent | `guideline-reviewer` | Project-guideline compliance + bug detection with confidence-scored findings (reports only ≥80/100) — the `code` aspect, runs on every review (the ported toolkit `code-reviewer`, renamed to avoid clashing with the plan-alignment `code-reviewer` above) |
| agent | `pr-test-analyzer` | Behavioral test-coverage quality of the diff, gaps rated 1–10 by criticality — the `tests` aspect |
| agent | `comment-analyzer` | Comment accuracy/completeness/rot analysis, advisory-only — the `comments` aspect |
| agent | `silent-failure-hunter` | Error-handling audit: silent failures, catch-block specificity, fallback justification (CRITICAL/HIGH/MEDIUM) — the `errors` aspect |
| agent | `type-design-analyzer` | Type invariant/encapsulation analysis on four 1–10 axes — the `types` aspect |
| agent | `code-simplifier` | Behavior-preserving clarity/maintainability polish; the only review agent that edits code — the explicit-only, non-blocking `simplify` aspect |

## Notes & limitations

- **Clean dedicated worktrees:** each worker's first action is to create a clean,
  dedicated worktree under `.worktrees/spec-loop/<run-id>/<slice-id>` (branch
  `spec-loop/<run-id>/<slice-id>`), branched from the current tip of the
  integration base, with a verified clean baseline. These per-slice branches are an
  **ephemeral isolation detail, not deliverables**: the controller merges each into
  the singular integration branch and deletes it (per-slice branches/PRs survive only
  in `--per-slice-pr` mode). Stale worktrees from aborted runs are removed and
  recreated; a worktree is reused only when resuming a paused slice that has committed
  progress. `.worktrees/` must be gitignored (the using-git-worktrees skill handles
  this).
- **Agent nesting / background rule:** only the top-level session can run agents
  in the background. The controller backgrounds the slice workers; each slice
  worker is a subagent and therefore dispatches its own implementer/reviewer
  agents **synchronously** (`run_in_background: false`) — required by the platform
  and correct for subagent-driven-development, which is sequential. If `/spec-loop`
  itself is invoked from inside another agent, the controller falls back to running
  slices synchronously (no cross-slice parallelism).
- If nested subagent dispatch is unsupported entirely in your environment, the
  slice worker falls back to inline `spec-loop:executing-plans`.
- Background agents cannot prompt you directly; that's why escalations are
  file-based and surfaced by the controller at wave boundaries.
- This loop intentionally overrides the human approval gates in `brainstorming`
  and `subagent-driven-development`. `verification-before-completion` is kept as a
  hard, no-human gate.
- **Dynamic decomposition is depth-capped:** a slice may split at most twice
  (`MAX_SPLIT_DEPTH = 2`). A slice still oversized at the cap stops splitting and
  falls back to the normal escalation path — splits never become a new way to
  interrupt you.
- **Integration gate runs on the integration branch,** then prompts you to publish it
  (push as a feature branch or merge onto `main`). In `--per-slice-pr` mode there is
  no single merged branch, so it verifies on a throwaway integration branch and
  reports, leaving the PRs for you to merge.

## License

[MIT](../../LICENSE) © Zach McMurry
