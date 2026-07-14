---
name: using-spec-loop
description: Use when starting any task or conversation in a repo that uses spec-loop, when unsure which skill you should use, or before responding, asking clarifying questions, or exploring the codebase — establishes how to find and invoke the right spec-loop skill before ANY response.
---

<SUBAGENT-STOP>
If you were dispatched as a subagent to execute a specific task — a spec-loop slice worker (`spec-loop:spec-loop-slice`), an implementer, a reviewer, or any council/peer-review agent — IGNORE this skill. It is the interactive-session router; a dispatched task-executor that re-enters it would recursively re-run the framework on its own subtask. Do your assigned task under the skills your dispatch prompt named, and stop.
</SUBAGENT-STOP>

# Using spec-loop — the skill router

## Overview

This is the gateway skill for interactive work in a spec-loop repo. spec-loop has **no SessionStart hook** (deliberate — the framework stays dormant until it is relevant); this skill loads on demand via its description. Its whole job is to make you check for a relevant skill and invoke it **before** you do anything else.

<EXTREMELY-IMPORTANT>
If you think there is even a 1% chance a skill might apply to what you are doing, you ABSOLUTELY MUST invoke the skill.

IF A SKILL APPLIES TO YOUR TASK, YOU DO NOT HAVE A CHOICE. YOU MUST USE IT.

This is not negotiable. You cannot rationalize your way out of this.
</EXTREMELY-IMPORTANT>

## The Rule

**Invoke relevant or requested skills BEFORE any response or action** — including clarifying questions, exploring the codebase, or checking files. If a skill turns out wrong for the situation, you don't have to use it — but you check first.

**Before entering plan mode:** if you haven't already brainstormed, invoke `spec-loop:brainstorming` first.

Then announce **"Using [skill] to [purpose]"** and follow the skill exactly. If it has a checklist, create one todo per item.

## Skill Priority

When multiple skills apply, **process skills come first** — they set the approach, then implementation skills (frontend-design, etc.) carry it out. Brainstorming and systematic-debugging are the most common process entry points, but the rule holds for any of them.

- "Let's build X" → `spec-loop:brainstorming` first, then implementation skills.
- "Fix this bug" → `spec-loop:systematic-debugging` first, then domain skills.

## Skill catalog — process skills

Pick by the WHEN column, then invoke the named skill. (`spec-loop:` prefix omitted below.)

| Skill | Use WHEN |
|---|---|
| `using-spec-loop` | This router. Starting any task/conversation, or unsure which skill applies. |
| `brainstorming` | Before ANY creative work — new feature, component, functionality, or behavior change. Explore intent/requirements/design before code. |
| `writing-plans` | You have a spec or requirements for a multi-step task, before touching code. |
| `test-driven-development` | Implementing any feature or bugfix, before writing implementation code. |
| `systematic-debugging` | Any bug, test failure, or unexpected behavior, before proposing a fix. |
| `subagent-driven-development` | Executing an implementation plan with independent tasks in the current session. |
| `executing-plans` | Executing a written plan inline in the current session (no subagents) — the fallback when subagent dispatch is unavailable. |
| `dispatching-parallel-agents` | 2+ independent tasks with no shared state or sequential dependency. |
| `using-git-worktrees` | Starting feature work that needs isolation, or before executing a plan. |
| `code-review-discipline` | Completing/merging work (request a review) or acting on review feedback (receive one). |
| `verification-before-completion` | About to claim work is complete/fixed/passing, before committing or opening a PR. **Hard gate — never skipped.** |
| `finishing-a-development-branch` | Implementation done and tests pass; deciding how to integrate (merge / PR / cleanup). |
| `writing-skills` | Creating, editing, or verifying a skill. |

## Skill catalog — loop machinery

These run the autonomous `/spec-loop` (and `/spec-loop:peer-review`) loop itself. In interactive use you rarely invoke them by hand — the controller and slice workers do — but knowing they exist tells you where a concern is already handled.

| Skill | Fires when |
|---|---|
| `escalation-gate` | The autonomy contract. Run before stopping or asking the human anything during a run; decides proceed-and-log vs. surface. Owns ALL human contact inside a run. |
| `iron-council` | Controller vetting a fresh request, or a slice worker about to execute a plan; convenes challengers and returns ENDORSE / ENDORSE_WITH_CONCERNS / OBJECT. |
| `review-depth-map` | A slice has a plan; maps its risk tier to how far the PR review and Iron Council go. |
| `quality-gate` | A slice passed PR review and the simplify pass; final objective complexity/length/CRAP gate before merge. |
| `peer-review-council` | A real open/merged PR plus business requirements to vet; produces one read-only advisory review report. |
| `runbook` | End of a run, after the integration gate is green; synthesizes `runbook.md` and the Executive Readout. |
| `knowledge-graph` | A phase boundary; records decisions/architecture/domain into the user's Obsidian graph (opt-in; no-ops unless a vault is configured). |

**Inside an active spec-loop run:** slice workers ignore this router (see `<SUBAGENT-STOP>`), and every human checkpoint the process skills below would raise (brainstorming's design approval, subagent-driven-development's consent-before-`main`, a review BLOCK) is governed by `spec-loop:escalation-gate` instead. `verification-before-completion` is the one exception — it is never overridden.

## Red Flags

These thoughts mean STOP — you're rationalizing:

| Thought | Reality |
|---------|---------|
| "This is just a simple question" | Questions are tasks. Check for skills. |
| "I need more context first" | Skill check comes BEFORE clarifying questions. |
| "Let me explore the codebase first" | Skills tell you HOW to explore. Check first. |
| "I can check git/files quickly" | Files lack conversation context. Check for skills. |
| "Let me gather information first" | Skills tell you HOW to gather information. |
| "This doesn't need a formal skill" | If a skill exists, use it. |
| "I remember this skill" | Skills evolve. Read the current version. |
| "This doesn't count as a task" | Action = task. Check for skills. |
| "The skill is overkill" | Simple things become complex. Use it. |
| "I'll just do this one thing first" | Check BEFORE doing anything. |
| "This feels productive" | Undisciplined action wastes time. Skills prevent this. |
| "I know what that means" | Knowing the concept ≠ using the skill. Invoke it. |

## User Instructions

User instructions (CLAUDE.md, AGENTS.md, direct requests) take precedence over skills, which in turn override default behavior. Only skip a skill workflow or instruction when your human partner has explicitly told you to.

## When NOT to use this

- **You were dispatched as a task-executing subagent** (spec-loop slice worker, implementer, reviewer, council/peer-review agent) → ignore this skill entirely; see `<SUBAGENT-STOP>` at the top.
- **You already know the exact skill you need** → invoke it directly (e.g. `spec-loop:systematic-debugging`); this router just helps you find it.
- **You need to decide whether to interrupt the human mid-run** → that is `spec-loop:escalation-gate`, not this skill.

## Provenance and maintenance

Ported from `superpowers` v6.1.1 (github.com/obra/superpowers, MIT) `skills/using-superpowers` on 2026-07-08; adapted for spec-loop. Cut the source's Platform Adaptation section and its `references/` files (cross-harness content, not applicable here). Added the two skill-catalog tables and the loop-machinery / escalation-gate integration notes.

Re-verify if things drift:
- Sibling process-skill names: `ls plugins/spec-loop/skills/` and confirm each row of the process-skill table resolves to a real `<name>/SKILL.md`.
- Loop-machinery one-liners track the real frontmatter: `head -4 plugins/spec-loop/skills/<name>/SKILL.md` for `escalation-gate`, `iron-council`, `review-depth-map`, `quality-gate`, `peer-review-council`, `runbook`, `knowledge-graph`.
