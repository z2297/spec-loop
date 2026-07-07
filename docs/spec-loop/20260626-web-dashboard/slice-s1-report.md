# Slice s1 report — read-only dashboard server + scan_runs data layer

**Status:** DONE  •  **Run:** 20260626-web-dashboard  •  **Tier:** 2  •  **Merged into:** alpha

## What shipped
- `scripts/dashboard_server.py` — stdlib-only, two layers: (A) pure `scan_runs(docs_root)` reusing dashboard.md's derivation rules verbatim (waves, six honest labels, both OPEN-escalation forms incl. intake, unreadable-tolerance); (B) read-only http.server with hard guardrails (GET/HEAD-only→405, 127.0.0.1 bind, exact Host allowlist, enumerate-and-exact-match run resolution, shared realpath/commonpath containment for data+asset roots, bounded counts+bytes, generic 404s, If-None-Match ETag/304). Endpoints `GET /api/runs` + `GET /api/runs/<id>`; flags `--port` (8787) / `--root`.
- `scripts/test_dashboard_server.py` — 30 stdlib-unittest tests (corrupt-dag→unreadable+siblings survive; split-parent + `<parent>.N` children waves; traversal→404, foreign/substring/absent Host→421, non-GET→405, static traversal→404, escaping symlink→404, no-oracle 404, ETag/304).
- `scripts/dashboard_assets/index.html` — minimal dark placeholder (s2 replaces it).

## Council, review, gate
- **Iron Council (plan):** 4 ENDORSE_WITH_CONCERNS (skeptic/architect/pragmatist/historian) + 1 OBJECT (guardian, explicitly NOT SAFETY). Not a majority and not SAFETY → proceeded with all concerns folded (static-asset realpath confinement + traversal tests; commonpath containment; exact Host/run-id matching; symlink/null-byte/oracle tests; bounded bytes; If-None-Match collection+per-run ETags; data-root resolved once at startup). Pragmatist right-sizing: ONE shippable PR — NOT split.
- **Scoped review (Tier 2, bar=MAJOR+):** no MAJOR/critical findings. 3 below-bar fixes folded (two-signal ANSWERED detection, `main() -> int`, docstring accuracy).
- **Quality gate:** PASS after 2 behavior-preserving refactor passes (ctx-dict + `_derive_label`; wave-derivation helpers; `Response` namedtuple; `slice_obj` kwargs). All metrics under config thresholds.

## Verification (fresh evidence)
- `python3 scripts/test_dashboard_server.py` → Ran 30 tests, OK.
- `python3 scripts/validate_marketplace.py` → exit 0.
- Live curl vs this repo: `/api/runs` → 200 surfacing `20260625-dashboard-cmd` + `20260626-web-dashboard`; ETag re-GET → 304; `../../etc/passwd` run-id → 404; `Host: evil.com` → 421; `/` → 200. Post-merge on alpha re-verified green.

## Scope adherence
Touched only the three declared files. CHANGELOG/READMEs/plugin.json/marketplace.json untouched (owned by s2). No open escalations.
