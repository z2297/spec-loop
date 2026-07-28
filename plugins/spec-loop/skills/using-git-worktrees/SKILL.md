---
name: using-git-worktrees
description: Use when starting feature work that needs isolation from the current workspace, or before executing an implementation plan — ensures an isolated workspace exists via native tools or a git worktree fallback, with a verified clean baseline
---

# Using Git Worktrees — isolate the work before you touch it

## Overview

Ensure work happens in an isolated workspace so your changes never contaminate the
user's current branch. A **worktree** is a second working directory linked to the same
repository, checked out on its own branch — you edit in it freely while the original
checkout stays untouched.

**Core principle:** Detect existing isolation → use native tools → fall back to git →
never fight the harness.

**Announce at start:** "I'm using the using-git-worktrees skill to set up an isolated workspace."

## Step 0: Detect existing isolation

Before creating anything, check whether you are already in an isolated workspace.

```bash
GIT_DIR=$(cd "$(git rev-parse --git-dir)" 2>/dev/null && pwd -P)
GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd -P)
BRANCH=$(git branch --show-current)
```

In a linked worktree, `GIT_DIR != GIT_COMMON`. That inequality is **also** true inside a
git **submodule**, which is a normal repo you should treat normally.

**Submodule guard** — before concluding "already in a worktree", rule out a submodule:

```bash
# If this prints a path, you are in a submodule, NOT a worktree — treat as a normal repo.
git rev-parse --show-superproject-working-tree 2>/dev/null
```

**If `GIT_DIR != GIT_COMMON` and NOT a submodule:** you are already in a linked worktree.
**Skip to Step 2 (Project Setup).** Do not create another worktree. Report with branch state:

- On a branch: "Already in isolated workspace at `<path>` on branch `<name>`."
- Detached HEAD: "Already in isolated workspace at `<path>` (detached HEAD, externally managed). Branch creation needed at finish time."

**If `GIT_DIR == GIT_COMMON` (or you are in a submodule):** you are in a normal repo checkout.

Has the user already declared a worktree preference in your instructions? Honor it without
asking. If not, ask for consent before creating one:

> "Would you like me to set up an isolated worktree? It protects your current branch from changes."

If the user declines, work in place and skip to Step 2.

> **Inside a spec-loop run:** this consent gate is governed by
> `spec-loop:escalation-gate`, not by asking the human. The controller has already
> decided each slice works in a worktree, so slice workers pass consent as **granted**
> and never prompt (they run in the background and cannot answer). See the pinned
> spec-loop note at the end of this skill. Outside a run (interactive use), the consent
> gate applies as written above.

## Step 1: Create the isolated workspace

Two mechanisms, tried in this order.

### 1a. Native worktree tools (preferred)

Step 0 established that isolation is wanted. Do you already have a harness tool that
creates a worktree? It may be named something like `EnterWorktree` or `WorktreeCreate`,
a `/worktree` command, or a `--worktree` flag. **If you do, use it and skip to Step 2.**
Native tools handle directory placement, branch creation, and cleanup automatically, and
the harness can see and manage what they create.

> **#1 mistake:** running `git worktree add` when a native tool exists. It creates
> **phantom state** your harness can't see or manage. Only proceed to Step 1b if you have
> no native worktree tool available.

### 1b. Git worktree fallback

**Only if Step 1a does not apply.** Create a worktree manually with git.

#### Directory selection

Follow this priority order. An explicit user preference always beats observed filesystem state.

1. **Declared preference in your instructions.** Use it without asking.
2. **Existing project-local worktree directory:**
   ```bash
   ls -d .worktrees 2>/dev/null     # preferred (hidden)
   ls -d worktrees 2>/dev/null      # alternative
   ```
   If found, use it. **If both exist, `.worktrees` wins.**
3. **Otherwise**, default to `.worktrees/` at the project root.

#### Safety verification (project-local directories only)

Verify the directory is git-ignored before creating a worktree in it — this is what
prevents worktree contents from being committed into the repository.

```bash
git check-ignore -q .worktrees 2>/dev/null || git check-ignore -q worktrees 2>/dev/null
```

If it is **not** ignored: add it to `.gitignore`, commit that change, then proceed.

#### Create the worktree

```bash
# LOCATION is the directory chosen above; BRANCH_NAME is the branch to create.
path="$LOCATION/$BRANCH_NAME"

git worktree add "$path" -b "$BRANCH_NAME"
cd "$path"
```

**Sandbox fallback:** if `git worktree add` fails with a permission error (a sandbox
denial), tell the user the sandbox blocked worktree creation and that you are working in
the current directory instead. Then run setup and baseline tests **in place**.

## Step 2: Project setup

Auto-detect the toolchain from its marker file and run the install/build, skipping any
whose marker is absent: `package.json` → `npm install`; `Cargo.toml` → `cargo build`;
`requirements.txt` → `pip install -r requirements.txt`; `pyproject.toml` → `poetry install`;
`go.mod` → `go mod download`.

## Step 3: Verify a clean baseline

Run the project's test suite (`npm test` / `cargo test` / `pytest` / `go test ./...`)
**before you start work**, so a later failure is attributable to your change rather than a
pre-existing one.

- **If tests fail:** report the failures and ask whether to proceed or investigate. Do not
  build on a red baseline.
- **If tests pass:** report ready.

```
Worktree ready at <full-path>
Tests passing (<N> tests, 0 failures)
Ready to implement <feature-name>
```

## Inside a spec-loop run (pinned)

During a spec-loop run this skill is the mechanism each **slice worker**
(`spec-loop:spec-loop-slice`) uses for its **first action**, before any exploration,
planning, or edits. The controller owns the policy; this skill owns the mechanics.

- **Layout (fixed, not the interactive default):** worktree path
  `.worktrees/spec-loop/<run-id>/<slice-id>`, branch `spec-loop/<run-id>/<slice-id>` —
  unique per slice, never shared. The worker passes these as the declared directory/branch
  so Step 1b uses them directly.
- **Consent does not apply here.** The controller already decided every slice runs in a
  worktree, so consent is passed as **granted** and the worker never prompts. Human contact
  during a run is owned by `spec-loop:escalation-gate`, not by this skill's Step 0 question.
- **`.worktrees/` must be gitignored** — this skill's Step 1b `git check-ignore` step (add
  to `.gitignore` + commit if missing) is exactly what guarantees that invariant for the run.
- **Verified clean baseline is mandatory** (Steps 2–3). If the baseline is already broken
  before the worker changes anything, that is a pre-existing condition: the worker runs
  `escalation-gate` and returns `NEEDS_DECISION` rather than building on a red baseline.
- **Ephemeral isolation detail, not deliverables.** These per-slice branches/worktrees are
  owned by the controller: it merges each into the singular integration branch and deletes
  it (they survive only in `--per-slice-pr` mode). Stale worktrees from an aborted run are
  removed and recreated; a worktree is reused only when resuming a paused slice with
  committed progress. Slice workers never merge into `main`/`master`.

## When NOT to use this

Already isolated (Step 0 says so) — don't nest, go straight to setup. Finishing rather
than starting — use `spec-loop:finishing-a-development-branch`. A trivial in-place edit
the user wants on the current branch — respect the declined-consent path.
