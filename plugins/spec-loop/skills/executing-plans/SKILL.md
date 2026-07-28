---
name: executing-plans
description: Use when you have a written implementation plan to execute inline (no subagents) — load and critically review the plan, raise concerns before starting, then work each task exactly with its verifications; the sanctioned fallback when subagent dispatch is unavailable
---

# Executing Plans — run a written plan inline, task by task

## Overview

Load a plan, review it critically, execute every task exactly as written with its
verifications, then finish the branch. This is the **inline** execution path: you do
the implementation yourself, sequentially, in the current session — no subagents.

**Announce at start:** "I'm using the executing-plans skill to implement this plan."

### Prefer subagents when you can dispatch them

`spec-loop:subagent-driven-development` produces significantly higher-quality work
than this skill: it dispatches a fresh implementer subagent per task with per-task
spec and quality review and fix loops. **If subagent dispatch is available in this
context, use `spec-loop:subagent-driven-development` instead.**

This skill is the **sanctioned fallback for when subagents are unavailable** — for
example inside another agent, since a subagent cannot background further agents. That
is exactly how the spec-loop slice worker uses it: it prefers subagent-driven
development and falls back to this skill to implement tasks inline when it cannot
dispatch nested subagents (see `plugins/spec-loop/agents/spec-loop-slice.md`, Step 2).

## The process

### Step 1: Load and review the plan

1. Read the plan file (under `docs/spec-loop/plans/` unless told otherwise).
2. Review it critically — identify any questions or concerns about the approach,
   the task ordering, missing prerequisites, or steps you do not understand.
3. **If you have concerns:** raise them before starting (see the run-override note
   below for who receives them).
4. **If no concerns:** create a todo per plan task and proceed to Step 2.

Return to this step if the plan is updated on your feedback, or if the fundamental
approach needs rethinking.

### Step 2: Execute tasks

For each task, in order:

1. Mark the todo **in_progress**.
2. Follow each step **exactly** — the plan has bite-sized steps; do not improvise or
   batch them.
3. Run the verifications the task specifies. Do not skip them.
4. When the task's verifications pass, mark the todo **completed**.

When the plan says to use another skill (e.g. `spec-loop:test-driven-development` for
a task that writes code), invoke that skill and follow it.

### Step 3: Complete development

After **all** tasks are complete and verified:

- Announce: "I'm using the finishing-a-development-branch skill to complete this work."
- **REQUIRED SUB-SKILL:** `spec-loop:finishing-a-development-branch` — follow it to
  verify tests, present integration options, and execute the chosen one.

## When to stop and ask for help

**STOP executing immediately** on a blocker — a missing dependency, a failing test you
cannot fix from context, a critical gap that prevents you from starting a task, an
instruction you do not understand, or a verification that fails repeatedly. Ask for
clarification rather than guessing; do not force through it.

> **Inside a spec-loop run:** these stop-and-ask conditions are governed by
> `spec-loop:escalation-gate`. A slice worker does not prompt the human directly — it
> writes the escalation to `docs/spec-loop/<run-id>/escalations.md`, returns status
> `NEEDS_DECISION` (pausing only that slice), and the controller batches it at the wave
> boundary. A genuine blocker here is usually escalation-gate trigger 1 (ambiguity) or
> 2 (material assumption). Outside a run (interactive use), raise concerns directly with
> your human partner as written above.
>
> `spec-loop:verification-before-completion` is **never** overridden — do not skip a
> task's verifications or claim completion without running them, run or no run.

## Never start on main/master

Never begin implementation on the `main` or `master` branch without **explicit user
consent**. Ensure an isolated workspace exists first via
`spec-loop:using-git-worktrees` (it creates a worktree or verifies an existing one).

> **Inside a spec-loop run:** this consent gate is governed by
> `spec-loop:escalation-gate` and is satisfied structurally — every slice runs in its
> own dedicated worktree on a slice branch, never on `main`, so the human is never
> prompted for branch consent mid-run. Outside a run, the explicit-consent rule applies
> as written.

## When NOT to use this

- **You can dispatch subagents** → use `spec-loop:subagent-driven-development` instead;
  it is the preferred, higher-quality path. Reach for this skill only when nested
  subagent dispatch is unavailable.
- **You don't have a written plan yet** → use `spec-loop:writing-plans` first.
- **You need an isolated workspace** → `spec-loop:using-git-worktrees` sets that up
  before execution begins.
