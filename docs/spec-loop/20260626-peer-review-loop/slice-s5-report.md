# Slice s5 report — release ritual + read-only command CI hardening

**Status:** DONE — merged into `alpha` (no-ff). **Risk tier:** 2. **Depth:** 0. **Deps:** s4 (complete). **Last slice of the run.**

## What shipped
- **CI hardening:** `scripts/validate_marketplace.py` now machine-enforces the read-only
  contract. New `check_readonly_no_edit` + `_allowed_tools` + `READONLY_MARKERS` constant: any
  command whose full text contains a read-only marker (`read-only`/`read only`/`never edits`)
  must not grant `Edit` in its frontmatter `allowed-tools`. Edit-membership is parsed from the
  frontmatter value ONLY (not prose) with exact token equality — so peer-review.md's prose
  ("allowed-tools excludes Edit") and a future `MultiEdit` do not false-positive. Existing
  checks unchanged. New `scripts/test_validate_marketplace.py` (stdlib unittest, mirrors
  test_dashboard_server.py / test_pr_resolver.py idiom): 6 tests — fails an Edit-granting
  read-only command, passes one without Edit, allows Edit on non-read-only commands, prose-only
  + MultiEdit guards, real-repo regression. CI runs the validator (the hardening); the test is
  run manually per the verification gate, matching the prior dashboard convention.
- **Release ritual (alpha):** CHANGELOG `[Unreleased] ### Added` entry for `/spec-loop:peer-review`
  + the 5 `peer-review-*` agents + `peer-review-council` skill + the local report; Components-table
  rows in `plugins/spec-loop/README.md`; top `README.md` directory-tree command/agent/skill
  enumeration + `scripts/` subtree (added the new test). `plugin.json` 1.1.0-alpha.2 → 1.1.0-alpha.3
  via `scripts/release.py ... --channel alpha` (alpha bumps plugin.json only). `.claude-plugin/marketplace.json` untouched.
- **Repo hygiene:** committed the previously-UNTRACKED `.gitignore` (Guardian's objection — it was
  absent on this branch, so `git rm --cached` alone would let the .pyc re-enter), then untracked
  both `scripts/__pycache__/*.cpython-314.pyc`. `git check-ignore` now reports the paths ignored.
- s1–s4 feature files (resolver/agents/skill/command) and marketplace.json untouched.

## Branch / merge
- Branch: `spec-loop/20260626-peer-review-loop/s5` (commit `c004610`); merged into `alpha` no-ff at `84a0931`. Base `0de0b7e..84a0931`. Worktree + merged branch cleaned up.

## Council (Iron Council on the plan)
4 ENDORSE_WITH_CONCERNS (skeptic/architect/pragmatist/historian) + 1 OBJECT (guardian, NON-SAFETY).
Not a council-OBJECT halt (single non-SAFETY objection, no majority). Folded ALL concerns:
guardian's `.gitignore` untracked premise (committed it + verify check-ignore); architect's
frontmatter-only Edit parse + exact-token match + prose-contamination test; pragmatist's keep-as-one-slice
+ trimmed marker set + named constant; historian's scripts/-subtree README sync + test idiom.

## Right-sizing
Judged NOT splittable (Pragmatist concurred): last slice, ~30-line validator + one test + 3 mechanical
doc edits + bump + git rm. Kept as one slice.

## Verification (fresh, hard gate — all green on merged alpha)
- `python3 scripts/validate_marketplace.py` → exit 0 (read-only check passes peer-review.md + both dashboard commands).
- `python3 scripts/test_validate_marketplace.py` → 6/6 OK (incl. the Edit-FAIL and no-Edit-PASS cases).
- `plugin.json` = `1.1.0-alpha.3`; `git diff 0de0b7e HEAD -- .claude-plugin/marketplace.json` empty (untouched).
- `git ls-files | grep -i pyc` → empty; `git check-ignore` on the .pyc paths → exit 0 (ignored).
- Sibling `test_dashboard_server.py` still passes.

## Review / simplify / quality
- Review (pr-review-toolkit, Tier 2): no High/Critical. 1 Medium (test not in CI) — pushed back & logged:
  the CI hardening (validator check) IS in CI; validate.yml is out of declared scope and wiring script
  tests would diverge from the existing convention. 1 Low (allowed-tools parser quoted-array-only) —
  below bar, documented best-effort design; logged.
- Simplify: production code left as-is (already minimal); one cosmetic test import-grouping edit. Behavior-preserving.
- Quality gate: PASS, no refactor. check_readonly_no_edit cc=4/lines=14/nesting=1/params=2; _allowed_tools cc=2/lines=7; Validator class 227 lines — all within thresholds. No thresholds weakened.

## Open escalations
None.
