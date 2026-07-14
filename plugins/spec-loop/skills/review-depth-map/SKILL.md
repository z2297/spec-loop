---
name: review-depth-map
description: Use when a spec-loop slice has a plan and needs to decide how far to take its PR review — maps the plan's risk tier and surface area to review-pr aspects, execution mode, the severity bar that counts as blocking, and the Iron Council composition for the plan review
---

# Review Depth Map — let the plan decide how far the review goes

## Overview

A slice's plan declares what it touches (files, subsystems) and a **risk tier**. This skill turns that into a concrete `review-pr` invocation so the review is proportionate: light for low-risk changes, exhaustive for high-risk ones. This is how "the plan determines how far to take the PR review." The same tier also scales the **Iron Council composition** for the pre-execution plan review (Step 1.5), so a docs slice doesn't pay for a five-agent deliberation.

The risk tier is written into the plan's metadata header by the slice worker during planning. If a slice's diff touches a higher-risk area than the plan predicted, **escalate the tier to match the diff** (never review below what the code warrants).

## Risk tier → review scope

### Tier 1 — Low risk
Docs, config, comments, isolated pure functions, no behavioral surface.
- Run: `spec-loop:review-pr code`
- Mode: sequential
- Blocking bar: **P0 blocks.** P1/P2 logged, not blocking.
- Council: **reduced** — `iron-council-pragmatist` + `iron-council-guardian`.

### Tier 2 — Standard (default)
Normal feature logic, internal modules, no auth/data/contract surface.
- Run: `spec-loop:review-pr` (default — auto-selects aspects from the diff: adds test/comment/error/type analyzers when those files change)
- Mode: sequential (or `all parallel` if the diff is large)
- Blocking bar: **P0 and P1 block.** P2 logged.
- Council: **full five.**

### Tier 3 — High risk
Authentication/authorization, persistence/migrations, error-handling paths, public APIs, exported types, security-sensitive or external-integration code.
- Run: `spec-loop:review-pr exhaustive` — ALL review aspects forced regardless of file types (always includes `spec-loop:silent-failure-hunter`, `spec-loop:type-design-analyzer`, and `spec-loop:pr-test-analyzer`), agents dispatched in parallel, findings reported on the P0–P3 scale (see `spec-loop:review-pr` for the exhaustive-mode contract).
- Mode: parallel
- Blocking bar: **P0 and P1 block.** P2/P3 logged.
- Council: **full five at high effort** (see below).

## Risk tier → council composition (pre-execution plan review, slice Step 1.5)

The tier also decides which Iron Council members the slice worker convenes on its
plan. The guardian sits on **every** council so the lone-SAFETY veto never loses
coverage; the aggregation rules already handle a reduced council of N (strictly
more than half of N objects → OBJECT).

- **Tier 1** → `pragmatist,guardian` — scope and risk are the only questions a
  no-behavioral-surface slice can meaningfully fail; ~3 fewer dispatches per slice.
- **Tier 2** → `skeptic,architect,pragmatist,guardian,historian` (full five).
- **Tier 3** → full five **at high effort**: give every member an explicit
  deep-review mandate in its dispatch prompt (read every file the plan names, trace
  the risky paths end-to-end, verify test coverage of them), and where the
  dispatching surface supports a per-call `model` override, lift the
  `model: sonnet` members to the session model.

This applies at **pre-execution only**. Intake (controller, Phase 0) always
convenes the full five — no tier exists before decomposition, and
premise-challenges (the skeptic's mandate) matter most on the raw request.

Record the chosen composition in the plan header's `council="..."` field, and pin
it when aggregating: pass `--expect <composition>` to `council_contracts.py
aggregate` so a member that never reported fails closed instead of vanishing from
the majority math. If the tier escalates to match the diff (rule above), the
council composition of a *future* convening escalates with it — a council that
already ran is not re-convened.

## Code-simplifier polish pass (all tiers)

Regardless of tier, every slice runs `code-simplifier` as a final polish pass —
`spec-loop:review-pr simplify` against the slice diff — **after** the main
review and auto-fix loop have converged (findings below the blocking bar, no open
escalation). This generalizes what Tier 3 previously did inline: `code-simplifier`
is not part of the default `review-pr` run or `all`, so it must be requested
explicitly via the `simplify` aspect.

The pass applies clarity/maintainability simplifications (and implements its own
fixes). It is **non-blocking**: record a one-line note in `decisions-log.md`; never
block the slice on it. Behavioral safety comes from Step 5 verification — the full
test/build run must still pass after simplification, which catches any regression a
simplification might introduce.

## Quality gate (all tiers, blocking)

After the simplify pass and before verification, every slice runs the `quality-gate`
skill (slice Step 4c). Its bar is the **configured thresholds** in
`~/.claude/spec-loop/quality-gate.json` (cyclomatic/cognitive complexity, method
length, etc.) — **separate from and independent of** the review severity bar above.
It is tier-independent and **blocking**: failures drive a bounded, behavior-preserving
refactor loop, then escalate if still unmet.

## Tier assignment heuristics (use when writing the plan header)

Assign Tier 3 if the slice touches ANY of: auth/permissions, secrets/credentials, database schema or migrations, money/billing, PII/security, public/exported API or types, error-handling or retry/fallback logic, concurrency.

Assign Tier 1 only if the slice is provably free of behavioral surface (docs/config/pure-helper with tests).

Everything else is Tier 2.

A `--risk-floor` argument on `/spec-loop` raises the minimum tier for the whole run (e.g. `--risk-floor 2` forbids Tier 1 reviews).

## Blocking bar → auto-fix loop

After review, the slice worker compares findings against the tier's blocking bar:
- Findings at/above the bar are **adversarially verified first** (slice Step 3b): one `review-finding-verifier` per finding (cap 6/round, highest severity first) tries to REFUTE it against the actual code. REFUTED findings are logged to `decisions-log.md` with their file:line evidence and never enter the fix loop; CONFIRMED findings (including any with an unreadable verdict — fail closed) proceed. Re-reviews verify only new findings.
- CONFIRMED findings at/above the bar (BLOCK / FIX) → enter the auto-fix loop (apply fixes via `spec-loop:code-review-discipline` (Part 2 — receiving feedback) discipline, re-review). Default budget: 2 attempts.
- After the budget is exhausted and CONFIRMED findings remain at/above the bar → consult `escalation-gate` (trigger: review-block) and return `NEEDS_DECISION`.
- Findings below the bar → record in `decisions-log.md`, do not block (they are not verified — they cost nothing).

## Plan metadata header (written by the slice worker)

Prepend to each slice plan, just under the title:
```
<!-- spec-loop: risk-tier=<1|2|3> council="<member,member,...>" review="<exact review-pr command>" simplify="spec-loop:review-pr simplify" blocking-bar="<P0 | P0,P1>" surface="<files/subsystems touched>" -->
```
`council` is the tier-mapped composition from the section above (e.g.
`council="pragmatist,guardian"` for Tier 1) — the slice worker dispatches exactly
these members at Step 1.5 and passes the same list to `aggregate --expect`.
