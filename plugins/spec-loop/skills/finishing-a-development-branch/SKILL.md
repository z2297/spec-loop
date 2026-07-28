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

**If tests fail — stop. Do not proceed to Step 2.** Report the failures and state that merge/PR cannot proceed until they pass. **If tests pass:** continue to Step 2.

## Step 2 — Detect environment

Determine the workspace state before presenting options — it selects which menu to show and how cleanup works. A **worktree** is a second working directory linked to the same repository (`git worktree`); its `git-dir` differs from the `git-common-dir` — see `spec-loop:using-git-worktrees`. A **detached HEAD** points at a commit rather than a branch, so it cannot cleanly merge *into* a base branch locally and the menu drops that option.

```bash
GIT_DIR=$(cd "$(git rev-parse --git-dir)" 2>/dev/null && pwd -P)
GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd -P)
```

| State | Menu | Cleanup |
|-------|------|---------|
| `GIT_DIR == GIT_COMMON` (normal repo) | Standard 4 options | No worktree to clean up |
| `GIT_DIR != GIT_COMMON`, named branch (worktree) | Standard 4 options | Provenance-based (see Step 6) |
| `GIT_DIR != GIT_COMMON`, detached HEAD | Reduced 3 options (no local merge) | None — externally managed |

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

Only after the merge succeeds and tests pass on the result: clean up the worktree (Step 6), **then** delete the branch. Order matters — `git branch -d` fails while a worktree still references the branch.

```bash
git branch -d <feature-branch>
```

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

Wait for the exact word `discard`. Only if confirmed, move to the main repo root, clean up the worktree (Step 6), **then** force-delete the branch:

```bash
MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)
cd "$MAIN_ROOT"
# ... Step 6 cleanup ...
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

**The guard hook (`spec_loop_guard.py`) mechanically blocks the wrong moves during an active run** (while a `docs/spec-loop/<run-id>/.active` marker exists and before the `.publish-choice` marker): `git push` that targets the run (except in `per-slice-pr` mode, where slices legitimately push), and any `git commit` / `git merge` while sitting on `main`/`master`. Publishing the integration branch and any main-branch merge are reserved for the human's Phase 5 publish choice.

## When NOT to use this

- **You have not finished, or tests are red.** Finish first; `spec-loop:verification-before-completion` establishes passing evidence. This skill starts *from* a green suite.
- **You are a background spec-loop slice worker in `single-branch` mode.** Stop at a verified committed branch and let the controller integrate.
- **You only need to create the isolated workspace, not finish it.** Use `spec-loop:using-git-worktrees`.
