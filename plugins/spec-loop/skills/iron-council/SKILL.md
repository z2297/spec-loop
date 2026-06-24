---
name: iron-council
description: Use when the spec-loop controller has a fresh user request to vet, or a slice worker has written a plan and is about to execute it — convenes the five-member Iron Council to challenge the request/plan, surface discrepancies, and return opinionated verdicts, then aggregates them into ENDORSE / ENDORSE_WITH_CONCERNS / OBJECT and routes an OBJECT through escalation-gate to the human.
---

# The Iron Council — challenge the request, vet every plan

## Overview

The Iron Council is spec-loop's adversarial review body. Its job is **not** to be
agreeable — it is to **challenge** the work before effort is spent on it. The
council exists to catch the failures that an eager, autonomous loop is most prone
to: building the wrong thing, building it the wrong way, building more than was
asked, breaking something on the way, or ignoring how the codebase already does it.

The council convenes at exactly two moments:

1. **Intake** — the **controller** convenes it on the **raw user request**, before
   decomposition. (Phase 0 of `/spec-loop`.)
2. **Pre-execution** — each **slice worker** convenes it on its **written plan**,
   after `writing-plans` and before any code is executed. (Slice Step 1.5.)

Each council member is its **own agent** with its **own mandate**. They are
**read-only and advisory** — they never edit code. They return structured verdicts;
the convening layer aggregates them and decides whether to proceed, fold in
concerns, or halt and lift the decision to the human.

This skill **composes with** `escalation-gate`: a council OBJECT is one of that
gate's surface triggers (`council-objection`). The council does not prompt the
human itself — it routes through the same batched-escalation machinery as
everything else, so background work is never blocked.

## The five members

| Agent | Mandate — what it challenges |
|-------|------------------------------|
| `iron-council-skeptic`    | The **premise**. Is this the right problem? Unstated requirements, hidden assumptions, ambiguity, XY-problems, success criteria that were never defined. |
| `iron-council-architect`  | The **design**. Soundness of the approach, coupling, layering, abstraction fit, error/edge handling, whether the plan's steps actually achieve the goal. |
| `iron-council-pragmatist` | The **scope**. Over-engineering, YAGNI, gold-plating, a simpler path, right-sizing of the slices, effort vs. value, whether anything here is unnecessary. |
| `iron-council-guardian`   | The **risk**. Security, secrets, PII, data integrity, migrations, breaking public contracts, irreversibility, concurrency, and test coverage of risky paths. |
| `iron-council-historian`  | **Consistency with the codebase**. Existing patterns, conventions, prior decisions, reuse-over-new — does this fit how the project already works, or reinvent it? |

## Convening protocol

1. **Dispatch all five members in a single message** so they deliberate
   concurrently. Pass each member:
   - The **subject** under review and its kind: either the verbatim user request
     (intake) or the full slice plan plus the slice object (pre-execution).
   - The relevant context (request file, plan file, run-state directory path).
   - This skill's **output contract** (below) so every member replies in the same
     shape.
   - **Nesting rule:** the **controller** is top-level and may dispatch the members
     however it likes, but an advisory gate that blocks the next step is cleanest
     run synchronously in one message. The **slice worker is a subagent** and MUST
     dispatch every member with `run_in_background: false` (the platform forbids
     subagents from backgrounding agents). A single message of synchronous Task
     calls still runs them concurrently.
2. Each member inspects the subject (and the codebase, read-only) and returns its
   verdict in the output contract shape.
3. The convening layer **aggregates** the five verdicts (rules below) into a single
   council verdict and acts on it.

## Member output contract

Every council member MUST end its reply with exactly this block:

```
COUNCIL MEMBER: <skeptic | architect | pragmatist | guardian | historian>
VERDICT: <ENDORSE | ENDORSE_WITH_CONCERNS | OBJECT>
DISCREPANCIES:
- <each gap/contradiction between what was asked and what would actually be sound — or "none">
FEEDBACK:
- <constructive, specific, opinionated guidance — name the file/step/decision>
BLOCKER: <only if VERDICT is OBJECT: the single concern that makes this unworthy, plus the recommended remedy. Mark "SAFETY" if it is irreversible data loss, a security hole, or a broken public contract.>
```

Verdict meanings:
- **ENDORSE** — sound as proposed; proceed.
- **ENDORSE_WITH_CONCERNS** — proceed, but there are real improvements the
  convening layer should fold in; not worth halting for.
- **OBJECT** — unworthy as proposed; the named blocker must be resolved first.

Members must be **opinionated but constructive**: every OBJECT and every concern
carries a concrete remedy, not just a complaint. Members must not rubber-stamp —
"none / ENDORSE" is only valid when they genuinely found nothing.

## Aggregation — the council verdict

Count the five members' verdicts:

- **Council OBJECT (halt)** when **a majority object** — **≥3 of 5** members return
  OBJECT (for a reduced council of N members, strictly more than half), **OR** when
  **any single member returns an OBJECT marked `SAFETY`** (irreversible data loss,
  security hole, or broken public contract). A lone safety objection is enough —
  this mirrors `escalation-gate`'s rule that anything a reasonable reviewer could
  reject the work over is material.
- **Council ENDORSE_WITH_CONCERNS** when there is at least one OBJECT (minority,
  non-safety) or any ENDORSE_WITH_CONCERNS, but the OBJECT count is below the
  majority threshold. Proceed, **folding the concrete concerns into the
  request decomposition (intake) or the plan (pre-execution)** before continuing,
  and logging what was folded in.
- **Council ENDORSE** when no member objects and none raised concerns. Proceed.

## Routing the verdict

### Council ENDORSE
Append one line to `decisions-log.md` and proceed:
```
[<slice-id|intake>] COUNCIL: ENDORSE — 5/5, no concerns.
```

### Council ENDORSE_WITH_CONCERNS
Revise the plan/decomposition to absorb the concrete, cheap concerns, then log each
folded change and proceed (do **not** halt):
```
[<slice-id|intake>] COUNCIL: ENDORSE_WITH_CONCERNS — folded: <what changed> — DEFERRED: <concerns intentionally not acted on + why>.
```
Concerns that are real but out of this slice's scope are logged as DEFERRED, not
silently dropped.

### Council OBJECT → lift to the human (never decided autonomously)
The council has deemed the work **unworthy**. Run `escalation-gate` with trigger
`council-objection` and write an escalation entry. **The decision belongs to the
human** — this is the one place the council overrides autonomy-by-default.
- **Intake (controller):** add the objection to the **up-front batched
  `AskUserQuestion` round** (Phase 0). Do not begin scheduling slices until the
  human resolves it.
- **Pre-execution (slice worker):** write the escalation to `escalations.md` and
  return **`NEEDS_DECISION`** so the controller surfaces it at the wave boundary.
  Do **not** execute the plan while it stands objected-to.

Use this council-objection escalation entry shape (an `escalation-gate` entry with
the council's reasoning attached):
```
## [<slice-id|intake>] Iron Council objects: <short title>   (status: OPEN)
- Trigger: council-objection
- Council verdict: OBJECT (<n>/5 object<, includes SAFETY blocker if any>)
- Objecting members: <skeptic/guardian/...> — <one-line blocker each>
- The decision: <the precise question for the human>
- Options:
  1. <proceed as-is / override the council> — (RECOMMENDED DEFAULT only if the objection is weak)
  2. <revise per the council's remedy> — <what would change>
  3. <abandon / redirect this work> — <tradeoff>
- If unanswered: <intake: block the run> | <slice: pause this slice; continue independent slices>
- Answer: <filled in by controller after the human responds>
```

After the human answers, the controller injects the answer and re-dispatches (the
slice re-runs from its plan with the resolution applied; the council is **not**
re-convened on an answer the human has already adjudicated).

## Red flags (you are misusing the council)
- Letting the council **prompt the human directly** — it never does; it routes
  through `escalation-gate`'s batched machinery.
- **Halting on ENDORSE_WITH_CONCERNS** — minority/non-safety concerns are folded
  in and logged, not surfaced. (Object-only halts.)
- **Proceeding past a SAFETY OBJECT** because it was only one member — a lone
  safety objection halts.
- Convening the council and then **ignoring its feedback** — concerns must be
  folded in or explicitly logged as DEFERRED.
- A council member **editing code** — members are read-only and advisory.
- Re-convening the council on a slice the human has already adjudicated via an
  answered escalation.
- Skipping the council to "save time" — both convenings (intake and per-plan) are
  mandatory parts of the loop.
