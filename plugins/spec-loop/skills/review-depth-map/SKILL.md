---
name: review-depth-map
description: Use when a spec-loop slice has a plan and needs to decide how far to take its PR review — maps the plan's risk tier and surface area to review-pr aspects, execution mode, the severity bar that counts as blocking, and the Iron Council composition for the plan review
---

# Review Depth Map — let the plan decide how far the review goes

## Overview

A slice's plan declares what it touches (files, subsystems) and a **risk tier**. This skill turns that into a concrete `review-pr` invocation so the review is proportionate: light for low-risk changes, exhaustive for high-risk ones. This is how "the plan determines how far to take the PR review." The same tier also scales the **Iron Council composition** for the pre-execution plan review (Step 1.5), so a docs slice doesn't pay for a five-agent deliberation.

The risk tier is written into the plan's metadata header by the slice worker during planning. If a slice's diff touches a higher-risk area than the plan predicted, **escalate the tier to match the diff** (never review below what the code warrants).

## Risk tier → review scope

The tier also scales model economics: agent frontmatter `model:` pins are the cost
defaults, and this file is the single home of the tier-scaled overrides that lift
or lower them.

### Tier 1 — Low risk
Docs, config, comments, isolated pure functions, no behavioral surface.
- Run: `spec-loop:review-pr code`
- Mode: parallel (default — moot at Tier 1, which dispatches a single aspect)
- Model: dispatch `guideline-reviewer` with a per-call `model: sonnet` override —
  no behavioral surface, and the Tier-1 bar is P0-only.
- Blocking bar: **P0 blocks.** P1/P2 logged, not blocking.
- Council: **reduced** — `iron-council-pragmatist` + `iron-council-guardian`.

### Tier 2 — Standard (default)
Normal feature logic, internal modules, no auth/data/contract surface.
- Run: `spec-loop:review-pr` (default — auto-selects aspects from the diff: adds test/comment/error/type analyzers when those files change)
- Mode: parallel (default)
- Blocking bar: **P0 and P1 block.** P2 logged.
- Council: **full five.**

### Tier 3 — High risk
Authentication/authorization, persistence/migrations, error-handling paths, public APIs, exported types, security-sensitive or external-integration code.
- Run: `spec-loop:review-pr exhaustive` — all review aspects forced regardless of file types (always includes `spec-loop:silent-failure-hunter`, `spec-loop:type-design-analyzer`, and `spec-loop:pr-test-analyzer`), agents dispatched in parallel, findings reported on the P0–P3 scale (see `spec-loop:review-pr` for the exhaustive-mode contract).
- Mode: parallel
- Blocking bar: **P0 and P1 block.** P2/P3 logged.
- Council: **full five at high effort** (see below).

## Risk tier → council composition (pre-execution plan review, slice Step 1.5)

The tier also decides which Iron Council members the slice worker convenes on its
plan. The guardian sits on **every** council so the lone-SAFETY veto never loses
coverage; aggregation already handles a reduced council of N (strictly more than
half of N objects → OBJECT).

- **Tier 1** → `pragmatist,guardian` — scope and risk are the only questions a
  no-behavioral-surface slice can meaningfully fail.
- **Tier 2** → `skeptic,architect,pragmatist,guardian,historian` (full five).
- **Tier 3** → full five **at high effort**: give every member an explicit
  deep-review mandate in its dispatch prompt (read every file the plan names, trace
  the risky paths end-to-end, verify test coverage of them), and where the dispatch
  surface supports a per-call `model` override, lift **every** sonnet-pinned agent
  convened for the slice — council members AND review aspect agents — up to the
  session model (Opus 5-class) for this slice: the pin is a cost default, not a
  capability ceiling. The one exception is `review-finding-verifier`, which stays
  sonnet at every tier — its CONFIRMED-by-default calibration makes model weakness
  fail safe.

This applies at **pre-execution only** — intake (controller, Phase 0) always
convenes the full five, since no tier exists before decomposition and
premise-challenges matter most on the raw request.

Record the chosen composition in the plan header's `council="..."` field and pass
the same list as `--expect <composition>` to `council_contracts.py aggregate`, so a
member that never reported fails closed instead of vanishing from the majority
math. If the tier escalates to match the diff, only a *future* convening escalates
with it — a council that already ran is not re-convened.

## Code-simplifier polish pass (all tiers)

Regardless of tier, every slice runs `code-simplifier` as a final polish pass —
`spec-loop:review-pr simplify` against the slice diff — **after** the main review
and auto-fix loop have converged (findings below the blocking bar, no open
escalation). It is never part of the default `review-pr` run or `all`, so it must be
requested explicitly via the `simplify` aspect.

The pass is **non-blocking**: record a one-line note in `decisions-log.md`; never
block the slice on it. Behavioral safety comes from the slice's Step 5 verification.

## Quality gate (all tiers, blocking)

After the simplify pass and before verification, every slice runs the `quality-gate`
skill (slice Step 4c). Its bar is that skill's configured thresholds — tier-independent,
**blocking**, and entirely separate from the review severity bar above.

## Tier assignment heuristics (use when writing the plan header)

- **Tier 3** if the slice touches any of: auth/permissions, secrets/credentials, database schema or migrations, money/billing, PII/security, public/exported API or types, error-handling or retry/fallback logic, concurrency.
- **Tier 1** only if the slice is provably free of behavioral surface (docs/config/pure-helper with tests).
- **Tier 2** for everything else.

A `--risk-floor` argument on `/spec-loop` raises the minimum tier for the whole run (e.g. `--risk-floor 2` forbids Tier 1 reviews).

## Blocking bar → auto-fix loop

The bar decides what the slice acts on; `spec-loop:spec-loop-slice` is the executor
and owns the mechanics (adversarial verification at Step 3b, the fix loop at Step 4).

- Findings **at/above the bar** are adversarially verified, then the CONFIRMED ones
  enter the bounded auto-fix loop. Survivors after the budget → `escalation-gate`
  (trigger: review-block) and `NEEDS_DECISION`.
- Findings **below the bar** → record in `decisions-log.md`, do not block; they are
  not verified, since they cost nothing.

## Plan metadata header (written by the slice worker)

Prepend to each slice plan, just under the title:
```
<!-- spec-loop: risk-tier=<1|2|3> council="<member,member,...>" review="<exact review-pr command>" simplify="spec-loop:review-pr simplify" blocking-bar="<P0 | P0,P1>" surface="<files/subsystems touched>" -->
```
`council` is the tier-mapped composition above (e.g. `council="pragmatist,guardian"`
for Tier 1) — the slice worker dispatches exactly those members at Step 1.5.
