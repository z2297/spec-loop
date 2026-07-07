# Slice s1 report — provider-agnostic READ-ONLY PR resolver

Status: DONE
Branch: spec-loop/20260626-peer-review-loop/s1 (merged --no-ff into alpha, then deleted)
Merge commit: ba33450  | Commits: b04b76f..e80ab5e (7 feature/fix/refactor + 1 hygiene)
Files: scripts/pr_resolver.py (new), scripts/test_pr_resolver.py (new)

Council (pre-execution, Step 1.5): ENDORSE_WITH_CONCERNS — 5 verdicts: skeptic EWC, architect OBJECT (non-SAFETY), pragmatist EWC, guardian OBJECT (non-SAFETY), historian ENDORSE. 2 OBJECT < majority (>=3) and no SAFETY -> aggregate EWC; both objections concrete/cheap/fixable, folded into the plan (provider-specific PR-ref fetch in resolve_diff; --end-of-options + segment allow-list for argv flag-injection; documented contracts; token-leak guard). No split (Pragmatist explicitly rejected per-provider split — one cohesive slice).

Right-sizing (Step 1.6): not split — one independently shippable module + its test.

Tests: `python3 scripts/test_pr_resolver.py` -> 47/47 pass. `python3 scripts/validate_marketplace.py` -> exit 0. Provider detection demonstrated (github/bitbucket/dev.azure.com/visualstudio.com) + rejection of unknown-host and leading-dash-segment URLs, all with no network.

Review: escalated Tier 2 -> Tier 3 depth (security-sensitive external-integration + error-handling surface). code-reviewer CLEAN; type-design 1 P1; silent-failure 2 P1; pr-test-analyzer 1 P1. Auto-fix loop converged in 1 attempt: unified record construction through a single _normalized() constructor; resolve_diff now fetches base+head SHAs and the provider PR-ref, verifies reachability (git rev-parse --verify) and rejects empty-diff-for-distinct-SHAs; added Azure resolve_diff + edge-case tests; wrapped malformed-JSON (P2). Re-review of changed surface: both source aspects CLEAN, no remaining P0/P1. Overall recommendation after auto-fix: APPROVE.

Simplify (Step 4b, non-blocking): code-simplifier added a named _is_remote predicate. No behavior change; tests still green.

Quality (Step 4c): PASS after 1 behavior-preserving refactor pass. Initial breaches vs config — _normalized 11 params (>4), resolve_diff 61 lines (>50) + cyclomatic 11 (>10). Refactored (grouped identity+content dicts; extracted _fetch_argvs + _materialize_commits). Re-measure: all functions within thresholds (cyclo<=10, method_lines<=50, params<=4, nesting<=3; no classes). Behavior preserved (47/47 tests unchanged & green).

Verification (Step 5, hard gate): fresh run on merged alpha — tests 47/47 pass, validator exit 0, provider-detection/rejection demo green.

Security posture delivered: stdlib only; READ verbs only (gh pr view, az repos pr show, git fetch/rev-parse/diff, HTTP GET); single _run choke-point shell=False; pr_id ^[0-9]+$; URL segment allow-list (no leading dash / metachars); host allow-list incl. .visualstudio.com suffix; --end-of-options before every user-derived git arg; BITBUCKET_TOKEN only in the header to the fixed api.bitbucket.org origin, never in argv/errors (tested). 10-field normalized record is the single-source-of-truth inter-slice JSON contract.

Open escalations: none.
