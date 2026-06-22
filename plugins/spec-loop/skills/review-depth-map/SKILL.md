---
name: review-depth-map
description: Use when a spec-loop slice has a plan and needs to decide how far to take its PR review — maps the plan's risk tier and surface area to review-pr aspects, execution mode, and the severity bar that counts as blocking
---

# Review Depth Map — let the plan decide how far the review goes

## Overview

A slice's plan declares what it touches (files, subsystems) and a **risk tier**. This skill turns that into a concrete `review-pr` invocation so the review is proportionate: light for low-risk changes, exhaustive for high-risk ones. This is how "the plan determines how far to take the PR review."

The risk tier is written into the plan's metadata header by the slice worker during planning. If a slice's diff touches a higher-risk area than the plan predicted, **escalate the tier to match the diff** (never review below what the code warrants).

## Risk tier → review scope

### Tier 1 — Low risk
Docs, config, comments, isolated pure functions, no behavioral surface.
- Run: `pr-review-toolkit:review-pr code`
- Mode: sequential
- Blocking bar: **P0 blocks.** P1/P2 logged, not blocking.

### Tier 2 — Standard (default)
Normal feature logic, internal modules, no auth/data/contract surface.
- Run: `pr-review-toolkit:review-pr` (default — auto-selects aspects from the diff: adds test/comment/error/type analyzers when those files change)
- Mode: sequential (or `all parallel` if the diff is large)
- Blocking bar: **P0 and P1 block.** P2 logged.

### Tier 3 — High risk
Authentication/authorization, persistence/migrations, error-handling paths, public APIs, exported types, security-sensitive or external-integration code.
- Run: ALL aspects, forced regardless of file types — i.e. `pr-review-toolkit:review-pr all parallel`, which always includes `silent-failure-hunter`, `type-design-analyzer`, and `pr-test-analyzer`.
- **Alternative:** invoke the user's own `/exhaustive-pr-review:exhaustive-pr all parallel` for zero-missed-findings depth (reports P0–P3, all agents always run).
- Mode: parallel
- Blocking bar: **P0 and P1 block.** P2 logged.

## Code-simplifier polish pass (all tiers)

Regardless of tier, every slice runs `code-simplifier` as a final polish pass —
`pr-review-toolkit:review-pr simplify` against the slice diff — **after** the main
review and auto-fix loop have converged (findings below the blocking bar, no open
escalation). This generalizes what Tier 3 previously did inline: `code-simplifier`
is not part of the default `review-pr` run or `all`, so it must be requested
explicitly via the `simplify` aspect.

The pass applies clarity/maintainability simplifications (and implements its own
fixes). It is **non-blocking**: record a one-line note in `decisions-log.md`; never
block the slice on it. Behavioral safety comes from Step 5 verification — the full
test/build run must still pass after simplification, which catches any regression a
simplification might introduce.

## Tier assignment heuristics (use when writing the plan header)

Assign Tier 3 if the slice touches ANY of: auth/permissions, secrets/credentials, database schema or migrations, money/billing, PII/security, public/exported API or types, error-handling or retry/fallback logic, concurrency.

Assign Tier 1 only if the slice is provably free of behavioral surface (docs/config/pure-helper with tests).

Everything else is Tier 2.

A `--risk-floor` argument on `/spec-loop` raises the minimum tier for the whole run (e.g. `--risk-floor 2` forbids Tier 1 reviews).

## Blocking bar → auto-fix loop

After review, the slice worker compares findings against the tier's blocking bar:
- Findings at/above the bar (BLOCK / FIX) → enter the auto-fix loop (apply fixes via `superpowers:receiving-code-review` discipline, re-review). Default budget: 2 attempts.
- After the budget is exhausted and findings remain at/above the bar → consult `escalation-gate` (trigger: review-block) and return `NEEDS_DECISION`.
- Findings below the bar → record in `decisions-log.md`, do not block.

## Plan metadata header (written by the slice worker)

Prepend to each slice plan, just under the title:
```
<!-- spec-loop: risk-tier=<1|2|3> review="<exact review-pr command>" simplify="pr-review-toolkit:review-pr simplify" blocking-bar="<P0 | P0,P1>" surface="<files/subsystems touched>" -->
```
