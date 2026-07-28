---
name: dispatching-parallel-agents
description: Use when facing 2+ independent failures, bugs, or subsystems that can be worked on with no shared state and no sequential dependencies — dispatch one isolated-context agent per domain and run them concurrently
---

# Dispatching Parallel Agents — one isolated agent per independent domain

## Overview

You delegate a task to an agent with **isolated context**: it never inherits
your session history, so everything it needs goes into its prompt. When several
unrelated problems each stand alone (different test files, different subsystems,
different bugs), dispatch one agent per independent problem domain and let them
work concurrently.

Use this when each problem can be understood and fixed without context from the
others and no shared state links them. Don't use it when failures may be related
(investigate together first), when agents would touch the same files or
resources, or when the work is still exploratory. If unsure whether two problems
are independent, treat them as related — a false-parallel dispatch produces
conflicting edits that cost more than the time saved.

## The pattern

1. **Identify independent domains.** Group failures by what is broken; each
   group must be fixable on its own.
2. **Write focused, self-contained prompts.** Each carries: the scope (one file
   or subsystem, named), the goal (observable outcome), constraints (what not to
   touch), and the expected return (root cause + what changed). Paste in the
   error messages — the agent sees none of your context.
3. **Dispatch in a single response.** Multiple dispatch calls in one response
   run concurrently; one per response runs sequentially.
4. **Review and integrate.** Read each summary, check for conflicting edits, run
   the full suite (not just the individual files), and spot-check — agents can
   make systematic errors.

## Subagent nesting

**Canonical statement — other skills point here:** only a top-level session may
dispatch background (concurrent) agents. From inside any agent — including a
spec-loop slice worker — every dispatch MUST be synchronous
(`run_in_background: false`); the platform forbids in-process teammates from
spawning background agents. A single message of synchronous Task calls still
runs them concurrently, but true background fan-out is available only at the
top level.

## When NOT to use this

This skill is for ad-hoc fan-out over independent, stateless problems — not for
spec-loop's structured execution paths:

- **Sequential plan execution → `spec-loop:subagent-driven-development`.** Its
  implementers run deliberately one at a time because later tasks build on the
  committed state of earlier ones; fanning them out would corrupt that shared,
  evolving state.
- **Cross-slice parallelism → the `/spec-loop` controller's wave scheduler.**
  The run already parallelizes independent slices through its DAG; a slice
  worker is itself an agent and dispatches synchronously (nesting rule above).
- **Related, shared-context, or exploratory work → one agent** (or your own
  session).
