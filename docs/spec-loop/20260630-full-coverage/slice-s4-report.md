# Slice s4 report — raise scripts/dashboard_server.py coverage

**Status:** DONE (merged into alpha).

**Goal:** Add tests for the uncovered HTTP handler branches + a minimal `main(argv=None)` refactor, raising measured coverage of the security-critical read-only dashboard server well above its floor.

**Root cause:** `measure_coverage.py`'s `trace.Trace(count=1)` traces only the CALLING thread; the existing HTTP tests exercised the handler over a real socket on a daemon `serve_forever` thread, so the whole request/response path read as UNCOVERED though behaviorally correct. Fix: invoke the handler methods + helpers synchronously on the test thread (additive, tracer-visible), leaving every real-socket security test untouched.

**Coverage — dashboard_server.py:** 45.0% (166/369) -> **72.1% (266/369)**, floor 42%. +27.1 pts / +100 lines. Gate green; no other file regressed.

**Changes:**
- `scripts/dashboard_server.py`: 4-line behavior-preserving `main(argv=None) -> int` + `ap.parse_args(argv)` refactor (`parse_args(None)` reads `sys.argv[1:]`, so real runs are byte-identical). serve_forever tail (654-659) + `__main__` shim (663-664) unchanged and already OMITted — no OMIT edit needed.
- `scripts/test_dashboard_server.py`: +25 tests — ContentTypeTests, ResponseHelperTests, HandlerUnitTests (in-thread, REAL `_host_allowed`/`resolve_within`/`os.path.isfile`, real `_emit` wire bytes incl. nosniff), MainEntrypointTests (ThreadingHTTPServer seam mocked, mandatory `--port 0`, redirect_stderr warning assertion).

**Security behavioral assertions:** INTACT. The pre-existing real-socket suites (HttpServerTests, BindHostAllowlistTests, MultiRootHttpTests, ContainmentTests) remain the authoritative source of truth for loopback bind, Host allowlist (not widened by 0.0.0.0), GET/HEAD-only 405, per-root realpath+commonpath path-traversal confinement, and uniform no-path-oracle 404 — untouched. New in-thread tests are additive coverage-visibility mirrors; NO security primitive stubbed; reviewers adversarially confirmed the traversal test is load-bearing (a naive resolve_within makes it fail with leaked "TOP SECRET"). The new `_emit` test adds a nosniff-header assertion no socket test had.

**No edits to** measure_coverage.py / coverage_omit.txt / validate.yml (s7's job). See decisions-log for the per-thread-trace finding handed to s7 (no new OMIT entry warranted).
