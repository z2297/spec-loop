---
name: writing-skills
description: Use when creating a new skill, editing an existing skill, or verifying a skill works before deployment — and when adding or changing a bundled script, command, agent, or guard in the spec-loop plugin that a skill relies on
---

# Writing Skills — TDD for process documentation

## Overview

**Writing a skill IS Test-Driven Development applied to process documentation.**

You write test cases (pressure scenarios run against subagents), watch them fail (baseline behavior with no skill), write the skill (the documentation), watch the tests pass (agents now comply), and refactor (close the loopholes agents find).

**Core principle:** If you didn't watch an agent fail *without* the skill, you don't know whether the skill teaches the right thing.

**REQUIRED BACKGROUND:** You MUST understand `spec-loop:test-driven-development` before using this skill. That skill defines the RED-GREEN-REFACTOR cycle; this skill adapts it to documentation.

**Official guidance:** For Anthropic's skill-authoring best practices (context budget, naming, description craft, packaging), read `anthropic-best-practices.md` in this directory. It complements the TDD-focused method here.

## What a skill is

A **skill** is a reference guide for a proven technique, pattern, or tool. It helps a future agent find and apply an effective approach.

**Skills ARE:** reusable techniques, patterns, tools, reference guides.
**Skills are NOT:** narratives about how you solved one problem once ("In the 2025-10-03 session we found…"). Too specific, not reusable.

## TDD mapping for skills

| TDD concept | Skill creation |
|-------------|----------------|
| Test case | Pressure scenario with a subagent |
| Production code | Skill document (SKILL.md) |
| Test fails (RED) | Agent violates the rule without the skill (baseline) |
| Test passes (GREEN) | Agent complies with the skill present |
| Refactor | Close loopholes while keeping compliance |
| Write test first | Run the baseline scenario BEFORE writing the skill |
| Watch it fail | Document the exact rationalizations the agent uses |
| Minimal code | Write only enough skill to address those violations |
| Watch it pass | Verify the agent now complies |
| Refactor cycle | Find new rationalization → plug → re-verify |

The entire creation process follows RED-GREEN-REFACTOR.

## The Iron Law (same as TDD)

```
NO SKILL WITHOUT A FAILING TEST FIRST
```

This applies to NEW skills **and to EDITS of existing skills.**

Wrote the skill before testing? Delete it. Start over.
Edited a skill without testing? Same violation.

**No exceptions:**
- Not for "simple additions."
- Not for "just adding a section."
- Not for "documentation updates."
- Don't keep untested changes as "reference."
- Don't "adapt" the change while running the tests.
- Delete means delete.

**Violating the letter of this rule is violating the spirit of it.**

**REQUIRED BACKGROUND:** `spec-loop:test-driven-development` explains why order matters. The same reasoning applies to documentation.

## When to create a skill

**Create when:** the technique wasn't obvious to you; you'd reference it again across projects; it applies broadly (not to one repo); others would benefit.

**Don't create for:** one-off solutions; standard practices documented elsewhere; project-specific conventions (put those in the instructions file); mechanical constraints enforceable with regex/validation (automate those — save documentation for judgment calls). In this plugin, "never do X" invariants are enforced by a guard, not by prose — see *Shipping a skill in THIS plugin*.

## Skill Discovery Optimization (SDO)

A future agent reads your `description` to decide whether to load the skill. Make it answer: "Should I read this right now?"

**CRITICAL: `description` states WHEN to use the skill, NOT what the skill does.** Never summarize the workflow.

**Why this matters (worked failure):** In testing, when a description summarized the workflow — "code review between tasks" — an agent did ONE review, even though the skill's flowchart clearly showed TWO (spec compliance, then code quality). It followed the description and skipped the body. When the description was changed to just triggering conditions — "Use when executing implementation plans with independent tasks" — the agent read the flowchart and did both reviews. A workflow summary in the description becomes a shortcut agents take instead of reading the skill.

```yaml
# BAD — summarizes workflow; agent may follow this and skip the body
description: Use when executing plans - dispatches subagent per task with review between tasks
# BAD — first person / vague
description: I can help with async tests when they're flaky
# GOOD — triggering conditions only
description: Use when executing implementation plans with independent tasks in the current session
# GOOD — describe the PROBLEM, not the language symptom
description: Use when tests have race conditions, timing dependencies, or pass/fail inconsistently
```

**Keywords:** use words an agent would grep — error messages ("ENOTEMPTY", "race condition"), symptoms ("flaky", "hanging", "pollution"), synonyms, real tool/command/library names.

**Naming:** active, verb-first, by what you DO or the core insight — `condition-based-waiting` > `async-test-helpers`; `root-cause-tracing` > `debugging-techniques`. Gerunds work for processes. `name` MUST equal the directory name and use only letters, numbers, hyphens.

## Token efficiency

Frequently-loaded skills load into many conversations; every token is shared context.

**Word targets for the skills you WRITE:** frequently-loaded skills < 200 words total; other skills < 500 words. (This meta-skill is a reference, loaded only when authoring — it may run longer, but stays as tight as it can.)

Techniques: move flag details to `--help`; cross-reference sibling skills by name instead of repeating their content; compress examples; delete anything obvious from the command itself. Verify with `wc -w SKILL.md`.

## Cross-referencing other skills

Reference a sibling skill **by name**, with an explicit requirement marker:

- Good: `**REQUIRED SUB-SKILL:** Use spec-loop:test-driven-development`
- Good: `**REQUIRED BACKGROUND:** You MUST understand spec-loop:systematic-debugging`
- Bad: `See skills/testing/...` (unclear if required)
- Bad: `@skills/.../SKILL.md`

**NEVER use `@`-links.** `@` force-loads the file immediately, burning 200k+ of context before you need it. Name the skill; let the agent load it on demand.

## Match the Form to the Failure

Before writing guidance, classify the baseline failure. The form that bulletproofs one failure type measurably backfires on another.

| Baseline failure | Right form | Wrong form |
|---|---|---|
| Skips/violates a rule under pressure (knows better, does it anyway) | Prohibition + rationalization table + red flags (see Bulletproofing) | Soft guidance ("prefer…", "consider…") |
| Complies, but output has the wrong shape (bloated, buried verdict, restated spec) | Positive recipe/contract: state what the output IS — its parts, in order | Prohibition list ("don't restate", "never narrate") |
| Omits a required element from something they already produce | Structural: a REQUIRED field/slot in the template they fill in | Prose reminders near the template |
| Behavior should depend on a condition | Conditional keyed to an observable predicate ("if the brief exists, reference it") | Unconditional rule + exemption clauses |

**Why prohibitions backfire on shaping problems:** under a competing incentive, agents negotiate with "don't X". In head-to-head wording tests, the prohibition arm produced clearly *more* of the unwanted content than the recipe arm, and trended worse than even the no-guidance control. A recipe leaves nothing to negotiate: the output matches the stated shape or it doesn't. Micro-test your own case; never reach for the prohibition by default.

**Rules for whichever form you pick:**
- **No nuance clauses.** "Don't X unless it matters" reopens the negotiation — one nuance clause degraded a winning recipe from consistent to noisy in the same tests. Express a real exception as its own conditional on an observable predicate.
- **Exemption clauses don't scope.** "This limit doesn't apply to code blocks" still suppresses code blocks. If part of the output must be exempt, restructure so the rule can't reach it.

## Bulletproofing against rationalization

**Scope:** this toolkit is for **discipline failures** — an agent that knows the rule and skips it under pressure. For wrong-shaped or omitted output, prohibition-based bulletproofing backfires; use the forms above.

**Psychology:** understanding WHY persuasion works helps you apply it systematically. See `persuasion-principles.md` (Cialdini 2021; Meincke et al. 2025) — authority, commitment, scarcity, social proof, unity.

1. **Close every loophole explicitly.** Don't just state the rule — forbid the specific workarounds. "Delete it." → "Delete it. Start over. Don't keep it as reference. Don't adapt it. Don't look at it. Delete means delete."
2. **Address spirit vs letter early:** "Violating the letter of the rules is violating the spirit of the rules." Cuts off a whole class of rationalization.
3. **Build a rationalization table** from baseline testing — every excuse an agent made, paired with its reality.
4. **Create a red-flags list** so an agent can self-check when it's about to rationalize.
5. **Update the description** with symptoms of being ABOUT to violate the rule.

## RED-GREEN-REFACTOR for skills

- **RED — baseline:** run the pressure scenario against a subagent WITHOUT the skill. Document choices and rationalizations verbatim. You must see what agents naturally do first.
- **GREEN — minimal skill:** write only enough to address those specific rationalizations. Re-run; the agent should comply.
- **REFACTOR — close loopholes:** new rationalization appears? Add an explicit counter. Re-test until bulletproof.

### Micro-test wording before full scenarios

Full pressure-scenario runs are the final gate, but slow. Verify the wording first with micro-tests:

1. **One fresh-context sample per call** — a raw API call, or a single-shot subagent. System prompt = the realistic context the guidance lives in (the whole skill/template, not the guidance in isolation); user message = a task that tempts the failure.
2. **ALWAYS include a no-guidance control.** If the control doesn't exhibit the failure, there is nothing to fix — stop, don't author the guidance.
3. **5+ reps per variant.** Single samples lie.
4. **Read every flagged match manually.** Template echoes and quoted counter-examples masquerade as hits; automated counts alone overstate both failure and success.
5. **Variance is a metric.** When guidance lands, reps converge on one shape. Five different interpretations across five reps means the wording isn't binding — tighten the form before adding words.

Micro-tests verify wording; they do NOT replace pressure scenarios for discipline skills.

**Dispatching the test subagents:** from inside any agent, every dispatch MUST be `run_in_background: false` — see `spec-loop:dispatching-parallel-agents` for the full rule.

**Full methodology:** `testing-skills-with-subagents.md` in this directory — pressure-scenario design, pressure types (time, sunk cost, authority, exhaustion), plugging holes, meta-testing.

## Flowcharts

Use a small inline `dot` flowchart ONLY for a non-obvious decision point, a loop where you might stop too early, or an "A vs B" choice. NEVER for reference material (use tables), code (use fenced blocks), or linear steps (use a numbered list). Style rules: `graphviz-conventions.dot` in this directory.

**Rendering for a human:** `render-graphs.js` extracts `dot` blocks from a SKILL.md and renders them to SVG. It requires the `graphviz` `dot` binary — an **optional dev tool**, not a runtime dependency of this plugin.
```bash
./render-graphs.js ../some-skill            # each diagram separately
./render-graphs.js ../some-skill --combine  # all diagrams in one SVG
```

## Shipping a skill in THIS plugin

Ground truth for the spec-loop plugin (verified 2026-07-08). This is where a portable, spec-loop-native skill differs from a personal one.

**Location & frontmatter:**
- Skills live at `plugins/spec-loop/skills/<name>/SKILL.md`.
- Frontmatter has ONLY two keys: `name` and `description`.
- `name` MUST equal the directory name exactly (the validator fails otherwise).
- If `description` contains a colon-then-space (`": "`), the whole value MUST be quoted — unquoted YAML reads it as a nested mapping and `claude plugin validate` rejects it.

**Bundled references must ship:**
- Every `${CLAUDE_PLUGIN_ROOT}` path reference you write MUST resolve to a real file under `plugins/spec-loop/`. A marketplace install copies only the plugin dir — if the skill points at a script, YOU ship that script in the same dir. (The validator greps for these references, so this rule is enforced.)

**Read-only commands stay read-only:**
- A command whose prose says "read-only" / "read only" / "never edits" MUST NOT grant `Edit` in its `allowed-tools`. The validator flags this.

**New bundled Python runtime scripts:**
- Any new shippable Python script under `plugins/spec-loop/scripts/` must be **stdlib-only** (no third-party runtime deps; Node scripts stay zero-dep) and needs a co-located `test_*.py` beside it.
- It must also be **registered in the coverage gate** at `scripts/measure_coverage.py`: add its canonical `scripts/<name>.py` key to `TARGET_FILES`, and add a per-file floor to `PER_FILE_FLOORS` (set the floor ≥5 points below the locally measured coverage, matching the existing entries). The gate discovers `test_*.py` across both the root and plugin `scripts/` dirs.

**Never route around change-control (hard project rule):**
- A new "never do X" invariant MUST be enforced by the PreToolUse guard, not by prompt text alone. Add the check to `plugins/spec-loop/scripts/spec_loop_guard.py` (registered via `plugins/spec-loop/hooks/hooks.json` for `Bash` and `Write|Edit|MultiEdit`). Prose in a skill is defense-in-depth; the guard is the control. Do not document workarounds to the git invariants the guard enforces (no `git push`/commit-on-`main`/broad `git add`/quality-gate edits mid-run).

**Local CI pre-check (run from the repo root before you call the work done):**
```bash
python3 scripts/validate_marketplace.py .   # structure, frontmatter, ${CLAUDE_PLUGIN_ROOT} refs
python3 scripts/measure_coverage.py         # coverage floors, if you added/changed a script
```
Peers may be editing other skills concurrently — fix only what the validator reports about YOUR files.

## Anti-patterns

- **Narrative example** — "In session 2025-10-03 we found…". Too specific, not reusable.
- **Multi-language dilution** — `example-js.js`, `example-py.py`, `example-go.go`. One excellent example beats many mediocre ones. Pick the most relevant language.
- **Code in flowcharts** — can't copy-paste, hard to read. Use fenced blocks.
- **Generic labels** — `helper1`, `step3`. Labels must carry semantic meaning.

## STOP: before moving to the next skill

After writing ANY skill you MUST stop and complete its testing. Do NOT batch-create skills without testing each, and do NOT move on before the current one is verified. Deploying an untested skill = deploying untested code.

## When NOT to use this skill

- **You need the RED-GREEN-REFACTOR cycle itself** (for code, not docs) → `spec-loop:test-driven-development`.
- **You're writing an implementation plan, not a skill** → `spec-loop:writing-plans`.
- **You just need to run the subagent test harness** → the mechanics live in `testing-skills-with-subagents.md`; this SKILL is the surrounding TDD discipline.
- **The constraint is mechanical (regex/validation-enforceable)** → automate it (a guard/validator), don't write a skill.

## Red flags — STOP and start over

- Wrote or edited the skill before running a baseline test.
- "It's just a small addition, testing is overkill."
- "The skill is obviously clear" / "I'm confident it's good."
- Description summarizes the workflow instead of stating when to use it.
- Reached for a prohibition to fix a wrong-shaped-output problem.
- Added a "…unless it matters" nuance clause to a rule.
- Used an `@`-link to reference another skill.
- Shipped a `${CLAUDE_PLUGIN_ROOT}/` reference to a file you didn't create.
- Enforced a "never do X" invariant with prose instead of the guard.

**All of these mean: stop. Return to RED. Write the failing test first.**

## Provenance and maintenance

Ported from `superpowers` v6.1.1 (github.com/obra/superpowers, MIT) `skills/writing-skills` on 2026-07-08; adapted for spec-loop. Namespaces remapped `superpowers:* → spec-loop:*`. Supporting files ported: `anthropic-best-practices.md` and `persuasion-principles.md` (verbatim — generic), `graphviz-conventions.dot` and `render-graphs.js` (verbatim; `render-graphs.js` needs the optional `graphviz` `dot` binary), `testing-skills-with-subagents.md` (one namespace fix). `examples/CLAUDE_MD_TESTING.md` kept as an illustrative worked test-campaign example referenced by the testing doc — its `~/.claude/skills/` paths are scenario content from the original campaign, not spec-loop instructions.

Re-verify if the repo drifts:
```bash
ls plugins/spec-loop/skills/test-driven-development/SKILL.md   # sibling skill name still valid
grep -n "TARGET_FILES\|PER_FILE_FLOORS" scripts/measure_coverage.py   # coverage-gate registration shape
grep -rn "READONLY_MARKERS\|CLAUDE_PLUGIN_ROOT" scripts/validate_marketplace.py   # validator rules
cat plugins/spec-loop/hooks/hooks.json                          # guard registration (PreToolUse matchers)
```
