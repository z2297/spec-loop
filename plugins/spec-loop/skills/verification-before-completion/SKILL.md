---
name: verification-before-completion
description: Use when about to claim work is complete, fixed, or passing, before committing or creating PRs, or before a slice reports DONE — requires running the verification command and reading its output before making any success claim; evidence before assertions, always
---

# Verification Before Completion — evidence before any completion claim

## Overview

Claiming work is complete without verification is dishonesty, not efficiency.

**Core principle:** Evidence before claims, always.

**Violating the letter of this rule is violating the spirit of this rule.**

This gate is the one spec-loop commitment that is **never** relaxed for autonomy. See the pinned note below.

## The Iron Law

```
NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE
```

If you haven't run the verification command **in this message**, you cannot claim it passes.

## The Gate Function

```
BEFORE claiming any status or expressing satisfaction:

1. IDENTIFY: What command proves this claim?
2. RUN:      Execute the FULL command (fresh, complete)
3. READ:     Full output, check exit code, count failures
4. VERIFY:   Does output confirm the claim?
             - If NO: State actual status with evidence
             - If YES: State claim WITH evidence
5. ONLY THEN: Make the claim

Skip any step = lying, not verifying
```

## This gate is never overridden by the autonomy contract

**Pinned — read before you rationalize skipping it.** During an active spec-loop run,
`spec-loop:escalation-gate` governs every *human* checkpoint (design approval,
consent-before-`main`, stop-and-ask, review BLOCK surfacing). It does **not** govern
this one. `verification-before-completion` is a **hard, no-human, evidence-before-claims
gate** and it stays in force at **every layer** of a run:

- **Slice worker** — a slice may not return `DONE` until its full test/build command
  has been run fresh and read in the same message (slice verification step).
- **Controller merge gate** — the controller may not merge a slice into the
  integration branch on a slice's word alone; the merge gate stands on fresh evidence,
  not on the slice's self-report.
- **Integration gate (Phase 5)** — the run is not "green" until the integration
  verification command has been run and read fresh.

`escalation-gate` saying PROCEED never authorizes skipping this gate. The two are
independent: one decides *whether to interrupt the human*, this one decides *whether you
have earned a completion claim*. There is no autonomy exception, no "the gate said
proceed" exception, and no human to wave it through — the evidence is the only authority.

## Common Failures

| Claim | Requires | Not Sufficient |
|-------|----------|----------------|
| Tests pass | Test command output: 0 failures | Previous run, "should pass" |
| Linter clean | Linter output: 0 errors | Partial check, extrapolation |
| Build succeeds | Build command: exit 0 | Linter passing, logs look good |
| Bug fixed | Test original symptom: passes | Code changed, assumed fixed |
| Regression test works | Red-green cycle verified | Test passes once |
| Agent completed | **VCS diff shows the changes** | Agent reports "success" |
| Requirements met | Line-by-line checklist | Tests passing |

The "agent completed" row is load-bearing in spec-loop: when a slice worker or the
controller delegates to a subagent, **verify against the VCS diff** (`git diff`,
`git status`), not the agent's own report of success. A subagent that says "done" has
proven nothing until its diff is on disk and read.

## Red Flags — STOP

- Using "should", "probably", "seems to"
- Expressing satisfaction before verification ("Great!", "Perfect!", "Done!", etc.)
- About to commit / push / open a PR / return `DONE` without verification
- Trusting a subagent's success report instead of checking its diff
- Relying on a partial or scoped verification and extrapolating
- Thinking "just this once"
- Tired and wanting the work over
- Telling yourself "escalation-gate said PROCEED, so I can claim it"
- **ANY wording implying success without having run verification in this message**

## Rationalization Prevention

| Excuse | Reality |
|--------|---------|
| "Should work now" | RUN the verification |
| "I'm confident" | Confidence ≠ evidence |
| "Just this once" | No exceptions |
| "Linter passed" | Linter ≠ compiler |
| "Agent said success" | Verify independently — read the diff |
| "I'm tired" | Exhaustion ≠ excuse |
| "Partial check is enough" | Partial proves nothing |
| "Different words so rule doesn't apply" | Spirit over letter |
| "The gate said proceed" | That gate is human contact, not this one — never skip |

## Key Patterns

**Tests:**
```
[Run test command] [See: 34/34 pass] "All tests pass"
NOT: "Should pass now" / "Looks correct"
```

**Regression tests (TDD Red-Green):**
```
Write -> Run (pass) -> Revert fix -> Run (MUST FAIL) -> Restore -> Run (pass)
NOT: "I've written a regression test" (without the red-green cycle verified)
```

**Build:**
```
[Run build] [See: exit 0] "Build passes"
NOT: "Linter passed" (linter doesn't check compilation)
```

**Requirements:**
```
Re-read plan -> Create checklist -> Verify each item -> Report gaps or completion
NOT: "Tests pass, phase complete"
```

**Agent delegation:**
```
Agent reports success -> Check VCS diff -> Verify the changes are real -> Report actual state
NOT: Trust the agent's report
```

## Why This Matters

Failure memories that produced this rule:
- Your human partner said "I don't believe you" — trust broken.
- Undefined functions shipped — would crash at runtime.
- Missing requirements shipped — incomplete features passed off as done.
- Time wasted on a false completion, then redirect, then rework.
- Violates the core value: honesty. A lie about completion is still a lie.

In a spec-loop run the blast radius is larger: an unverified `DONE` merges into the
integration branch and every downstream slice inherits a false foundation.

## When To Apply

**ALWAYS before:**
- ANY variation of a success / completion claim
- ANY expression of satisfaction
- ANY positive statement about work state
- Committing, PR creation, task completion, returning a slice `DONE`
- A controller merge or the Phase 5 integration gate
- Moving to the next task
- Delegating to, or accepting a result from, a subagent

**The rule applies to:**
- Exact phrases
- Paraphrases and synonyms
- Implications of success
- ANY communication suggesting completion or correctness

## When NOT to use this

This skill is never "not applicable" — the gate always stands. But if your situation is
actually a different one, reach for the sibling skill instead:
- You are **writing or fixing** code and need the discipline for *how* to build it
  test-first → `spec-loop:test-driven-development` (this skill only verifies the result).
- A test or build is **failing** and you need to find out *why* before you can verify
  anything → `spec-loop:systematic-debugging`. Return here once you have a fix to verify.
- You need to decide whether to **stop and ask the human** → `spec-loop:escalation-gate`.
  That is a separate decision and it never lets you skip this gate.

## The Bottom Line

**No shortcuts for verification.**

Run the command. Read the output. THEN claim the result.

This is non-negotiable.

## Provenance and maintenance

Ported from `superpowers` v6.1.1 (github.com/obra/superpowers, MIT)
`skills/verification-before-completion` on 2026-07-08; adapted for spec-loop. Adaptations:
added the pinned "never overridden by the autonomy contract" section tying the gate to the
slice `DONE` claim, controller merge gate, and Phase 5 integration gate; expanded the
"agent completed" guidance to say check the VCS diff, not the report; added a
"When NOT to use this" section pointing at sibling skills. Cut the ASCII check/cross glyphs
in favor of plain labels (house style / CI safety).

Re-verify if things drift:
- Sibling skill names still exist:
  `ls plugins/spec-loop/skills/{test-driven-development,systematic-debugging,escalation-gate}`
- The "never overridden" claim still matches the contract:
  `sed -n '17p' plugins/spec-loop/skills/escalation-gate/SKILL.md` and
  `sed -n '55,57p' plugins/spec-loop/commands/spec-loop.md`
