# Slice s1 — report

Status: DONE (merged into alpha)
Branch: spec-loop/20260629-docker-dashboard/s1 (deleted post-merge)
Merge commit: cd58f06 on alpha; slice commits e3d051a..9c73175
Council: ENDORSE_WITH_CONCERNS (4/5 EWC; guardian OBJECT but explicitly NOT SAFETY -> single non-SAFETY objection, folded, not a council OBJECT)
Tests: python3 scripts/test_dashboard_server.py -> 47/47 pass (30 pre-existing + 17 new)
Review: 3 Tier-3 reviewers (code-reviewer, silent-failure-hunter, pr-test-analyzer) all NON-BLOCKING; 5 security invariants independently verified
Quality: PASS (1 behavior-preserving refactor: NetworkConfig value object -> build_server back to 4 params; all metrics within thresholds)
Open escalations: none

## What shipped (one server, extended in place)
- Part A: build_server(root, assets_dir, port, net=NetworkConfig(bind_host, advertise_port)).
  Allowlist derives ONLY from the advertised port via _host_allowlist (hardcoded
  127.0.0.1/localhost); bind_host never enters it -> binding 0.0.0.0 never widens
  the allowlist. main() gains --bind-host and --advertise-port.
- Part B: scan_all_roots aggregates scan_runs across roots; multi-root run-ids
  namespaced <root_key>:<run_id> (deterministic, stable, collision de-duped repo#1/#2)
  with a 'root' field; single root stays byte-for-byte (bare run_id, no 'root').
  Detail route decodes id, splits on FIRST ':' only, gates against the OWNING root's
  known-id set, confines via resolve_within scoped to that one root; uniform
  no-path-oracle 404 preserved.

Files: scripts/dashboard_server.py, scripts/test_dashboard_server.py (stayed in scope).
