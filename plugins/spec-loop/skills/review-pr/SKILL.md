---
name: review-pr
description: Use when a diff needs the aspect-based PR review — dispatched by slice workers at Step 3, the controller's Phase 5 integration gate, peer-review-council's corroboration pass, or the /spec-loop:review-pr command. Maps review aspects to specialized agents, runs them sequential/parallel/exhaustive, and aggregates their findings onto the canonical P0–P3 severity scale.
---

# Review PR — aspect-based diff review, aggregated to one severity scale

## Overview

This skill is the single home of the spec-loop PR-review contract: given a diff, it selects one or more **aspects** (a facet of code quality — comments, tests, error handling, types, general guidelines, simplification), dispatches the specialized agent that owns each aspect, and merges their reports into one severity-keyed summary. It is the native replacement for the external `pr-review-toolkit:review-pr` command; every other spec-loop file that needs an aspect review cross-references this file.

**Core principle:** the diff decides which aspects run, the caller decides how deep, and every finding lands on one severity scale (P0–P3) so downstream callers never have to reconcile taxonomies.

Three terms used throughout, defined once:
- **Aspect** — a named facet of the review (`code`, `tests`, `comments`, `errors`, `types`, `simplify`), each backed by exactly one agent.
- **Report-only mode** — a caller flag that forbids any code change: never run `simplify`, never apply a fix, emit findings only (used by `spec-loop:peer-review-council`).
- **P0–P3** — spec-loop's cross-council severity scale. P0 = must-fix-before-merge, P1 = should-fix, P2 = suggestion, P3 = below-suggestion nitpick (only emitted in `exhaustive` mode; reported, never blocking).

This skill produces a review. It does **not** decide the severity bar that blocks a merge or run the auto-fix loop — those belong to `spec-loop:review-depth-map` and `spec-loop:spec-loop-slice`. See *When NOT to use this*.

## Aspects and their agents

Each aspect maps to exactly one agent. Names are fixed — dispatch by these exact names.

| Aspect | Agent | Auto-selection trigger | Notes |
|--------|-------|------------------------|-------|
| `code` | `spec-loop:guideline-reviewer` | **always runs, every invocation** | General guideline/quality review; the ported toolkit code-reviewer |
| `tests` | `spec-loop:pr-test-analyzer` | test files changed, or new logic needing coverage | behavioral coverage and gaps |
| `comments` | `spec-loop:comment-analyzer` | comments/docs added or modified | comment accuracy, rot, doc completeness |
| `errors` | `spec-loop:silent-failure-hunter` | error handling / catch / fallback / retry changed | silent failures, swallowed errors |
| `types` | `spec-loop:type-design-analyzer` | types / interfaces / schemas added or modified | encapsulation, invariants |
| `simplify` | `spec-loop:code-simplifier` | **explicit request only** — never part of default or `all` | runs last, after review converges; the only agent that edits code; non-blocking (per `spec-loop:review-depth-map`) |

`all` = the five **review** aspects forced (`code`, `tests`, `comments`, `errors`, `types`) regardless of file types. `all` never includes `simplify`.

Default (no aspects given) = **auto-selection**: `code` always, plus each of the other four review aspects whose auto-selection trigger fires on the diff.

## Determine scope

1. **Establish the diff.** Default scope is the unstaged working tree: `git diff`. A caller may instead pass a diff range `BASE..HEAD` or a pre-built diff package — spec-loop slice workers pass their slice diff (`base..head` for the slice branch); `peer-review-council` passes the materialized `base_sha..head_sha`. Use what the caller gives you; only fall back to `git diff` when nothing was passed. When the caller passed a range but no package and more than one aspect will run, materialize the package once — `"${CLAUDE_PLUGIN_ROOT}/skills/subagent-driven-development/scripts/review-package" <BASE> <HEAD>` — and hand every dispatched aspect agent that same file path plus the SHAs; aspect agents must never each re-derive the diff.
2. **List changed files.** `git diff --name-only` (add the range if one was passed) identifies the changed files and their types.
3. **Existing PR.** If reviewing an already-open PR, `gh pr view` surfaces its metadata.
4. **Auto-select aspects** (only when the caller gave none and did not force a mode): `code` always, then match each file against the auto-selection triggers in the table above.

## Execution modes

Append a mode keyword after the aspects (e.g. `spec-loop:review-pr all parallel`).

| Mode | What runs | Order |
|------|-----------|-------|
| `parallel` (default) | selected aspects | all review agents dispatched together in a single message, results aggregated together — they are read-only and independent, so concurrency is always safe |
| `sequential` | selected aspects | one agent at a time; an interactive-readability option — never required for correctness |
| `exhaustive` | all five review agents forced regardless of file types, no auto-selection | parallel; findings reported on **P0–P3** (adds the P3 nitpick band) |

`exhaustive` is the Tier-3 depth option that `spec-loop:review-depth-map` maps to. It forces the five review agents only — `simplify` is still not included and runs only when separately requested. The P3 band is reported but never blocking.

Subagent callers dispatch synchronously in one message — see `spec-loop:dispatching-parallel-agents` §Subagent nesting. In all three modes, the diff-package path (and SHAs) from §Determine scope goes into every aspect agent's dispatch prompt.

`simplify` is the exception to any parallel dispatch: it runs **last, alone, after the main review has converged** (findings below the caller's blocking bar, no open escalation), because it edits code and must not race the reviewers.

## Aggregate

After the agents return, merge their findings into four buckets and emit one summary:

- **Critical Issues** — must fix before merge
- **Important Issues** — should fix
- **Suggestions** — nice to have
- **Positive Observations** — what is well done

Tag every finding with its agent and location: `[agent-name] [file:line]`.

### Canonical severity mapping (this table is the single home of this contract)

The review buckets map onto spec-loop's cross-council P0–P3 scale as follows. `spec-loop:peer-review-council` cross-references this table when normalizing a report-only pass onto its own scale — do not restate it there.

| Review bucket | Severity |
|---------------|----------|
| Critical Issue | **P0** |
| Important Issue | **P1** |
| Suggestion | **P2** |
| Nitpick (below Suggestion) | **P3** — only in `exhaustive` mode; reported, never merged upward, never blocking |

Positive Observations carry no severity.

### Summary template

```markdown
# PR Review Summary

## Critical Issues (X found)
- [agent-name] Issue description [file:line]

## Important Issues (X found)
- [agent-name] Issue description [file:line]

## Suggestions (X found)
- [agent-name] Suggestion [file:line]

## Strengths
- What's well-done in this PR

## Recommended Action
1. Fix critical issues first
2. Address important issues
3. Consider suggestions
4. Re-run review after fixes
```

In `exhaustive` mode, add a `## Nitpicks (P3, non-blocking)` section below Suggestions.

## Report-only mode

When the caller sets the report-only flag (`spec-loop:peer-review-council`'s corroboration pass does), obey these hard constraints:
- **Never run the `simplify` aspect** and never dispatch `spec-loop:code-simplifier`.
- **Never fix, edit, apply, commit, or merge** anything.
- **Emit findings only.** The output is the aggregated summary above; the caller consumes it as data.

Report-only mode is compatible with any review mode (`sequential` / `parallel` / `exhaustive`), since none of the five review agents edit code.

## How callers consume this skill

- **`spec-loop:review-depth-map`** maps a slice's risk tier to the exact invocation string it writes into the plan header — Tier 1 `spec-loop:review-pr code`; Tier 2 `spec-loop:review-pr` (default auto-selection); Tier 3 `spec-loop:review-pr exhaustive`. The **blocking bar** (which severities block a merge) and the **auto-fix loop** live in `review-depth-map` and `spec-loop:spec-loop-slice`, not here — this skill reports findings; the caller decides what to do with them.
- **`spec-loop:spec-loop-slice`** runs the exact command from its plan header at Step 3, verifies blocking findings adversarially (Step 3b), auto-fixes (Step 4), then runs the `simplify` polish pass (Step 4b) once the review converges. Its Step 3 message also carries `spec-loop:code-reviewer` (subagent-driven-development's whole-branch review, subsumed — contract in the slice agent); that agent is not an aspect of this skill, but its findings normalize onto the canonical severity table above. Its fix-loop re-reviews are scoped by the slice worker to the aspects that produced blocking findings — that contract lives in the slice agent, not here. If a plan header written before this skill existed still names `pr-review-toolkit:review-pr <args>`, the worker executes it as the equivalent `spec-loop:review-pr <args>`.
- **`spec-loop:peer-review-council`** runs a **report-only** pass, picking depth via `review-depth-map`, and normalizes the findings onto its P0/P1/P2 scale using the canonical mapping above.

## When NOT to use this

- **Read-only review of a merged or open PR against business requirements** → `spec-loop:peer-review-council`. That skill *calls* this one in report-only mode for corroboration, but it owns the requirement-traceability matrix and the published report.
- **Deciding how deep the review goes** (which aspects, which mode, what blocks) → `spec-loop:review-depth-map`.
- **Acting on review feedback** (verifying a finding, pushing back, applying a fix) → `spec-loop:code-review-discipline` (Part 2). This skill produces findings; that skill governs how you respond to them.
- **Choosing whether to interrupt the human** on an unfixable block → `spec-loop:escalation-gate`.
