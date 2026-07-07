# Slice s2 — report

Status: DONE (merged into alpha)
Branch: spec-loop/20260629-docker-dashboard/s2 (deleted post-merge)
Merge commit: f77c787 on alpha; slice commit eb0ef2a (base cd58f06..eb0ef2a)
Council: ENDORSE_WITH_CONCERNS (skeptic/architect/guardian EWC, pragmatist ENDORSE, historian ENDORSE; 0 OBJECT, no SAFETY). Folded: .dockerignore scoped to the two runtime paths only (not blanket !scripts/); header documents empty-default-root behavior + s3 run contract; CMD kept python3; digest-pin explicitly out of scope.
Tests: python3 scripts/test_dashboard_server.py -> 47/47 pass (unchanged; no source touched). docker build + run verified locally.
Review: Tier-2 code-reviewer on Dockerfile+.dockerignore -> NO P0/P1 (blocking bar clean). Below-bar: P3 comment imprecision (fixed), P3 unpinned tag (by design), P2 run-contract enforced by s3 (by design).
Quality: PASS (vacuous — Dockerfile/.dockerignore have no measurable code units; no thresholds apply; config untouched).
Open escalations: none

## What shipped (2 files, within scope)
- Dockerfile: python:3.12-slim (matches CI's pinned 3.12), stdlib only (no pip/build
  stage). Non-root user app (uid/gid 10001), USER app before CMD. COPY bakes ONLY
  scripts/dashboard_server.py + scripts/dashboard_assets/ into /app/scripts/ so the
  server's __file__-relative asset resolution works unchanged. EXPOSE 8787 (doc only).
  CMD ["python3","scripts/dashboard_server.py","--bind-host","0.0.0.0","--port","8787"]
  — no --advertise-port, no --root (s3 supplies both at runtime). Header comment
  documents the REQUIRED run contract s3 enforces (publish -p 127.0.0.1:PORT:PORT
  loopback-only, mount artifacts :ro, --cap-drop ALL, non-root, no --privileged, no
  docker.sock) and that the default-root container serves zero runs until s3 mounts.
- .dockerignore: deny-all (*) then narrow re-include of only the two runtime paths;
  keeps .git, .worktrees, docs/ (run artifacts), tests, pr_resolver.py, release.py,
  validate_marketplace.py, __pycache__ out of the build context.

## Local verification evidence (docker daemon available; NOT a CI dependency)
- docker build -> OK. Runs uid=10001(app) (non-root). Only dashboard_server.py +
  dashboard_assets/index.html baked; tests/docs/other scripts absent.
- server --help resolves. -p 127.0.0.1:8787:8787 -> GET / 200 + /api/runs {"runs":[]}.
  Foreign Host header -> 421 (allowlist NOT widened by the 0.0.0.0 bind — the
  load-bearing anti-DNS-rebinding invariant holds). With --advertise-port matching a
  differently-published host port -> 200 (proves s3's runtime contract).

Single source of truth honored: image runs the EXISTING dashboard_server.py; no fork,
no reimplementation, no new server code. No CI Docker test added (CI has no daemon).
