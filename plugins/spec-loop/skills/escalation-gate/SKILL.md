---
name: escalation-gate
description: Use when running the spec-loop autonomously and about to stop, ask the human a question, request approval, or pause on a review BLOCK — decides whether to proceed-and-log or surface to the human, and how to record the decision
---

# Escalation Gate — the spec-loop autonomy contract

## Overview

This is the single decision procedure every spec-loop layer (controller, slice worker, and any skill they invoke) MUST run **before stopping or asking the human anything**. Its job is to keep the loop autonomous by default and interrupt the human **only** when a decision genuinely cannot be made.

This contract **intentionally overrides** the built-in human checkpoints of the chained skills:
- `superpowers:brainstorming`'s "ask one question at a time + require design approval" → replaced by this gate.
- `superpowers:subagent-driven-development`'s consent-before-`main` and BLOCKED→human escalation → satisfied by always working in a worktree and routing through this gate.
- `pr-review-toolkit:review-pr`'s BLOCK MERGE surfacing → routed through this gate after the auto-fix loop.

`superpowers:verification-before-completion` is **NOT** overridden — it remains a hard, no-human gate (evidence before any completion claim).

## The decision procedure

For any point where you would otherwise stop or ask, classify it:

### PROCEED + log (the default)
Take the action yourself and append a one-line entry to `decisions-log.md` when ALL of these hold:
- The choice is determinable from the spec, the codebase, existing conventions, or an unambiguous best practice, **OR**
- The assumption is trivial, cosmetic, and cheaply reversible (naming, formatting, internal helper placement, test fixture details), **AND**
- Getting it wrong does not silently change observable behavior, public contracts, persisted data, or security posture.

Log format (one line each, append-only):
```
[<slice-id>] DECISION: <what was decided> — RATIONALE: <evidence/convention> — REVERSIBILITY: <trivial|moderate>
```

### SURFACE to human (only these four triggers)
Do NOT act. Write an escalation entry (format below) and return control:

1. **Genuine ambiguity** — there are ≥2 valid interpretations that materially change scope or behavior, and the codebase/spec cannot resolve which is intended.
2. **Material assumption** — you would be assuming something non-trivial that affects behavior, scope, public contracts, persisted data, security, or external integrations. (Per the user's global CLAUDE.md, material assumptions must be stated and confirmed — not silently made.)
3. **Unfixable review BLOCK** — `review-pr` still returns BLOCK MERGE after the auto-fix loop has exhausted its attempt budget.
4. **Council objection** — the `iron-council` deems a request or plan **unworthy**: a majority of members OBJECT, or any single member raises a `SAFETY` OBJECT (irreversible data loss, security hole, broken public contract). Lesser council concerns (ENDORSE_WITH_CONCERNS, minority non-safety objections) are folded in and logged — they do **not** surface.

When uncertain whether something is "material": if a reasonable reviewer could reject the slice over it, it is material → surface it.

### Not triggers (autonomous by design)
These look like stopping points but are **not** surfaced — they are handled by the loop itself, keeping the bar at exactly the four triggers above:
- **Slice split (dynamic decomposition).** A slice that turns out to be two-or-more independently shippable changes returns `SPLIT` with a sub-decomposition the controller grafts into the DAG (slice Step 1.6). Autonomous, logged to `decisions-log.md`, no human contact. Only an oversized slice already at the split-depth cap falls back to a trigger above (material assumption / council objection).
- **Integration remediation.** When the per-wave check or the Phase 5 integration gate finds a cross-slice failure, the controller opens a remediation slice and fixes it through the normal slice loop. The human is reached only if that remediation slice itself exhausts its bounded auto-fix loop — i.e. via trigger 3 (unfixable review BLOCK), unchanged.

## Batching rule (critical for non-blocking operation)

**Never interrupt mid-wave, once per item.** Background slice workers cannot prompt the human directly. So:

1. Append each escalation to `docs/spec-loop/<run-id>/escalations.md`.
2. The slice worker returns status `NEEDS_DECISION` (pausing only that slice) and keeps independent slices running.
3. The **controller** (running in the main session) collects all open escalations at the **wave boundary** and surfaces them as ONE batched `AskUserQuestion` round, then injects answers and re-dispatches the paused slices.

## Escalation entry format

Append to `escalations.md`:
```
## [<slice-id>] <short title>   (status: OPEN)
- Trigger: <ambiguity | material-assumption | review-block | council-objection>
- Context: <what the loop was doing and why it cannot decide>
- The decision: <the precise question>
- Options:
  1. <option A> — (RECOMMENDED DEFAULT) <why>
  2. <option B> — <tradeoff>
  3. <option C> — <tradeoff>
- If unanswered: pause this slice; continue all independent slices.
- Answer: <filled in by controller after human responds>
```

Always include a **recommended default** — the loop should make the human's decision as cheap as possible (confirm vs. redirect), consistent with the user's preference for conservative/balanced/innovative options where relevant.

## Red flags (you are violating the contract)
- Asking the human something resolvable from the codebase or a clear convention.
- Surfacing escalations one at a time instead of batching at the wave boundary.
- Proceeding silently on a material assumption (must log AND surface).
- Looping the auto-fix step forever instead of surfacing after the attempt budget.
- Skipping `verification-before-completion` because "the gate said proceed" — that gate is separate and never skipped.
