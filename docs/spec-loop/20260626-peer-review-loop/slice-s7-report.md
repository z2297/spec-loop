# Slice s7 — report

**Goal:** Harden `scripts/validate_marketplace.py` to catch the YAML-frontmatter-parse-error
class LOCALLY (stdlib-only) — the gap that let unquoted colon-space `description` scalars
pass the local gate but fail CI's authoritative `claude plugin validate` (commit f5c96ab).

**Status:** DONE
**Branch:** spec-loop/20260626-peer-review-loop/s7 (merged + deleted)
**Merge:** alpha f5c96ab -> e590fc8 (--no-ff; slice commit 6cdf577)
**Risk tier:** 2 | depth 0 | NOT split

## What changed (2 files only — scope clean)
- `scripts/validate_marketplace.py` (+42): new pure `@staticmethod _frontmatter_value_error(key, value)`
  wired into `read_frontmatter`. Rule 1 (FIRST): a value wrapped in matching single/double
  quotes is safe — even if it contains `': '`. Rule 2: an unquoted value containing `': '`
  is flagged `frontmatter value for '<key>' contains ': ' and must be quoted ...`. Operates
  on the trailing-stripped value (CRLF/trailing-space safe). Documented as a targeted
  heuristic, NOT a YAML parser; CI's `claude plugin validate` remains authoritative.
- `scripts/test_validate_marketplace.py` (+200): `FrontmatterColonSpaceTest` + generalized
  fixtures (`write_frontmatter_plugin`/`run_on_frontmatter`/`command_fm`/`agent_fm`/`skill_fm`).
- No plugin.json / CHANGELOG / README / marketplace.json touched (no version churn).

## Council (Step 1.5)
ENDORSE_WITH_CONCERNS 5/5 (skeptic, architect, pragmatist, guardian, historian — 0 OBJECT,
no SAFETY). Folded before execution: operate on stripped value (regex eats leading ws; only
trailing `\r`/space differs — a naive `endswith(quote)` would false-positive a quoted value);
DROPPED speculative rule 3 (tab — interior tab is legal YAML post-strip) and rule 4 (leading
indicator char — never broke, CI covers it, a 3-of-~18 subset invites drift; 5 real cmd files
have `allowed-tools` starting `[`); ship lean core rules 1+2; extend existing fixtures vs fork.

## Verification (fresh, Step 5)
- `python3 scripts/test_validate_marketplace.py` -> 16/16 OK (RED proven first: 2 colon-space
  cases failed + helper AttributeError before implementation; GREEN after).
- `python3 scripts/validate_marketplace.py` -> exit 0 on current repo.
- Behavior demo: unquoted `': '` FAILS; double- and single-quoted PASS; URL colon-no-space
  NOT flagged; `[`-leading `allowed-tools` NOT flagged; empty value deferred to require_keys.
- Alignment proof: re-introducing the f5c96ab bug -> BOTH local gate AND
  `claude plugin validate plugins/spec-loop/` reject it (the local gate now catches the
  exact class CI catches). Restored cleanly.
- `claude plugin validate plugins/spec-loop/` AND `claude plugin validate .` -> both PASS.
- Siblings unaffected: test_pr_resolver 49/49, test_dashboard_server 30/30. Post-merge on
  alpha: 16/16 + validator exit 0.

## Review / Simplify / Quality (Steps 3-4c)
- Review (Tier 2, pr-review-toolkit:code-reviewer, f5c96ab..HEAD): APPROVE — 0 Critical,
  0 Important. Auto-fix loop NOT entered (nothing at/above the MAJOR bar). 2 NITs below the
  bar (documented scope boundaries deferred to CI), logged not fixed.
- Simplify (code-simplifier): no edits — code already clear/minimal.
- Quality gate: PASS, 0 refactor passes. _frontmatter_value_error cc=6/lines=30/nesting=1/
  params=2; read_frontmatter cc=6/lines=26/nesting=3/params=1; Validator class=265 — all
  within thresholds. Config not weakened.
