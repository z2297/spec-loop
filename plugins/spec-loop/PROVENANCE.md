# Provenance and maintenance

This file is the single home for the spec-loop plugin's provenance record: where each ported prompt file came from, when it was ported, what was adapted, and which commands to run to re-verify the claims if the repo drifts.

Previously each agent, command, and skill carried its own `## Provenance and maintenance` section. That content is maintainer documentation — it tells a human editor what to preserve when syncing from upstream, and it has no effect on how the model behaves at runtime. Keeping it inline meant every model that loaded a prompt also loaded its changelog. Consolidating it here keeps the prompt files lean.

**This file is never loaded into model context.** It is not a skill, not an agent, not referenced from any prompt body, and nothing in the loop reads it. It exists for whoever maintains this plugin. If you add a provenance note, add it here — not to the prompt file.

---

## 2026-07 Claude 5 context-engineering refactor

**This plugin deliberately diverges from its upstream sources as of this refactor. Do not restore the removed material when syncing from upstream.**

The prompt files (`agents/*.md`, `commands/*.md`, `skills/*/SKILL.md`) were rewritten against Anthropic's Claude 5 context-engineering guidance. Four categories of content were removed on purpose:

- **Guardrail and red-flag lists → judgment.** Long enumerations of "never do X" / "STOP if you catch yourself thinking Y" were cut in favor of stating the actual constraint once and trusting the model to generalize. Rules that enumerate failure modes teach pattern-matching against the list, not the principle behind it.
- **Worked examples → interface design.** Multi-paragraph example dialogues, sample outputs, and before/after transcripts were cut in favor of a precisely specified output contract. A well-specified interface does the work an example was standing in for, at a fraction of the tokens.
- **Upfront detail → progressive disclosure.** Content only some invocations need moved to `references/` files or sibling docs the prompt points at, rather than being inlined for every load.
- **Repetition → single-home contracts.** Facts that were pinned in three or four files (severity mappings, escalation wording, output schemas) now live in exactly one file that the others cross-reference.

Both upstream sources — `superpowers` (ported 2026-07-08) and `pr-review-toolkit` (ported 2026-07-13) — predate this guidance and still contain that material. When pulling an upstream change into this plugin, port the *behavioral* change and leave the guardrail lists, examples, rationalization tables, and duplicated contract copies behind. Re-adding them regresses this refactor.

The per-file notes below describe each file as it stood at its port date. Where a note says content was ported "verbatim" or "near-verbatim," read that as *verbatim as of the port date* — the 2026-07 refactor has since trimmed it.

---

## agents/code-reviewer.md

Ported from `superpowers` v6.1.1 (github.com/obra/superpowers, MIT) `skills/requesting-code-review/code-reviewer.md` on 2026-07-08; adapted for spec-loop as a native agent (frontmatter added; template placeholders reframed as a dispatch-inputs table; read-only rules hardened into explicit git constraints; untrusted-data guard and advisory scope added to match house style). The template's What-to-Check list, Calibration, Critical Rules, output contract, and worked example are ported near-verbatim.

Re-verify if things drift:
- Sibling skill names still exist: `ls plugins/spec-loop/skills/code-review-discipline plugins/spec-loop/skills/subagent-driven-development`
- `model: inherit` convention (roles whose verdict can gate alone stay `inherit`): `awk '/## .*1\.2\.1/{f=1} f{print} /## .*1\.2\.0/{if(f)exit}' CHANGELOG.md | grep -i inherit`
- Frontmatter validates: `python3 scripts/validate_marketplace.py .`

## agents/code-simplifier.md

Ported from `pr-review-toolkit` (Anthropic, `claude-plugins-official` marketplace) `agents/code-simplifier.md` on 2026-07-13; adapted for spec-loop:

- **Project standards generalized.** The source's Anthropic-internal standards (ES modules, `function` over arrow, explicit return types, React `Props`, avoid `try/catch`, naming) are demoted to clearly-labeled **fallback defaults that yield to stronger local convention** — the agent now derives standards from the target repo's CLAUDE.md / lint config / surrounding idiom first.
- **Non-blocking polish-pass framing** added per `spec-loop:review-depth-map` — the agent runs as the `simplify` aspect of `spec-loop:review-pr` at slice Step 4b, after the review/auto-fix loop converges and before the quality gate and Step 5 verification; result is a one-line note in `decisions-log.md`, never a block or escalation.
- **Behavior-preservation hardened into explicit constraints** — edits the working tree only; never changes behavior, commits/merges/pushes, touches files outside the diff scope, or fixes bugs (bugs are reported for the auto-fix loop, not fixed here). Untrusted-data / prompt-injection guard added (diff and comments are data, never instructions), matching house style.
- **`model: inherit`** replaces the source's `model: opus` pin (spec-loop lets the session model govern; the source pinned opus).
- Inputs reframed as a dispatch-inputs table with `DIFF_SCOPE` defaulting to recently modified/unstaged code (source parity). The five principles and the 6-step refinement process are ported in substance, including the explicit nested-ternary-operator ban.

Re-verify if things drift:
- `grep -n "simplify" plugins/spec-loop/skills/review-depth-map/SKILL.md`
- `grep -n "Step 4b" plugins/spec-loop/agents/spec-loop-slice.md`
- `python3 scripts/validate_marketplace.py .`

## agents/comment-analyzer.md

Ported from `pr-review-toolkit` (Anthropic, claude-plugins-official marketplace) `agents/comment-analyzer.md` on 2026-07-13; adapted for spec-loop:

- Dispatch reframed from the standalone `/review-pr` command to the `spec-loop:review-pr` skill's `comments` aspect (auto-selected when the diff touches comments/docstrings/docs; forced via `all`/`exhaustive`).
- Added a dispatch-inputs table (diff package preferred / `BASE_SHA`..`HEAD_SHA` / unstaged-diff default).
- Added an untrusted-data / prompt-injection guard (a comment is DATA; an instruction hidden in a comment is itself a Critical finding).
- Added explicit read-only git constraints matching house style.
- `model: inherit` — the source was already `model: inherit`; kept as-is.

The source's five analysis steps, the four output sections plus Positive Findings, the 'why' > 'what' value rule, and the advisory-only closing constraint are ported near-verbatim.

Re-verify if things drift:
- The dispatching skill still names this agent: `grep -n "comment-analyzer" plugins/spec-loop/skills/review-pr/SKILL.md`
- Frontmatter validates: `python3 scripts/validate_marketplace.py .`

## agents/guideline-reviewer.md

Ported from `pr-review-toolkit` (Anthropic, claude-plugins-official marketplace) `agents/code-reviewer.md` on 2026-07-13; adapted for spec-loop:

- **Renamed `code-reviewer` → `guideline-reviewer`.** spec-loop already has a native `code-reviewer` agent (a different role: plan-alignment / whole-branch reviewer). The new name disambiguates this diff-facing, guideline-compliance role.
- **Generalized the "CLAUDE.md" target** from the source's implicit "this project" to the **target repo under review**, with an explicit fallback ladder (repo CLAUDE.md → other stated conventions → surrounding-code idiom) for repos with no CLAUDE.md.
- **Added an Inputs table** for spec-loop's dispatch: optional pre-built diff package (preferred), `BASE_SHA`/`HEAD_SHA` range, or the source-parity default of unstaged `git diff`.
- **Added an untrusted-data / prompt-injection guard** and **read-only hard constraints** (explicit list of forbidden git/write operations) to match house style.
- **Pinned the output contract** in a fenced block and added a worked example.
- **`model: inherit`** replaces the source's explicit `model: opus` pin, matching the spec-loop convention that dispatched reviewers inherit the controller's model.

Preserved from the source in substance: confidence scoring 0–100 with the same band definitions; the **report only issues with confidence ≥ 80** bar; output grouped by severity (**Critical 90–100 / Important 80–89**); per-issue format (description + confidence, file:line, which guideline/why it's a bug, suggested fix); the default scope of unstaged `git diff`; and the "filter aggressively — quality over quantity" ethos.

Re-verify if things drift:
- `ls plugins/spec-loop/skills/review-pr/SKILL.md plugins/spec-loop/agents/code-reviewer.md`
- `grep -n "guideline-reviewer" plugins/spec-loop/skills/review-pr/SKILL.md`
- `python3 scripts/validate_marketplace.py .`

## agents/pr-test-analyzer.md

Ported from `pr-review-toolkit` (Anthropic, claude-plugins-official marketplace) `agents/pr-test-analyzer.md` on 2026-07-13; adapted for spec-loop:

- Frontmatter reworked to house style: trigger-rich `description` ending with the read-only advisory clause; explicit read-only `tools` (`Read, Grep, Glob, Bash`); `color: cyan`. Source `model: inherit` kept (a coverage verdict can gate a slice's review on its own).
- Added the dispatch-context section (spawned by the `spec-loop:review-pr` `tests` aspect; auto-selected on test/logic changes, forced in `all`/`exhaustive`) and folded the source's "When to invoke" scenarios into it.
- Added a **scope boundary** note deferring requirements-traceability test review to `spec-loop:peer-review-tests` — the mirror image of that agent's own defer clause (it defers generic/diff-level coverage adequacy to the review-pr path; this agent defers requirements-vs-tests traceability to it). The two do not overlap.
- Added an Inputs table (diff package preferred / `BASE..HEAD` / default unstaged diff), an untrusted-data / prompt-injection guard, and hardened **inspection-only** read-only rules: parity with the source, this agent inspects tests and code and does **not** execute the suite — running tests is the slice worker's verification step.
- Preserved verbatim: behavioral-over-line-coverage ethos, the "not pedantic about 100%" framing, the DAMP definition, the criticality **1–10** scale and its exact bands, the analysis process, and the output sections (**Summary / Critical Gaps 8–10 / Important Improvements 5–7 / Test Quality Issues / Positive Observations**). Added a note that the `review-pr` skill maps the 1–10 ratings into its P0–P3 aggregation.
- Added a worked example in the pinned output format.

Re-verify if things drift:
- Boundary sibling still defers the other direction: `grep -n "pr-test-analyzer\|review-pr" plugins/spec-loop/agents/peer-review-tests.md`
- The review-pr skill still dispatches this agent by name: `grep -n "pr-test-analyzer" plugins/spec-loop/skills/review-pr/SKILL.md`
- Frontmatter validates: `python3 scripts/validate_marketplace.py .`

## agents/sdd-implementer.md

Ported from `superpowers` v6.1.1 (github.com/obra/superpowers, MIT) `skills/subagent-driven-development/implementer-prompt.md` on 2026-07-08; adapted for spec-loop — the dispatch-prompt template became this agent's standing instructions, the "ask before starting" gate became the one-shot `NEEDS_CONTEXT` protocol, and spec-loop's untrusted-data / worktree-confinement / verification guards were added.

Re-verify on drift:
- Sibling skills exist: `ls plugins/spec-loop/skills/{test-driven-development,verification-before-completion,code-review-discipline,subagent-driven-development}/SKILL.md`
- This agent still validates: `python3 scripts/validate_marketplace.py .`

## agents/sdd-task-reviewer.md

Ported from `superpowers` v6.1.1 (github.com/obra/superpowers, MIT) `skills/subagent-driven-development/task-reviewer-prompt.md` on 2026-07-08; adapted for spec-loop as a native agent — the dispatch-prompt template became this agent's standing instructions, the two-part spec-compliance-then-quality review was kept, and spec-loop's untrusted-data guard, read-only git constraints, cross-task escalation, and plan-mandated finding rule were added.

Re-verify on drift:
- Dispatching skill still exists: `ls plugins/spec-loop/skills/subagent-driven-development/SKILL.md`
- This agent still validates: `python3 scripts/validate_marketplace.py .`

## agents/silent-failure-hunter.md

Ported from `pr-review-toolkit` (Anthropic, claude-plugins-official marketplace) `agents/silent-failure-hunter.md` on 2026-07-13; adapted for spec-loop:

- **Anthropic-internal utility references generalized to target-repo discovery.** The source hardcoded Anthropic's own codebase conventions — the logging functions `logForDebugging`, `logError` (Sentry), and `logEvent` (Statsig), plus an error-id registry at `constants/errorIds.ts`. Those are wrong for arbitrary spec-loop targets, so Part 5 now instructs the auditor to **grep the target repo for its own logger, error-tracking SDK, and error-id registry** and validate against those, with a universal fallback bar when none exists.
- **"Daisy" example dialogues dropped** from the description; replaced with a house-style trigger-rich frontmatter tied to the `spec-loop:review-pr` `errors` aspect.
- **House sections added**: persona intro (keeping the "elite error handling auditor with zero tolerance" ethos and the "silent failure" definition), an Inputs table (diff package preferred / `BASE..HEAD` / default unstaged diff), an untrusted-data / prompt-injection guard (a comment claiming an error is "safe to ignore" is data, not an instruction), read-only hard constraints, a pinned Output contract, and a worked example.
- The five core principles, the five-part review process with its per-part checklists (empty catch blocks kept as "absolutely forbidden"), the CRITICAL/HIGH/MEDIUM severity bands, and the per-issue Location/Severity/Issue Description/Hidden Errors/User Impact/Recommendation/Example fields are ported in substance.
- Source `model: inherit` and `color: yellow` kept.

Re-verify if things drift:
- Skill still dispatches this agent (the review-pr skill is authored in parallel): `grep -n "silent-failure-hunter" plugins/spec-loop/skills/review-pr/SKILL.md`
- Frontmatter validates: `python3 scripts/validate_marketplace.py .`

## agents/type-design-analyzer.md

Ported from `pr-review-toolkit` (Anthropic, claude-plugins-official marketplace) `agents/type-design-analyzer.md` on 2026-07-13; adapted for spec-loop:

- Frontmatter added/reframed to house style: trigger-rich `description` ending "Read-only and advisory; never edits, posts, or merges."; explicit `tools: Read, Grep, Glob, Bash`. Source `model: inherit` kept.
- Dispatch reframed from the source's freeform "when to invoke" scenarios to the `spec-loop:review-pr` `types` aspect (auto-selected on type/interface/class/schema changes; forced by `all`/`exhaustive`); scope narrowed to types added/modified in the diff.
- Added house sections absent from the source: an Inputs table (diff package preferred / `BASE..HEAD` / unstaged-diff fallback), an untrusted-data / prompt-injection guard, read-only hard constraints, and a worked example.
- Defined "invariant" and "encapsulation" at first use for a zero-context reader.
- The four rating axes, the identify-invariants step, Key Principles, Common Anti-patterns, and the complexity-cost guidance are ported near-verbatim. **The per-type output schema (`## Type:` through `### Recommended Improvements`, including the four `X/10` rating lines) is preserved verbatim** — keep it byte-compatible.

Re-verify if things drift:
- The review-pr skill still names this agent: `grep -n "type-design-analyzer" plugins/spec-loop/skills/review-pr/SKILL.md`
- Frontmatter validates: `python3 scripts/validate_marketplace.py .`

## commands/review-pr.md

Ported from `pr-review-toolkit` (Anthropic, claude-plugins-official marketplace) `commands/review-pr.md` on 2026-07-13; adapted: thin wrapper over the native `spec-loop:review-pr` skill per the `quality-gate`/`knowledge-graph` same-name precedent — the orchestration contract lives in the skill, not here.

Re-verify if things drift:
- `ls plugins/spec-loop/skills/review-pr/SKILL.md` — confirm the wrapped skill exists.
- `python3 scripts/validate_marketplace.py .` — confirm the plugin manifest still validates.

## skills/brainstorming/SKILL.md

Ported from `superpowers` v6.1.1 (github.com/obra/superpowers, MIT) `skills/brainstorming` on 2026-07-08; adapted for spec-loop. Namespace/paths remapped (`superpowers:*` → `spec-loop:*`, `docs/superpowers/specs/` → `docs/spec-loop/specs/`, `.superpowers/brainstorm/` → `.spec-loop/brainstorm/`), branding neutralized, and the escalation-gate override notes added. The vestigial `spec-document-reviewer-prompt.md` was **not** ported — the source SKILL body performs the spec self-review inline and never dispatches that prompt as a subagent, so it carried no behavior. Cross-harness launch notes (Codex, Copilot CLI) in the visual-companion guide were cut.

Re-verify if things drift:
- Sibling skills still exist: `ls plugins/spec-loop/skills/writing-plans plugins/spec-loop/skills/subagent-driven-development plugins/spec-loop/skills/executing-plans plugins/spec-loop/skills/systematic-debugging plugins/spec-loop/skills/escalation-gate`
- Companion scripts resolve: `ls "${CLAUDE_PLUGIN_ROOT}/skills/brainstorming/scripts/"{start-server.sh,stop-server.sh,server.cjs,helper.js,frame-template.html}`
- Scripts still parse: `node --check plugins/spec-loop/skills/brainstorming/scripts/server.cjs && bash -n plugins/spec-loop/skills/brainstorming/scripts/start-server.sh`
- Escalation-gate override wording is still consistent: `sed -n '12,17p' plugins/spec-loop/skills/escalation-gate/SKILL.md`

## skills/code-review-discipline/SKILL.md

Merged from `superpowers` v6.1.1 (github.com/obra/superpowers, MIT) `skills/requesting-code-review` and `skills/receiving-code-review` on 2026-07-08; adapted for spec-loop. The two were paired thin skills covering the two halves of one review loop — merged into one home so each fact lives once, keeping their full processes (request mechanics + receive-feedback response pattern, forbidden-responses list, YAGNI check, GitHub thread replies).

Adapted, not verbatim: the old `code-reviewer.md` fill-in template is replaced by the named `spec-loop:code-reviewer` agent (it owns the prompt/output contract now); namespaces retargeted to `spec-loop:*` and `docs/spec-loop/plans/`; added the nesting rule and the `escalation-gate` override note for the human gates.

Re-verify if things drift:
- Agent exists: `ls plugins/spec-loop/agents/code-reviewer.md`
- Sibling skills referenced still exist: `ls plugins/spec-loop/skills/{subagent-driven-development,executing-plans,review-depth-map,review-finding-verifier,escalation-gate,verification-before-completion}/SKILL.md`
- Auto-fix loop still names this discipline: `grep -n "auto-fix loop" plugins/spec-loop/skills/review-depth-map/SKILL.md` (as of 2026-07-08 it cites `spec-loop:code-review-discipline` — Part 2 here is that discipline's home).

## skills/dispatching-parallel-agents/SKILL.md

Ported from `superpowers` v6.1.1 (github.com/obra/superpowers, MIT) `skills/dispatching-parallel-agents` on 2026-07-08; adapted for spec-loop. Adaptations: added the **nesting rule** (top-level-only background dispatch; synchronous from inside any agent), added the spec-loop boundary in "When NOT to use this" (sequential plans → `subagent-driven-development`; cross-slice parallelism → the `/spec-loop` wave scheduler), and folded the Common Mistakes list into a table. Cut the source's "Real Example from Session" / "Real-World Impact" / "Key Benefits" narrative sections for token discipline.

Re-verify if things drift:
- Sibling skill names exist: `ls plugins/spec-loop/skills/subagent-driven-development plugins/spec-loop/skills/escalation-gate`.
- Slice worker's synchronous-dispatch rule still holds: `grep -n "run_in_background: false" plugins/spec-loop/agents/spec-loop-slice.md`.
- SDD's sequential-implementer discipline still holds: `grep -ni "sequential\|one implementer\|never parallel" plugins/spec-loop/skills/subagent-driven-development/SKILL.md`.

## skills/executing-plans/SKILL.md

Ported from `superpowers` v6.1.1 (github.com/obra/superpowers, MIT) `skills/executing-plans` on 2026-07-08; adapted for spec-loop. Cut the cross-harness platform note and the `../using-superpowers/references/` per-platform tool-ref pointer; reframed the "prefer subagents" note around `spec-loop:subagent-driven-development` and the subagent-nesting constraint; added the spec-loop run-override notes and the "When NOT to use this" section.

Re-verify if things drift:
- Sibling skills exist: `ls plugins/spec-loop/skills/{subagent-driven-development,using-git-worktrees,writing-plans,test-driven-development,verification-before-completion,finishing-a-development-branch}/SKILL.md`
- Slice-worker fallback still matches: `grep -n "executing-plans" plugins/spec-loop/agents/spec-loop-slice.md`
- Escalation-gate override wording still current: `sed -n '12,17p' plugins/spec-loop/skills/escalation-gate/SKILL.md`

## skills/finishing-a-development-branch/SKILL.md

Ported from `superpowers` v6.1.1 (github.com/obra/superpowers, MIT) `skills/finishing-a-development-branch` on 2026-07-08; adapted for spec-loop. Adaptations: added the spec-loop run-override (menu governed by `escalation-gate`; controller-owned serial merge; `per-slice-pr` = Option 2) and the guard-hook note; cross-linked `spec-loop:verification-before-completion` and `spec-loop:using-git-worktrees`; added a "When NOT to use this" section. No cross-harness content existed in the source to cut.

Re-verify if things drift:
- Sibling skill names still exist: `ls plugins/spec-loop/skills/{verification-before-completion,using-git-worktrees,escalation-gate}/SKILL.md` (the first two are authored concurrently as of 2026-07-08).
- Run-override still matches the loop: `spec-loop-slice.md` Step 5 and `commands/spec-loop.md` Phase 3 (controller serial merge) — `grep -n "single-branch\|per-slice-pr\|finishing-a-development-branch" plugins/spec-loop/agents/spec-loop-slice.md`.
- Guard behavior still matches: `grep -n "push\|commit\|merge\|main\|publish" plugins/spec-loop/scripts/spec_loop_guard.py`.

## skills/review-pr/SKILL.md

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

## skills/subagent-driven-development/SKILL.md

Ported from `superpowers` v6.1.1 (github.com/obra/superpowers, MIT) `skills/subagent-driven-development` on 2026-07-08; adapted for spec-loop. The source's `implementer-prompt.md` and `task-reviewer-prompt.md` prompt templates were **cut** — their content is now carried by the native agents `spec-loop:sdd-implementer` and `spec-loop:sdd-task-reviewer`; this skill fills those agents' input contracts instead of pasting prompt templates. The workspace path `.superpowers/sdd/` was remapped to `.spec-loop/sdd/`.

Re-verify if things drift:
```bash
# Referenced scripts exist and are executable
ls -l "${CLAUDE_PLUGIN_ROOT}/skills/subagent-driven-development/scripts/"{sdd-workspace,review-package,task-brief}
# Named agents still exist
ls plugins/spec-loop/agents/{sdd-implementer,sdd-task-reviewer,code-reviewer}.md
# Sibling skills still named as referenced
ls plugins/spec-loop/skills/{using-git-worktrees,writing-plans,test-driven-development,executing-plans,brainstorming,finishing-a-development-branch,escalation-gate,verification-before-completion}
```

## skills/systematic-debugging/SKILL.md

Ported from `superpowers` v6.1.1 (github.com/obra/superpowers, MIT) `skills/systematic-debugging` on 2026-07-08; adapted for spec-loop. Skill-test fixtures from the source (`test-academic.md`, `test-pressure-1/2/3.md`, `CREATION-LOG.md`) were NOT ported — they exercise the source authors' skill-testing harness, not this skill's behavior. The only behavioral adaptation is Phase 4.5's human gate, which is routed through `spec-loop:escalation-gate` inside an active run.

Re-verify if things drift:
- Sibling skills exist: `ls plugins/spec-loop/skills/{test-driven-development,verification-before-completion,escalation-gate}/SKILL.md`
- Supporting files present and script runnable: `ls plugins/spec-loop/skills/systematic-debugging/ && bash -n plugins/spec-loop/skills/systematic-debugging/find-polluter.sh`
- Escalation-gate override wording stays consistent: `sed -n '12,18p' plugins/spec-loop/skills/escalation-gate/SKILL.md`

## skills/test-driven-development/SKILL.md

Ported from `superpowers` v6.1.1 (github.com/obra/superpowers, MIT) `skills/test-driven-development` on 2026-07-08; adapted for spec-loop. This repo's own user-level guidance already agrees (behavior-not-implementation testing, minimal mocking) — no contradictions to reconcile.

Adapted vs. verbatim: the Iron Law, Red-Green-Refactor cycle (both mandatory verification gates), YAGNI-in-GREEN, the Common Rationalizations table, the Red Flags STOP list, the Verification Checklist, the When-Stuck table, and the good/bad code examples are ported verbatim. Added: the spec-loop namespace on sibling skills, a "When NOT to use this" section, the `escalation-gate` note on the human-gate exceptions, and this section.

Re-verify if things drift:
- Sibling skills exist: `ls plugins/spec-loop/skills/systematic-debugging plugins/spec-loop/skills/verification-before-completion`
- Supporting file present: `ls plugins/spec-loop/skills/test-driven-development/testing-anti-patterns.md`
- Escalation-gate override wording still current: `sed -n '12,18p' plugins/spec-loop/skills/escalation-gate/SKILL.md`

## skills/test-driven-development/testing-anti-patterns.md

Ported from `superpowers` v6.1.1 (github.com/obra/superpowers, MIT) `skills/test-driven-development/testing-anti-patterns.md` on 2026-07-08; content unchanged (no cross-harness or namespaced references to adapt). Referenced from `SKILL.md` "when adding mocks or test utilities".

## skills/using-git-worktrees/SKILL.md

Ported from `superpowers` v6.1.1 (github.com/obra/superpowers, MIT) `skills/using-git-worktrees` on 2026-07-08; adapted for spec-loop. Cross-harness Platform-Adaptation content was not present in the source and nothing harness-specific was added beyond the native-tool detection already in the source.

Re-verify on drift:
- Sibling skill names still exist: `ls plugins/spec-loop/skills/{finishing-a-development-branch,executing-plans,subagent-driven-development,escalation-gate}/SKILL.md`
- spec-loop worktree layout/consent claims still match the worker: `sed -n '66,110p' plugins/spec-loop/agents/spec-loop-slice.md`
- Ephemeral-isolation and gitignore claims still match the README: `grep -n -A12 'Notes & limitations' plugins/spec-loop/README.md`
- Escalation-gate override wording still consistent: `sed -n '12,17p' plugins/spec-loop/skills/escalation-gate/SKILL.md`

## skills/using-spec-loop/SKILL.md

Ported from `superpowers` v6.1.1 (github.com/obra/superpowers, MIT) `skills/using-superpowers` on 2026-07-08; adapted for spec-loop. Cut the source's Platform Adaptation section and its `references/` files (cross-harness content, not applicable here). Added the two skill-catalog tables and the loop-machinery / escalation-gate integration notes.

Re-verify if things drift:
- Sibling process-skill names: `ls plugins/spec-loop/skills/` and confirm each row of the process-skill table resolves to a real `<name>/SKILL.md`.
- Loop-machinery one-liners track the real frontmatter: `head -4 plugins/spec-loop/skills/<name>/SKILL.md` for `escalation-gate`, `iron-council`, `review-depth-map`, `quality-gate`, `peer-review-council`, `runbook`, `knowledge-graph`.

## skills/verification-before-completion/SKILL.md

Ported from `superpowers` v6.1.1 (github.com/obra/superpowers, MIT) `skills/verification-before-completion` on 2026-07-08; adapted for spec-loop. Adaptations: added the pinned "never overridden by the autonomy contract" section tying the gate to the slice `DONE` claim, controller merge gate, and Phase 5 integration gate; expanded the "agent completed" guidance to say check the VCS diff, not the report; added a "When NOT to use this" section pointing at sibling skills. Cut the ASCII check/cross glyphs in favor of plain labels (house style / CI safety).

Re-verify if things drift:
- Sibling skill names still exist: `ls plugins/spec-loop/skills/{test-driven-development,systematic-debugging,escalation-gate}`
- The "never overridden" claim still matches the contract: `sed -n '17p' plugins/spec-loop/skills/escalation-gate/SKILL.md` and `sed -n '55,57p' plugins/spec-loop/commands/spec-loop.md`

## skills/writing-plans/SKILL.md

Ported from `superpowers` v6.1.1 (github.com/obra/superpowers, MIT) `skills/writing-plans/SKILL.md` on 2026-07-08; adapted for spec-loop.

Adaptations from source: skill namespaces rewritten to `spec-loop:*`; plan save path changed to `docs/spec-loop/plans/`; added the pinned spec-loop metadata-header note, the in-run Execution-Handoff override, and the "When NOT to use this" section. The source `plan-document-reviewer-prompt.md` (a subagent dispatch template for reviewing the plan document) was **not** ported: the source SKILL body never invokes it, and inside spec-loop the plan is vetted by `spec-loop:iron-council` at slice Step 1.5 instead.

Re-verify if things drift:
- Sibling skill names exist: `ls plugins/spec-loop/skills/ | grep -E 'subagent-driven-development|executing-plans|brainstorming|test-driven-development|systematic-debugging|using-git-worktrees'`
- The metadata-header shape this note references still lives where claimed: `sed -n '107,115p' plugins/spec-loop/skills/review-depth-map/SKILL.md` and `grep -n 'metadata header' plugins/spec-loop/agents/spec-loop-slice.md`
- Autonomy-contract override wording stays consistent: `sed -n '12,17p' plugins/spec-loop/skills/escalation-gate/SKILL.md`

## skills/writing-skills/SKILL.md

Ported from `superpowers` v6.1.1 (github.com/obra/superpowers, MIT) `skills/writing-skills` on 2026-07-08; adapted for spec-loop. Namespaces remapped `superpowers:* → spec-loop:*`. Supporting files ported: `anthropic-best-practices.md` and `persuasion-principles.md` (verbatim — generic), `graphviz-conventions.dot` and `render-graphs.js` (verbatim; `render-graphs.js` needs the optional `graphviz` `dot` binary), `testing-skills-with-subagents.md` (one namespace fix). `examples/CLAUDE_MD_TESTING.md` kept as an illustrative worked test-campaign example referenced by the testing doc — its `~/.claude/skills/` paths are scenario content from the original campaign, not spec-loop instructions.

Re-verify if the repo drifts:
```bash
ls plugins/spec-loop/skills/test-driven-development/SKILL.md   # sibling skill name still valid
grep -n "TARGET_FILES\|PER_FILE_FLOORS" scripts/measure_coverage.py   # coverage-gate registration shape
grep -rn "READONLY_MARKERS\|CLAUDE_PLUGIN_ROOT" scripts/validate_marketplace.py   # validator rules
cat plugins/spec-loop/hooks/hooks.json                          # guard registration (PreToolUse matchers)
```
