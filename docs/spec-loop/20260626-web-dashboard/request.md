# Request

I want to enhance the dashboarding capability. Build an interactive web page that is
able to display the dashboard in near real time. The dahsboard should have a modern
dark theme. Ideally the dashboard would connect to all local sessions for spec-loop

## Resolved up-front (Phase 0 — Iron Council intake + human answers)

This is the **HTML/visual dashboard follow-on** that the prior run
(`20260625-dashboard-cmd`) explicitly deferred as "a separable follow-on." It reads the
same durable artifacts as the read-only `/spec-loop:dashboard` terminal command and
reuses its exact derivation rules — it does NOT introduce a second source of truth.

- **Session scope:** **This repo's runs only.** Discover runs by globbing
  `docs/spec-loop/*/dag.json` in the repo the server is launched from — exactly how the
  terminal dashboard finds runs. No machine-wide filesystem scan; no cross-repo
  discovery. (Multi-root is an explicit, separately-reviewed future follow-on.)
- **Contract:** **Strictly read-only viewer.** "Interactive" = client-side navigation,
  filtering, expanding slices, and auto-refresh. GET/HEAD only, bound to `127.0.0.1`.
  No trigger/resume/cancel/mutate endpoints — preserves the read-only security boundary
  the whole dashboard feature is built on. (Run control from the browser, if ever
  wanted, is a separate security-reviewed feature.)
- **Development base:** **the `alpha` branch** (per the human). Alpha (`1.1.0-alpha.1`)
  is the bleeding-edge channel and already contains the merged read-only
  `/spec-loop:dashboard` markdown command that `main` lacks (the prior run merged it at
  `8f0a55c`/`12bfd65`, which are on `alpha`/`beta` but not `main`). Developing here
  resolves that drift and lets the web dashboard reuse the existing command's contract.
- **Architecture (council-converged):** a stdlib-Python `http.server` (zero third-party
  deps, matching `scripts/*.py`) that scans the run artifacts, serves a JSON API plus a
  self-contained modern dark-theme single-page UI, and achieves "near real time" via
  client-side **polling** (no websockets, no node/build toolchain). Hard guardrails:
  path-traversal-safe (enumerate-and-match run-ids; realpath-under-root), `Host`-header
  allowlist (anti-DNS-rebinding), tolerate half-written `dag.json`, no directory
  listing.
- **"near real time" cadence:** polling every ~2–3s against a localhost JSON endpoint
  is indistinguishable from real time for a source that changes at wave boundaries —
  resolved as PROCEED+log (not surfaced).
