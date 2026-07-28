#!/usr/bin/env python3
"""Guard tests for run_metrics.py — the run-metrics harness.

Fixture strategy:
* LEGACY_* fixtures are verbatim-shaped excerpts of the committed
  docs/spec-loop/20260630-full-coverage artifacts, pinning the lenient
  parsers against the real (un-instrumented) log grammar — including the
  drift the parsers must accept (REVERSIBILITY: high / n/a, negated SAFETY
  mentions, "tests pass" prose vs PASS verdict tokens).
* MODERN_* fixtures carry the instrumented fields (AT timestamps, Opened/
  Answered-at, sidecar started_at/finished_at/wave/counters) and pin the
  performance/precision channels.
* Everything runs against isolated tmp dirs; git via the established
  mock.patch("run_metrics.subprocess.run") argv-recording-fake pattern;
  transcripts are synthetic files in the fixture layout run_metrics expects.

Standard library only (unittest).
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import run_metrics as rm


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

LEGACY_DECISIONS = """\
# Decisions Log — legacy

Append-only. One line per autonomous decision made on the human's behalf.

[intake] COUNCIL: ENDORSE_WITH_CONCERNS — 2/5 OBJECT (skeptic, pragmatist: literal "every line"/100% ill-posed), architect+guardian+historian EWC. No SAFETY. Below majority-halt.
[intake] DECISION: durable coverage gate lives in the REPO's .github/workflows/validate.yml — RATIONALE: repo-scoped, deterministic. — REVERSIBILITY: moderate.
[s1] COUNCIL on plan: ENDORSE_WITH_CONCERNS — 1/5 OBJECT (guardian, explicitly NOT SAFETY), skeptic+architect+pragmatist+historian EWC. — REVERSIBILITY: high.
[s1] QUALITY-GATE: initial FAIL (2 breaches) → PASS after 1 behavior-preserving refactor pass. — REVERSIBILITY: high.
[s1] MERGE: slice merged into alpha via --no-ff (merge commit f5c84ef). — REVERSIBILITY: high.
[s3] QUALITY-GATE: PASS on first measurement, no refactor loop needed.
[s7] COUNCIL: OBJECT — 3/5 object (Architect, Skeptic, Guardian; none SAFETY). Majority-OBJECT halts. — REVERSIBILITY: n/a (no code changed; plan not executed).
[s7] HUMAN RESOLVED — Option 1: apply the council's proven remedy.
[s5] DONE — dashboard_launcher.py 65.7%->72.4%; merge ccce2bb.
[s2] MERGE: slice merged into alpha via --no-ff (merge commit fb1a744; slice commit a576ce0, cut from f5c84ef). — REVERSIBILITY: high.
[wave2] INTEGRATION CHECK: 281 tests pass, coverage gate PASS, TOTAL 54.0%->77.0%.
[phase5] INTEGRATION GATE: PASS. Full suite 313 tests. RUN COMPLETE.
[s7] FAIL-CLOSED verified (local dry-run, reverted): Python gate rc=1 on a floor perturbed to 101%. — REVERSIBILITY: high.
"""

LEGACY_ESCALATIONS = """\
# Escalations — legacy

## [intake] Define "every line tested": target, client-JS scope, and durability   (status: ANSWERED)
- Trigger: ambiguity + material-assumption (Iron Council ENDORSE_WITH_CONCERNS; skeptic + pragmatist OBJECT on well-posedness)
- Context: "Ensure that every line of code is tested" specifies no metric.
- The decision: three coupled scope questions.
- If unanswered: block the run.
- Answer:
  1. Target = **Coverable-max + documented exclusions**.

## [s7] Iron Council objects: coverage-fix ordering splits module identity   (status: ANSWERED)
- Trigger: council-objection
- The decision: how should the slice worker proceed on the objected-to plan?
- If unanswered: pause this slice (s7); continue all independent slices.
- Answer: **Option 1 — apply the council's proven remedy, then execute.**
"""

LEGACY_DAG = {
    "base_ref": "alpha",
    "base_sha": "ac3759b88f4b3c8f49017a12edd2ef6188c890f9",
    "shared_constraints": [],
    "slices": [
        {"id": "s1", "deps": [], "risk_tier": 2, "depth": 0,
         "parent": None, "status": "complete"},
        {"id": "s2", "deps": ["s1"], "risk_tier": 2, "depth": 0,
         "parent": None, "status": "complete"},
        {"id": "s3", "deps": ["s1"], "risk_tier": 2, "depth": 0,
         "parent": None, "status": "split"},
        {"id": "s3a", "deps": ["s1"], "risk_tier": 2, "depth": 1,
         "parent": "s3", "status": "complete"},
    ],
}

MODERN_DAG = {
    "base_ref": "alpha",
    "merge_mode": "single-branch",
    "created_at": "2026-07-14T10:00:00Z",
    "shared_constraints": [],
    "slices": [
        {"id": "s1", "deps": [], "risk_tier": 2, "depth": 0,
         "parent": None, "status": "complete"},
        {"id": "s2", "deps": [], "risk_tier": 1, "depth": 0,
         "parent": None, "status": "complete"},
        {"id": "r1", "deps": ["s1", "s2"], "risk_tier": 1, "depth": 0,
         "parent": None, "status": "complete", "remediation": True},
    ],
}

MODERN_DECISIONS = """\
# Decisions Log — modern

[intake] DECISION: reuse existing helper — RATIONALE: precedent — run 20260630-full-coverage (same question answered). — REVERSIBILITY: trivial. — AT: 2026-07-14T10:02:00Z
[s1] DECISION: keep the function name — RATIONALE: file convention. — REVERSIBILITY: trivial. — AT: 2026-07-14T10:30:00Z
[s1] REVIEW-FINDING REFUTED: claimed nil-deref is behind an isinstance guard (verifier, file:line evidence). — AT: 2026-07-14T10:45:00Z
[phase5] INTEGRATION GATE: PASS. — AT: 2026-07-14T11:30:00Z
"""

MODERN_ESCALATIONS = """\
# Escalations — modern

## [s2] Choose serializer   (status: ANSWERED)
- Trigger: material-assumption
- Opened: 2026-07-14T10:15:00Z
- Context: two candidate formats.
- The decision: which serializer?
- Answer: use JSON.
- Answered-at: 2026-07-14T10:25:00Z
"""

MODERN_SIDECAR_S1 = {
    "version": 1, "id": "s1", "status": "DONE",
    "started_at": "2026-07-14T10:10:00Z",
    "finished_at": "2026-07-14T11:10:00Z",
    "wave": 1,
    "counters": {"review_confirmed": 2, "review_refuted": 1, "fix_passes": 1,
                 "quality_refactor_passes": 2, "fail_closed": 1},
}

MODERN_SIDECAR_S2 = {
    "version": 1, "id": "s2", "status": "DONE",
    "started_at": "2026-07-14T10:20:00Z",
    "finished_at": "2026-07-14T11:00:00Z",
    "wave": 1,
    "counters": {"fail_closed": 0},
}

MODERN_RUNBOOK = """\
# Runbook — modern

## 4. Requirement Traceability

| Requirement (from request / slice goal) | Status | Evidence (commit / test) |
|------------------------------------------|--------|--------------------------|
| Parse decisions log | delivered | abc1234 |
| Cross-run trend report | delivered | abc1234 |
| Token capture | partial | best-effort, transcripts opt-in |
| Dashboard charts | deferred | next run |

## 5. Decisions Summary
"""


def write_run(root, run_id, files):
    """Write a synthetic run directory; dict/list values become JSON files."""
    run_dir = Path(root) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        path = run_dir / name
        if isinstance(content, (dict, list)):
            path.write_text(json.dumps(content, indent=1), encoding="utf-8")
        else:
            path.write_text(content, encoding="utf-8")
    return run_dir


def legacy_files():
    return {"dag.json": LEGACY_DAG, "decisions-log.md": LEGACY_DECISIONS,
            "escalations.md": LEGACY_ESCALATIONS}


def modern_files():
    return {
        "dag.json": MODERN_DAG,
        "decisions-log.md": MODERN_DECISIONS,
        "escalations.md": MODERN_ESCALATIONS,
        "runbook.md": MODERN_RUNBOOK,
        "slice-s1-status.json": MODERN_SIDECAR_S1,
        "slice-s2-status.json": MODERN_SIDECAR_S2,
    }


def compute_for(files, run_id="fixture-run"):
    with tempfile.TemporaryDirectory() as tmp:
        run_dir = write_run(tmp, run_id, files)
        return rm.compute_metrics(rm.load_run_artifacts(run_dir))


USAGE_A = {"input_tokens": 100, "output_tokens": 50,
           "cache_read_input_tokens": 10, "cache_creation_input_tokens": 5}
USAGE_SUB = {"input_tokens": 200, "output_tokens": 80}


def write_transcripts(root, sub_ts="2026-07-14T10:30:00Z"):
    """Two sessions: sess-a on branch alpha (with one subagent, one malformed
    line, one usage-less line) and sess-b on an unrelated branch."""
    root = Path(root)
    lines_a = [
        json.dumps({"timestamp": "2026-07-14T10:05:00Z", "gitBranch": "alpha",
                    "message": {"usage": USAGE_A}}),
        "this is not json {{{",
        json.dumps({"type": "user", "timestamp": "2026-07-14T10:06:00Z",
                    "gitBranch": "alpha"}),
    ]
    (root / "sess-a.jsonl").write_text("\n".join(lines_a) + "\n",
                                       encoding="utf-8")
    sub = root / "sess-a" / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-1.meta.json").write_text(json.dumps(
        {"agentType": "spec-loop:spec-loop-slice",
         "description": "slice s1 worker"}), encoding="utf-8")
    (sub / "agent-1.jsonl").write_text(json.dumps(
        {"timestamp": sub_ts, "message": {"usage": USAGE_SUB}}) + "\n",
        encoding="utf-8")
    (root / "sess-b.jsonl").write_text(json.dumps(
        {"timestamp": "2026-07-14T10:05:00Z", "gitBranch": "other-branch",
         "message": {"usage": {"input_tokens": 999, "output_tokens": 999}}})
        + "\n", encoding="utf-8")


def transcript_spec(**overrides):
    spec = {"run_id": "20260714-modern", "base_ref": "alpha",
            "window": None, "slice_ids": ["s1", "s2"]}
    spec.update(overrides)
    return spec


# ---------------------------------------------------------------------------
# decisions-log parsing
# ---------------------------------------------------------------------------

class DecisionsLogParseTests(unittest.TestCase):
    def setUp(self):
        self.events = rm.parse_decisions_log(LEGACY_DECISIONS)

    def test_one_event_per_bracketed_line(self):
        self.assertEqual(len(self.events), 13)
        self.assertEqual(self.events[0]["token"], "intake")

    def test_tag_classification(self):
        tags = [e["tag"] for e in self.events]
        self.assertEqual(tags.count("council"), 3)
        self.assertEqual(tags.count("decision"), 1)
        self.assertEqual(tags.count("quality_gate"), 2)
        self.assertEqual(tags.count("merge"), 2)
        self.assertEqual(tags.count("integration"), 2)
        self.assertEqual(tags.count("done"), 1)
        self.assertEqual(tags.count("human_resolved"), 1)

    def test_refuted_classified_before_review(self):
        events = rm.parse_decisions_log(MODERN_DECISIONS)
        self.assertEqual([e["tag"] for e in events].count("refuted"), 1)

    def test_reversibility_accepts_observed_drift(self):
        mix = [e["reversibility"] for e in self.events if e["reversibility"]]
        self.assertEqual(mix.count("moderate"), 1)
        self.assertEqual(mix.count("high"), 5)
        self.assertEqual(mix.count("n/a"), 1)

    def test_unknown_reversibility_becomes_other(self):
        events = rm.parse_decisions_log(
            "[s1] DECISION: x — REVERSIBILITY: reversible-ish.")
        self.assertEqual(events[0]["reversibility"], "other")

    def test_merge_shas_collected_slice_commits_ignored(self):
        shas = {sha for e in self.events for sha in e["shas"]}
        self.assertEqual(shas, {"f5c84ef", "fb1a744", "ccce2bb"})

    def test_at_suffix_parsed_only_when_valid_iso(self):
        events = rm.parse_decisions_log(
            "[s1] DECISION: a — AT: 2026-07-14T10:00:00Z\n"
            "[s2] DECISION: b — AT: not-a-date\n"
            "[s3] DECISION: c")
        self.assertEqual(events[0]["at"], "2026-07-14T10:00:00Z")
        self.assertIsNone(events[1]["at"])
        self.assertIsNone(events[2]["at"])

    def test_unbracketed_lines_ignored(self):
        events = rm.parse_decisions_log("# heading\n\nplain prose line\n")
        self.assertEqual(events, [])


class SafetyDetectionTests(unittest.TestCase):
    def test_negated_mentions_do_not_count(self):
        for text in ("none SAFETY", "No SAFETY (guardian explicit)",
                     "explicitly NOT SAFETY", "non-SAFETY: false-red",
                     "0 SAFETY objections"):
            self.assertFalse(rm._mentions_unnegated_safety(text), text)

    def test_unnegated_mention_counts(self):
        self.assertTrue(rm._mentions_unnegated_safety(
            "OBJECT — guardian raises a SAFETY blocker on data loss"))

    def test_council_stats_on_legacy_log(self):
        stats = rm._council_stats(rm.parse_decisions_log(LEGACY_DECISIONS))
        self.assertEqual(stats["lines"], 3)
        self.assertEqual(stats["verdicts"]["ENDORSE_WITH_CONCERNS"], 2)
        self.assertEqual(stats["verdicts"]["OBJECT"], 1)
        self.assertAlmostEqual(stats["object_rate"], 1 / 3, places=3)
        self.assertEqual(stats["safety_objections"], 0)

    def test_safety_objection_counted_on_object_line(self):
        events = rm.parse_decisions_log(
            "[s1] COUNCIL: OBJECT — guardian SAFETY blocker: secrets in log.")
        self.assertEqual(rm._council_stats(events)["safety_objections"], 1)


# ---------------------------------------------------------------------------
# escalations parsing
# ---------------------------------------------------------------------------

class EscalationParseTests(unittest.TestCase):
    def test_legacy_blocks_statuses_and_triggers(self):
        escs = rm.parse_escalations(LEGACY_ESCALATIONS)
        self.assertEqual(len(escs), 2)
        self.assertEqual([e["status"] for e in escs],
                         ["ANSWERED", "ANSWERED"])
        self.assertEqual(escs[0]["triggers"],
                         ["ambiguity", "material-assumption"])
        self.assertEqual(escs[1]["triggers"], ["council-objection"])
        self.assertEqual(escs[0]["token"], "intake")
        self.assertEqual(escs[1]["token"], "s7")

    def test_open_block_stays_open(self):
        escs = rm.parse_escalations(
            "## [s1] Pick a port   (status: OPEN)\n"
            "- Trigger: material-assumption\n- Answer:\n")
        self.assertEqual(escs[0]["status"], "OPEN")

    def test_filled_answer_overrides_open_header(self):
        escs = rm.parse_escalations(
            "## [s1] Pick a port   (status: OPEN)\n"
            "- Trigger: material-assumption\n- Answer: use 8080.\n")
        self.assertEqual(escs[0]["status"], "ANSWERED")

    def test_unmatched_trigger_becomes_other(self):
        escs = rm.parse_escalations(
            "## [s1] T   (status: OPEN)\n- Trigger: cosmic rays\n")
        self.assertEqual(escs[0]["triggers"], ["other"])

    def test_opened_and_answered_at_parsed(self):
        escs = rm.parse_escalations(MODERN_ESCALATIONS)
        self.assertEqual(escs[0]["opened"], "2026-07-14T10:15:00Z")
        self.assertEqual(escs[0]["answered_at"], "2026-07-14T10:25:00Z")


# ---------------------------------------------------------------------------
# gate / runbook / dag / sidecar parsing
# ---------------------------------------------------------------------------

class QualityGateParseTests(unittest.TestCase):
    def test_first_pass_rate_and_iterations(self):
        stats = rm._quality_gate_stats(
            rm.parse_decisions_log(LEGACY_DECISIONS))
        self.assertEqual(stats["measurements"], 2)
        self.assertEqual(stats["first_pass"], 1)
        self.assertAlmostEqual(stats["first_pass_rate"], 0.5)
        self.assertEqual(stats["refactor_passes_total"], 1)
        self.assertEqual(stats["failures"], 0)

    def test_lowercase_pass_prose_is_not_a_verdict(self):
        self.assertIsNone(rm._line_result(
            "measurement skipped; one refactor pass noted, tests pass"))
        self.assertEqual(rm._line_result("coverage gate PASS"), "PASS")
        self.assertEqual(rm._line_result("gate FAIL after budget"), "FAIL")

    def test_no_gate_lines_all_null(self):
        stats = rm._quality_gate_stats([])
        self.assertEqual(stats["measurements"], 0)
        self.assertIsNone(stats["first_pass_rate"])
        self.assertIsNone(stats["refactor_passes_total"])


class RunbookParseTests(unittest.TestCase):
    def test_traceability_counts(self):
        counts = rm.parse_runbook_traceability(MODERN_RUNBOOK)
        self.assertEqual(counts,
                         {"delivered": 2, "partial": 1, "deferred": 1})

    def test_absent_section_is_none(self):
        self.assertIsNone(rm.parse_runbook_traceability("# Runbook\nprose\n"))
        self.assertIsNone(rm.parse_runbook_traceability(""))


class DagAndSidecarParseTests(unittest.TestCase):
    def test_dag_splits_depth_and_remediation(self):
        dag = rm.parse_dag(LEGACY_DAG)
        self.assertEqual(dag["slice_count"], 4)
        self.assertEqual(dag["split_parents"], 1)
        self.assertEqual(dag["max_depth"], 1)
        self.assertEqual(dag["remediation_count"], 0)
        self.assertEqual(rm.parse_dag(MODERN_DAG)["remediation_count"], 1)

    def test_malformed_dag_is_none(self):
        self.assertIsNone(rm.parse_dag(None))
        self.assertIsNone(rm.parse_dag({"slices": "nope"}))
        self.assertIsNone(rm.parse_dag([1, 2]))

    def test_sidecar_optional_fields(self):
        sc = rm.parse_sidecar(MODERN_SIDECAR_S1)
        self.assertEqual(sc["wave"], 1)
        self.assertEqual(sc["counters"]["review_confirmed"], 2)
        legacy = rm.parse_sidecar({"version": 1, "id": "s1", "status": "DONE"})
        self.assertIsNone(legacy["started_at"])
        self.assertIsNone(legacy["wave"])
        self.assertIsNone(legacy["counters"])

    def test_sidecar_rejects_garbage_fields(self):
        sc = rm.parse_sidecar({
            "id": "s1", "status": "DONE", "wave": True,
            "started_at": "yesterday-ish",
            "counters": {"fail_closed": -1, "unknown_key": 3,
                         "fix_passes": 2},
        })
        self.assertIsNone(sc["wave"])
        self.assertIsNone(sc["started_at"])
        self.assertEqual(sc["counters"], {"fix_passes": 2})


# ---------------------------------------------------------------------------
# compute_metrics — legacy (retroactive) and modern (instrumented)
# ---------------------------------------------------------------------------

class LegacyComputeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.metrics = compute_for(legacy_files(), run_id="20260101-legacy")

    def test_sources(self):
        self.assertEqual(self.metrics["sources"], {
            "dag": True, "decisions_log": True, "escalations": True,
            "sidecars": 0, "runbook": False, "git": False,
            "transcripts": False,
        })

    def test_safety_section(self):
        safety = self.metrics["safety"]
        self.assertEqual(safety["escalations"]["total"], 2)
        self.assertEqual(safety["escalations"]["answered"], 2)
        self.assertEqual(safety["escalations"]["by_trigger"], {
            "ambiguity": 1, "material-assumption": 1, "council-objection": 1})
        self.assertEqual(safety["decisions_total"], 1)
        self.assertAlmostEqual(safety["autonomy_ratio"], 1 / 3, places=3)
        self.assertEqual(safety["fail_closed_events"],
                         {"count": 1, "basis": "keyword"})
        self.assertEqual(safety["reversibility_mix"],
                         {"moderate": 1, "high": 5, "n/a": 1})

    def test_quality_section(self):
        quality = self.metrics["quality"]
        self.assertEqual(quality["merges"]["count"], 3)
        self.assertEqual(quality["integration"]["gate"], "PASS")
        self.assertEqual(len(quality["integration"]["checks"]), 2)
        self.assertAlmostEqual(quality["splits"]["split_rate"], 0.25)
        self.assertIsNone(quality["sidecar_counters"])
        self.assertIsNone(quality["requirement_coverage"])
        self.assertEqual(quality["slice_outcomes"]["basis"], "dag")
        self.assertEqual(quality["slice_outcomes"]["counts"],
                         {"complete": 3, "split": 1})

    def test_performance_degrades_to_none(self):
        perf = self.metrics["performance"]
        self.assertEqual(perf["basis"], "none")
        self.assertIsNone(perf["run_wall_clock_s"])
        self.assertIsNone(perf["slices"])
        self.assertIsNone(perf["waves"])
        self.assertIsNone(perf["escalation_answer_latency_s"])

    def test_tokens_null_without_transcripts(self):
        self.assertIsNone(self.metrics["tokens"])


class ModernComputeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.metrics = compute_for(modern_files(), run_id="20260714-modern")

    def test_performance_from_timestamps(self):
        perf = self.metrics["performance"]
        self.assertEqual(perf["basis"], "timestamps")
        self.assertEqual(perf["run_wall_clock_s"], 5400.0)
        self.assertEqual(perf["slices"], {"s1": 3600.0, "s2": 2400.0})
        self.assertEqual(perf["waves"],
                         [{"wave": 1, "slices": 2, "max_parallelism": 2}])
        self.assertEqual(perf["escalation_answer_latency_s"],
                         {"count": 1, "median_s": 600.0, "max_s": 600.0})

    def test_fail_closed_prefers_sidecar_basis(self):
        self.assertEqual(self.metrics["safety"]["fail_closed_events"],
                         {"count": 1, "basis": "sidecar"})

    def test_sidecar_counters_summed(self):
        self.assertEqual(self.metrics["quality"]["sidecar_counters"], {
            "review_confirmed": 2, "review_refuted": 1, "fix_passes": 1,
            "quality_refactor_passes": 2, "fail_closed": 1,
        })

    def test_precedent_reuse_detected(self):
        self.assertEqual(self.metrics["safety"]["precedent_reuse"],
                         {"count": 1, "rate": 0.5})

    def test_requirement_coverage(self):
        self.assertEqual(self.metrics["quality"]["requirement_coverage"], {
            "delivered": 2, "partial": 1, "deferred": 1, "rate": 0.5})

    def test_refuted_findings_logged(self):
        self.assertEqual(
            self.metrics["quality"]["review"]["refuted_findings_logged"], 1)

    def test_slice_outcomes_from_sidecars(self):
        self.assertEqual(self.metrics["quality"]["slice_outcomes"],
                         {"basis": "sidecars", "counts": {"DONE": 2}})


class DegradationTests(unittest.TestCase):
    def test_empty_run_dir_yields_null_honest_document(self):
        metrics = compute_for({}, run_id="empty")
        self.assertEqual(metrics["schema_version"], rm.SCHEMA_VERSION)
        self.assertFalse(metrics["sources"]["dag"])
        self.assertEqual(metrics["safety"]["escalations"]["total"], 0)
        self.assertIsNone(metrics["safety"]["autonomy_ratio"])
        self.assertIsNone(metrics["safety"]["fail_closed_events"]["count"])
        self.assertIsNone(metrics["quality"]["splits"])
        self.assertEqual(metrics["performance"]["basis"], "none")
        self.assertIsNone(metrics["tokens"])

    def test_malformed_dag_decisions_still_parse(self):
        metrics = compute_for({"dag.json": "{{{not json",
                               "decisions-log.md": LEGACY_DECISIONS})
        self.assertFalse(metrics["sources"]["dag"])
        self.assertEqual(metrics["safety"]["decisions_total"], 1)
        self.assertIsNone(metrics["quality"]["splits"])

    def test_malformed_sidecar_skipped(self):
        metrics = compute_for({"slice-s1-status.json": "not json",
                               "slice-s2-status.json": MODERN_SIDECAR_S2})
        self.assertEqual(metrics["sources"]["sidecars"], 1)


# ---------------------------------------------------------------------------
# git enrichment
# ---------------------------------------------------------------------------

class GitTimingTests(unittest.TestCase):
    def test_two_dates_set_git_basis(self):
        metrics = compute_for(legacy_files())
        rm.merge_git_timing(metrics, {
            "aaaaaaa": "2026-07-14T10:00:00+00:00",
            "bbbbbbb": "2026-07-14T12:00:00+00:00",
        })
        perf = metrics["performance"]
        self.assertEqual(perf["run_wall_clock_s"], 7200.0)
        self.assertEqual(perf["basis"], "git")
        self.assertTrue(metrics["sources"]["git"])

    def test_single_date_leaves_wall_clock_null(self):
        metrics = compute_for(legacy_files())
        rm.merge_git_timing(metrics, {"aaaaaaa": "2026-07-14T10:00:00+00:00"})
        self.assertIsNone(metrics["performance"]["run_wall_clock_s"])
        self.assertEqual(metrics["performance"]["basis"], "none")

    def test_timestamp_basis_never_downgraded(self):
        metrics = compute_for(modern_files())
        rm.merge_git_timing(metrics, {
            "aaaaaaa": "2026-07-10T00:00:00+00:00",
            "bbbbbbb": "2026-07-11T00:00:00+00:00",
        })
        self.assertEqual(metrics["performance"]["basis"], "timestamps")
        self.assertEqual(metrics["performance"]["run_wall_clock_s"], 5400.0)

    def test_git_commit_dates_skips_unresolvable_shas(self):
        calls = []

        def fake_run(argv, **kwargs):
            calls.append(argv)
            if argv[-1] == "badbadb":
                return SimpleNamespace(returncode=128, stdout="", stderr="x")
            return SimpleNamespace(
                returncode=0, stdout="2026-07-14T10:00:00-06:00\n", stderr="")

        with mock.patch("run_metrics.subprocess.run", side_effect=fake_run):
            dates = rm._git_commit_dates("/repo", ["aaaaaaa", "badbadb"])
        self.assertEqual(list(dates), ["aaaaaaa"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][:4], ["git", "-C", "/repo", "show"])


# ---------------------------------------------------------------------------
# token capture (best-effort transcripts)
# ---------------------------------------------------------------------------

class TokenCaptureTests(unittest.TestCase):
    def collect(self, **spec_overrides):
        with tempfile.TemporaryDirectory() as tmp:
            write_transcripts(tmp)
            return rm.collect_usage_rows(tmp, transcript_spec(**spec_overrides))

    def test_qualifies_by_branch_and_sums_subagents(self):
        collected = self.collect()
        self.assertEqual(collected["sessions"], 1)
        self.assertEqual(len(collected["rows"]), 2)
        self.assertEqual(collected["parse_skipped"], 1)
        totals = rm._sum_usage(r["usage"] for r in collected["rows"])
        self.assertEqual(totals, {"input": 300, "output": 130,
                                  "cache_read": 10, "cache_creation": 5})

    def test_qualifies_by_run_id_in_session_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_transcripts(tmp)
            (Path(tmp) / "sess-c.jsonl").write_text(json.dumps(
                {"timestamp": "2026-07-14T10:07:00Z", "gitBranch": "main",
                 "cwd": "/x/docs/spec-loop/20260714-modern",
                 "message": {"usage": {"input_tokens": 7,
                                       "output_tokens": 3}}}) + "\n",
                encoding="utf-8")
            collected = rm.collect_usage_rows(
                tmp, transcript_spec(base_ref="nope"))
        self.assertEqual(collected["sessions"], 1)
        self.assertEqual(len(collected["rows"]), 1)
        self.assertEqual(collected["rows"][0]["usage"]["input"], 7)

    def test_non_qualifying_sessions_excluded(self):
        collected = self.collect(base_ref="nonexistent-branch",
                                 run_id="no-such-run")
        self.assertEqual(collected["sessions"], 0)
        self.assertEqual(collected["rows"], [])

    def test_window_filters_rows(self):
        collected = self.collect(window=("2026-07-14T10:00:00Z",
                                         "2026-07-14T10:10:00Z"))
        self.assertEqual(len(collected["rows"]), 1)
        self.assertEqual(collected["rows"][0]["usage"]["input"], 100)

    def test_subagent_attribution(self):
        metrics = compute_for(modern_files(), run_id="20260714-modern")
        rm.merge_token_usage(metrics, self.collect())
        tokens = metrics["tokens"]
        self.assertTrue(tokens["best_effort"])
        self.assertEqual(tokens["by_agent_type"]["(main)"]["input"], 100)
        self.assertEqual(
            tokens["by_agent_type"]["spec-loop:spec-loop-slice"]["input"], 200)
        self.assertEqual(tokens["by_slice"], {
            "s1": {"input": 200, "output": 80,
                   "cache_read": 0, "cache_creation": 0}})
        self.assertEqual(tokens["parse_skipped"], 1)
        self.assertTrue(metrics["sources"]["transcripts"])

    def test_usd_only_with_user_supplied_rates(self):
        metrics = compute_for(modern_files())
        rm.merge_token_usage(metrics, self.collect())
        self.assertIsNone(metrics["tokens"]["usd"])
        rm.merge_token_usage(metrics, self.collect(),
                             rates={"input": 10.0, "output": 100.0})
        self.assertAlmostEqual(metrics["tokens"]["usd"], 0.016)

    def test_probe_reports_visibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_transcripts(tmp)
            info = rm.probe_transcripts(tmp)
        self.assertEqual(info["session_files"], 2)
        self.assertEqual(info["subagent_files"], 1)
        self.assertEqual(info["usage_lines"], 3)
        self.assertEqual(info["parse_skipped"], 1)
        self.assertIn("alpha", info["git_branches_seen"])
        self.assertIn("input", info["usage_fields_seen"])


# ---------------------------------------------------------------------------
# write / trend / CLI
# ---------------------------------------------------------------------------

class WriteMetricsTests(unittest.TestCase):
    def test_atomic_write_leaves_only_metrics_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = write_run(tmp, "r1", legacy_files())
            before = set(p.name for p in run_dir.iterdir())
            metrics = rm.compute_metrics(rm.load_run_artifacts(run_dir))
            target = rm.write_metrics(run_dir, metrics)
            self.assertTrue(target.is_file())
            self.assertFalse((run_dir / "metrics.json.tmp").exists())
            self.assertEqual(set(p.name for p in run_dir.iterdir()),
                             before | {"metrics.json"})
            reread = json.loads(target.read_text())
            self.assertEqual(reread["schema_version"], rm.SCHEMA_VERSION)


class TrendTests(unittest.TestCase):
    def make_root(self, tmp):
        docs = Path(tmp) / "docs" / "spec-loop"
        write_run(docs, "20260101-legacy", legacy_files())
        write_run(docs, "20260714-modern", modern_files())
        return tmp

    def test_rows_cover_all_runs_untimed_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = rm.trend_rows(self.make_root(tmp))
        self.assertEqual([r["run_id"] for r in rows],
                         ["20260101-legacy", "20260714-modern"])
        self.assertIsNone(rows[0]["wall_clock_s"])
        self.assertEqual(rows[1]["wall_clock_s"], 5400.0)
        self.assertEqual(rows[0]["integration_gate"], "PASS")

    def test_backfill_from_committed_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_root(tmp)
            run_dir = Path(root) / "docs" / "spec-loop" / "20260101-legacy"
            committed = rm.compute_metrics(rm.load_run_artifacts(run_dir))
            rm.merge_git_timing(committed, {
                "aaaaaaa": "2026-01-01T10:00:00+00:00",
                "bbbbbbb": "2026-01-01T11:00:00+00:00"})
            rm.write_metrics(run_dir, committed)
            rows = rm.trend_rows(root)
        legacy = [r for r in rows if r["run_id"] == "20260101-legacy"][0]
        self.assertEqual(legacy["wall_clock_s"], 3600.0)

    def test_markdown_rendering_uses_em_dash_for_null(self):
        with tempfile.TemporaryDirectory() as tmp:
            table = rm.render_trend_md(rm.trend_rows(self.make_root(tmp)))
        self.assertIn("| Run |", table)
        self.assertIn("20260101-legacy", table)
        self.assertIn("—", table)
        self.assertNotIn("None", table)


class CliTests(unittest.TestCase):
    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = rm.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_compute_prints_document_and_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = write_run(tmp, "r1", modern_files())
            rc, out, _ = self.run_main(["compute", str(run_dir), "--write"])
            self.assertEqual(rc, 0)
            document = json.loads(out)
            self.assertEqual(document["run_id"], "r1")
            self.assertIsNotNone(document["generated_at"])
            self.assertTrue((run_dir / "metrics.json").is_file())

    def test_compute_missing_dir_is_usage_error(self):
        rc, _, err = self.run_main(["compute", "/no/such/run-dir"])
        self.assertEqual(rc, 2)
        self.assertIn("not a run directory", err)

    def test_compute_with_git_uses_mocked_subprocess(self):
        def fake_run(argv, **kwargs):
            return SimpleNamespace(returncode=0,
                                   stdout="2026-07-14T10:00:00+00:00\n",
                                   stderr="")
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = write_run(tmp, "r1", legacy_files())
            with mock.patch("run_metrics.subprocess.run",
                            side_effect=fake_run):
                rc, out, _ = self.run_main(["compute", str(run_dir), "--git"])
        document = json.loads(out)
        self.assertEqual(rc, 0)
        self.assertTrue(document["sources"]["git"])
        self.assertEqual(
            len(document["performance"]["merge_commit_dates"]), 3)

    def test_trend_md_and_empty_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs = Path(tmp) / "docs" / "spec-loop"
            write_run(docs, "20260101-legacy", legacy_files())
            rc, out, _ = self.run_main(["trend", tmp, "--md"])
            self.assertEqual(rc, 0)
            self.assertIn("| Run |", out)
        with tempfile.TemporaryDirectory() as empty:
            rc, _, err = self.run_main(["trend", empty])
            self.assertEqual(rc, 2)
            self.assertIn("no runs found", err)

    def test_probe_transcripts_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_transcripts(tmp)
            rc, out, _ = self.run_main(["probe-transcripts", tmp])
        self.assertEqual(rc, 0)
        info = json.loads(out)
        self.assertEqual(info["session_files"], 2)
        self.assertIn("note", info)

    def test_probe_missing_dir_is_usage_error(self):
        rc, _, err = self.run_main(["probe-transcripts", "/no/such/dir"])
        self.assertEqual(rc, 2)


# ---------------------------------------------------------------------------
# smoke test against the real committed sample run (repo checkouts only)
# ---------------------------------------------------------------------------

_SAMPLE_RUN = (Path(__file__).resolve().parents[3]
               / "docs" / "spec-loop" / "20260630-full-coverage")


@unittest.skipUnless(_SAMPLE_RUN.is_dir(),
                     "committed sample run not present (marketplace install)")
class RealSampleRunSmokeTests(unittest.TestCase):
    def test_retroactive_analysis_of_committed_run(self):
        metrics = rm.compute_metrics(rm.load_run_artifacts(_SAMPLE_RUN))
        self.assertEqual(metrics["safety"]["escalations"]["total"], 2)
        self.assertEqual(metrics["safety"]["escalations"]["answered"], 2)
        self.assertGreater(metrics["safety"]["decisions_total"], 0)
        self.assertGreater(metrics["safety"]["council"]["lines"], 5)
        self.assertEqual(metrics["safety"]["council"]["safety_objections"], 0)
        self.assertEqual(metrics["quality"]["integration"]["gate"], "PASS")
        self.assertGreaterEqual(metrics["quality"]["merges"]["count"], 5)
        gate = metrics["quality"]["quality_gate"]
        self.assertGreater(gate["measurements"], 3)
        self.assertEqual(metrics["performance"]["basis"], "none")
        self.assertIsNone(metrics["tokens"])


if __name__ == "__main__":
    unittest.main()
