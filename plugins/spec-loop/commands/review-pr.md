---
description: "Comprehensive aspect-based PR review using spec-loop's native review agents (guideline-reviewer, pr-test-analyzer, comment-analyzer, silent-failure-hunter, type-design-analyzer, code-simplifier)"
argument-hint: "[review-aspects]"
allowed-tools: ["Bash", "Glob", "Grep", "Read", "Task", "Skill"]
---

# Spec-Loop PR Review

Thin wrapper: **load the `spec-loop:review-pr` skill and follow its workflow.**
The skill is the contract — it owns scope resolution (default: unstaged
`git diff`, or a PR via `gh pr view`), the aspect table and auto-selection, mode
keywords (`parallel`, `exhaustive`, `all`, `simplify`), agent dispatch, and the
`# PR Review Summary` aggregation. Do not re-derive any of that here.

**Review aspects (optional, free-form):** "$ARGUMENTS"

Use standalone, outside a `/spec-loop` run, to review working changes or an open
PR. Inside a run, slice review depth is decided by `spec-loop:review-depth-map`.
For a read-only review of a PR against stated business requirements, use
`/spec-loop:peer-review` instead — it never edits, merges, or posts anything.
