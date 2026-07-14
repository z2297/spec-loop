---
name: finishing-a-development-branch
description: Use when implementation is complete and tests pass and you must decide how to integrate the work — presents structured merge / PR / keep / discard options, detects worktree vs detached-HEAD environment, and cleans up only worktrees it owns
---

# Finishing a Development Branch — merge, PR, keep, or discard, safely

## Overview

Guide completion of finished development work: verify tests, detect the workspace, present a small fixed menu, execute the chosen workflow, and clean up only what this process created.

**Core principle:** Verify tests → Detect environment → Present options → Execute choice → Clean up.

Announce at the start: "Using `spec-loop:finishing-a-development-branch` to complete this work."

**Inside a spec-loop run:** the options menu below is an interactive/standalone human gate, and it is **governed by `spec-loop:escalation-gate`** — a background slice worker cannot prompt the human and never chooses an integration option. The controller owns integration (see "Inside a spec-loop run" below). The **test-verification gate (Step 1) is never overridden** — it is an instance of `spec-loop:verification-before-completion`, a hard no-human gate. Outside a run (interactive use), the whole menu applies as written.

## Step 1 — Verify tests

Before presenting any option, verify the project's suite passes. This is an instance of `spec-loop:verification-before-completion`: evidence before any completion claim.

```bash
# Run the project's test suite (pick the one that applies)
npm test        # or: cargo test / pytest / go test ./...
```

**If tests fail — stop. Do not proceed to Step 2.** Report:

```
Tests failing (<N> failures). Must fix before completing:

[show failures]

Cannot proceed with merge/PR until tests pass.
```

**If tests pass:** continue to Step 2.

## Step 2 — Detect environment

Determine the workspace state before presenting options — it selects which menu to show and how cleanup works.

```bash
GIT_DIR=$(cd "$(git rev-parse --git-dir)" 2>/dev/null && pwd -P)
GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd -P)
```

| State | Menu | Cleanup |
|-------|------|---------|
| `GIT_DIR == GIT_COMMON` (normal repo) | Standard 4 options | No worktree to clean up |
| `GIT_DIR != GIT_COMMON`, named branch (worktree) | Standard 4 options | Provenance-based (see Step 6) |
| `GIT_DIR != GIT_COMMON`, detached HEAD | Reduced 3 options (no local merge) | None — externally managed |

A **worktree** is a second working directory linked to the same repository (`git worktree`); its `git-dir` differs from the `git-common-dir`. See `spec-loop:using-git-worktrees` for how they are created and named. A **detached HEAD** means the checkout points at a commit rather than a branch — you cannot cleanly merge *into* a base branch locally, so the menu drops that option.

## Step 3 — Determine base branch

```bash
# Find the branch this work split from
git merge-base HEAD main 2>/dev/null || git merge-base HEAD master 2>/dev/null
```

If neither resolves, ask: "This branch split from `main` — is that correct?"

## Step 4 — Present options

Present **exactly** these — verbatim. **Don't add explanation**; keep the menu concise.

**Normal repo and named-branch worktree — 4 options:**

```
Implementation complete. What would you like to do?

1. Merge back to <base-branch> locally
2. Push and create a Pull Request
3. Keep the branch as-is (I'll handle it later)
4. Discard this work

Which option?
```

**Detached HEAD — 3 options (no local merge):**

```
Implementation complete. You're on a detached HEAD (externally managed workspace).

1. Push as new branch and create a Pull Request
2. Keep as-is (I'll handle it later)
3. Discard this work

Which option?
```

## Step 5 — Execute the choice

### Option 1: Merge locally

Merge first, verify tests on the **merged result**, and only then clean up. Never remove anything before confirming the merge succeeded.

```bash
# cd to the main repo root for CWD safety (never merge from inside the worktree)
MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)
cd "$MAIN_ROOT"

git checkout <base-branch>
git pull
git merge <feature-branch>

# Verify tests on the merged result
<test command>
```

Only after the merge succeeds and tests pass on the result: clean up the worktree (Step 6), **then** delete the branch:

```bash
git branch -d <feature-branch>
```

Order matters — `git branch -d` fails while a worktree still references the branch.

### Option 2: Push and create a PR

```bash
git push -u origin <feature-branch>
```

**Do NOT clean up the worktree** — the user needs it alive to iterate on PR feedback. No Step 6.

### Option 3: Keep as-is

Report: "Keeping branch `<name>`. Worktree preserved at `<path>`." **Do not clean up the worktree.** No Step 6.

### Option 4: Discard

Require an explicit typed confirmation before any destructive command:

```
This will permanently delete:
- Branch <name>
- All commits: <commit-list>
- Worktree at <path>

Type 'discard' to confirm.
```

Wait for the exact word `discard`. Only if confirmed:

```bash
MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)
cd "$MAIN_ROOT"
```

Then clean up the worktree (Step 6), **then** force-delete the branch:

```bash
git branch -D <feature-branch>
```

## Step 6 — Clean up workspace

**Runs only for Options 1 and 4.** Options 2 and 3 always preserve the worktree.

```bash
GIT_DIR=$(cd "$(git rev-parse --git-dir)" 2>/dev/null && pwd -P)
GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd -P)
WORKTREE_PATH=$(git rev-parse --show-toplevel)
```

**Provenance check — remove only worktrees this tooling created:**

- **If `GIT_DIR == GIT_COMMON`:** normal repo, no worktree to clean up. Done.
- **If `WORKTREE_PATH` is under `.worktrees/` or `worktrees/`:** this tooling created the worktree — we own its cleanup.

  ```bash
  MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)
  cd "$MAIN_ROOT"                       # never remove a worktree from inside it
  git worktree remove "$WORKTREE_PATH"
  git worktree prune                    # self-healing: clear any stale registrations
  ```

- **Otherwise:** the host environment (harness) owns this workspace. **Do NOT remove it** — that causes phantom state. If your platform provides a workspace-exit tool, use it; otherwise leave the workspace in place.

## Inside a spec-loop run

During an active `/spec-loop` run this skill's menu does **not** drive integration — the controller does. Verified against `plugins/spec-loop/agents/spec-loop-slice.md` (Step 5) and `plugins/spec-loop/commands/spec-loop.md` (Phase 3):

- **`single-branch` mode (the default).** A slice worker finishes as a **verified, committed branch** and stops — it does not merge, push, open a PR, or remove its own worktree. The **controller** performs the serial merge into the single integration branch (sitting on `base_ref`, one slice at a time, `git merge --no-ff spec-loop/<run-id>/<slice-id>`), then removes the slice worktree and runs `git branch -d`. Slice workers **skip this skill entirely** here — self-merging would race with sibling slices landing on the same branch.
- **`--per-slice-pr` mode (only when the controller passes it).** The slice worker *does* use this skill and takes **Option 2** (push + open a PR), passed as a declared preference since it runs in the background and cannot answer a prompt. It never falls back to a local merge in this mode.

So the four-option menu is for **interactive / standalone** use. A background slice worker never chooses an integration option; `spec-loop:escalation-gate` owns all human contact during a run.

**The guard hook (`spec_loop_guard.py`) mechanically blocks the wrong moves during an active run** (while a `docs/spec-loop/<run-id>/.active` marker exists and before the `.publish-choice` marker): `git push` that targets the run (except in `per-slice-pr` mode, where slices legitimately push), and any `git commit` / `git merge` while sitting on `main`/`master`. Don't try to work around it — publishing the integration branch and any main-branch merge are reserved for the human's Phase 5 publish choice.

## Quick reference

| Option | Merge | Push | Keep worktree | Delete branch |
|--------|-------|------|---------------|---------------|
| 1. Merge locally | yes | — | — | yes (`-d`) |
| 2. Create PR | — | yes | yes | — |
| 3. Keep as-is | — | — | yes | — |
| 4. Discard | — | — | — | yes (`-D`, force) |

## When NOT to use this

- **You have not finished, or tests are red.** Finish first; use `spec-loop:verification-before-completion` to establish passing evidence. This skill starts *from* a green suite.
- **You are a background spec-loop slice worker in `single-branch` mode.** Do not run this skill — stop at a verified committed branch and let the controller integrate (see "Inside a spec-loop run").
- **You only need to create the isolated workspace, not finish it.** Use `spec-loop:using-git-worktrees`.
- **The work isn't integration-ready and you're mid-implementation.** Keep executing your plan; come back here when it's done.

## Common mistakes

| Mistake | Problem | Fix |
|---------|---------|-----|
| Skipping test verification | Merge broken code / open a failing PR | Always verify tests before offering options (Step 1) |
| Open-ended "what next?" | Ambiguous; invites scope creep | Present exactly the 4 (or 3) fixed options |
| Cleaning up the worktree for Option 2 | Removes the worktree the user needs for PR iteration | Clean up for Options 1 and 4 only |
| Deleting the branch before removing the worktree | `git branch -d` fails while the worktree references it | Merge → remove worktree → delete branch, in that order |
| `git worktree remove` from inside the worktree | Fails silently when CWD is inside the target | `cd` to the main repo root first |
| Cleaning up a harness-owned worktree | Removing a worktree you didn't create causes phantom state | Only remove worktrees under `.worktrees/` or `worktrees/` |
| No confirmation for discard | Accidentally destroys work | Require the typed word `discard` |

## Red flags

**Never:**
- Proceed with failing tests.
- Merge without verifying tests on the merged result.
- Delete work without the typed `discard` confirmation.
- Force-push without an explicit request.
- Remove a worktree before confirming the merge succeeded.
- Clean up a worktree you didn't create (run the provenance check).
- Run `git worktree remove` from inside the worktree being removed.
- (In a run) push mid-run or merge on `main`/`master` — the guard hook blocks it and the human owns the Phase 5 publish choice.

**Always:**
- Verify tests before offering options.
- Detect the environment before presenting the menu.
- Present exactly 4 options (or 3 for detached HEAD).
- Get typed confirmation for Option 4.
- Clean up the worktree for Options 1 and 4 only.
- `cd` to the main repo root before worktree removal, and `git worktree prune` after.

## Provenance and maintenance

Ported from `superpowers` v6.1.1 (github.com/obra/superpowers, MIT) `skills/finishing-a-development-branch` on 2026-07-08; adapted for spec-loop. Adaptations: added the spec-loop run-override (menu governed by `escalation-gate`; controller-owned serial merge; `per-slice-pr` = Option 2) and the guard-hook note; cross-linked `spec-loop:verification-before-completion` and `spec-loop:using-git-worktrees`; added a "When NOT to use this" section. No cross-harness content existed in the source to cut.

Re-verify if things drift:
- Sibling skill names still exist: `ls plugins/spec-loop/skills/{verification-before-completion,using-git-worktrees,escalation-gate}/SKILL.md` (the first two are authored concurrently as of 2026-07-08).
- Run-override still matches the loop: `spec-loop-slice.md` Step 5 and `commands/spec-loop.md` Phase 3 (controller serial merge) — `grep -n "single-branch\|per-slice-pr\|finishing-a-development-branch" plugins/spec-loop/agents/spec-loop-slice.md`.
- Guard behavior still matches: `grep -n "push\|commit\|merge\|main\|publish" plugins/spec-loop/scripts/spec_loop_guard.py`.
