---
name: escalation-gate
description: Use when running the spec-loop autonomously and about to stop, ask the human a question, request approval, or pause on a review BLOCK — decides whether to proceed-and-log or surface to the human, and how to record the decision
---

# Escalation Gate — the spec-loop autonomy contract

## Overview

This is the single decision procedure every spec-loop layer (controller, slice worker, and any skill they invoke) runs **before stopping or asking the human anything**. Its job is to keep the loop autonomous by default and interrupt the human **only** when a decision genuinely cannot be made.

This contract **intentionally overrides** the built-in human checkpoints of the chained skills:
- `spec-loop:brainstorming`'s "ask one question at a time + require design approval" → replaced by this gate.
- `spec-loop:subagent-driven-development`'s consent-before-`main` and BLOCKED→human escalation → satisfied by always working in a worktree and routing through this gate.
- A `spec-loop:review-pr` finding at/above the slice's blocking bar (per `spec-loop:review-depth-map`) → routed through this gate after the auto-fix loop.

`spec-loop:verification-before-completion` is **not** overridden — it remains a hard, no-human gate (evidence before any completion claim).

## The decision procedure

For any point where you would otherwise stop or ask, classify it:

### PROCEED + log (the default)
Take the action yourself and append a one-line entry to `decisions-log.md` when all of these hold:
- The choice is determinable from the spec, the codebase, existing conventions, or an unambiguous best practice, **OR**
- The assumption is trivial, cosmetic, and cheaply reversible (naming, formatting, internal helper placement, test fixture details), **AND**
- Getting it wrong does not silently change observable behavior, public contracts, persisted data, or security posture.

Log format (one line each, append-only):
```
[<slice-id>] DECISION: <what was decided> — RATIONALE: <evidence/convention> — REVERSIBILITY: <trivial|moderate|high|n/a> — AT: <ISO-8601 UTC, e.g. 2026-07-14T10:30:00Z>
```
The trailing ` — AT: <timestamp>` token feeds `run_metrics.py`; keep it last on the line
and never move the leading `[<slice-id>]` bracket, which the dashboard and metrics
parsers key on. Get the timestamp from `date -u +%Y-%m-%dT%H:%M:%SZ`; if unavailable,
omit the token rather than inventing one.

### SURFACE to human (only these five triggers)
Do not act. Write an escalation entry (format below) and return control:

1. **Genuine ambiguity** — there are ≥2 valid interpretations that materially change scope or behavior, and the codebase/spec cannot resolve which is intended.
2. **Material assumption** — you would be assuming something non-trivial that affects behavior, scope, public contracts, persisted data, security, or external integrations. (Per the user's global CLAUDE.md, material assumptions must be stated and confirmed — not silently made.)
3. **Unfixable review BLOCK** — CONFIRMED `review-pr` findings at/above the slice's blocking bar (set by `spec-loop:review-depth-map`) survive after the auto-fix loop has exhausted its attempt budget.
4. **Council objection** — the `iron-council` deems a request or plan **unworthy**: a majority of members OBJECT, or any single member raises a `SAFETY` OBJECT (irreversible data loss, security hole, broken public contract). Lesser council concerns (ENDORSE_WITH_CONCERNS, minority non-safety objections) are folded in and logged — they do **not** surface.
5. **Unfixable quality-gate block** — the `quality-gate` skill's metrics still exceed the configured thresholds after its bounded, behavior-preserving refactor loop has exhausted its attempt budget (trigger: `quality-gate-block`). Thresholds are never weakened to avoid this.

When uncertain whether something is "material": if a reasonable reviewer could reject the slice over it, it is material → surface it.

### Precedent check (before writing any SURFACE escalation)

Prior runs' human answers are settled decisions — check them before asking a question
the human may have already answered. Search prior runs (excluding this one), e.g.
`grep -l "status: ANSWERED" docs/spec-loop/*/escalations.md` plus the Decisions Summary
of any `docs/spec-loop/*/runbook.md`:

- **A prior human answer squarely resolves this decision** (same question in
  substance, answer still applicable to this codebase state) → do not surface.
  PROCEED + log, citing the precedent:
  ```
  [<slice-id>] DECISION: <what was decided> — RATIONALE: precedent — run <run-id> escalation "<title>" answered: <one-line summary of the human's answer> — REVERSIBILITY: <trivial|moderate|high|n/a> — AT: <ISO-8601 UTC>
  ```
  This is what keeps run N's adjudication from becoming run N+1's escalation.
- **A prior answer is related but not squarely on point** → still surface, but
  quote the prior answer in the escalation's RECOMMENDED DEFAULT option so the
  human confirms rather than re-derives.
- **Guard:** precedent only resolves what a human has *already* adjudicated. It never
  downgrades a new material assumption, a SAFETY objection, or a decision whose context
  has materially changed. When in doubt, surface with the precedent as the default.

### Not triggers (autonomous by design)
Two things that look like stopping points but are handled by the loop itself, keeping the bar at exactly the five triggers above:
- **Slice split.** A slice that turns out to be two-or-more independently shippable changes returns `SPLIT` for the controller to graft into the DAG — logged, no human contact. Only an oversized slice already at the split-depth cap falls back to a trigger above.
- **Integration remediation.** A cross-slice failure opens a remediation slice that runs the normal slice loop; the human is reached only if that slice exhausts its own auto-fix budget (trigger 3).

## Batching rule (critical for non-blocking operation)

**Never interrupt mid-wave, once per item.** Background slice workers cannot prompt the human directly. So:

1. Append each escalation to `docs/spec-loop/<run-id>/escalations.md`.
2. The slice worker returns status `NEEDS_DECISION` (pausing only that slice) and keeps independent slices running.
3. The **controller** (running in the main session) collects all open escalations at the **wave boundary** and surfaces them as one batched `AskUserQuestion` round, then injects answers and re-dispatches the paused slices.

## Escalation entry format

Append to `escalations.md`:
```
## [<slice-id>] <short title>   (status: OPEN)
- Trigger: <ambiguity | material-assumption | review-block | council-objection | quality-gate-block>
- Opened: <ISO-8601 UTC, from date -u +%Y-%m-%dT%H:%M:%SZ>
- Context: <what the loop was doing and why it cannot decide>
- The decision: <the precise question>
- Options:
  1. <option A> — (RECOMMENDED DEFAULT) <why>
  2. <option B> — <tradeoff>
  3. <option C> — <tradeoff>
- If unanswered: pause this slice; continue all independent slices.
- Answer: <filled in by controller after human responds>
- Answered-at: <ISO-8601 UTC, written by the controller with the answer>
```

`Opened:`/`Answered-at:` feed `run_metrics.py`'s answer-latency metric. Both are optional
to the parsers, but new escalations should always carry `Opened:`.

Always include a **recommended default** — make the human's decision as cheap as possible
(confirm vs. redirect).

## Violations of the contract
- Asking the human something resolvable from the codebase, a convention, or a prior
  run's answered escalation (run the precedent check first).
- Proceeding silently on a material assumption — it must be logged *and* surfaced.
- Skipping `verification-before-completion` because this gate said proceed; that gate
  is separate and never skipped.
