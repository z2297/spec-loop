---
description: "Comprehensive aspect-based PR review using spec-loop's native review agents (guideline-reviewer, pr-test-analyzer, comment-analyzer, silent-failure-hunter, type-design-analyzer, code-simplifier)"
argument-hint: "[review-aspects]"
allowed-tools: ["Bash", "Glob", "Grep", "Read", "Task", "Skill"]
---

# Spec-Loop PR Review

Run a comprehensive, aspect-based review of a set of changes using spec-loop's own
review agents, each focused on a different facet of code quality. This command is a thin
wrapper: it hands off to the `spec-loop:review-pr` skill, which owns the full workflow
(scope resolution, aspect selection, agent dispatch, and aggregation). Use it standalone,
outside a `/spec-loop` run, to review your working changes or an open PR.

**Review aspects (optional):** "$ARGUMENTS"

## What to do

**Load the `spec-loop:review-pr` skill and follow its workflow.** Parse `$ARGUMENTS`
into the aspects and mode keywords below, then let the skill determine scope (default:
unstaged `git diff`; or a PR resolved via `gh pr view`), select the applicable aspects,
dispatch the native review agents, and aggregate their findings into the
`# PR Review Summary` template (Critical / Important / Suggestions / Positive
Observations). Do not re-derive that orchestration here — the skill is the contract.

## Arguments

Free-form, space-separated. Aspects and mode keywords may be combined in any order.

| Aspect | What it reviews |
| --- | --- |
| `comments` | Comment accuracy vs. code, comment rot, doc completeness (comment-analyzer) |
| `tests` | Behavioral test coverage and gaps for the change (pr-test-analyzer) |
| `errors` | Silent failures, swallowed exceptions, error logging (silent-failure-hunter) |
| `types` | Type encapsulation and invariant expression, when types are added/changed (type-design-analyzer) |
| `code` | General code-guideline compliance, bugs, quality (guideline-reviewer) |
| `simplify` | Behavior-preserving clarity polish — **the only aspect that edits code** (code-simplifier) |
| `all` | All five review aspects (`code`, `tests`, `comments`, `errors`, `types`), forced regardless of file types; excludes `simplify` |
| _(none)_ | Default: auto-select aspects from the diff's file types |

`simplify` is never part of the default or `all`; request it explicitly. It is
non-blocking polish and the only aspect that modifies code.

| Mode keyword | Effect |
| --- | --- |
| `parallel` | Dispatch the selected review agents simultaneously rather than one at a time |
| `exhaustive` | Force all five review agents regardless of the diff, and report findings on the P0–P3 severity scale |

## Usage examples

**Full review (auto-selected aspects):**
```
/spec-loop:review-pr
```

**Specific aspects:**
```
/spec-loop:review-pr tests errors
# Reviews only test coverage and error handling
```

**All applicable reviews, run in parallel:**
```
/spec-loop:review-pr all parallel
```

**Exhaustive — every review agent, P0–P3 reporting:**
```
/spec-loop:review-pr exhaustive
```

**Simplify (edits code — request explicitly):**
```
/spec-loop:review-pr simplify
```

## Related

- Review depth for slices inside a `/spec-loop` run is decided automatically by the
  `spec-loop:review-depth-map` skill (risk tier → aspects, mode, and blocking bar).
- For a read-only review of a PR against its stated business requirements, use
  `/spec-loop:peer-review` instead — it never edits, merges, or posts anything.

## Provenance and maintenance

Ported from `pr-review-toolkit` (Anthropic, claude-plugins-official marketplace)
`commands/review-pr.md` on 2026-07-13; adapted: thin wrapper over the native
`spec-loop:review-pr` skill per the `quality-gate`/`knowledge-graph` same-name
precedent — the orchestration contract lives in the skill, not here.

Re-verify if things drift:
- `ls plugins/spec-loop/skills/review-pr/SKILL.md` — confirm the wrapped skill exists.
- `python3 scripts/validate_marketplace.py .` — confirm the plugin manifest still validates.
