---
name: code-review-discipline
description: Use when you finish a task/feature or are about to merge and need a review dispatched, AND when you receive review feedback — especially if it seems unclear or technically questionable. Covers crafting a review request and responding to findings with verification, not performative agreement.
---

# Code Review Discipline — request reviews well, receive feedback with rigor

## Overview

Code review has two directions, and both are disciplines you can get wrong:

- **Requesting (Part 1):** dispatch a reviewer with precisely crafted context — the work product and its requirements, never your session history. Review early, review often.
- **Receiving (Part 2):** treat feedback as suggestions to *evaluate*, not orders to follow. Verify before implementing. Ask before assuming. Technical correctness over social comfort.

This skill is the single home for both. They were separate thin skills upstream; a review request and the response to its findings are two halves of one loop.

---

# Part 1 — Requesting a review

Dispatch a code reviewer to catch issues before they cascade into more work. The reviewer gets crafted context for evaluation, never your session's history — that keeps it focused on the work product and preserves your own context for continued work.

**Core principle:** Review early, review often.

## When to request a review

**Mandatory:** after each task in `spec-loop:subagent-driven-development`, after completing a major feature, and before merging to `main`.

**Optional but valuable:** when stuck (fresh perspective), before refactoring (baseline check), after fixing a complex bug.

## How to request

**1. Get the git SHAs that bound the change:**
```bash
BASE_SHA=$(git rev-parse HEAD~1)   # or origin/main — the last commit NOT under review
HEAD_SHA=$(git rev-parse HEAD)     # the tip of the work
```

**2. Dispatch the `spec-loop:code-reviewer` agent.** It owns the reviewer prompt, the read-only checkout rules, and the output contract; you supply its inputs:

| Input | What to pass |
|---|---|
| `DESCRIPTION` | Brief summary of what you built |
| `PLAN_OR_REQUIREMENTS` | What it should do — a plan file path (e.g. `docs/spec-loop/plans/<plan>.md`), the task text, or the requirements |
| `BASE_SHA` | Starting commit (the `BASE_SHA` above) |
| `HEAD_SHA` | Ending commit (the `HEAD_SHA` above) |
| diff package file *(optional)* | Path to a pre-computed diff package, if one was produced for this slice — lets the reviewer work from a frozen diff instead of the live checkout |

**Nesting rule (which affects HOW you dispatch):** from inside any agent, every dispatch MUST be `run_in_background: false` — see `spec-loop:dispatching-parallel-agents` §Subagent nesting for the full rule.

**3. Read the verdict.** The agent returns Strengths, Issues graded Critical / Important / Minor, Recommendations, and an Assessment ending "Ready to merge? Yes / No / With fixes".

**4. Act on the feedback** (apply Part 2's discipline to every item): fix **Critical** immediately; fix **Important** before proceeding to the next task; note **Minor** for later without letting it block. If the reviewer is wrong, push back with technical reasoning rather than silently complying — and equally, do not argue a valid finding away, which is avoidance wearing pushback's clothes.

## Integration with workflows

- **`spec-loop:subagent-driven-development`:** review after EACH task so issues cannot compound; fix before the next task.
- **`spec-loop:executing-plans`:** review after each task or at natural checkpoints.
- **Ad-hoc development:** review before merge, and whenever you are stuck.

---

# Part 2 — Receiving feedback

Code review requires technical evaluation, not emotional performance.

**Core principle:** Verify before implementing. Ask before assuming. Technical correctness over social comfort.

## The response pattern

```
WHEN receiving code review feedback:

1. READ:       Complete feedback without reacting.
2. UNDERSTAND: Restate the requirement in your own words (or ask).
3. VERIFY:     Check each claim against the codebase reality.
4. EVALUATE:   Technically sound for THIS codebase?
5. RESPOND:    Technical acknowledgment or reasoned pushback.
6. IMPLEMENT:  One item at a time, test each.
```

Step 3 is the load-bearing one: a suggestion is a claim about the code, and you check claims before acting on them. "Let me implement that now" before verification is how a confident wrong finding becomes a regression.

## Handling unclear feedback

If any item is unclear, stop and ask about the unclear items before implementing *any* of them. Items are often related, and partial understanding produces a wrong implementation of the parts you thought you understood. Given "fix items 1-6" where 4 and 5 are opaque: say you understand 1, 2, 3, 6 and need clarification on 4 and 5 — do not ship four items now and ask later.

## Implementation order

Clarify anything unclear first. Then implement blocking issues (breaks, security), then simple fixes (typos, imports), then complex fixes (refactoring, logic). Test each fix individually and verify no regressions.

## YAGNI check for "professional" features

When a reviewer suggests "implementing this properly", grep the codebase for actual usage first. If nothing calls it, the honest answer is removal, not a proper implementation: "Grepped the codebase — nothing calls this endpoint. Remove it (YAGNI), or is there usage I'm missing?" A proper implementation of dead code is maintenance debt with a review stamp on it.

## When to push back

Push back when the suggestion breaks existing functionality, comes from a reviewer lacking full context, violates YAGNI, is technically incorrect for this stack, ignores a legacy or compatibility reason, or conflicts with a prior architectural decision.

Push back with technical reasoning rather than defensiveness: ask specific questions, reference the working tests or code that prove your position, and escalate if the disagreement is architectural. If you feel uncomfortable pushing back, name that tension and state the issue anyway — honest technical disagreement is the point of review.

Source-specific handling (GitHub in-thread replies, responding to human vs automated reviewers, gracefully correcting your own pushback) → see [review-communication.md](review-communication.md).

## The bottom line

**External feedback = suggestions to evaluate, not orders to follow.** Verify. Question. Then implement.

---

## When NOT to use this

- **For a spec-loop slice's automated PR review.** The loop does not use this skill to *choose* a review. It runs `spec-loop:review-pr` (aspects and depth chosen by `spec-loop:review-depth-map` from the slice's risk tier) and adversarially verifies each blocking finding with `spec-loop:review-finding-verifier`. This skill governs how the orchestrator/worker *behaves* around that review: Part 1 for constructing a request when a slice needs a directed reviewer, and Part 2 as the discipline the auto-fix loop applies when turning verified findings into fixes.
- **To make a completion claim.** Passing review is not verification. Use `spec-loop:verification-before-completion` before asserting anything is done — it is a hard gate this skill never replaces.
- **To decide whether to interrupt the human during a run.** That is `spec-loop:escalation-gate`.
