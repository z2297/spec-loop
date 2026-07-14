---
name: code-review-discipline
description: Use when you finish a task/feature or are about to merge and need a review dispatched, AND when you receive review feedback — especially if it seems unclear or technically questionable. Covers crafting a review request and responding to findings with verification, not performative agreement.
---

# Code Review Discipline — request reviews well, receive feedback with rigor

## Overview

Code review has two directions, and both are disciplines you can get wrong:

- **Requesting (Part 1):** dispatch a reviewer with precisely crafted context — the work product and its requirements, never your session history. Review early, review often.
- **Receiving (Part 2):** treat feedback as suggestions to *evaluate*, not orders to follow. Verify before implementing. Ask before assuming. Technical correctness over social comfort.

This skill is the single home for both. They were separate thin skills upstream; a review request and the response to its findings are two halves of one loop, so they live together here.

**When NOT to use this** — see the section at the end. In short: this skill governs how *you* behave around reviews (constructing the request, applying the findings). It does **not** decide *which* automated review a spec-loop slice runs — that is `spec-loop:review-depth-map` driving `spec-loop:review-pr` + `spec-loop:review-finding-verifier`.

---

# Part 1 — Requesting a review

Dispatch a code reviewer to catch issues before they cascade into more work. The reviewer gets crafted context for evaluation, never your session's history. This keeps the reviewer focused on the work product, not your thought process, and preserves your own context for continued work.

**Core principle:** Review early, review often.

## When to request a review

**Mandatory:**
- After each task in subagent-driven development (`spec-loop:subagent-driven-development`)
- After completing a major feature
- Before merging to `main`

**Optional but valuable:**
- When stuck (fresh perspective)
- Before refactoring (baseline check)
- After fixing a complex bug

## How to request

**1. Get the git SHAs that bound the change:**
```bash
BASE_SHA=$(git rev-parse HEAD~1)   # or origin/main — the last commit NOT under review
HEAD_SHA=$(git rev-parse HEAD)     # the tip of the work
```

**2. Dispatch the `spec-loop:code-reviewer` agent.** This named agent replaces the old fill-in-a-template mechanism — it owns the reviewer prompt, the read-only checkout rules, and the output contract. You just supply its inputs:

| Input | What to pass |
|---|---|
| `DESCRIPTION` | Brief summary of what you built |
| `PLAN_OR_REQUIREMENTS` | What it should do — a plan file path (e.g. `docs/spec-loop/plans/<plan>.md`), the task text, or the requirements |
| `BASE_SHA` | Starting commit (the `BASE_SHA` above) |
| `HEAD_SHA` | Ending commit (the `HEAD_SHA` above) |
| diff package file *(optional)* | Path to a pre-computed diff package, if one was produced for this slice — lets the reviewer work from a frozen diff instead of the live checkout |

**Nesting rule (which affects HOW you dispatch):** from inside any agent, every dispatch MUST be `run_in_background: false` — see `spec-loop:dispatching-parallel-agents` for the full rule.

**3. Read the verdict.** The `spec-loop:code-reviewer` agent returns:
- **Strengths** — what was done well
- **Issues** graded **Critical** / **Important** / **Minor**
- **Recommendations**
- **Assessment** — Ready to merge? Yes / No / With fixes, plus reasoning

**4. Act on the feedback** (apply Part 2's discipline to every item):
- **Critical** — fix immediately.
- **Important** — fix before proceeding to the next task.
- **Minor** — note for later; do not let it block.
- **Reviewer is wrong** — push back with technical reasoning (see Part 2, "When to push back").

## Example

```
[Just completed Task 2: Add verification function]

You: Request code review before proceeding.

BASE_SHA=$(git log --oneline | grep "Task 1" | head -1 | awk '{print $1}')
HEAD_SHA=$(git rev-parse HEAD)

[Dispatch spec-loop:code-reviewer]
  DESCRIPTION:          Added verifyIndex() and repairIndex() with 4 issue types
  PLAN_OR_REQUIREMENTS: Task 2 from docs/spec-loop/plans/deployment-plan.md
  BASE_SHA:             a7981ec
  HEAD_SHA:             3df7661

[Agent returns]
  Strengths: Clean architecture, real tests
  Issues:
    Important: Missing progress indicators
    Minor:     Magic number (100) for reporting interval
  Assessment: Ready to proceed with fixes

You: [Fix progress indicators — an Important issue — before Task 3]
```

## Integration with workflows

- **Subagent-driven development** (`spec-loop:subagent-driven-development`): review after EACH task so issues cannot compound; fix before the next task.
- **Executing plans** (`spec-loop:executing-plans`): review after each task or at natural checkpoints; get feedback, apply, continue.
- **Ad-hoc development:** review before merge, and whenever you are stuck.

## Red flags — requesting

**Never:**
- Skip review because "it's simple."
- Ignore a Critical issue.
- Proceed with an unfixed Important issue.
- Argue with valid technical feedback (that is not pushback — that is avoidance).

**If the reviewer is genuinely wrong:** push back with technical reasoning, show the code/tests that prove it works, or request clarification. That is Part 2's job.

---

# Part 2 — Receiving feedback

Code review requires technical evaluation, not emotional performance.

**Core principle:** Verify before implementing. Ask before assuming. Technical correctness over social comfort.

## The response pattern

```
WHEN receiving code review feedback:

1. READ:      Complete feedback without reacting.
2. UNDERSTAND: Restate the requirement in your own words (or ask).
3. VERIFY:    Check each claim against the codebase reality.
4. EVALUATE:  Technically sound for THIS codebase?
5. RESPOND:   Technical acknowledgment or reasoned pushback.
6. IMPLEMENT: One item at a time, test each.
```

## Forbidden responses

**NEVER:**
- "You're absolutely right!" (explicit instruction-file violation)
- "Great point!" / "Excellent feedback!" (performative)
- "Let me implement that now" — *before* verification

**INSTEAD:**
- Restate the technical requirement.
- Ask clarifying questions.
- Push back with technical reasoning if the feedback is wrong.
- Just start working — actions over words.

## Handling unclear feedback

```
IF any item is unclear:
  STOP — do not implement anything yet.
  ASK for clarification on the unclear items.

WHY: Items may be related. Partial understanding = wrong implementation.
```

**Example:**
```
Reviewer: "Fix 1-6"
You understand 1,2,3,6. Unclear on 4,5.

❌ WRONG: Implement 1,2,3,6 now, ask about 4,5 later.
✅ RIGHT: "I understand items 1,2,3,6. Need clarification on 4 and 5 before proceeding."
```

## Source-specific handling

### From a human partner
- **Trusted** — implement after understanding.
- **Still ask** if scope is unclear.
- **No performative agreement.**
- Skip to action or a technical acknowledgment.

### From an external reviewer (human or agent)
Run the five-point skeptical check **before implementing**:
```
1. Check: Technically correct for THIS codebase?
2. Check: Does it break existing functionality?
3. Check: Is there a reason for the current implementation?
4. Check: Does it work on all platforms/versions?
5. Check: Does the reviewer understand the full context?

IF the suggestion seems wrong:
  Push back with technical reasoning.

IF you can't easily verify:
  Say so: "I can't verify this without [X]. Should I [investigate / ask / proceed]?"

IF it conflicts with a prior architectural decision:
  Stop and discuss before implementing.
```

**Rule of thumb:** external feedback — be skeptical, but check carefully.

> **Inside a spec-loop run:** the "stop and discuss" / "ask the human" moments in this section are human gates governed by `spec-loop:escalation-gate` — you do not pause and message the human directly; you classify the point through the gate (PROCEED + log, or surface at the wave boundary). Outside a run (interactive use), the gate applies as written: raise it with your partner. `spec-loop:verification-before-completion` is never overridden — the VERIFY step here is a hard gate regardless.

## YAGNI check for "professional" features

```
IF a reviewer suggests "implementing this properly":
  grep the codebase for actual usage first.

  IF unused: "This endpoint isn't called anywhere. Remove it (YAGNI)?"
  IF used:   Then implement properly.
```

**Rule of thumb:** if the feature isn't needed, don't add it — a reviewer asking for a "proper" implementation of dead code is asking for maintenance debt.

## Implementation order

```
FOR multi-item feedback:
  1. Clarify anything unclear FIRST.
  2. Then implement in this order:
     - Blocking issues (breaks, security)
     - Simple fixes (typos, imports)
     - Complex fixes (refactoring, logic)
  3. Test each fix individually.
  4. Verify no regressions.
```

## When to push back

Push back when the suggestion:
- Breaks existing functionality.
- Comes from a reviewer lacking full context.
- Violates YAGNI (unused feature).
- Is technically incorrect for this stack.
- Ignores a legacy/compatibility reason.
- Conflicts with a prior architectural decision.

**How to push back:**
- Use technical reasoning, not defensiveness.
- Ask specific questions.
- Reference working tests/code.
- Escalate if the disagreement is architectural (see the escalation-gate note above when inside a run).

**If you're uncomfortable pushing back:** name that tension, then state the issue you've seen anyway. Honest technical disagreement is the point of review.

## Acknowledging correct feedback

When the feedback IS correct:
```
✅ "Fixed. [Brief description of what changed]"
✅ "Good catch — [specific issue]. Fixed in [location]."
✅ [Just fix it and show it in the code]

❌ "You're absolutely right!"
❌ "Great point!"
❌ "Thanks for catching that!"
❌ "Thanks for [anything]"
❌ ANY gratitude expression
```

**Why no thanks:** actions speak. Just fix it — the code itself shows you heard the feedback.

**If you catch yourself about to write "Thanks":** DELETE IT. State the fix instead.

## Gracefully correcting your own pushback

If you pushed back and turned out to be wrong:
```
✅ "You were right — I checked [X] and it does [Y]. Implementing now."
✅ "Verified this; you're correct. My initial understanding was wrong because [reason]. Fixing."

❌ Long apology
❌ Defending why you pushed back
❌ Over-explaining
```

State the correction factually and move on.

## Common mistakes

| Mistake | Fix |
|---|---|
| Performative agreement | State the requirement, or just act |
| Blind implementation | Verify against the codebase first |
| Batch without testing | One at a time, test each |
| Assuming the reviewer is right | Check whether it breaks things |
| Avoiding pushback | Technical correctness > comfort |
| Partial implementation | Clarify all items first |
| Can't verify, proceed anyway | State the limitation, ask for direction |

## Real examples

**Performative agreement (bad):**
```
Reviewer: "Remove legacy code"
❌ "You're absolutely right! Let me remove that..."
```

**Technical verification (good):**
```
Reviewer: "Remove legacy code"
✅ "Checking... build target is 10.15+, this API needs 13+. Need the legacy path for
    backward compat. Current impl has the wrong bundle ID — fix it, or drop pre-13 support?"
```

**YAGNI (good):**
```
Reviewer: "Implement proper metrics tracking with a database, date filters, CSV export"
✅ "Grepped the codebase — nothing calls this endpoint. Remove it (YAGNI)? Or is there usage I'm missing?"
```

**Unclear item (good):**
```
Reviewer: "Fix items 1-6"
You understand 1,2,3,6. Unclear on 4,5.
✅ "Understand 1,2,3,6. Need clarification on 4 and 5 before implementing."
```

## GitHub in-thread replies

When replying to an inline review comment on GitHub, reply **in the comment thread**, not as a top-level PR comment:
```bash
gh api repos/{owner}/{repo}/pulls/{pr}/comments/{id}/replies \
  -f body="Fixed in <sha>. <what changed>"
```
`{id}` is the review comment's id. A top-level comment loses the thread context and forces reviewers to hunt for what you answered.

## The bottom line

**External feedback = suggestions to evaluate, not orders to follow.**

Verify. Question. Then implement. No performative agreement. Technical rigor always.

---

## When NOT to use this

- **For a spec-loop slice's automated PR review.** The loop does not use this skill to *choose* a review. It runs `spec-loop:review-pr` (aspects and depth chosen by `spec-loop:review-depth-map` from the slice's risk tier) and adversarially verifies each blocking finding with `spec-loop:review-finding-verifier`. This skill governs how the orchestrator/worker *behaves* around that review: Part 1 for constructing a request when a slice needs a directed reviewer, and Part 2 as the discipline the auto-fix loop applies when turning verified findings into fixes (see `spec-loop:review-depth-map`, "Blocking bar → auto-fix loop").
- **To make a completion claim.** Passing review is not verification. Use `spec-loop:verification-before-completion` before asserting anything is done — it is a hard gate this skill never replaces.
- **To decide whether to interrupt the human during a run.** That is `spec-loop:escalation-gate`.

## Provenance and maintenance

Merged from `superpowers` v6.1.1 (github.com/obra/superpowers, MIT) `skills/requesting-code-review` and `skills/receiving-code-review` on 2026-07-08; adapted for spec-loop. The two were paired thin skills covering the two halves of one review loop — merged into one home so each fact lives once, keeping their full processes (request mechanics + receive-feedback response pattern, forbidden-responses list, YAGNI check, GitHub thread replies).

Adapted, not verbatim: the old `code-reviewer.md` fill-in template is replaced by the named `spec-loop:code-reviewer` agent (it owns the prompt/output contract now); namespaces retargeted to `spec-loop:*` and `docs/spec-loop/plans/`; added the nesting rule and the `escalation-gate` override note for the human gates.

Re-verify if things drift:
- Agent exists: `ls plugins/spec-loop/agents/code-reviewer.md`
- Sibling skills referenced still exist: `ls plugins/spec-loop/skills/{subagent-driven-development,executing-plans,review-depth-map,review-finding-verifier,escalation-gate,verification-before-completion}/SKILL.md`
- Auto-fix loop still names this discipline: `grep -n "auto-fix loop" plugins/spec-loop/skills/review-depth-map/SKILL.md` (as of 2026-07-08 it cites `spec-loop:code-review-discipline` — Part 2 here is that discipline's home).
