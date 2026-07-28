---
name: subagent-driven-development
description: Use when executing an implementation plan with mostly-independent tasks in the current session — dispatch a fresh implementer agent per task, review each (spec + quality) with a fix loop, then run one whole-branch review before finishing
---

# Subagent-Driven Development — one fresh agent per task, reviewed, then a whole-branch pass

## Overview

Execute a plan by dispatching a fresh **implementer** agent per task, a **task reviewer** (spec compliance + code quality) after each, and one broad **whole-branch reviewer** at the end. You are the orchestrator: you never write the code yourself, you construct exactly the context each agent needs, and you move artifacts as files so they never pollute your context.

**Why subagents:** each task goes to an agent with isolated context. By crafting its instructions precisely, you keep it focused and preserve your own context for coordination. Agents never inherit your session history — you build exactly what they need.

**Core principle:** fresh implementer per task + task review (spec AND quality) + broad final review = high quality, fast iteration.

**Narration:** between tool calls, narrate at most one short line — the ledger and tool results carry the record.

**Continuous execution:** do not pause to check in between tasks. Execute every task in the plan without stopping. The only reasons to stop are a `BLOCKED` you cannot resolve, ambiguity that genuinely prevents progress, or all tasks complete. The human asked you to execute the plan, so execute it. (Inside a spec-loop run, stopping is never a direct prompt — see [Inside a spec-loop run](#inside-a-spec-loop-run).)

This skill dispatches the plugin's named agent types, not raw `general-purpose` agents with pasted prompt templates:

| Role | Agent type | Runs |
|---|---|---|
| Implementer (per task) | `spec-loop:sdd-implementer` | one per task, sequentially |
| Task reviewer (per task) | `spec-loop:sdd-task-reviewer` | after each implementer, spec + quality |
| Fix agent (per finding batch) | `spec-loop:sdd-implementer` | same contract as implementer |
| Whole-branch reviewer (once) | `spec-loop:code-reviewer` | after all tasks pass |

## When NOT to use this

- **No plan yet** → use `spec-loop:brainstorming` then `spec-loop:writing-plans` first. This skill consumes a plan; it does not create one.
- **Tightly coupled tasks** (each depends on the last, cannot be reviewed in isolation) → execute manually or restructure the plan.
- **You cannot dispatch subagents** (e.g. you are already inside an agent that cannot background further agents) → use `spec-loop:executing-plans`, which executes the plan inline and sequentially. Prefer this skill whenever subagent dispatch is available — it produces higher-quality work.

## The Process

**Before starting**, ensure an isolated workspace exists — drive `spec-loop:using-git-worktrees` (a spec-loop slice worker is already in one). Implementers follow `spec-loop:test-driven-development`.

1. Read the plan once; note project context and Global Constraints; create todos; check the progress ledger.
2. Pre-Flight Plan Review — batch any conflicts to the human before Task 1.
3. Per task, in order: record `BASE`; `task-brief` → brief file; dispatch `spec-loop:sdd-implementer`; handle its status; `review-package BASE HEAD` → diff file; dispatch `spec-loop:sdd-task-reviewer`; loop fix-agent → re-review until spec-compliant AND quality Approved; mark complete in todos AND the ledger.
4. After the last task: `review-package MERGE_BASE HEAD`; dispatch `spec-loop:code-reviewer` once; if it returns findings, dispatch ONE fix agent with the whole list, then re-review.
5. Hand off to `spec-loop:finishing-a-development-branch`.

## Pre-Flight Plan Review

Before dispatching Task 1, scan the plan once for conflicts:

- tasks that contradict each other or the plan's Global Constraints;
- anything the plan explicitly mandates that the review rubric treats as a defect (a test that asserts nothing, verbatim duplication of a logic block).

Present everything you find as ONE batched question — each finding beside the plan text that mandates it, asking which governs — before execution begins, not one interrupt per discovery mid-plan. If the scan is clean, proceed without comment. The review loop remains the net for conflicts that only emerge from implementation.

**Inside a spec-loop run:** this up-front human gate is governed by `spec-loop:escalation-gate` — batch the conflicts into an escalation entry and return `NEEDS_DECISION` rather than prompting directly. Outside a run (interactive use), ask the human as written.

## Model Selection

**Default to `model: inherit`** — the session model (Opus 5-class). It is the right choice for implementers, for the final whole-branch review, and for anything that requires judgment: multi-file work, pattern matching, debugging, prose-only specs, subtle concurrency or security diffs, architecture.

Pass `model: sonnet` only for cheap mechanical lanes:

- transcription-style implementation, where the plan text already contains the code to write;
- single-file mechanical fixes;
- routine per-task review of a small, low-risk diff.

Always set `model` explicitly on a dispatch so the tier is a stated choice rather than an accident.

**Turn count beats token price:** a weaker model routinely takes 2-3× the turns on multi-step work, so it costs more wall-clock and more context than the model that gets it right the first time.

## Handling Implementer Status

`spec-loop:sdd-implementer` returns one of four statuses (the agent's own return contract in `agents/sdd-implementer.md` is the canonical definition of each; this section covers the orchestrator-side handling):

- **DONE:** generate the review package (below) and dispatch the task reviewer.
- **DONE_WITH_CONCERNS:** the work is complete but the implementer flagged doubts. Read them first. Correctness or scope concerns get addressed before review; observations (e.g. "this file is getting large") go in the ledger and review proceeds.
- **NEEDS_CONTEXT:** provide the missing information and re-dispatch (same model unless the gap was reasoning, not information).
- **BLOCKED:** assess the blocker — context problem → supply more context and re-dispatch; needs more reasoning → re-dispatch at a more capable tier; task too large → split it; the plan itself is wrong → escalate to the human (inside a run: `spec-loop:escalation-gate` → `NEEDS_DECISION`).

If the implementer said it is stuck, something must change before the retry — never re-dispatch the same prompt to the same model, and never drop an escalation.

## Handling Reviewer ⚠️ Items

The task reviewer may report "⚠️ Cannot verify from diff" items — requirements that live in unchanged code or span tasks. These do not block the rest of the review, but **you must resolve each one yourself before marking the task complete**: you hold the plan and cross-task context the reviewer lacks. If you confirm an item is a real gap, treat it as a failed spec review — send it back to the implementer and re-review.

## Constructing Dispatch Prompts

Per-task reviews are task-scoped gates. The broad review happens once, at the final whole-branch review. When you compose a dispatch:

- **No open-ended directives.** Do not add "check all uses" or "run race tests if useful" without a concrete, task-specific reason.
- **Do not re-run the implementer's tests.** The implementer's report carries the test evidence for the code it just wrote.
- **Never pre-judge findings.** Do not instruct a reviewer to ignore an issue or to cap its severity. If you believe a finding would be a false positive, let the reviewer raise it and adjudicate it in the review loop. Phrases like "do not flag," "don't treat X as a defect," "at most Minor," or "the plan chose" in a prompt you are writing mean you are pre-judging — usually to spare yourself a review loop.
- **Global constraints, verbatim.** The global-constraints block you hand the reviewer is its attention lens. Copy the binding requirements verbatim from the plan's Global Constraints section or the spec: exact values, exact formats, and the stated relationships between components ("same layout as X", "matches Y"). The agent's own definition already carries the process rules (YAGNI, test hygiene, review method) — the constraints block is for what THIS project's spec demands.
- **Hand diffs as files.** Run `review-package BASE HEAD` (below) and pass the reviewer the file path it prints. The output never enters your own context, and the reviewer sees the commit list, stat summary, and full diff with context in one Read call.
- **One task per dispatch, never session history.** A dispatch prompt describes one task, not the session's history. Do not paste accumulated prior-task summaries ("state after Tasks 1-3") into later dispatches — a real session's dispatch hit 42k chars of which 99% was pasted history. A fresh agent needs its task, the interfaces it touches, and the global constraints. Nothing else.
- **Fix dispatches carry the implementer contract.** Dispatch fix agents (`spec-loop:sdd-implementer`) for Critical and Important findings. The fix agent re-runs the tests covering its change and reports the results — name the covering test files in the dispatch; a one-line fix does not need the whole suite. Before re-dispatching the reviewer, confirm the fix report contains the covering tests, the command run, and the output.
- **Record Minor findings** in the progress ledger as you go, and point the final whole-branch review at that list so it can triage which must be fixed before merge. A roll-up nobody reads is a silent discard.
- **Plan-mandated findings are the human's call.** A finding labeled plan-mandated — or any finding that conflicts with what the plan's text requires — is the human's decision, like any plan contradiction: present the finding and the plan text, ask which governs. (Inside a run: route via `spec-loop:escalation-gate`.)
- **One final-review fix agent.** If the final whole-branch review returns findings, dispatch ONE fix agent with the complete findings list — not one fixer per finding. Per-finding fixers each rebuild context and re-run suites; a real session's final-review fix wave cost more than all its tasks combined.

### Recording BASE and generating the review package

```bash
# BEFORE dispatching the implementer for task N, record the base:
BASE=$(git rev-parse HEAD)

# AFTER the implementer returns DONE, generate the package. BASE is the commit
# you recorded above — NEVER HEAD~1, which silently drops all but the last
# commit of a multi-commit task. The script prints the unique path it wrote.
"${CLAUDE_PLUGIN_ROOT}/skills/subagent-driven-development/scripts/review-package" "$BASE" HEAD
```

## Dispatch Contracts

Dispatch the plugin's named agents via the Task tool. Fill each agent's input contract exactly — these are the fields the agent expects in its dispatch prompt.

**spec-loop:sdd-implementer** (implementer and fix agent) — supply:
```
description: "Implement Task N: <name>"   (fix: "Fix Task N review findings")
model: <chosen tier — REQUIRED, see Model Selection>
prompt:
  - Task brief FILE PATH ("read this first — it is your requirements, with the
    exact values to use verbatim"): <…/task-N-brief.md>
  - Report file PATH to write: <…/task-N-report.md>
  - One line on where this task fits in the project
  - Interfaces / decisions from earlier tasks the brief cannot know
  - Your resolution of any ambiguity you noticed in the brief
  - Global constraints, verbatim from the plan/spec
  - The model choice rationale (why this tier)
  - Instruction: if you have questions, return NEEDS_CONTEXT — do not guess
  - (fix dispatch only) the findings to fix + the covering test files to re-run
```

**spec-loop:sdd-task-reviewer** — supply:
```
description: "Review Task N (spec + quality)"
model: <inherit, or sonnet for a small low-risk diff — REQUIRED>
prompt:
  - Task brief FILE PATH (same file the implementer worked from)
  - Global constraints, verbatim from the plan/spec (its attention lens)
  - Implementer report FILE PATH: <…/task-N-report.md>
  - Review-package diff FILE PATH: <the path review-package printed>
  - BASE_SHA and HEAD_SHA of the range
Returns: pinned verdict ending "Task quality: Approved | Needs fixes",
  a Spec Compliance verdict (✅ / ❌ / ⚠️), Strengths, and Issues
  (Critical / Important / Minor with file:line).
```

**spec-loop:code-reviewer** (final whole-branch review, once) — supply:
```
description: "Whole-branch review"
model: inherit — REQUIRED
prompt:
  - DESCRIPTION: one line on what the branch delivers
  - PLAN_OR_REQUIREMENTS: the plan path (or requirements text)
  - BASE_SHA: MERGE_BASE (e.g. `git merge-base <integration-branch> HEAD`)
  - HEAD_SHA: current HEAD
  - Diff-package FILE PATH: run
    review-package MERGE_BASE HEAD and pass the printed path
  - The rolled-up Minor findings from the ledger, for triage
Returns: assessment ending "Ready to merge? Yes | No | With fixes".
```

## File Handoffs

Everything you paste into a dispatch prompt — and everything an agent prints back — stays resident in your context for the rest of the session and is re-read on every later turn. **Pasted text stays resident = the anti-pattern.** Hand artifacts over as files:

- **Task brief:** before dispatching an implementer, run
  `"${CLAUDE_PLUGIN_ROOT}/skills/subagent-driven-development/scripts/task-brief" PLAN_FILE N` — it extracts the task's full text to a uniquely named file and prints the path. The brief is the single source of requirements. Exact values (numbers, magic strings, signatures, test cases) appear **only** in the brief, never pasted into the dispatch.
- **Report file:** name the implementer's report file after the brief (`…/task-N-brief.md` → `…/task-N-report.md`) and put its path in the dispatch. The implementer writes the full report there and returns only status, commits, a one-line test summary, and concerns.
- **Reviewer inputs:** the task reviewer gets file paths — the same brief file, the report file, and the review package — plus the global constraints that bind the task.
- **Fix handoffs:** fix dispatches append their fix report (with test results) to the same report file and return a short summary; re-reviews read the updated file.

## Durable Progress

Conversation memory does not survive compaction. In real sessions, controllers that lost their place have **re-dispatched entire completed task sequences — the single most expensive failure observed.** Track progress in a ledger file, not only in todos.

- **At skill start, check for a ledger:**
  ```bash
  cat "$(git rev-parse --show-toplevel)/.spec-loop/sdd/progress.md" 2>/dev/null
  ```
  Tasks listed there as complete are DONE — **do not re-dispatch them**; resume at the first task not marked complete.
- **When a task's review comes back clean,** append one line to the ledger in the same message as your other bookkeeping (exact format):
  ```
  Task N: complete (commits <base7>..<head7>, review clean)
  ```
- **The ledger is your recovery map:** the commits it names exist in git even when your context no longer remembers creating them. **After compaction, trust the ledger and `git log` over your own recollection.**
- `git clean -fdx` will destroy the ledger (it is git-ignored scratch); if that happens, recover from `git log`.

## Inside a spec-loop run

This skill is the engine of a spec-loop slice worker's Step 2. Two rules apply during an active run:

- **Nesting rule.** From inside any agent, every dispatch MUST be `run_in_background: false` — see `spec-loop:dispatching-parallel-agents` §Subagent nesting for the full rule. The slice worker runs tasks sequentially anyway (one implementer at a time, never parallel), so synchronous is both mandatory and correct.
- **Autonomy override.** Every human gate in this skill — Pre-Flight conflicts, consent-before-`main`, a `BLOCKED` you cannot resolve, plan-mandated findings — is governed by `spec-loop:escalation-gate` during a run. The slice worker always works in a **dedicated worktree** (so consent-before-`main` is already satisfied) and escalates by writing to `escalations.md` and returning `NEEDS_DECISION` rather than prompting the human directly. Outside a run (interactive use), the gates apply as written. `spec-loop:verification-before-completion` is never overridden — it is a hard, no-human gate.
