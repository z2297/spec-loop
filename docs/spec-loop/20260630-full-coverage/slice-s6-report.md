# Slice s6 — Node-builtin test harness for the client JS

STATUS: DONE
Branch: spec-loop/20260630-full-coverage/s6 → merged into alpha (--no-ff, d449ae7)
Commits: 52f730b..5f4f0c4 (impl, review auto-fix ×2, simplify) + merge d449ae7

## How the single-file page became testable without breaking
Internal dual-mode seams in the SAME inline <script>, all inert in a browser:
- HAS_DOM guard around every top-level browser side effect (DOM refs, initial
  `view = parseHash()`, and the hashchange/setInterval/enterView bootstrap) so
  importing under Node arms no listeners/timers/fetch.
- `_doc`/`__setDocument()` seam so el() DOM output is testable (byte-identical in a
  browser: _doc === document).
- `parseHashFrom(hash)` pure core extracted from parseHash().
- Browser-inert `/* test-export */` UMD tail (module undefined in a classic script).
The page stays self-contained (browser loads nothing but the inline script; 1 fetch
GET unchanged, 0 new network verbs).

## Coverage transport (folds Iron Council architect OBJECT)
node:vm string-load yields ZERO coverage attribution; instead index.test.mjs extracts
the inline script → strips the UMD tail → appends an ESM export → writes a temp .mjs →
import()s it as a REAL module, so `--experimental-test-coverage` attributes coverage to
the client code (verified). Numeric coverage floor deferred to s7 (Node 20 lacks
per-metric threshold flags).

## Node test run
`node --test --experimental-test-coverage scripts/dashboard_assets/index.test.mjs`
→ 15 tests, 15 pass, 0 fail. Coverage attributes to the extracted client module
(~49% line = the deliberate in-scope subset; poll/fetch/freshness/orchestrator layer
out of scope for s6). CI step added after setup-node with two fail-closed gates:
node exit-status AND a >=12 min-test-count floor.
