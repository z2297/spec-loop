---
name: systematic-debugging
description: Use when encountering any bug, test failure, or unexpected behavior, before proposing fixes — enforces root-cause investigation over symptom patching, gates each debugging phase on the previous, and stops thrashing after 3 failed fixes
---

# Systematic Debugging — root cause before any fix

## Overview

Random fixes waste time and create new bugs. Quick patches mask underlying issues.

**Core principle:** find root cause before attempting fixes. A symptom fix is a failure, not a partial success.

## The Iron Law

```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```

If you haven't completed Phase 1, you cannot propose fixes.

## When to Use

Any technical issue: test failures, production bugs, unexpected behavior, performance problems, build failures, integration issues.

The pressure to skip this is highest exactly where it costs most — under a deadline, when "just one quick fix" looks obvious, when you have already tried two fixes, when you don't fully understand the issue. Simple-looking bugs have root causes too, and systematic is faster than thrashing.

## When NOT to use this

- **You have not yet observed a failure.** This skill starts from a symptom; there is nothing to investigate without one.
- **You are about to claim work is complete/fixed/passing and need to prove it** → `spec-loop:verification-before-completion` (a hard, no-human gate). This skill finds the cause; that skill confirms the cure.
- **You are writing the failing test Phase 4 calls for** → hand off to `spec-loop:test-driven-development` for the red→green→refactor mechanics.

## The Four Phases

Complete each phase before proceeding to the next.

### Phase 1: Root Cause Investigation

**Gate: you understand WHAT is happening and WHY, before any fix is proposed.**

- **Read the error completely** — full stack trace, line numbers, file paths, error codes. Errors and warnings often contain the exact solution.
- **Reproduce consistently** — exact steps, every time. Not reproducible means gather more data, not guess.
- **Check recent changes** — git diff and recent commits, new dependencies, config changes, environmental differences.
- **Instrument component boundaries** in multi-component systems (CI → build → signing, API → service → database). Before proposing a fix, log what data enters and exits each component, verify environment/config propagation, and check state at each layer. Run once to gather evidence showing *where* it breaks, then investigate that specific component.
- **Trace data flow backward** when the error is deep in the call stack: where did the bad value originate, what called this with it, keep going up to the source. Fix at the source, not at the symptom.

### Phase 2: Pattern Analysis

**Gate: you can name every difference between what works and what is broken.**

Find similar working code in the same codebase. If you are implementing a documented pattern, read the reference implementation completely — skimming guarantees you miss the line that matters. List every difference between working and broken, however small; "that can't matter" is a hypothesis, not a fact. Understand what the broken code depends on: other components, settings, config, environment, and the assumptions it makes.

### Phase 3: Hypothesis and Testing

**Gate: one stated hypothesis, tested by one minimal change.**

State it explicitly — "I think X is the root cause because Y" — specific, written down. Test it with the smallest possible change, one variable at a time. If it worked, go to Phase 4. If it didn't, form a *new* hypothesis; do not stack another fix on top of the failed one. When you don't understand something, say "I don't understand X" and research it rather than proceeding on a guess.

### Phase 4: Implementation

**Gate: a failing test exists before the fix, and passes after it.**

1. **Create the failing test case** — simplest possible reproduction, automated if a framework exists, a one-off script if not. Use `spec-loop:test-driven-development` for the mechanics.
2. **Implement a single fix** addressing the identified root cause. One change; no "while I'm here" improvements, no bundled refactoring.
3. **Verify** — the test passes, no other tests broke, the original issue is actually resolved.
4. **If the fix didn't work,** stop and count your attempts. Under 3: return to Phase 1 and re-analyze with what you just learned. At 3 or more: do not attempt another fix — go to Phase 4.5.

### Phase 4.5: Question the Architecture (after 3+ failed fixes)

Three failures is a signal about the design, not about your luck. The pattern to recognize: each fix reveals new shared state or coupling somewhere else, each fix creates new symptoms elsewhere, and the real fix keeps looking like "massive refactoring."

Stop and question fundamentals: is this pattern sound, or is it being kept through inertia? Should the architecture be refactored instead of the symptoms patched? Discuss with your human partner before attempting more fixes.

> **Inside a spec-loop run:** this human gate is governed by `spec-loop:escalation-gate` — do not stop the loop to ask directly. The 3-fixes-failed condition is a material-assumption + ambiguity trigger: route it through the gate (batched at the wave boundary), which decides proceed-and-log vs. surface to the human and records the decision. Outside a run, talk to your human partner directly.

## Quick Reference

| Phase | Key activities | Gate |
|-------|---------------|------|
| **1. Root Cause** | Read errors, reproduce, check changes, instrument boundaries, trace backward | Understand WHAT and WHY |
| **2. Pattern** | Find working examples, read references fully, list differences | Every difference identified |
| **3. Hypothesis** | State one theory, test minimally | Confirmed, or a new hypothesis |
| **4. Implementation** | Failing test, single fix, verify | Bug resolved, tests pass |
| **4.5. Architecture** | After 3 failed fixes: question the pattern | Human decision (via escalation-gate in a run) |

## When Process Reveals "No Root Cause"

If systematic investigation shows the issue is truly environmental, timing-dependent, or external: document what you investigated, implement appropriate handling (retry, timeout, clear error message), and add monitoring or logging for future investigation. But treat this conclusion with suspicion — most "no root cause" cases are incomplete investigation.

## Supporting Techniques

Load these from this directory when the situation calls for them:

- [root-cause-tracing.md](root-cause-tracing.md) — when the error surfaces deep in a call stack and you need the full backward-tracing technique for Phase 1.
- [defense-in-depth.md](defense-in-depth.md) — after the root cause is found, when a bad value should be caught at more than one layer.
- [condition-based-waiting.md](condition-based-waiting.md) — when the bug is a flaky timing failure and the code waits on arbitrary timeouts.
- `find-polluter.sh` — bisect a test suite to find which test creates unwanted files or state.

**Related skills:**
- `spec-loop:test-driven-development` — for creating the failing test case (Phase 4, step 1).
- `spec-loop:verification-before-completion` — verify the fix worked before claiming success (never overridden, even inside a run).
