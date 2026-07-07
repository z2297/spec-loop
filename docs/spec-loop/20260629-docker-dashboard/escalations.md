# Escalations — 20260629-docker-dashboard

## [intake] Iron Council objects: Docker-mandatory framing, "all sessions" scope, and lifecycle contradiction   (status: ANSWERED)
- Trigger: council-objection
- Council verdict: OBJECT (3/5 object — skeptic, pragmatist, historian; architect + guardian ENDORSE_WITH_CONCERNS; no SAFETY blocker)
- Objecting members:
  - skeptic — request is not well-posed: "live updates from all sessions" has ≥2 readings that change scope, and one (cross-repo) breaks the codebase's explicit no-cross-repo-scan guarantee; "shared across sessions" conflicts with "exit/no-drift when the terminal closes."
  - pragmatist — mandatory Docker is a hard new runtime dependency that breaks plugin end users without a Docker daemon and buys nothing over the existing zero-dep `python3 dashboard_server.py` for a localhost read-only viewer; should be opt-in.
  - historian — Docker-as-required-runtime reverses the repo's load-bearing stdlib-only/no-build/zero-third-party constitution and the deliberately DEFERRED single-repo scoping (docs/spec-loop/20260626-web-dashboard/decisions-log.md).
- Reinforcing concerns (architect + guardian): a detached container is orphaned from the terminal by construction, so literal terminal-lifetime teardown needs an explicit ownership/naming model; must-not-regress security invariants — publish `127.0.0.1:PORT:PORT` only (never LAN-exposed), keep the Host-header allowlist closed (no `*`), mount run artifacts read-only (`:ro`), per-repo-scoped teardown (never unscoped `docker rm -f`), least-privilege image (non-root, cap-drop, no docker.sock).
- The decision: three coupled questions for the human (see AskUserQuestion round). Docker mandatory-vs-opt-in; the meaning of "all sessions"; and how to reconcile a shared/persistent container with "exit when the terminal closes / no drift."
- Options: see the batched AskUserQuestion round.
- If unanswered: block the run (intake-scoped objection; nothing scheduled until resolved).
- Answer:
  1. Docker mode = **Docker preferred, python fallback**. Container is the default WHEN a Docker daemon is available; silently fall back to the existing `python3 scripts/dashboard_server.py` when Docker is absent/down (clear message). The direct-python path MUST remain fully functional.
  2. Sessions scope = **Cross-repo / machine-wide**. One aggregated view across multiple repos/working dirs on the machine. This is the previously-deferred multi-root feature; implement it while HONORING the Guardian's must-not-regress security invariants (loopback-only publish, closed Host allowlist, read-only mounts, minimal-scope mounts — NO broad `$HOME` mount, per-root confinement preserved, least-privilege image).
  3. Lifecycle = **Idempotent + explicit stop**, applied at machine scope: a SINGLE machine-wide singleton container (deterministic fixed name). Launch = start detached if absent, else reuse & reprint URL (never a second container); register this repo's root into the aggregated view; Claude only starts the listener and EXITS (holds no shell). Explicit `--stop` tears it down. Stale/closed-repo roots are pruned from the view so there is no drift.
