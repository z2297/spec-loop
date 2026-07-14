---
name: writing-plans
description: Use when you have a spec or requirements for a multi-step task, before touching code — turns a spec into a bite-sized, TDD, no-placeholder implementation plan a zero-context engineer can execute
---

# Writing Plans — turn a spec into an executable, no-placeholder plan

## Overview

Write comprehensive implementation plans assuming the engineer has zero context for this codebase and questionable taste. Document everything they need: which files to touch for each task, the code, the tests, docs they might need to check, and how to test it. Give them the whole plan as bite-sized tasks. DRY. YAGNI. TDD. Frequent commits.

Assume they are a skilled developer, but know almost nothing about this toolset or problem domain. Assume they don't know good test design very well.

**Announce at start:** "I'm using the writing-plans skill to create the implementation plan."

**Context:** If working in an isolated worktree, it should have been created via the `spec-loop:using-git-worktrees` skill at execution time.

**Save plans to:** `docs/spec-loop/plans/YYYY-MM-DD-<feature-name>.md`
- (User preferences for plan location override this default.)

## Scope Check

If the spec covers multiple independent subsystems, it should have been broken into sub-project specs during brainstorming. If it wasn't, suggest breaking this into separate plans — one per subsystem. Each plan should produce working, testable software on its own.

## File Structure

Before defining tasks, map out which files will be created or modified and what each one is responsible for. This is where decomposition decisions get locked in.

- Design units with clear boundaries and well-defined interfaces. Each file should have one clear responsibility.
- You reason best about code you can hold in context at once, and your edits are more reliable when files are focused. Prefer smaller, focused files over large ones that do too much.
- Files that change together should live together. Split by responsibility, not by technical layer.
- In existing codebases, follow established patterns. If the codebase uses large files, don't unilaterally restructure — but if a file you're modifying has grown unwieldy, including a split in the plan is reasonable.

This structure informs the task decomposition. Each task should produce self-contained changes that make sense independently.

## Task Right-Sizing

A task is the smallest unit that carries its own test cycle and is worth a fresh reviewer's gate. When drawing task boundaries: fold setup, configuration, scaffolding, and documentation steps into the task whose deliverable needs them; split only where a reviewer could meaningfully reject one task while approving its neighbor. Each task ends with an independently testable deliverable.

## Bite-Sized Task Granularity

**Each step is one action (2-5 minutes):**
- "Write the failing test" — step
- "Run it to make sure it fails" — step
- "Implement the minimal code to make the test pass" — step
- "Run the tests and make sure they pass" — step
- "Commit" — step

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

## Remember
- Exact file paths always
- Complete code in every step — if a step changes code, show the code
- Exact commands with expected output
- DRY, YAGNI, TDD, frequent commits

## Self-Review

After writing the complete plan, look at the spec with fresh eyes and check the plan against it. This is a checklist you run **yourself** — not a subagent dispatch.

**1. Spec coverage:** Skim each section/requirement in the spec. Can you point to a task that implements it? List any gaps.

**2. Placeholder scan:** Search your plan for red flags — any of the patterns from the "No Placeholders" section above. Fix them.

**3. Type consistency:** Do the types, method signatures, and property names you used in later tasks match what you defined in earlier tasks? A function called `clearLayers()` in Task 3 but `clearFullLayers()` in Task 7 is a bug.

If you find issues, fix them inline. No need to re-review — just fix and move on. If you find a spec requirement with no task, add the task.

## Execution Handoff

After saving the plan, offer execution choice:

**"Plan complete and saved to `docs/spec-loop/plans/<filename>.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?"**

**If Subagent-Driven chosen:**
- **REQUIRED SUB-SKILL:** Use `spec-loop:subagent-driven-development`
- Fresh subagent per task + two-stage review

**If Inline Execution chosen:**
- **REQUIRED SUB-SKILL:** Use `spec-loop:executing-plans`
- Batch execution with checkpoints for review

> **Inside a spec-loop run:** you do NOT present this menu. The slice worker already knows it executes with `spec-loop:subagent-driven-development` (Step 1.5+ of `spec-loop-slice`), and `spec-loop:escalation-gate` owns all human contact — a mid-run "which approach?" prompt would violate the autonomy contract. Present the menu only in interactive use, outside a run.

## When NOT to use this

- **You don't have a spec or clear requirements yet** → use `spec-loop:brainstorming` first to nail down WHAT you're building, then come back here.
- **The task is a single, trivial change** (one file, one obvious edit, no cross-task interfaces) → skip the plan and just do it with `spec-loop:test-driven-development`. A plan is overhead when there's nothing to decompose.
- **The plan is already written and you're ready to build** → use `spec-loop:subagent-driven-development` (recommended) or `spec-loop:executing-plans` to execute it.
- **You're chasing a bug, not building a feature** → use `spec-loop:systematic-debugging`.

## Provenance and maintenance

Ported from `superpowers` v6.1.1 (github.com/obra/superpowers, MIT) `skills/writing-plans/SKILL.md` on 2026-07-08; adapted for spec-loop.

Adaptations from source: skill namespaces rewritten to `spec-loop:*`; plan save path changed to `docs/spec-loop/plans/`; added the pinned spec-loop metadata-header note, the in-run Execution-Handoff override, and the "When NOT to use this" section. The source `plan-document-reviewer-prompt.md` (a subagent dispatch template for reviewing the plan document) was **not** ported: the source SKILL body never invokes it, and inside spec-loop the plan is vetted by `spec-loop:iron-council` at slice Step 1.5 instead.

Re-verify if things drift:
- Sibling skill names exist: `ls plugins/spec-loop/skills/ | grep -E 'subagent-driven-development|executing-plans|brainstorming|test-driven-development|systematic-debugging|using-git-worktrees'`
- The metadata-header shape this note references still lives where claimed: `sed -n '107,115p' plugins/spec-loop/skills/review-depth-map/SKILL.md` and `grep -n 'metadata header' plugins/spec-loop/agents/spec-loop-slice.md`
- Autonomy-contract override wording stays consistent: `sed -n '12,17p' plugins/spec-loop/skills/escalation-gate/SKILL.md`
