---
name: verification-before-completion
description: Use when about to claim work is complete, fixed, or passing, before committing or creating PRs, or before a slice reports DONE — requires running the verification command and reading its output before making any success claim; evidence before assertions, always
---

# Verification Before Completion — evidence before any completion claim

## Overview

Claiming work is complete without verification is dishonesty, not efficiency.

**Core principle:** Evidence before claims, always.

This gate is the one spec-loop commitment that is never relaxed for autonomy. See the
pinned note below.

## The Iron Law

```
NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE
```

If you haven't run the verification command **in this message**, you cannot claim it passes.

## The Gate Function

```
BEFORE claiming any status or expressing satisfaction:

1. IDENTIFY: What command proves this claim?
2. RUN:      Execute the FULL command (fresh, complete)
3. READ:     Full output, check exit code, count failures
4. VERIFY:   Does output confirm the claim?
             - If NO: State actual status with evidence
             - If YES: State claim WITH evidence
5. ONLY THEN: Make the claim

Skip any step = lying, not verifying
```

## What counts as evidence

Each claim has one thing that proves it. A stale, partial, or adjacent substitute proves
nothing.

- **Tests pass** — the full test command's output, zero failures, run now.
- **Linter clean / build succeeds** — each tool's own output. A clean linter says nothing
  about whether the code compiles.
- **Bug fixed** — the original symptom retested, not merely code changed.
- **Regression test works** — the red-green cycle actually observed: write it, run (pass),
  revert the fix, run (**must fail**), restore, run (pass).
- **Requirements met** — the plan re-read and checked item by item. Passing tests are not
  a coverage argument.
- **A subagent completed its work** — the VCS diff (`git diff`, `git status`), never the
  agent's own report. This is load-bearing in spec-loop: when a slice worker or the
  controller delegates, a subagent that says "done" has proven nothing until its diff is
  on disk and you have read it.

## Scoped vs. full verification (single home)

Scoping narrows the *claim*, never the *gate*. Two rules:

1. **Scoped test evidence.** A *task-level* completion claim (one task inside a slice)
   may be verified by the task's **covering tests** — the test files/filters that
   exercise the files the task touched, named by the dispatcher or derived from the
   diff (`npm test -- <paths>`, `pytest <paths>`, `go test ./pkg/...`,
   `dotnet test --filter`, …). If the covering set cannot be derived confidently, or
   the change touches shared infrastructure (build config, DI wiring, shared
   utilities, schema, lockfiles), run the full suite — ambiguity never narrows the
   scope. Scoped evidence never substitutes for the three **full-suite checkpoints**,
   which may never be scoped: **(a)** slice verification before `DONE`, **(b)** the
   controller's wave integration gate, **(c)** the Phase 5 integration gate.
2. **Evidence transfer by tree identity.** Fresh full-suite evidence attaches to a
   *git tree*, not a branch: if `git rev-parse <A>^{tree}` equals the tree the suite
   was verifiably run on (command + result + tree SHA recorded), the claim "this tree
   is green" transfers without re-running. Any tree mismatch, missing record, or
   doubt → run the suite (fail closed). This is the only sanctioned way to skip a
   full-suite run, and it never applies to checkpoints (a) or (c) — a slice always
   runs its own Step-5 suite (that run is the very evidence checkpoint (b) may
   transfer), and the Phase 5 gate always runs fresh.

## This gate is never overridden by the autonomy contract

**Pinned.** During an active spec-loop run, `spec-loop:escalation-gate` governs every
*human* checkpoint (design approval, consent-before-`main`, stop-and-ask, review BLOCK
surfacing). It does **not** govern this one. `verification-before-completion` is a hard,
no-human, evidence-before-claims gate and it stays in force at every layer of a run:

- **Slice worker** — a slice may not return `DONE` until its full test/build command has
  been run fresh and read in the same message (slice verification step); scoped task
  runs earlier in the slice never satisfy this.
- **Controller merge gate** — the controller may not merge a slice into the integration
  branch on the slice's word alone; the merge gate stands on fresh evidence, not on the
  slice's self-report.
- **Integration gate (Phase 5)** — the run is not "green" until the integration
  verification command has been run and read fresh.

`escalation-gate` saying PROCEED never authorizes skipping this gate. The two are
independent: one decides *whether to interrupt the human*, this one decides *whether you
have earned a completion claim*. There is no autonomy exception and no human to wave it
through — the evidence is the only authority.

The blast radius inside a run is larger than in interactive work: an unverified `DONE`
merges into the integration branch and every downstream slice inherits a false foundation.

## When to apply

Before any claim of success, completion, or correctness — including paraphrases,
implications, and expressions of satisfaction. Concretely: before committing, opening a
PR, returning a slice `DONE`, a controller merge, the Phase 5 integration gate, moving to
the next task, and accepting a result from a subagent.

## When NOT to use this

This skill is never "not applicable" — the gate always stands. But if your situation is
actually a different one, reach for the sibling skill instead:

- You are **writing or fixing** code and need the discipline for *how* to build it
  test-first → `spec-loop:test-driven-development` (this skill only verifies the result).
- A test or build is **failing** and you need to find out *why* before you can verify
  anything → `spec-loop:systematic-debugging`. Return here once you have a fix to verify.
- You need to decide whether to **stop and ask the human** → `spec-loop:escalation-gate`.
  That is a separate decision and it never lets you skip this gate.

Run the command. Read the output. Then claim the result.
