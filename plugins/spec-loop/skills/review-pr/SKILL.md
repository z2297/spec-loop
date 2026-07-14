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
| `simplify` | `spec-loop:code-simplifier` | **explicit request only** — never part of default or `all` | runs LAST after review converges; the ONLY agent that edits code; non-blocking (per `spec-loop:review-depth-map`) |

`all` = the five **review** aspects forced (`code`, `tests`, `comments`, `errors`, `types`) regardless of file types. `all` never includes `simplify`.

Default (no aspects given) = **auto-selection**: `code` always, plus each of the other four review aspects whose auto-selection trigger fires on the diff.

## Determine scope

1. **Establish the diff.** Default scope is the unstaged working tree: `git diff`. A caller may instead pass a diff range `BASE..HEAD` or a pre-built diff package — spec-loop slice workers pass their slice diff (`base..head` for the slice branch); `peer-review-council` passes the materialized `base_sha..head_sha`. Use what the caller gives you; only fall back to `git diff` when nothing was passed.
2. **List changed files.** `git diff --name-only` (add the range if one was passed) identifies the changed files and their types.
3. **Existing PR.** If reviewing an already-open PR, `gh pr view` surfaces its metadata.
4. **Auto-select aspects** (only when the caller gave none and did not force a mode): `code` always, then match each file against the auto-selection triggers in the table above.

## Execution modes

Append a mode keyword after the aspects (e.g. `spec-loop:review-pr all parallel`).

| Mode | What runs | Order |
|------|-----------|-------|
| `sequential` (default) | selected aspects | one agent at a time; each report complete before the next — easier to read and act on |
| `parallel` | selected aspects | all review agents dispatched together, results return together — faster for a large diff |
| `exhaustive` **(NEW, spec-loop 2026-07-13)** | ALL FIVE review agents forced regardless of file types, no auto-selection | parallel; findings reported on **P0–P3** (adds the P3 nitpick band) |

`exhaustive` is the Tier-3 depth option that `spec-loop:review-depth-map` maps to. It forces the five review agents only — `simplify` is still not included and runs only when separately requested. The P3 band is reported but never blocking. This natively replaces the formerly-optional external `/exhaustive-pr-review:exhaustive-pr all parallel`.

### Subagent-nesting rule (mandatory when the caller is a subagent)

When the caller is itself a subagent — the `spec-loop:spec-loop-slice` worker at its Step 3, or a subagent `peer-review-council` controller — the platform forbids it from backgrounding agents. So it MUST dispatch **all review agents via Task in a single message, each with `run_in_background: false`**. This mirrors `spec-loop-slice.md` Step 1.5: "dispatch every member with `run_in_background: false` (one message of synchronous Task calls still runs them concurrently)." A top-level (non-subagent) caller may dispatch however it likes.

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

- **`spec-loop:review-depth-map`** maps a slice's risk tier to the exact invocation string it writes into the plan header — Tier 1 `spec-loop:review-pr code`; Tier 2 `spec-loop:review-pr` (default auto-selection); Tier 3 `spec-loop:review-pr exhaustive` (or `all parallel`). The **blocking bar** (which severities block a merge) and the **auto-fix loop** live in `review-depth-map` and `spec-loop:spec-loop-slice`, not here — this skill reports findings; the caller decides what to do with them.
- **`spec-loop:spec-loop-slice`** runs the exact command from its plan header at Step 3, verifies blocking findings adversarially (Step 3b), auto-fixes (Step 4), then runs the `simplify` polish pass (Step 4b) once the review converges. If a plan header written before this skill existed still names `pr-review-toolkit:review-pr <args>`, the worker executes it as the equivalent `spec-loop:review-pr <args>`.
- **`spec-loop:peer-review-council`** runs a **report-only** pass, picking depth via `review-depth-map`, and normalizes the findings onto its P0/P1/P2 scale using the canonical mapping above.

## Worked example

A slice worker's plan header set `review="spec-loop:review-pr exhaustive"` for a Tier-3 change touching `src/export.py`. At Step 3 the worker dispatches — in one message, each `run_in_background: false` — the five review agents against the slice diff:

```
spec-loop:review-pr exhaustive
# scope: slice diff  a7981ec..3df7661  (src/export.py, tests/test_export.py)
# forced: guideline-reviewer, pr-test-analyzer, comment-analyzer,
#         silent-failure-hunter, type-design-analyzer  (parallel, P0–P3)
```

Expected aggregated output:

```markdown
# PR Review Summary

## Critical Issues (1 found)
- [silent-failure-hunter] Auth check skipped on the streaming path — unauthenticated export possible [src/export.py:41]

## Important Issues (1 found)
- [pr-test-analyzer] No test asserts delimiter escaping round-trips [tests/test_export.py]

## Suggestions (1 found)
- [guideline-reviewer] Duplicated header-formatting block; extract a helper [src/export.py:88]

## Nitpicks (P3, non-blocking)
- [comment-analyzer] Docstring says "returns list" but function yields [src/export.py:50]

## Strengths
- Streaming implementation avoids buffering the full result set

## Recommended Action
1. Fix critical issues first
2. Address important issues
3. Consider suggestions
4. Re-run review after fixes
```

The Critical → P0 / Important → P1 / Suggestion → P2 / Nitpick → P3 mapping lets the slice worker compare these findings against its plan header's blocking bar without re-reading the agents.

## When NOT to use this

- **Read-only review of a merged or open PR against business requirements** → `spec-loop:peer-review-council`. That skill *calls* this one in report-only mode for corroboration, but it owns the requirement-traceability matrix and the published report.
- **Deciding how deep the review goes** (which aspects, which mode, what blocks) → `spec-loop:review-depth-map`.
- **Acting on review feedback** (verifying a finding, pushing back, applying a fix) → `spec-loop:code-review-discipline` (Part 2). This skill produces findings; that skill governs how you respond to them.
- **Choosing whether to interrupt the human** on an unfixable block → `spec-loop:escalation-gate`.

## Provenance and maintenance

Ported from `pr-review-toolkit` (Anthropic, claude-plugins-official marketplace) `commands/review-pr.md` on 2026-07-13; adapted for spec-loop:
- **Command → skill reframing.** Reframed as a subagent-loadable contract (this file) with a thin same-name command wrapper, following the precedent of `spec-loop:quality-gate` and `spec-loop:knowledge-graph`. `pr-review-toolkit` is not a live dependency.
- **Agent renames.** `code-reviewer` → `spec-loop:guideline-reviewer` (disambiguated from other reviewers and named for what it does — checks project guidelines). The other four review agents and `code-simplifier` keep their names under the `spec-loop:` namespace.
- **Native `exhaustive` mode + P3 band (NEW, unproven).** Forces all five review agents in parallel with a P3 nitpick band; replaces the formerly-optional external `/exhaustive-pr-review:exhaustive-pr all parallel` for Tier 3. New in spec-loop 2026-07-13 — treat as unproven until it has runtime mileage.
- **Canonical severity mapping moved here.** The Critical/Important/Suggestion → P0/P1/P2 (+P3) table now lives in this skill's Aggregation section; `spec-loop:peer-review-council` cross-references it instead of pinning its own copy.
- **Report-only mode formalized.** The flag `peer-review-council` needs (no simplify, no fixes, findings-only) is now a first-class part of the contract.

Re-verify if things drift:
- `ls plugins/spec-loop/agents/guideline-reviewer.md plugins/spec-loop/agents/code-simplifier.md plugins/spec-loop/agents/comment-analyzer.md plugins/spec-loop/agents/pr-test-analyzer.md plugins/spec-loop/agents/silent-failure-hunter.md plugins/spec-loop/agents/type-design-analyzer.md`
- `grep -n "spec-loop:review-pr" plugins/spec-loop/skills/review-depth-map/SKILL.md plugins/spec-loop/agents/spec-loop-slice.md`
- `python3 scripts/validate_marketplace.py .`
