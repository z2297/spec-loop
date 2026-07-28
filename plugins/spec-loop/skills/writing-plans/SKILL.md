---
name: writing-plans
description: Use when you have a spec or requirements for a multi-step task, before touching code — turns a spec into a bite-sized, TDD, no-placeholder implementation plan a zero-context engineer can execute
---

# Writing Plans — turn a spec into an executable, no-placeholder plan

## Overview

Write comprehensive implementation plans assuming the engineer has zero context for this codebase and questionable taste. Document everything they need: which files to touch for each task, the code, the tests, docs they might need to check, and how to test it. Give them the whole plan as bite-sized tasks. DRY. YAGNI. TDD. Frequent commits. Assume they are a skilled developer, but know almost nothing about this toolset or problem domain, and don't know good test design very well.

**Announce at start:** "I'm using the writing-plans skill to create the implementation plan."

**Save plans to:** `docs/spec-loop/plans/YYYY-MM-DD-<feature-name>.md` (user preferences for plan location override this default). If working in an isolated worktree, it should have been created via `spec-loop:using-git-worktrees` at execution time.

**Scope check:** if the spec covers multiple independent subsystems, it should have been broken into sub-project specs during brainstorming. If it wasn't, suggest breaking this into separate plans — one per subsystem, each producing working, testable software on its own.

## File Structure

Before defining tasks, map out which files will be created or modified and what each one is responsible for. This is where decomposition decisions get locked in. Design units with clear boundaries and well-defined interfaces, one clear responsibility per file. You reason best about code you can hold in context at once and your edits are more reliable when files are focused, so prefer smaller files; keep files that change together together, splitting by responsibility rather than by technical layer. In existing codebases follow established patterns — if the codebase uses large files, don't unilaterally restructure, but if a file you're modifying has grown unwieldy, including a split in the plan is reasonable.

## Task Right-Sizing

A task is the smallest unit that carries its own test cycle and is worth a fresh reviewer's gate. When drawing task boundaries: fold setup, configuration, scaffolding, and documentation steps into the task whose deliverable needs them; split only where a reviewer could meaningfully reject one task while approving its neighbor. Each task ends with an independently testable deliverable.

Within a task, each step is one action taking 2-5 minutes — write the failing test, run it to confirm it fails, implement minimally, run the tests, commit.

## Plan Document Header

**Every plan MUST start with this header:**

```markdown
# [Feature Name] Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use spec-loop:subagent-driven-development (recommended) or spec-loop:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** [One sentence describing what this builds]

**Architecture:** [2-3 sentences about approach]

**Tech Stack:** [Key technologies/libraries]

## Global Constraints

[The spec's project-wide requirements — version floors, dependency limits,
naming and copy rules, platform requirements — one line each, with exact
values copied verbatim from the spec. Every task's requirements implicitly
include this section.]

---
```

> **Inside a spec-loop run:** the slice worker prepends a `<!-- spec-loop: risk-tier=... council="..." review="..." ... -->` metadata comment line *above* this plan header (see `plugins/spec-loop/agents/spec-loop-slice.md` Step 1). That comment is owned and specified by `spec-loop:review-depth-map` — do not restate or invent its fields here; the slice worker adds it. When writing a plan yourself (interactive use, outside a run), you don't add that comment.

## Task Structure

````markdown
### Task N: [Component Name]

**Files:**
- Create: `exact/path/to/file.py`
- Modify: `exact/path/to/existing.py:123-145`
- Test: `tests/exact/path/to/test.py`

**Interfaces:**
- Consumes: [what this task uses from earlier tasks — exact signatures]
- Produces: [what later tasks rely on — exact function names, parameter
  and return types. A task's implementer sees only their own task; this
  block is how they learn the names and types neighboring tasks use.]

- [ ] **Step 1: Write the failing test**

```python
def test_specific_behavior():
    result = function(input)
    assert result == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/path/test.py::test_name -v`
Expected: FAIL with "function not defined"

- [ ] **Step 3: Write minimal implementation**

```python
def function(input):
    return expected
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/path/test.py::test_name -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/path/test.py src/path/file.py
git commit -m "feat: add specific feature"
```
````

## No Placeholders

Every step must contain the actual content an engineer needs. These are **plan failures** — never write them:

- "TBD", "TODO", "implement later", "fill in details"
- "Add appropriate error handling" / "add validation" / "handle edge cases"
- "Write tests for the above" (without actual test code)
- "Similar to Task N" (repeat the code — the engineer may be reading tasks out of order)
- Steps that describe what to do without showing how (code blocks required for code steps)
- References to types, functions, or methods not defined in any task

Exact file paths always. Complete code in every step. Exact commands with expected output.

Before you hand the plan off, check it against the spec with fresh eyes: every spec requirement maps to a task, no placeholder patterns survived, and the types and signatures used in later tasks match what earlier tasks defined. Fix what you find inline.

## Execution Handoff

After saving the plan, offer execution choice:

**"Plan complete and saved to `docs/spec-loop/plans/<filename>.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?"**

Subagent-Driven → **REQUIRED SUB-SKILL:** `spec-loop:subagent-driven-development` (fresh subagent per task + two-stage review). Inline → **REQUIRED SUB-SKILL:** `spec-loop:executing-plans` (batch execution with checkpoints for review).

> **Inside a spec-loop run:** you do NOT present this menu. The slice worker already knows it executes with `spec-loop:subagent-driven-development` (Step 1.5+ of `spec-loop-slice`), and `spec-loop:escalation-gate` owns all human contact — a mid-run "which approach?" prompt would violate the autonomy contract. Present the menu only in interactive use, outside a run.

## When NOT to use this

- **No spec or clear requirements yet** → `spec-loop:brainstorming` first to nail down WHAT you're building, then come back here.
- **A single, trivial change** (one file, one obvious edit, no cross-task interfaces) → skip the plan and do it with `spec-loop:test-driven-development`. A plan is overhead when there's nothing to decompose.
- **The plan is written and you're ready to build** → `spec-loop:subagent-driven-development` (recommended) or `spec-loop:executing-plans`.
- **Chasing a bug, not building a feature** → `spec-loop:systematic-debugging`.
