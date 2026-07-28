#!/usr/bin/env python3
"""Run-metrics harness for spec-loop runs.

Derives safety, quality, performance, and (best-effort) token metrics from a
run's durable artifacts under ``docs/spec-loop/<run-id>/`` so the plugin's own
development can be steered by data: did a change regress the escalation rate,
the auto-fix success, the quality-gate first-pass rate, the wall clock?

  compute <run-dir>       print one versioned metrics JSON document for a run;
                          ``--write`` additionally persists it atomically as
                          ``<run-dir>/metrics.json`` (the ONLY mutating action).
                          ``--git`` enriches timing from the merge-commit
                          committer dates recorded in decisions-log MERGE lines.
                          ``--transcripts <dir>`` opts in to best-effort token
                          accounting from Claude Code session transcripts.
  trend <repo-root>       recompute metrics across every run under
                          ``docs/spec-loop/`` and print a cross-run comparison
                          (``--md`` for a human table, JSON otherwise).
  probe-transcripts <dir> visibility probe over a transcripts directory: what
                          sessions/fields the token parser can currently see,
                          so transcript schema drift is loud, never a silent 0.

Design rules (mirrors dashboard_server's layering):
* Pure core: every parser takes text/dicts, never paths; ``compute_metrics``
  assembles the document; ``merge_git_timing``/``merge_token_usage`` are pure
  and fed by the thin shell. The shell is the only layer that touches the
  filesystem, git, or transcripts.
* Fail-soft, null-honest: a metric that cannot be derived is ``null`` — never
  a fabricated 0. Old runs (no timestamps, no sidecars) still analyze; their
  performance section simply degrades. Every timing/token section carries a
  ``basis``/provenance marker.
* decisions-log.md and escalations.md are LLM-authored prose behind a thin
  line grammar; parse them leniently and never claim numeric precision from
  prose. The slice status sidecar's optional ``counters`` block is the only
  channel treated as precise.

TRANSCRIPT FRAGILITY (read before trusting the tokens section): the Claude
Code session transcript layout (``<munged-cwd>/<session-id>.jsonl`` +
``<session-id>/subagents/agent-*.jsonl`` with ``agent-*.meta.json``) is an
UNDOCUMENTED internal format that can change across Claude Code versions.
Token capture is therefore strictly opt-in (``--transcripts``, default unset —
never auto-derived, per the plugin's portability rule), tolerant (malformed
lines are counted in ``parse_skipped``, never crash), and marked
``"best_effort": true``. If the format drifts, run ``probe-transcripts`` to
see what the parser can still recognize. Fallback path if this breaks for
good: Claude Code's OTEL telemetry export (requires a running collector and
pre-run env setup — heavier, so not the default here).

Standard library only. Exit codes: 0 ok, 2 usage error.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
MAX_FILE_BYTES = 1_000_000       # cap any single artifact read into memory

SLICE_STATUSES = ("DONE", "NEEDS_DECISION", "BLOCKED", "SPLIT")
COUNCIL_VERDICTS = ("ENDORSE", "ENDORSE_WITH_CONCERNS", "OBJECT")
ESCALATION_TRIGGERS = (
    "ambiguity",
    "material-assumption",
    "review-block",
    "council-objection",
    "quality-gate-block",
)
REVERSIBILITY_BUCKETS = ("trivial", "moderate", "high", "n/a")
SIDECAR_COUNTER_KEYS = (
    "review_confirmed",
    "review_refuted",
    "fix_passes",
    "quality_refactor_passes",
    "fail_closed",
)

# Trailing timestamp token on instrumented log lines: `… — AT: <ISO-8601>`.
AT_SUFFIX = re.compile(r"[—–-]\s*AT:\s*(\S+)\s*$")
REVERSIBILITY = re.compile(r"REVERSIBILITY:\s*([A-Za-z/\-]+)", re.IGNORECASE)
MERGE_SHA = re.compile(
    r"\bmerged?(?:\s+commit)?\s*\(?\s*([0-9a-f]{7,40})\b", re.IGNORECASE
)
GATE_ITERATIONS = re.compile(r"\bafter\s+(\d+)\b", re.IGNORECASE)
INITIAL_FAIL = re.compile(r"\binitial\s+FAIL\b", re.IGNORECASE)
# Deliberately case-SENSITIVE: gate/integration lines write PASS/FAIL in
# caps; prose like "refactor pass" / "tests pass" must not count.
RESULT_PASS = re.compile(r"\bPASS(?:ED)?\b")
RESULT_FAIL = re.compile(r"\bFAIL(?:ED)?\b")
PRECEDENT = re.compile(r"RATIONALE:\s*precedent\b", re.IGNORECASE)
FAIL_CLOSED = re.compile(r"\bfail[\s-]closed\b", re.IGNORECASE)
# A SAFETY mention only counts when not negated ("none SAFETY", "no SAFETY",
# "NOT SAFETY", "non-SAFETY", "0 SAFETY", "without SAFETY").
SAFETY_MENTION = re.compile(
    r"(?:\b(?:none|no|not|non|zero|without)\b[\s—:,-]{0,4}|\b0\s+)?safety\b",
    re.IGNORECASE,
)

_TAG_CLASSES = (
    ("REVIEW-FINDING REFUTED", "refuted"),
    ("IRON COUNCIL", "council"),
    ("COUNCIL", "council"),
    ("DECISION", "decision"),
    ("QUALITY-GATE", "quality_gate"),
    ("INTEGRATION", "integration"),
    ("HUMAN RESOLVED", "human_resolved"),
    ("MERGE", "merge"),
    ("REVIEW", "review"),
    ("DONE", "done"),
)


# ==========================================================================
# generic pure helpers
# ==========================================================================

def _read_text_capped(path):
    """Read up to MAX_FILE_BYTES of text, or return '' if absent/unreadable."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(MAX_FILE_BYTES)
    except (OSError, ValueError):
        return ""


def _load_json(path):
    """Parse a JSON file, or return None if absent/unreadable/malformed."""
    text = _read_text_capped(path)
    if not text.strip():
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def parse_iso(value):
    """Parse an ISO-8601 string to an aware UTC datetime, or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp


def _iso_or_none(value):
    """The input string when it parses as ISO-8601, else None."""
    return value if parse_iso(value) else None


def _bracket_prefix(line):
    """Split a ``[token] rest`` line into ``(token, rest)`` or ``(None, "")``."""
    s = line.lstrip("#-* \t")
    if not s.startswith("["):
        return None, ""
    close = s.find("]")
    if close == -1:
        return None, ""
    return s[1:close].strip(), s[close + 1:].strip()


def _first_verdict(upper):
    """The council verdict named in an upper-cased line, or ''.
    ENDORSE_WITH_CONCERNS is checked before ENDORSE (it contains 'ENDORSE')."""
    for v in ("ENDORSE_WITH_CONCERNS", "OBJECT", "ENDORSE"):
        if v in upper:
            return v
    return ""


def _ratio(part, whole):
    """part/whole rounded to 4 places, or None when whole is 0."""
    return round(part / whole, 4) if whole else None


def _median(values):
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _max_overlap(intervals):
    """Max number of concurrently-open ``(start, end)`` intervals."""
    points = []
    for start, end in intervals:
        points.append((start, 1))
        points.append((end, -1))
    points.sort(key=lambda p: (p[0], p[1]))
    best = current = 0
    for _, delta in points:
        current += delta
        best = max(best, current)
    return best


# ==========================================================================
# pure core — decisions-log.md
# ==========================================================================

def parse_decisions_log(text):
    """Lenient line parser. Returns a list of event dicts, one per
    ``[token] TAG…`` line: {token, tag, rest, at, reversibility, shas}."""
    events = []
    for line in (text or "").splitlines():
        token, rest = _bracket_prefix(line)
        if token is None or not rest:
            continue
        events.append({
            "token": token,
            "tag": _classify_tag(rest),
            "rest": rest,
            "at": _extract_at(rest),
            "reversibility": _extract_reversibility(rest),
            "shas": MERGE_SHA.findall(rest),
        })
    return events


def _classify_tag(rest):
    upper = rest.upper()
    for prefix, tag in _TAG_CLASSES:
        if upper.startswith(prefix):
            return tag
    return "other"


def _extract_at(rest):
    match = AT_SUFFIX.search(rest)
    return _iso_or_none(match.group(1)) if match else None


def _extract_reversibility(rest):
    match = REVERSIBILITY.search(rest)
    if not match:
        return None
    value = match.group(1).strip().lower()
    return value if value in REVERSIBILITY_BUCKETS else "other"


def _mentions_unnegated_safety(text):
    """True when SAFETY appears at least once without a negating prefix.
    (A negated mention is consumed whole by SAFETY_MENTION's prefix group,
    so its group(0) is longer than the bare word.)"""
    return any(match.group(0).lower() == "safety"
               for match in SAFETY_MENTION.finditer(text))


def _line_result(rest):
    """PASS/FAIL verdict of a gate/integration line (caps-only), or None."""
    if RESULT_PASS.search(rest):
        return "PASS"
    if RESULT_FAIL.search(rest):
        return "FAIL"
    return None


# ==========================================================================
# pure core — escalations.md
# ==========================================================================

def parse_escalations(text):
    """Parse escalation blocks. Returns a list of dicts:
    {token, title, status, triggers, opened, answered_at}."""
    out = []
    for header, body in _split_escalation_blocks(text or ""):
        token, title, header_state = _parse_escalation_header(header)
        if token is None:
            continue
        fields = _escalation_body_fields(body)
        status = ("ANSWERED" if header_state == "ANSWERED" or fields["answered"]
                  else header_state)
        out.append({
            "token": token,
            "title": title,
            "status": status,
            "triggers": fields["triggers"],
            "opened": fields["opened"],
            "answered_at": fields["answered_at"],
        })
    return out


def _split_escalation_blocks(text):
    """Yield ``(header_line, [body_lines])`` for each ``## [...]`` block."""
    header, body = None, []
    for line in text.splitlines():
        if line.startswith("## ["):
            if header is not None:
                yield header, body
            header, body = line, []
        elif header is not None:
            body.append(line)
    if header is not None:
        yield header, body


def _parse_escalation_header(line):
    """Return ``(token, title, state)`` for a header, or ``(None, '', '')``."""
    close = line.find("]", 4)
    if close == -1:
        return None, "", ""
    rest = line[close + 1:]
    if "(status: ANSWERED)" in rest:
        state = "ANSWERED"
    elif "(status: OPEN)" in rest:
        state = "OPEN"
    else:
        state = ""
    return line[4:close].strip(), rest.split("(status:")[0].strip(), state


def _escalation_body_fields(body_lines):
    """Extract Trigger/Opened/Answered-at/filled-Answer from a block body."""
    fields = {"triggers": [], "opened": None, "answered_at": None,
              "answered": False}
    for line in body_lines:
        stripped = line.strip().lstrip("-* ").strip()
        lower = stripped.lower()
        if lower.startswith("trigger:"):
            fields["triggers"] = _match_triggers(stripped[len("trigger:"):])
        elif lower.startswith("opened:"):
            fields["opened"] = _iso_or_none(stripped[len("opened:"):].strip())
        elif lower.startswith("answered-at:"):
            fields["answered_at"] = _iso_or_none(
                stripped[len("answered-at:"):].strip())
        elif lower.startswith("answer:") and stripped[len("answer:"):].strip():
            fields["answered"] = True
    return fields


def _match_triggers(text):
    """Keyword-match the canonical triggers; unmatched non-empty -> other."""
    lower = text.lower()
    matched = [t for t in ESCALATION_TRIGGERS if t in lower]
    if matched:
        return matched
    return ["other"] if lower.strip() else []


# ==========================================================================
# pure core — dag.json / sidecars / runbook.md
# ==========================================================================

def parse_dag(obj):
    """Normalize dag.json, or return None when it is not a usable DAG."""
    if not isinstance(obj, dict) or not isinstance(obj.get("slices"), list):
        return None
    slices = [s for s in obj["slices"] if isinstance(s, dict)]
    status_counts = {}
    for s in slices:
        key = s.get("status") or "unknown"
        status_counts[key] = status_counts.get(key, 0) + 1
    depths = [s["depth"] for s in slices
              if isinstance(s.get("depth"), int) and not isinstance(s.get("depth"), bool)]
    return {
        "base_ref": obj.get("base_ref"),
        "merge_mode": obj.get("merge_mode"),
        "created_at": _iso_or_none(obj.get("created_at")),
        "slice_ids": [s.get("id") for s in slices if isinstance(s.get("id"), str)],
        "slice_count": len(slices),
        "split_parents": sum(1 for s in slices if s.get("status") == "split"),
        "max_depth": max(depths) if depths else None,
        "remediation_count": sum(1 for s in slices if s.get("remediation") is True),
        "status_counts": status_counts,
    }


def parse_sidecar(obj):
    """Normalize a slice-<id>-status.json sidecar, or None when unusable.
    Every instrumented field is optional — absence is normal (legacy runs)."""
    if not isinstance(obj, dict):
        return None
    status = obj.get("status")
    wave = obj.get("wave")
    return {
        "id": obj.get("id") if isinstance(obj.get("id"), str) else None,
        "status": status if status in SLICE_STATUSES else None,
        "started_at": _iso_or_none(obj.get("started_at")),
        "finished_at": _iso_or_none(obj.get("finished_at")),
        "wave": wave if _is_count(wave) else None,
        "counters": _clean_counters(obj.get("counters")),
    }


def _is_count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _clean_counters(counters):
    if not isinstance(counters, dict):
        return None
    cleaned = {k: v for k, v in counters.items()
               if k in SIDECAR_COUNTER_KEYS and _is_count(v)}
    return cleaned or None


def parse_runbook_traceability(text):
    """Count delivered/partial/deferred rows in the runbook's Requirement
    Traceability table, or None when the section/table is absent."""
    in_section = False
    counts = {"delivered": 0, "partial": 0, "deferred": 0}
    seen_row = False
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            in_section = "requirement traceability" in stripped.lower()
            continue
        if not in_section or not stripped.startswith("|"):
            continue
        status = _traceability_row_status(stripped)
        if status:
            counts[status] += 1
            seen_row = True
    return counts if seen_row else None


def _traceability_row_status(row):
    """The status keyword of one table row, or None for header/divider rows."""
    cells = [c.strip().lower() for c in row.strip("|").split("|")]
    if len(cells) < 2:
        return None
    for status in ("delivered", "partial", "deferred"):
        if status in cells[1]:
            return status
    return None


# ==========================================================================
# pure core — metric computation
# ==========================================================================

def compute_metrics(artifacts):
    """Assemble the versioned metrics document from loaded artifacts.

    ``artifacts``: {run_id, dag, decisions_text, escalations_text,
    runbook_text, sidecars} (see ``load_run_artifacts``). Pure — no clock,
    no filesystem; the shell stamps ``generated_at`` and merges git/tokens."""
    parsed = {
        "events": parse_decisions_log(artifacts.get("decisions_text") or ""),
        "escalations": parse_escalations(artifacts.get("escalations_text") or ""),
        "dag": parse_dag(artifacts.get("dag")),
        "sidecars": [s for s in (parse_sidecar(x)
                                 for x in artifacts.get("sidecars") or []) if s],
        "runbook": parse_runbook_traceability(artifacts.get("runbook_text") or ""),
        "has_decisions": bool((artifacts.get("decisions_text") or "").strip()),
        "has_escalations": bool((artifacts.get("escalations_text") or "").strip()),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": artifacts.get("run_id"),
        "generated_at": None,
        "sources": _sources(parsed),
        "safety": _safety_metrics(parsed),
        "quality": _quality_metrics(parsed),
        "performance": _performance_metrics(parsed),
        "tokens": None,
    }


def _sources(parsed):
    return {
        "dag": parsed["dag"] is not None,
        "decisions_log": parsed["has_decisions"],
        "escalations": parsed["has_escalations"],
        "sidecars": len(parsed["sidecars"]),
        "runbook": parsed["runbook"] is not None,
        "git": False,
        "transcripts": False,
    }


def _safety_metrics(parsed):
    events, escalations = parsed["events"], parsed["escalations"]
    decisions = [e for e in events if e["tag"] == "decision"]
    return {
        "escalations": _escalation_stats(escalations),
        "decisions_total": len(decisions),
        "autonomy_ratio": _ratio(len(decisions),
                                 len(decisions) + len(escalations)),
        "council": _council_stats(events),
        "reversibility_mix": _reversibility_mix(events),
        "precedent_reuse": _precedent_stats(decisions),
        "fail_closed_events": _fail_closed_stats(parsed),
    }


def _escalation_stats(escalations):
    by_trigger, per_slice = {}, {}
    for esc in escalations:
        per_slice[esc["token"]] = per_slice.get(esc["token"], 0) + 1
        for trig in esc["triggers"]:
            by_trigger[trig] = by_trigger.get(trig, 0) + 1
    return {
        "total": len(escalations),
        "open": sum(1 for e in escalations if e["status"] == "OPEN"),
        "answered": sum(1 for e in escalations if e["status"] == "ANSWERED"),
        "by_trigger": by_trigger,
        "per_slice": per_slice,
    }


def _council_stats(events):
    lines = [e for e in events if e["tag"] == "council"]
    verdicts = {v: 0 for v in COUNCIL_VERDICTS}
    safety = 0
    for e in lines:
        verdict = _first_verdict(e["rest"].upper())
        if verdict:
            verdicts[verdict] += 1
        if verdict == "OBJECT" and _mentions_unnegated_safety(e["rest"]):
            safety += 1
    return {
        "lines": len(lines),
        "verdicts": verdicts,
        "object_rate": _ratio(verdicts["OBJECT"], len(lines)),
        "safety_objections": safety,
    }


def _reversibility_mix(events):
    mix = {}
    for e in events:
        if e["reversibility"]:
            mix[e["reversibility"]] = mix.get(e["reversibility"], 0) + 1
    return mix


def _precedent_stats(decisions):
    count = sum(1 for e in decisions if PRECEDENT.search(e["rest"]))
    return {"count": count, "rate": _ratio(count, len(decisions))}


def _fail_closed_stats(parsed):
    """Sidecar counters when present (precise); else keyword scan (proxy)."""
    sidecar_counts = [s["counters"]["fail_closed"] for s in parsed["sidecars"]
                      if s["counters"] and "fail_closed" in s["counters"]]
    if sidecar_counts:
        return {"count": sum(sidecar_counts), "basis": "sidecar"}
    if parsed["has_decisions"]:
        count = sum(1 for e in parsed["events"] if FAIL_CLOSED.search(e["rest"]))
        return {"count": count, "basis": "keyword"}
    return {"count": None, "basis": None}


def _quality_metrics(parsed):
    events = parsed["events"]
    return {
        "quality_gate": _quality_gate_stats(events),
        "review": _review_stats(parsed),
        "sidecar_counters": _summed_counters(parsed["sidecars"]),
        "merges": _merge_stats(events),
        "splits": _split_stats(parsed["dag"]),
        "integration": _integration_stats(events, parsed["dag"]),
        "requirement_coverage": _coverage_stats(parsed["runbook"]),
        "slice_outcomes": _slice_outcomes(parsed),
    }


def _quality_gate_stats(events):
    lines = [e for e in events if e["tag"] == "quality_gate"]
    first_pass = [e for e in lines if not INITIAL_FAIL.search(e["rest"])]
    failures = sum(1 for e in lines if _line_result(e["rest"]) == "FAIL")
    iterations = None
    if lines:
        iterations = 0
        for e in lines:
            match = GATE_ITERATIONS.search(e["rest"])
            if match:
                iterations += int(match.group(1))
    return {
        "measurements": len(lines),
        "first_pass": len(first_pass),
        "first_pass_rate": _ratio(len(first_pass), len(lines)),
        "refactor_passes_total": iterations,
        "failures": failures,
    }


def _review_stats(parsed):
    refuted = sum(1 for e in parsed["events"] if e["tag"] == "refuted")
    review_blocks = sum(1 for esc in parsed["escalations"]
                        if "review-block" in esc["triggers"])
    return {
        "refuted_findings_logged": refuted,
        "review_block_escalations": review_blocks,
    }


def _summed_counters(sidecars):
    """Sum the structured sidecar counters across slices, or None when no
    sidecar carries any — the only numerically-precise quality channel."""
    totals = {}
    for sc in sidecars:
        for key, value in (sc["counters"] or {}).items():
            totals[key] = totals.get(key, 0) + value
    return totals or None


def _merge_stats(events):
    shas = sorted({sha for e in events for sha in e["shas"]})
    return {"commits": shas, "count": len(shas)}


def _split_stats(dag):
    if dag is None:
        return None
    return {
        "total_slices": dag["slice_count"],
        "split_parents": dag["split_parents"],
        "split_rate": _ratio(dag["split_parents"], dag["slice_count"]),
        "max_depth": dag["max_depth"],
        "remediation_slices": dag["remediation_count"],
    }


def _integration_stats(events, dag):
    checks = [{"scope": e["token"], "result": _line_result(e["rest"])}
              for e in events if e["tag"] == "integration"]
    gate = None
    for e in events:
        if e["tag"] == "integration" and "INTEGRATION GATE" in e["rest"].upper():
            gate = _line_result(e["rest"])
    return {
        "checks": checks,
        "gate": gate,
        "remediation_slices": dag["remediation_count"] if dag else None,
    }


def _coverage_stats(runbook):
    if runbook is None:
        return None
    total = sum(runbook.values())
    return {**runbook, "rate": _ratio(runbook["delivered"], total)}


def _slice_outcomes(parsed):
    sidecar_statuses = [s["status"] for s in parsed["sidecars"] if s["status"]]
    if sidecar_statuses:
        counts = {}
        for status in sidecar_statuses:
            counts[status] = counts.get(status, 0) + 1
        return {"basis": "sidecars", "counts": counts}
    if parsed["dag"] is not None:
        return {"basis": "dag", "counts": parsed["dag"]["status_counts"]}
    return {"basis": None, "counts": None}


def _performance_metrics(parsed):
    stamps = _collect_timestamps(parsed)
    wall = (max(stamps) - min(stamps)).total_seconds() if len(stamps) >= 2 else None
    return {
        "basis": "timestamps" if stamps else "none",
        "run_wall_clock_s": wall,
        "started_at": min(stamps).isoformat() if stamps else None,
        "finished_at": max(stamps).isoformat() if stamps else None,
        "slices": _slice_durations(parsed["sidecars"]),
        "waves": _wave_parallelism(parsed["sidecars"]),
        "escalation_answer_latency_s": _answer_latency(parsed["escalations"]),
    }


def _collect_timestamps(parsed):
    """Every parseable instrumented timestamp across the artifacts."""
    raw = [e["at"] for e in parsed["events"]]
    if parsed["dag"]:
        raw.append(parsed["dag"]["created_at"])
    for sc in parsed["sidecars"]:
        raw += [sc["started_at"], sc["finished_at"]]
    for esc in parsed["escalations"]:
        raw += [esc["opened"], esc["answered_at"]]
    return sorted(dt for dt in (parse_iso(v) for v in raw) if dt)


def _slice_durations(sidecars):
    durations = {}
    for sc in sidecars:
        start, end = parse_iso(sc["started_at"]), parse_iso(sc["finished_at"])
        if sc["id"] and start and end:
            durations[sc["id"]] = round((end - start).total_seconds(), 1)
    return durations or None


def _wave_parallelism(sidecars):
    by_wave = {}
    for sc in sidecars:
        if sc["wave"] is not None:
            by_wave.setdefault(sc["wave"], []).append(sc)
    if not by_wave:
        return None
    out = []
    for wave in sorted(by_wave):
        members = by_wave[wave]
        intervals = [(parse_iso(sc["started_at"]), parse_iso(sc["finished_at"]))
                     for sc in members]
        intervals = [(s, e) for s, e in intervals if s and e]
        out.append({
            "wave": wave,
            "slices": len(members),
            "max_parallelism": _max_overlap(intervals) if intervals else None,
        })
    return out


def _answer_latency(escalations):
    latencies = []
    for esc in escalations:
        opened, answered = parse_iso(esc["opened"]), parse_iso(esc["answered_at"])
        if opened and answered:
            latencies.append((answered - opened).total_seconds())
    if not latencies:
        return None
    return {
        "count": len(latencies),
        "median_s": round(_median(latencies), 1),
        "max_s": round(max(latencies), 1),
    }


# ==========================================================================
# pure core — shell-fed enrichment (git timing / token usage)
# ==========================================================================

def merge_git_timing(metrics, sha_dates):
    """Fold merge-commit committer dates into the performance section.
    ``sha_dates``: {sha: iso-date}. Upgrades wall clock only when the
    timestamp basis produced none (git is the retroactive fallback)."""
    metrics["sources"]["git"] = True
    perf = metrics["performance"]
    perf["merge_commit_dates"] = dict(sorted(sha_dates.items()))
    stamps = sorted(dt for dt in (parse_iso(v) for v in sha_dates.values()) if dt)
    if len(stamps) >= 2 and perf["run_wall_clock_s"] is None:
        perf["run_wall_clock_s"] = (stamps[-1] - stamps[0]).total_seconds()
        perf["started_at"] = stamps[0].isoformat()
        perf["finished_at"] = stamps[-1].isoformat()
        perf["basis"] = "git"
    return metrics


def merge_token_usage(metrics, collected, rates=None):
    """Fold collected transcript usage rows into the tokens section.
    ``collected``: {rows, sessions, parse_skipped, fields_seen} (see
    ``collect_usage_rows``). Always marked best_effort."""
    metrics["sources"]["transcripts"] = True
    rows = collected["rows"]
    totals = _sum_usage(row["usage"] for row in rows)
    metrics["tokens"] = {
        "best_effort": True,
        "totals": totals,
        "messages": len(rows),
        "sessions": collected["sessions"],
        "by_agent_type": _usage_by(rows, "agent_type", default="(main)"),
        "by_slice": _usage_by(rows, "slice", default=None),
        "parse_skipped": collected["parse_skipped"],
        "usage_fields_seen": sorted(collected["fields_seen"]),
        "usd": _usd(totals, rates),
    }
    return metrics


def _sum_usage(usages):
    totals = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}
    for usage in usages:
        for key in totals:
            totals[key] += usage.get(key, 0)
    return totals


def _usage_by(rows, field, default):
    grouped = {}
    for row in rows:
        key = row.get(field) or default
        if key is None:
            continue
        grouped[key] = _sum_usage([grouped.get(key, {}), row["usage"]])
    return grouped


def _usd(totals, rates):
    """User-supplied $/Mtok rates -> dollars; None when no rate was given
    (no pricing is bundled — it goes stale and is model-dependent)."""
    if not rates or not any(rates.values()):
        return None
    cost = sum(totals[key] * rate / 1_000_000
               for key, rate in rates.items() if rate)
    return round(cost, 4)


# ==========================================================================
# thin shell — filesystem / git / transcripts
# ==========================================================================

def load_run_artifacts(run_dir):
    """Read one run directory into the artifacts dict compute_metrics takes."""
    run_dir = Path(run_dir)
    return {
        "run_id": run_dir.name,
        "dag": _load_json(run_dir / "dag.json"),
        "decisions_text": _read_text_capped(run_dir / "decisions-log.md"),
        "escalations_text": _read_text_capped(run_dir / "escalations.md"),
        "runbook_text": _read_text_capped(run_dir / "runbook.md"),
        "sidecars": [_load_json(p)
                     for p in sorted(run_dir.glob("slice-*-status.json"))],
    }


def write_metrics(run_dir, metrics):
    """Atomically persist metrics.json into the run dir (tmp + os.replace)."""
    target = Path(run_dir) / "metrics.json"
    tmp = Path(run_dir) / "metrics.json.tmp"
    tmp.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, target)
    return target


def _git_commit_dates(repo_dir, shas):
    """Committer date (%cI) per resolvable sha; unresolvable shas are skipped
    (never crash — old runs may reference garbage-collected commits)."""
    dates = {}
    for sha in shas:
        try:
            proc = subprocess.run(
                ["git", "-C", str(repo_dir), "show", "-s", "--format=%cI", sha],
                capture_output=True, text=True, timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        value = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
        if proc.returncode == 0 and parse_iso(value):
            dates[sha] = value
    return dates


# --- transcripts (best-effort, opt-in; see module docstring) ----------------

def collect_usage_rows(transcripts_dir, spec):
    """Scan a Claude Code transcripts directory for this run's token usage.

    ``spec``: {run_id, base_ref, window: (start_iso, end_iso)|None, slice_ids}.
    A session qualifies when any line's gitBranch equals the run's base_ref OR
    the run id appears anywhere in the session file. Qualifying sessions
    contribute their own usage rows plus their subagents' (attributed by
    agentType and, when the dispatch description names it, by slice id)."""
    result = {"rows": [], "sessions": 0, "parse_skipped": 0,
              "fields_seen": set()}
    for session_file in sorted(Path(transcripts_dir).glob("*.jsonl")):
        scanned = _scan_jsonl(session_file, spec)
        if not scanned["qualifies"]:
            continue
        subs = _collect_subagent_rows(session_file, spec)
        result["sessions"] += 1
        result["rows"] += scanned["rows"] + subs["rows"]
        result["parse_skipped"] += scanned["skipped"] + subs["skipped"]
        result["fields_seen"] |= scanned["fields"] | subs["fields"]
    return result


def _scan_jsonl(path, spec):
    """One tolerant pass over a .jsonl transcript file."""
    out = {"rows": [], "skipped": 0, "fields": set(), "qualifies": False}
    try:
        fh = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return out
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            if spec.get("run_id") and spec["run_id"] in line:
                out["qualifies"] = True
            obj = _loads_or_none(line)
            if obj is None:
                out["skipped"] += 1
                continue
            if spec.get("base_ref") and obj.get("gitBranch") == spec["base_ref"]:
                out["qualifies"] = True
            _append_usage_row(out, obj, spec.get("window"))
    return out


def _loads_or_none(line):
    try:
        obj = json.loads(line)
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def _append_usage_row(out, obj, window):
    usage = _usage_of(obj)
    if usage is None:
        return
    out["fields"].update(usage)
    if _in_window(obj.get("timestamp"), window):
        out["rows"].append({"usage": usage, "ts": obj.get("timestamp")})


def _usage_of(obj):
    """Normalized token counts from a transcript line, or None."""
    message = obj.get("message")
    usage = message.get("usage") if isinstance(message, dict) else None
    if not isinstance(usage, dict):
        return None
    mapping = {
        "input": "input_tokens",
        "output": "output_tokens",
        "cache_read": "cache_read_input_tokens",
        "cache_creation": "cache_creation_input_tokens",
    }
    normalized = {key: usage[src] for key, src in mapping.items()
                  if _is_count(usage.get(src))}
    return normalized or None


def _in_window(ts, window):
    """True when ts falls inside the (start, end) window; unknown -> include."""
    if not window or not all(window):
        return True
    stamp = parse_iso(ts)
    if stamp is None:
        return True
    start, end = parse_iso(window[0]), parse_iso(window[1])
    if start is None or end is None:
        return True
    return start <= stamp <= end


def _collect_subagent_rows(session_file, spec):
    """Usage rows from ``<session>/subagents/agent-*.jsonl``, attributed by
    the sibling ``agent-*.meta.json``'s agentType/description."""
    sub_dir = session_file.with_suffix("") / "subagents"
    out = {"rows": [], "skipped": 0, "fields": set()}
    child_spec = {"window": spec.get("window")}
    for meta_path in sorted(sub_dir.glob("agent-*.meta.json")):
        meta = _load_json(meta_path) or {}
        slice_id = _slice_from_description(
            meta.get("description"), spec.get("slice_ids") or [])
        jsonl = meta_path.with_name(
            meta_path.name.replace(".meta.json", ".jsonl"))
        scanned = _scan_jsonl(jsonl, child_spec)
        for row in scanned["rows"]:
            row["agent_type"] = meta.get("agentType")
            row["slice"] = slice_id
        out["rows"] += scanned["rows"]
        out["skipped"] += scanned["skipped"]
        out["fields"] |= scanned["fields"]
    return out


def _slice_from_description(description, slice_ids):
    if not isinstance(description, str):
        return None
    for sid in slice_ids:
        if sid and re.search(r"\b%s\b" % re.escape(sid), description):
            return sid
    return None


def probe_transcripts(directory):
    """What the token parser can currently see — schema-drift visibility."""
    info = {"session_files": 0, "subagent_files": 0, "usage_lines": 0,
            "parse_skipped": 0, "usage_fields_seen": set(),
            "git_branches_seen": set()}
    for path in sorted(Path(directory).glob("*.jsonl")):
        info["session_files"] += 1
        _probe_file(path, info)
        for sub in sorted((path.with_suffix("") / "subagents").glob("*.jsonl")):
            info["subagent_files"] += 1
            _probe_file(sub, info)
    return info


def _probe_file(path, info):
    scanned = _scan_jsonl(path, {})
    info["usage_lines"] += len(scanned["rows"])
    info["parse_skipped"] += scanned["skipped"]
    info["usage_fields_seen"] |= scanned["fields"]
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                obj = _loads_or_none(line.strip()) or {}
                branch = obj.get("gitBranch")
                if isinstance(branch, str) and branch:
                    info["git_branches_seen"].add(branch)
    except OSError:
        pass


# ==========================================================================
# thin shell — trend
# ==========================================================================

def discover_run_dirs(root):
    """Run directories under <root>/docs/spec-loop (or under root itself when
    it already IS a docs/spec-loop directory)."""
    root = Path(root)
    docs = root / "docs" / "spec-loop"
    base = docs if docs.is_dir() else root
    if not base.is_dir():
        return []
    return [child for child in sorted(base.iterdir())
            if child.is_dir() and (
                (child / "dag.json").is_file()
                or (child / "decisions-log.md").is_file())]


def _backfill_from_committed(metrics, run_dir):
    """A pure artifact recompute cannot re-derive git timing or token usage;
    borrow those sections from a committed metrics.json when ours are null."""
    committed = _load_json(Path(run_dir) / "metrics.json")
    if not isinstance(committed, dict) or committed.get("schema_version") != SCHEMA_VERSION:
        return
    perf = committed.get("performance") or {}
    if metrics["performance"]["run_wall_clock_s"] is None \
            and perf.get("run_wall_clock_s") is not None:
        metrics["performance"] = perf
        metrics["sources"]["git"] = bool((committed.get("sources") or {}).get("git"))
    if metrics["tokens"] is None and committed.get("tokens") is not None:
        metrics["tokens"] = committed["tokens"]
        metrics["sources"]["transcripts"] = True


def trend_rows(root):
    """One summary row per run under root, ordered oldest-first."""
    rows = []
    for run_dir in discover_run_dirs(root):
        metrics = compute_metrics(load_run_artifacts(run_dir))
        _backfill_from_committed(metrics, run_dir)
        rows.append(summary_row(metrics))
    rows.sort(key=lambda r: (r["started_at"] or "", r["run_id"]))
    return rows


def summary_row(metrics):
    """The fixed small cross-run summary of one metrics document — the trend
    row, also reused by dashboard_server for its collection payload. Tolerant
    of partially-shaped documents (a committed metrics.json is disk input):
    every missing section degrades to None, never a KeyError."""
    safety = metrics.get("safety") or {}
    quality = metrics.get("quality") or {}
    perf = metrics.get("performance") or {}
    tokens = metrics.get("tokens")
    totals = (tokens or {}).get("totals") or {}
    token_total = totals.get("input", 0) + totals.get("output", 0) if tokens else None
    return {
        "run_id": metrics.get("run_id"),
        "started_at": perf.get("started_at"),
        "escalations": (safety.get("escalations") or {}).get("total"),
        "autonomy_ratio": safety.get("autonomy_ratio"),
        "council_object_rate": (safety.get("council") or {}).get("object_rate"),
        "quality_gate_first_pass_rate":
            (quality.get("quality_gate") or {}).get("first_pass_rate"),
        "split_rate": (quality.get("splits") or {}).get("split_rate"),
        "integration_gate": (quality.get("integration") or {}).get("gate"),
        "wall_clock_s": perf.get("run_wall_clock_s"),
        "tokens_total": token_total,
    }


def render_trend_md(rows):
    """Human trend table (markdown)."""
    header = ("| Run | Escalations | Autonomy | Council OBJ | QG 1st-pass "
              "| Split rate | Gate | Wall clock | Tokens |")
    divider = "|" + "---|" * 9
    lines = [header, divider]
    for row in rows:
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            row["run_id"],
            _fmt(row["escalations"]),
            _fmt(row["autonomy_ratio"]),
            _fmt(row["council_object_rate"]),
            _fmt(row["quality_gate_first_pass_rate"]),
            _fmt(row["split_rate"]),
            _fmt(row["integration_gate"]),
            _fmt_duration(row["wall_clock_s"]),
            _fmt(row["tokens_total"]),
        ))
    return "\n".join(lines)


def _fmt(value):
    if value is None:
        return "—"
    if isinstance(value, float):
        return "%.2f" % value
    return str(value)


def _fmt_duration(seconds):
    if seconds is None:
        return "—"
    seconds = int(seconds)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return "%dh%02dm" % (hours, minutes)
    if minutes:
        return "%dm%02ds" % (minutes, secs)
    return "%ds" % secs


# ==========================================================================
# CLI
# ==========================================================================

def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def cmd_compute(args):
    run_dir = Path(args.run_dir)
    if not run_dir.is_dir():
        print("error: not a run directory: %s" % run_dir, file=sys.stderr)
        return 2
    artifacts = load_run_artifacts(run_dir)
    metrics = compute_metrics(artifacts)
    metrics["generated_at"] = _now_iso()
    if args.git:
        shas = metrics["quality"]["merges"]["commits"]
        merge_git_timing(metrics, _git_commit_dates(run_dir, shas))
    if args.transcripts:
        merge_token_usage(
            metrics,
            collect_usage_rows(args.transcripts, _transcript_spec(metrics, artifacts)),
            rates=_rates(args),
        )
    if args.write:
        write_metrics(run_dir, metrics)
    print(json.dumps(metrics, indent=2))
    return 0


def _transcript_spec(metrics, artifacts):
    dag = artifacts.get("dag") if isinstance(artifacts.get("dag"), dict) else {}
    perf = metrics["performance"]
    window = (perf["started_at"], perf["finished_at"])
    return {
        "run_id": metrics["run_id"],
        "base_ref": (dag or {}).get("base_ref"),
        "window": window if all(window) else None,
        "slice_ids": (parse_dag(dag) or {}).get("slice_ids") or [],
    }


def _rates(args):
    return {
        "input": args.usd_per_mtok_input,
        "output": args.usd_per_mtok_output,
        "cache_read": args.usd_per_mtok_cache_read,
        "cache_creation": args.usd_per_mtok_cache_creation,
    }


def cmd_trend(args):
    rows = trend_rows(args.root)
    if not rows:
        print("error: no runs found under %s" % args.root, file=sys.stderr)
        return 2
    if args.md:
        print(render_trend_md(rows))
    else:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "runs": rows},
                         indent=2))
    return 0


def cmd_probe(args):
    directory = Path(args.directory)
    if not directory.is_dir():
        print("error: not a directory: %s" % directory, file=sys.stderr)
        return 2
    info = probe_transcripts(directory)
    info["usage_fields_seen"] = sorted(info["usage_fields_seen"])
    info["git_branches_seen"] = sorted(info["git_branches_seen"])[:20]
    info["note"] = ("transcript layout is an undocumented Claude Code "
                    "internal format and may drift across versions")
    print(json.dumps(info, indent=2))
    return 0


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="run_metrics.py",
        description="Derive safety/quality/performance/token metrics for "
                    "spec-loop runs from their durable artifacts.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    comp = sub.add_parser("compute", help="metrics for one run directory")
    comp.add_argument("run_dir", help="docs/spec-loop/<run-id> directory")
    comp.add_argument("--git", action="store_true",
                      help="enrich timing from merge-commit committer dates")
    comp.add_argument("--transcripts", metavar="DIR",
                      help="opt-in token accounting from a Claude Code "
                           "transcripts directory (best-effort)")
    comp.add_argument("--write", action="store_true",
                      help="atomically persist <run-dir>/metrics.json")
    for kind in ("input", "output", "cache-read", "cache-creation"):
        comp.add_argument("--usd-per-mtok-%s" % kind, type=float,
                          metavar="RATE", help="$ per Mtok (%s)" % kind)

    trend = sub.add_parser("trend", help="cross-run comparison")
    trend.add_argument("root", nargs="?", default=".",
                       help="repo root (or a docs/spec-loop directory)")
    trend.add_argument("--md", action="store_true",
                       help="markdown table instead of JSON")

    probe = sub.add_parser("probe-transcripts",
                           help="show what the token parser can see")
    probe.add_argument("directory")
    return parser


def main(argv=None):
    args = _build_parser().parse_args(argv)
    if args.command == "compute":
        return cmd_compute(args)
    if args.command == "trend":
        return cmd_trend(args)
    return cmd_probe(args)


if __name__ == "__main__":
    sys.exit(main())
