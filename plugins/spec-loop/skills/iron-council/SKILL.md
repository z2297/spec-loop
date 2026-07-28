---
name: iron-council
description: Use when the spec-loop controller has a fresh user request to vet, or a slice worker has written a plan and is about to execute it — convenes the Iron Council (full five at intake; tier-scaled composition at pre-execution) to challenge the request/plan, surface discrepancies, and return opinionated verdicts, then aggregates them into ENDORSE / ENDORSE_WITH_CONCERNS / OBJECT and routes an OBJECT through escalation-gate to the human.
---

# The Iron Council — challenge the request, vet every plan

## Overview

The Iron Council is spec-loop's adversarial review body: it challenges the work
before effort is spent on it, catching what an eager autonomous loop is most
prone to — building the wrong thing, the wrong way, more than was asked,
breaking something, or ignoring how the codebase already does it.

It convenes at exactly two moments: **intake** (the controller, on the raw user
request, before decomposition) and **pre-execution** (each slice worker, on its
written plan, before any code). Each member is its own read-only, advisory agent
with its own mandate; the convening layer aggregates their verdicts. Intake
always convenes the full five; at pre-execution `review-depth-map` scales the
composition by risk tier (Tier 1 → `pragmatist,guardian`; Tier 2 → full five;
Tier 3 → full five with a high-effort mandate). The guardian is on **every**
council, so the lone-SAFETY veto never loses coverage. A council OBJECT routes
through `escalation-gate` (`council-objection`) — the council never prompts the
human itself.

## The five members

| Agent | Mandate — what it challenges |
|-------|------------------------------|
| `iron-council-skeptic`    | The **premise**. Right problem? Unstated requirements, hidden assumptions, ambiguity, XY-problems, undefined success criteria. |
| `iron-council-architect`  | The **design**. Soundness, coupling, layering, abstraction fit, error/edge handling, whether the plan's steps achieve the goal. |
| `iron-council-pragmatist` | The **scope**. Over-engineering, YAGNI, gold-plating, a simpler path, right-sizing, effort vs. value. |
| `iron-council-guardian`   | The **risk**. Security, secrets, PII, data integrity, migrations, breaking public contracts, irreversibility, concurrency, test coverage of risky paths. |
| `iron-council-historian`  | **Consistency with the codebase**. Existing patterns, conventions, prior decisions, reuse-over-new. |

## Convening protocol

1. **Pick the composition** (above). Pre-execution reads it from the plan
   header's `council="..."` field.
2. **Assemble ONE shared context packet** and dispatch the convened members in a
   single message so they deliberate concurrently — the packet passed verbatim
   and identically at the top of every member's prompt (identical prefixes earn
   prompt-cache hits). It contains: the subject under review and its kind
   (verbatim request, or plan + slice object), the run's `conventions.md`
   (content if small, else its path), the `shared_constraints`, the run-state
   directory path, at pre-execution the files the plan names, and this skill's
   **member output contract** (below). The packet is a floor, not a ceiling —
   members explore the codebase read-only beyond it as their mandate needs.
   Subagent callers dispatch synchronously in one message — see
   `spec-loop:dispatching-parallel-agents` §Subagent nesting.
3. **Validate every reply mechanically — never hand-parse.** Pipe each member's
   full reply through
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/council_contracts.py" validate-member`
   (reply on stdin; prints the normalized verdict JSON on exit 0). Invalid →
   re-dispatch that member once, quoting the validator's errors. Still invalid →
   fail closed: synthesize
   `{"member": "<name>", "verdict": "OBJECT", "discrepancies": [], "feedback": [], "blocker": {"text": "invalid council output after re-dispatch", "safety": false}}`
   and log one line. An unreadable reply is never an ENDORSE.
4. **Aggregate** the normalized verdicts as one JSON array through
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/council_contracts.py" aggregate --expect <convened composition>`.
   `--expect` pins the composition: a missing, duplicate, or uninvited verdict is
   exit 2 — do not proceed without a verdict. Always pass `--expect`; an absent
   member must fail closed, not silently shrink the majority math. The rules
   below are the normative spec; the script is their mandatory executor.

## Member output contract

This is the single home of the verdict schema — the dispatch packet inlines it;
`council_contracts.py validate-member` is its mechanical executor. Every member
MUST end its reply with exactly one fenced ```json block in this shape (the LAST
fenced json block in the reply is the verdict of record):

```json
{
  "member": "<skeptic | architect | pragmatist | guardian | historian>",
  "verdict": "<ENDORSE | ENDORSE_WITH_CONCERNS | OBJECT>",
  "discrepancies": ["<each gap/contradiction between what was asked and what would actually be sound — [] if none>"],
  "feedback": ["<constructive, specific, opinionated guidance — name the file/step/decision>"],
  "blocker": {"text": "<only if verdict is OBJECT: the single concern that makes this unworthy, plus the recommended remedy>", "safety": false}
}
```

`blocker` is `null` unless the verdict is `OBJECT`; `"safety": true` only for
irreversible data loss, a security hole, or a broken public contract.

Verdicts: **ENDORSE** — sound as proposed. **ENDORSE_WITH_CONCERNS** — proceed,
but fold in the named improvements. **OBJECT** — unworthy as proposed; the named
blocker must be resolved first. Members are opinionated but constructive — every
objection carries a concrete remedy, and "ENDORSE" is only valid when they
genuinely found nothing.

## Aggregation — the council verdict

- **Council OBJECT (halt)** when a **majority** of the N convened members object
  (strictly more than half; both, on a 2-member council), **OR** any single
  member returns an OBJECT marked `SAFETY`. A lone safety objection halts.
- **Council ENDORSE_WITH_CONCERNS** when there is any minority non-safety OBJECT
  or any ENDORSE_WITH_CONCERNS below the majority threshold. Proceed, folding
  the concrete concerns into the decomposition (intake) or plan (pre-execution)
  and logging what was folded.
- **Council ENDORSE** when no member objects and none raised concerns.

## Routing the verdict

**ENDORSE** — one line to `decisions-log.md`, naming the composition:
`[<slice-id|intake>] COUNCIL: ENDORSE — <n>/<N>, no concerns.`

**ENDORSE_WITH_CONCERNS** — revise to absorb the concrete, cheap concerns, then
log and proceed (never halt):
`[<slice-id|intake>] COUNCIL: ENDORSE_WITH_CONCERNS — folded: <what changed> — DEFERRED: <concerns not acted on + why>.`
Real-but-out-of-scope concerns are logged as DEFERRED, not silently dropped.

**Split special case (pre-execution only).** A right-sizing finding that the
plan is two-or-more independently shippable changes — from the Pragmatist or
Architect, as concern or OBJECT — routes to **dynamic decomposition** (the slice
worker returns `SPLIT`), autonomously, never to the human. It short-circuits
only the size dimension: any other objection in the same round aggregates
normally, and a slice already at the split-depth cap routes its right-sizing
OBJECT to the human like any other. At intake, right-sizing concerns just fold
into the decomposition.

**OBJECT → lift to the human (never decided autonomously).** Run
`escalation-gate` with trigger `council-objection`. Intake: add the objection to
the up-front batched `AskUserQuestion` round and do not schedule slices until
resolved. Pre-execution: write the escalation to `escalations.md` and return
`NEEDS_DECISION`; do not execute an objected-to plan. Entry shape:

```
## [<slice-id|intake>] Iron Council objects: <short title>   (status: OPEN)
- Trigger: council-objection
- Council verdict: OBJECT (<n>/<N> object<, includes SAFETY blocker if any>; convened: <member,member,...>)
- Objecting members: <skeptic/guardian/...> — <one-line blocker each>
- The decision: <the precise question for the human>
- Options:
  1. <proceed as-is / override the council> — (RECOMMENDED DEFAULT only if the objection is weak)
  2. <revise per the council's remedy> — <what would change>
  3. <abandon / redirect this work> — <tradeoff>
- If unanswered: <intake: block the run> | <slice: pause this slice; continue independent slices>
- Answer: <filled in by controller after the human responds>
```

After the human answers, the controller injects the answer and re-dispatches;
the council is **not** re-convened on an answer the human has already
adjudicated.

## Fail-closed rules

- An invalid member reply, after one re-dispatch, is a synthesized non-SAFETY
  OBJECT — never an ENDORSE.
- A lone SAFETY OBJECT halts, regardless of the majority.
- Both convenings (intake and per-plan) are mandatory; tier scaling changes the
  composition, never whether the council convenes, and the guardian is always
  convened.
