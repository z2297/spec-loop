#!/usr/bin/env python3
"""Validate and aggregate spec-loop's structured JSON contracts.

The Iron Council members and the slice workers emit machine-readable JSON
(fenced ```json blocks in agent replies; sidecar files on disk). This script
is the deterministic executor of those contracts so the convening layer never
hand-parses or eyeballs a verdict:

  validate-member         stdin: a full council-member reply. Extracts the
                          LAST fenced ```json block, validates it against the
                          member-verdict schema, prints the normalized verdict.
                          Exit 0 valid / 1 invalid.
  aggregate               stdin: JSON array of normalized member verdicts.
                          Applies the iron-council aggregation rules and prints
                          the council verdict. Exit 0 / 2 on malformed input
                          (fail-closed: no verdict means do not proceed).
                          --expect <m1,m2,...> pins the convened composition:
                          every named member must report exactly once — a
                          missing, duplicate, or uninvited verdict is exit 2,
                          so a member that never reported cannot silently
                          vanish from the majority math (reduced councils).
  validate-slice-status   --file <path> (or stdin): validates a slice status
                          sidecar (slice-<id>-status.json). Exit 0 / 1.

Standard library only. All output is JSON on stdout; nothing is written to
disk. Fail-closed policy lives in the calling skills: an invalid member reply
becomes a non-SAFETY OBJECT after one re-dispatch; an invalid sidecar makes
the slice NEEDS_DECISION.
"""

from __future__ import annotations

import argparse
import json
import re
import sys

MEMBERS = ("skeptic", "architect", "pragmatist", "guardian", "historian")
VERDICTS = ("ENDORSE", "ENDORSE_WITH_CONCERNS", "OBJECT")
SLICE_STATUSES = ("DONE", "NEEDS_DECISION", "BLOCKED", "SPLIT")
QUALITY_STATUSES = ("PASS", "FAIL", "SKIPPED")

FENCED_JSON = re.compile(r"```json\s*\n(.*?)\n\s*```", re.DOTALL | re.IGNORECASE)


# ---------------------------------------------------------------------------
# member verdicts
# ---------------------------------------------------------------------------

def extract_last_json_block(text):
    """Return the contents of the last fenced ```json block, or None."""
    blocks = FENCED_JSON.findall(text or "")
    return blocks[-1] if blocks else None


def _string_list(value, field, errors):
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
        errors.append("%s must be an array of strings" % field)
        return []
    return value


def validate_member_verdict(obj):
    """Validate one member verdict. Returns (normalized, errors)."""
    errors = []
    if not isinstance(obj, dict):
        return None, ["verdict must be a JSON object"]

    member = obj.get("member")
    if member not in MEMBERS:
        errors.append("member must be one of %s" % (", ".join(MEMBERS)))
    verdict = obj.get("verdict")
    if verdict not in VERDICTS:
        errors.append("verdict must be one of %s" % (", ".join(VERDICTS)))

    discrepancies = _string_list(obj.get("discrepancies"), "discrepancies", errors)
    feedback = _string_list(obj.get("feedback"), "feedback", errors)

    blocker = obj.get("blocker")
    if verdict == "OBJECT":
        if not isinstance(blocker, dict):
            errors.append("blocker is required (object) when verdict is OBJECT")
        else:
            text = blocker.get("text")
            if not isinstance(text, str) or not text.strip():
                errors.append("blocker.text must be a non-empty string")
            if not isinstance(blocker.get("safety"), bool):
                errors.append("blocker.safety must be a boolean")
    elif blocker not in (None, {}):
        errors.append("blocker must be null unless verdict is OBJECT")

    if errors:
        return None, errors

    return {
        "member": member,
        "verdict": verdict,
        "discrepancies": discrepancies,
        "feedback": feedback,
        "blocker": (
            {"text": blocker["text"].strip(), "safety": blocker["safety"]}
            if verdict == "OBJECT"
            else None
        ),
    }, []


def cmd_validate_member(text):
    block = extract_last_json_block(text)
    if block is None:
        print(json.dumps({"valid": False, "errors": ["no fenced ```json block found in reply"]}))
        return 1
    try:
        obj = json.loads(block)
    except ValueError as exc:
        print(json.dumps({"valid": False, "errors": ["invalid JSON in fenced block: %s" % exc]}))
        return 1
    normalized, errors = validate_member_verdict(obj)
    if errors:
        print(json.dumps({"valid": False, "errors": errors}))
        return 1
    print(json.dumps(normalized))
    return 0


# ---------------------------------------------------------------------------
# aggregation
# ---------------------------------------------------------------------------

def aggregate_verdicts(verdicts):
    """Apply the iron-council aggregation rules to normalized verdicts.

    - any SAFETY blocker  -> OBJECT (a lone safety objection halts)
    - objections strictly more than half of N -> OBJECT
    - any OBJECT or ENDORSE_WITH_CONCERNS     -> ENDORSE_WITH_CONCERNS
    - otherwise                               -> ENDORSE
    """
    counts = {v: 0 for v in VERDICTS}
    objecting = []
    concerns = []
    safety = False

    for v in verdicts:
        counts[v["verdict"]] += 1
        if v["verdict"] == "OBJECT":
            blocker = v.get("blocker") or {}
            if blocker.get("safety"):
                safety = True
            objecting.append(
                {
                    "member": v["member"],
                    "blocker": blocker.get("text", ""),
                    "safety": bool(blocker.get("safety")),
                }
            )
        if v["verdict"] != "ENDORSE":
            for item in v.get("discrepancies", []) + v.get("feedback", []):
                if item and item.strip().lower() != "none":
                    concerns.append("[%s] %s" % (v["member"], item))

    n = len(verdicts)
    if safety or counts["OBJECT"] * 2 > n:
        verdict = "OBJECT"
    elif counts["OBJECT"] or counts["ENDORSE_WITH_CONCERNS"]:
        verdict = "ENDORSE_WITH_CONCERNS"
    else:
        verdict = "ENDORSE"

    return {
        "verdict": verdict,
        "counts": counts,
        "members": n,
        "safety_object": safety,
        "objecting_members": objecting,
        "concerns": concerns,
    }


def parse_expected_members(spec):
    """Parse a comma-separated --expect list. Returns (members, error).

    Members come back in canonical MEMBERS order regardless of input order.
    """
    names = [n.strip() for n in (spec or "").split(",") if n.strip()]
    if not names:
        return None, "--expect must name at least one member"
    unknown = [n for n in names if n not in MEMBERS]
    if unknown:
        return None, "--expect contains unknown members: %s" % ", ".join(unknown)
    if len(set(names)) != len(names):
        return None, "--expect contains duplicate members"
    return tuple(m for m in MEMBERS if m in set(names)), None


def check_expected_members(verdicts, expected):
    """Return an error string unless each expected member reported exactly once."""
    seen = [v["member"] for v in verdicts]
    duplicates = sorted({m for m in seen if seen.count(m) > 1})
    if duplicates:
        return "duplicate verdicts for: %s" % ", ".join(duplicates)
    missing = [m for m in expected if m not in seen]
    extra = sorted(set(seen) - set(expected))
    problems = []
    if missing:
        problems.append("missing verdicts from: %s" % ", ".join(missing))
    if extra:
        problems.append("unexpected verdicts from: %s" % ", ".join(extra))
    return "; ".join(problems) if problems else None


def cmd_aggregate(text, expect=None):
    expected = None
    if expect is not None:
        expected, err = parse_expected_members(expect)
        if err:
            print(json.dumps({"error": err}))
            return 2
    try:
        data = json.loads(text)
    except ValueError as exc:
        print(json.dumps({"error": "invalid JSON on stdin: %s" % exc}))
        return 2
    if not isinstance(data, list) or not data:
        print(json.dumps({"error": "expected a non-empty JSON array of member verdicts"}))
        return 2
    normalized = []
    for i, item in enumerate(data):
        verdict, errors = validate_member_verdict(item)
        if errors:
            print(json.dumps({"error": "verdict[%d] invalid: %s" % (i, "; ".join(errors))}))
            return 2
        normalized.append(verdict)
    if expected:
        err = check_expected_members(normalized, expected)
        if err:
            print(json.dumps({"error": "council incomplete (fail closed): %s" % err}))
            return 2
    result = aggregate_verdicts(normalized)
    if expected:
        result["expected_members"] = list(expected)
    print(json.dumps(result))
    return 0


# ---------------------------------------------------------------------------
# slice status sidecars
# ---------------------------------------------------------------------------

def validate_slice_status(obj):
    """Validate a slice status sidecar. Returns a list of errors (empty = valid)."""
    errors = []
    if not isinstance(obj, dict):
        return ["slice status must be a JSON object"]

    if obj.get("version") != 1:
        errors.append("version must be 1")
    if not isinstance(obj.get("id"), str) or not obj["id"].strip():
        errors.append("id must be a non-empty string")
    status = obj.get("status")
    if status not in SLICE_STATUSES:
        errors.append("status must be one of %s" % (", ".join(SLICE_STATUSES)))

    if status == "DONE":
        if not isinstance(obj.get("branch"), str) or not obj["branch"].strip():
            errors.append("DONE requires a non-empty branch")
        commits = obj.get("commits")
        if not isinstance(commits, dict) or not commits.get("base") or not commits.get("head"):
            errors.append("DONE requires commits.base and commits.head")
        tests = obj.get("tests")
        if not isinstance(tests, dict) or not tests.get("command") or not tests.get("result"):
            errors.append("DONE requires tests.command and tests.result")
        quality = obj.get("quality")
        if not isinstance(quality, dict) or quality.get("status") not in QUALITY_STATUSES:
            errors.append("DONE requires quality.status of %s" % (", ".join(QUALITY_STATUSES)))

    if status == "SPLIT":
        split = obj.get("split")
        if (
            not isinstance(split, dict)
            or not isinstance(split.get("children"), int)
            or split["children"] < 2
            or not isinstance(split.get("proposal"), str)
            or not split["proposal"].strip()
        ):
            errors.append("SPLIT requires split.children (int >= 2) and split.proposal")

    escalations = obj.get("open_escalations")
    if escalations is not None and (
        not isinstance(escalations, list) or any(not isinstance(x, str) for x in escalations)
    ):
        errors.append("open_escalations must be an array of strings")

    _validate_metrics_fields(obj, errors)

    return errors


# Optional run-metrics instrumentation fields (consumed by run_metrics.py).
# All of them are OPTIONAL forever: a legacy sidecar without any of them must
# still validate — they are only shape-checked when present.
ISO_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")


def _is_count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _validate_metrics_fields(obj, errors):
    """Shape-check the optional started_at/finished_at/wave/counters fields."""
    for field in ("started_at", "finished_at"):
        value = obj.get(field)
        if value is not None and not (
            isinstance(value, str) and ISO_TIMESTAMP.match(value)
        ):
            errors.append("%s must be an ISO-8601 timestamp string" % field)
    wave = obj.get("wave")
    if wave is not None and not _is_count(wave):
        errors.append("wave must be a non-negative integer")
    counters = obj.get("counters")
    if counters is None:
        return
    if not isinstance(counters, dict):
        errors.append("counters must be an object of non-negative integers")
        return
    for key, value in counters.items():
        if not _is_count(value):
            errors.append("counters.%s must be a non-negative integer" % key)


def cmd_validate_slice_status(text):
    try:
        obj = json.loads(text)
    except ValueError as exc:
        print(json.dumps({"valid": False, "errors": ["invalid JSON: %s" % exc]}))
        return 1
    errors = validate_slice_status(obj)
    if errors:
        print(json.dumps({"valid": False, "errors": errors}))
        return 1
    print(json.dumps({"valid": True, "id": obj["id"], "status": obj["status"]}))
    return 0


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="council_contracts.py",
        description="Validate and aggregate spec-loop JSON contracts.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate-member", help="validate a council member reply from stdin")
    aggregate = sub.add_parser(
        "aggregate", help="aggregate a JSON array of member verdicts from stdin"
    )
    aggregate.add_argument(
        "--expect",
        help="comma-separated convened members that must each report exactly once "
        "(fail closed on any missing/duplicate/unexpected verdict)",
    )
    status = sub.add_parser("validate-slice-status", help="validate a slice status sidecar")
    status.add_argument("--file", help="path to the sidecar (default: read stdin)")

    args = parser.parse_args(argv)

    if args.command == "validate-slice-status" and args.file:
        try:
            with open(args.file, "r", encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            print(json.dumps({"valid": False, "errors": ["cannot read %s: %s" % (args.file, exc)]}))
            return 1
    else:
        text = sys.stdin.read()

    if args.command == "validate-member":
        return cmd_validate_member(text)
    if args.command == "aggregate":
        return cmd_aggregate(text, expect=args.expect)
    return cmd_validate_slice_status(text)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
