# Request

Create a loop that is dedicated for PR-reviews of peers. This loop should not change
any implementation. The user should provide the "plan" as a prompt, which the review
should use as the business requirements. Create a set of agents that are the "review
council" that analyzes the code as well as leveraging pr-review-toolkit. This loop
should also publish a final md file for human & Agent consumption.

## Resolved up-front (Phase 0 — Iron Council intake + human answers)

The new feature is a **read-only peer-PR-review loop** — a diff-reviewing SIBLING of
the Iron Council (which reviews plans/requests pre-execution). Its genuinely-new
capability is **requirements-conformance review of a real diff**: does the diff satisfy
the user-supplied "plan" (business requirements), no more and no less? Generic
code-quality is DELEGATED to `pr-review-toolkit:review-pr` (not reinvented) and
synthesized in.

- **Review target (per human): a flexible multi-provider PR link** — **Azure DevOps,
  GitHub, or Bitbucket**. The loop detects the provider from the URL and resolves the
  PR read-only: PR metadata (title/description) + the `base..head` SHAs, then diffs
  locally. Prefer the official CLI where present (`gh` for GitHub, `az repos pr` for
  Azure DevOps); Bitbucket via its REST API. A local `--base/--head` ref-range is also
  accepted. Missing CLI/credentials → fail with clear guidance, never half-review.
- **Council size (per human): broader bespoke panel** — 5 NEW diff-facing agents
  (`peer-review-{conformance,correctness,risk,design,tests}`) mirroring the iron-council
  agent shape but with a PR-review verdict vocabulary
  (APPROVE / APPROVE_WITH_COMMENTS / REQUEST_CHANGES). pr-review-toolkit's analyzers are
  ALSO run; findings from the council and the toolkit are **merged and deduplicated**
  onto ONE severity scale (P0/P1/P2, mapping the toolkit's Critical/Important/Suggestion).
- **Report (per human): local markdown only** — one stable-schema `.md` under
  `docs/pr-review/<review-id>/` for human + agent consumption, plus the verbatim
  `requirements.md` and `target.md` inputs. Strictly read-only; nothing is posted to any
  provider. Provider post-back (gh/az/Bitbucket comment APIs) is a DEFERRED follow-on.

### Folded council concerns (all 5 members; aggregate = ENDORSE_WITH_CONCERNS)
- **Read-only by construction** (guardian/skeptic): the controller command's
  `allowed-tools` is locked — NO `Edit`, no merge/commit/push; `Write` limited to the
  report artifact; `review-pr` invoked in **report-only** mode (NEVER the `simplify`/fix
  aspect, which writes code); read-only git/gh/az verbs only; the PR URL/number is
  validated and never interpolated unsafely into a shell string; the requirements prompt
  and the diff/PR body are treated as untrusted **data**, never instructions
  (prompt-injection); secrets appearing in the diff are FLAGGED + REDACTED in the report.
- **CI hardening** (guardian): `scripts/validate_marketplace.py` only checks frontmatter
  key *presence* — it does not inspect `allowed-tools`. Extend it to assert the
  peer-review command's `allowed-tools` excludes `Edit`, so the read-only boundary stops
  being convention-only.
- **Reuse over new** (historian/architect/pragmatist): mirror the `iron-council`
  agent+skill convening/aggregation pattern (dispatch-in-one-message, structured verdict
  block) but LEANER — no DAG/SPLIT routing, no escalation-gate/AskUserQuestion machinery
  (the report IS the human surface). Reuse `review-depth-map` to pick review depth + the
  single severity scale. DELEGATE generic code review to pr-review-toolkit; do not pull in
  the heavier `exhaustive-pr-review` plugin.
- **Diff-resolution contract** (architect — load-bearing): `review-pr` resolves its diff
  from the working tree / `gh pr view`, NOT an arbitrary `base..head` range. So the loop
  must resolve the target to a concrete `base_sha..head_sha` and MATERIALIZE it (checkout /
  throwaway integration branch) so the council and `review-pr` review identical bytes.
- **Stdlib-Python resolver** (overrides the pragmatist's "no Python", which assumed
  GitHub-only): multi-provider URL parsing + REST/CLI calls across 3 providers is safer and
  more testable as a small stdlib-Python module (`scripts/pr_resolver.py`, urllib +
  read-only subprocess) than shell string-munging — and it directly addresses the
  guardian's injection concern.
- **Report schema** (architect/skeptic/historian): YAML front-matter
  (`review_id`, target {provider, pr, base_sha, head_sha}, `requirements_source`, overall
  `verdict`, severity counts, generated marker) + a **requirement-traceability matrix**
  (each requirement → covered | violated | unclear, with evidence file:line) +
  severity-keyed merged findings + a dedup note. Pinned in the convening skill as a stable
  contract.
- **Mandate boundaries** (architect): conformance = spec↔diff (does it do what the
  requirements say); correctness = diff↔itself (internal soundness); risk keeps the lone
  REQUEST_CHANGES/SAFETY semantics. Stated in each agent file to prevent duplicate findings.
- **Naming family** (historian): `peer-review` family — `/spec-loop:peer-review` command,
  `peer-review-*` agents, `peer-review-council` skill — no collision with existing
  spec-loop/dashboard/quality-gate/iron-council/escalation-gate/review-depth-map names.
- **Release ritual owed**: `### Added` in CHANGELOG [Unreleased]; Components row in
  plugins/spec-loop/README.md; top-level README.md command tree; version bump via
  `scripts/release.py 1.1.0-alpha.3 --channel alpha` (NOT hand-edited); marketplace.json
  untouched; `description` frontmatter on the new command for CI.

### Deferred (logged, out of this run)
Provider post-back of the report (gh/az/Bitbucket comment APIs), multi-PR batch review,
CI integration, surfacing peer-reviews in the web dashboard, and ANY auto-fix / suggested-
edit capability (explicitly forbidden — the loop must change no implementation).
