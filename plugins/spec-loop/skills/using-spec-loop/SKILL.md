---
name: using-spec-loop
description: Use when starting any task or conversation in a repo that uses spec-loop, when unsure which skill you should use, or before responding, asking clarifying questions, or exploring the codebase — establishes how to find and invoke the right spec-loop skill before ANY response.
---

<SUBAGENT-STOP>
If you were dispatched as a subagent to execute a task — a slice worker, implementer, reviewer, or any council/peer-review agent — ignore this skill. It routes interactive sessions; a task-executor that re-entered it would recursively re-run the framework on its own subtask. Do your assigned task under the skills your dispatch prompt named.
</SUBAGENT-STOP>

# Using spec-loop — the skill router

## Overview

This is the gateway skill for interactive work in a spec-loop repo. spec-loop has **no SessionStart hook** (deliberate — the framework stays dormant until it is relevant); this skill loads on demand via its description. Its whole job is to make you check for a relevant skill and invoke it **before** you do anything else.

## The Rule

If a skill plausibly applies to the task, invoke it before responding — including before clarifying questions, exploring the codebase, or checking files. Announce which skill you are using and why.

If a skill turns out wrong for the situation you don't have to use it, but you check first. Before entering plan mode, invoke `spec-loop:brainstorming` if you haven't already brainstormed. Follow the skill exactly; if it has a checklist, create one todo per item.

## Skill Priority

When multiple skills apply, **process skills come first** — they set the approach, then implementation skills carry it out. So "let's build X" starts at `brainstorming` and "fix this bug" starts at `systematic-debugging`, then domain skills follow.

## Skill catalog — process skills

Pick by the WHEN column, then invoke the named skill. (`spec-loop:` prefix omitted below.)

| Skill | Use WHEN |
|---|---|
| `using-spec-loop` | This router. Starting any task/conversation, or unsure which skill applies. |
| `brainstorming` | Before any creative work — new feature, component, functionality, or behavior change. Explore intent/requirements/design before code. |
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
| `escalation-gate` | The autonomy contract. Run before stopping or asking the human anything during a run; decides proceed-and-log vs. surface. Owns all human contact inside a run. |
| `iron-council` | Controller vetting a fresh request, or a slice worker about to execute a plan; convenes challengers and returns ENDORSE / ENDORSE_WITH_CONCERNS / OBJECT. |
| `review-depth-map` | A slice has a plan; maps its risk tier to how far the PR review and Iron Council go. |
| `quality-gate` | A slice passed PR review and the simplify pass; final objective complexity/length/CRAP gate before merge. |
| `peer-review-council` | A real open/merged PR plus business requirements to vet; produces one read-only advisory review report. |
| `runbook` | End of a run, after the integration gate is green; synthesizes `runbook.md` and the Executive Readout. |
| `knowledge-graph` | A phase boundary; records decisions/architecture/domain into the user's Obsidian graph (opt-in; no-ops unless a vault is configured). |

**Inside an active spec-loop run:** slice workers ignore this router (see `<SUBAGENT-STOP>`), and every human checkpoint the process skills below would raise (brainstorming's design approval, subagent-driven-development's consent-before-`main`, a review BLOCK) is governed by `spec-loop:escalation-gate` instead. `verification-before-completion` is the one exception — it is never overridden.

## User Instructions

User instructions (CLAUDE.md, AGENTS.md, direct requests) take precedence over skills, which in turn override default behavior. Only skip a skill workflow or instruction when your human partner has explicitly told you to.

## When NOT to use this

Skip it when you were dispatched as a task-executing subagent (see `<SUBAGENT-STOP>`), or when you already know the exact skill you need — invoke that directly. Deciding whether to interrupt the human mid-run is `spec-loop:escalation-gate`, not this skill.
