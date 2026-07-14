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

Prefer your harness's **native** worktree tools. Fall back to manual `git worktree`
only when no native tool exists. Detect existing isolation first so you never nest a
worktree inside a worktree.

**Core principle:** Detect existing isolation → use native tools → fall back to git →
never fight the harness.

**Announce at start:** "I'm using the using-git-worktrees skill to set up an isolated workspace."

## Step 0: Detect existing isolation

**Before creating anything, check whether you are already in an isolated workspace.**

```bash
GIT_DIR=$(cd "$(git rev-parse --git-dir)" 2>/dev/null && pwd -P)
GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd -P)
BRANCH=$(git branch --show-current)
```

In a linked worktree, `GIT_DIR != GIT_COMMON`. But that inequality is **also** true
inside a git **submodule**, which is a normal repo you should treat normally.

**Submodule guard** — before concluding "already in a worktree", rule out a submodule:

```bash
# If this prints a path, you are in a submodule, NOT a worktree — treat as a normal repo.
git rev-parse --show-superproject-working-tree 2>/dev/null
```

**If `GIT_DIR != GIT_COMMON` and NOT a submodule:** you are already in a linked
worktree. **Skip to Step 2 (Project Setup).** Do NOT create another worktree.

Report with branch state:
- On a branch: "Already in isolated workspace at `<path>` on branch `<name>`."
- Detached HEAD: "Already in isolated workspace at `<path>` (detached HEAD, externally managed). Branch creation needed at finish time."

**If `GIT_DIR == GIT_COMMON` (or you are in a submodule):** you are in a normal repo checkout.

Has the user already declared a worktree preference in your instructions? If not, ask for
consent before creating one:

> "Would you like me to set up an isolated worktree? It protects your current branch from changes."

Honor any declared preference without asking. If the user declines, work in place and skip to Step 2.

> **Inside a spec-loop run:** this consent gate is governed by
> `spec-loop:escalation-gate`, not by asking the human. The controller has already
> decided each slice works in a worktree, so slice workers pass consent as **granted**
> and never prompt (they run in the background and cannot answer). See the pinned
> spec-loop note at the end of this skill. Outside a run (interactive use), the consent
> gate applies as written above.

## Step 1: Create the isolated workspace

**You have two mechanisms. Try them in this order.**

### 1a. Native worktree tools (preferred)

Step 0 established that isolation is wanted. Do you already have a harness tool that
creates a worktree? It may be named something like `EnterWorktree` or `WorktreeCreate`,
a `/worktree` command, or a `--worktree` flag. **If you do, use it and skip to Step 2.**

Native tools handle directory placement, branch creation, and cleanup automatically, and
the harness can see and manage what they create.

> **#1 mistake:** running `git worktree add` when a native tool exists. It creates
> **phantom state** your harness can't see or manage. If you have a native tool, use it —
> do not drop to Step 1b.

Only proceed to Step 1b if you have **no** native worktree tool available.

### 1b. Git worktree fallback

**Only use this if Step 1a does not apply.** Create a worktree manually with git.

#### Directory selection

Follow this priority order. An explicit user preference always beats observed filesystem state.

1. **Declared preference in your instructions.** If the user specified a worktree
   directory, use it without asking.
2. **Existing project-local worktree directory:**
   ```bash
   ls -d .worktrees 2>/dev/null     # preferred (hidden)
   ls -d worktrees 2>/dev/null      # alternative
   ```
   If found, use it. **If both exist, `.worktrees` wins.**
3. **Otherwise**, default to `.worktrees/` at the project root.

#### Safety verification (project-local directories only)

**You MUST verify the directory is git-ignored before creating a worktree in it:**

```bash
git check-ignore -q .worktrees 2>/dev/null || git check-ignore -q worktrees 2>/dev/null
```

- **If NOT ignored:** add it to `.gitignore`, commit that change, then proceed.
- **Why this is critical:** it prevents accidentally committing worktree contents into the repository.

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

Auto-detect the toolchain and run the appropriate install/build:

```bash
# Node.js
if [ -f package.json ]; then npm install; fi

# Rust
if [ -f Cargo.toml ]; then cargo build; fi

# Python
if [ -f requirements.txt ]; then pip install -r requirements.txt; fi
if [ -f pyproject.toml ]; then poetry install; fi

# Go
if [ -f go.mod ]; then go mod download; fi
```

Skip any step whose marker file is absent.

## Step 3: Verify a clean baseline

Run the test suite **before you start work** so a later failure is attributable to your change, not a pre-existing one:

```bash
# Use the project-appropriate command:
npm test        # Node
cargo test      # Rust
pytest          # Python
go test ./...   # Go
```

- **If tests fail:** report the failures and ask whether to proceed or investigate. Do not build on a red baseline.
- **If tests pass:** report ready.

### Report

```
Worktree ready at <full-path>
Tests passing (<N> tests, 0 failures)
Ready to implement <feature-name>
```

## Quick reference

| Situation | Action |
|-----------|--------|
| Already in a linked worktree | Skip creation (Step 0) |
| In a submodule | Treat as a normal repo (Step 0 guard) |
| Native worktree tool available | Use it (Step 1a) |
| No native tool | Git worktree fallback (Step 1b) |
| `.worktrees/` exists | Use it (verify ignored) |
| `worktrees/` exists | Use it (verify ignored) |
| Both exist | Use `.worktrees/` |
| Neither exists | Check instructions, then default `.worktrees/` |
| Directory not ignored | Add to `.gitignore` + commit |
| Permission error on create | Sandbox fallback, work in place |
| Tests fail during baseline | Report failures + ask |
| No package.json/Cargo.toml/etc. | Skip dependency install |

## Common mistakes

- **Fighting the harness** — using `git worktree add` when the platform already provides
  isolation. *Fix:* Step 0 detects existing isolation; Step 1a defers to native tools.
- **Skipping detection** — creating a nested worktree inside an existing one. *Fix:*
  always run Step 0 before creating anything.
- **Skipping ignore verification** — worktree contents get tracked and pollute
  `git status`. *Fix:* always `git check-ignore` before creating a project-local worktree.
- **Assuming the directory location** — creates inconsistency and violates project
  conventions. *Fix:* follow the priority (explicit instructions > existing project-local
  directory > default).
- **Proceeding with failing tests** — you can't distinguish new bugs from pre-existing
  ones. *Fix:* report failures and get explicit permission to proceed.

## Red flags

**Never:**
- Create a worktree when Step 0 detects existing isolation.
- Use `git worktree add` when you have a native worktree tool (e.g. `EnterWorktree`). This is the #1 mistake — if you have it, use it.
- Skip Step 1a by jumping straight to Step 1b's git commands.
- Create a project-local worktree without verifying it is ignored.
- Skip baseline test verification.
- Proceed with failing tests without asking.

**Always:**
- Run Step 0 detection first.
- Prefer native tools over the git fallback.
- Follow the directory priority: explicit instructions > existing project-local directory > default.
- Verify the directory is ignored for project-local worktrees.
- Auto-detect and run project setup.
- Verify a clean test baseline.

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

- **The work is already isolated** (Step 0 says you are in a linked worktree) — don't nest;
  just proceed to setup.
- **You are finishing, not starting** — to merge, PR, or clean up a completed worktree, use
  `spec-loop:finishing-a-development-branch`.
- **You are the consumer, not the setup step** — this skill is invoked *by*
  `spec-loop:executing-plans` and `spec-loop:subagent-driven-development` to guarantee an
  isolated workspace before they begin; run it once at the start, then hand back to them.
- **A trivial, in-place edit the user explicitly wants on the current branch** — isolation
  adds no value; respect the declined-consent path and work in place.

## Provenance and maintenance

Ported from `superpowers` v6.1.1 (github.com/obra/superpowers, MIT) `skills/using-git-worktrees`
on 2026-07-08; adapted for spec-loop. Cross-harness Platform-Adaptation content was not
present in the source and nothing harness-specific was added beyond the native-tool detection
already in the source.

Re-verify on drift:
- Sibling skill names still exist: `ls plugins/spec-loop/skills/{finishing-a-development-branch,executing-plans,subagent-driven-development,escalation-gate}/SKILL.md`
- spec-loop worktree layout/consent claims still match the worker: `sed -n '66,110p' plugins/spec-loop/agents/spec-loop-slice.md`
- Ephemeral-isolation and gitignore claims still match the README: `grep -n -A12 'Notes & limitations' plugins/spec-loop/README.md`
- Escalation-gate override wording still consistent: `sed -n '12,17p' plugins/spec-loop/skills/escalation-gate/SKILL.md`
