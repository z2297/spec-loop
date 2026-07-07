# Slice s7 — finalize coverage gate — NEEDS_DECISION (Iron Council OBJECT)

Status: NEEDS_DECISION (halted at Step 1.5, before execution — no code changed).
Branch: spec-loop/20260630-full-coverage/s7 (worktree at .worktrees/spec-loop/20260630-full-coverage/s7, branched from alpha tip 8cfd864). No commits.
Council: OBJECT 3/5 (Architect, Skeptic, Guardian — none SAFETY; Pragmatist ENDORSE, Historian ENDORSE_WITH_CONCERNS). Majority-OBJECT → lift to human per iron-council (not autonomously foldable).

Why halted: the plan's fix mechanism (purge target modules + re-import fresh under trace BEFORE running the already-discovered suite) splits each target into two live module identities. Empirically confirmed by the Architect: baseline 310 tests / 0 fail vs the plan's ordering = 12 errors / 6 failures — the suite goes red, the gate returns 1, and coverage can never be reported. Skeptic: 54 string-target mock.patch sites would also patch the wrong object. Guardian (non-SAFETY): floors "rounded down ~2-3 pts" from local py3.14 are too thin for CI py3.12 co_lines() drift (false-red wedge risk).

Proven remedy (recommended in escalation): move test discovery INSIDE tracer.runfunc, AFTER the fresh re-import, so the suite binds one traced module copy (verified: suite stays green, release.py import-time lines get attributed); widen the floor round-down margin to >=5 pts; refresh the stale 188-test/54.0% baseline block to the current 310-test/79.2% reality; rewrite the now-false "under-report is safe direction" docstring.

BEFORE numbers (current tool, this worktree, verified): launcher 72.4% (173/239), server 77.0% (284/369), pr_resolver 82.8% (227/274), release 82.4% (103/125), validate_marketplace 84.1% (175/208); TOTAL 79.2% (962/1215); 310 tests pass; Node 15/15.
Corrected-fix preview (prototype, honest logic coverage): launcher ~100%, server ~100%, pr_resolver ~85.4% (40 genuinely-unhit lines — real gap, ~85% is a healthy floor, logged not escalated), release ~100%, validate_marketplace ~99.5%.

Escalation written to escalations.md ([s7] council-objection, OPEN). Decision logged to decisions-log.md. No merge, no PR, no files under the slice's file-set modified.
