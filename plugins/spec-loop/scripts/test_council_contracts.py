"""Tests for council_contracts.py.

Standard library only. Exercises the fenced-block extractor, member-verdict
validation, the aggregation rules (including reduced councils and the SAFETY
veto), the slice-status sidecar schema, and the CLI subcommands end-to-end
via main() with patched stdin/stdout.
"""

import io
import json
import unittest
from unittest import mock

import council_contracts as cc


def member(name="skeptic", verdict="ENDORSE", discrepancies=None, feedback=None, blocker=None):
    obj = {
        "member": name,
        "verdict": verdict,
        "discrepancies": discrepancies or [],
        "feedback": feedback or [],
        "blocker": blocker,
    }
    return obj


def objecting(name, text="bad premise", safety=False):
    return member(name, "OBJECT", blocker={"text": text, "safety": safety})


def reply_with(obj, prose="Some deliberation prose.\n"):
    return prose + "```json\n" + json.dumps(obj) + "\n```\n"


def run_main(argv, stdin_text=""):
    """Run main() with captured stdin/stdout; returns (exit_code, parsed_json)."""
    stdout = io.StringIO()
    with mock.patch("sys.stdin", io.StringIO(stdin_text)):
        with mock.patch("sys.stdout", stdout):
            code = cc.main(argv)
    return code, json.loads(stdout.getvalue())


class ExtractLastJsonBlockTests(unittest.TestCase):
    def test_no_block_returns_none(self):
        self.assertIsNone(cc.extract_last_json_block("plain prose, no fences"))
        self.assertIsNone(cc.extract_last_json_block(""))
        self.assertIsNone(cc.extract_last_json_block(None))

    def test_single_block(self):
        text = "prose\n```json\n{\"a\": 1}\n```\n"
        self.assertEqual(cc.extract_last_json_block(text), '{"a": 1}')

    def test_last_of_multiple_blocks_wins(self):
        text = "```json\n{\"a\": 1}\n```\nmore\n```json\n{\"b\": 2}\n```\n"
        self.assertEqual(cc.extract_last_json_block(text), '{"b": 2}')

    def test_case_insensitive_fence_tag(self):
        text = "```JSON\n{\"a\": 1}\n```\n"
        self.assertEqual(cc.extract_last_json_block(text), '{"a": 1}')

    def test_non_json_fences_ignored(self):
        text = "```python\nx = 1\n```\n```json\n{\"a\": 1}\n```\n"
        self.assertEqual(cc.extract_last_json_block(text), '{"a": 1}')


class ValidateMemberVerdictTests(unittest.TestCase):
    def test_valid_endorse(self):
        normalized, errors = cc.validate_member_verdict(member())
        self.assertEqual(errors, [])
        self.assertEqual(normalized["verdict"], "ENDORSE")
        self.assertIsNone(normalized["blocker"])

    def test_valid_object_with_blocker(self):
        normalized, errors = cc.validate_member_verdict(objecting("guardian", "PII leak", True))
        self.assertEqual(errors, [])
        self.assertEqual(normalized["blocker"], {"text": "PII leak", "safety": True})

    def test_missing_arrays_normalize_to_empty(self):
        normalized, errors = cc.validate_member_verdict(
            {"member": "architect", "verdict": "ENDORSE"}
        )
        self.assertEqual(errors, [])
        self.assertEqual(normalized["discrepancies"], [])
        self.assertEqual(normalized["feedback"], [])

    def test_not_a_dict(self):
        normalized, errors = cc.validate_member_verdict(["nope"])
        self.assertIsNone(normalized)
        self.assertTrue(errors)

    def test_bad_member_and_verdict(self):
        _, errors = cc.validate_member_verdict({"member": "jester", "verdict": "MAYBE"})
        joined = " ".join(errors)
        self.assertIn("member", joined)
        self.assertIn("verdict", joined)

    def test_object_requires_blocker(self):
        _, errors = cc.validate_member_verdict(member(verdict="OBJECT"))
        self.assertIn("blocker is required", " ".join(errors))

    def test_object_blocker_needs_text_and_safety_bool(self):
        _, errors = cc.validate_member_verdict(
            member(verdict="OBJECT", blocker={"text": "  ", "safety": "yes"})
        )
        joined = " ".join(errors)
        self.assertIn("blocker.text", joined)
        self.assertIn("blocker.safety", joined)

    def test_blocker_forbidden_unless_object(self):
        _, errors = cc.validate_member_verdict(
            member(blocker={"text": "sneaky", "safety": False})
        )
        self.assertIn("blocker must be null", " ".join(errors))

    def test_non_string_arrays_rejected(self):
        _, errors = cc.validate_member_verdict(
            {"member": "skeptic", "verdict": "ENDORSE", "feedback": [1, 2]}
        )
        self.assertIn("feedback", " ".join(errors))

    def test_blocker_text_is_stripped(self):
        normalized, _ = cc.validate_member_verdict(
            objecting("skeptic", "  padded  ")
        )
        self.assertEqual(normalized["blocker"]["text"], "padded")


class AggregateTests(unittest.TestCase):
    def _normalize(self, objs):
        return [cc.validate_member_verdict(o)[0] for o in objs]

    def test_all_endorse(self):
        result = cc.aggregate_verdicts(
            self._normalize([member(m) for m in cc.MEMBERS])
        )
        self.assertEqual(result["verdict"], "ENDORSE")
        self.assertEqual(result["members"], 5)
        self.assertFalse(result["safety_object"])
        self.assertEqual(result["concerns"], [])

    def test_single_safety_object_halts(self):
        verdicts = [member(m) for m in ("skeptic", "architect", "pragmatist", "historian")]
        verdicts.append(objecting("guardian", "secret in diff", safety=True))
        result = cc.aggregate_verdicts(self._normalize(verdicts))
        self.assertEqual(result["verdict"], "OBJECT")
        self.assertTrue(result["safety_object"])
        self.assertEqual(result["objecting_members"][0]["member"], "guardian")

    def test_majority_object_halts(self):
        verdicts = [
            objecting("skeptic"),
            objecting("architect"),
            objecting("pragmatist"),
            member("guardian"),
            member("historian"),
        ]
        result = cc.aggregate_verdicts(self._normalize(verdicts))
        self.assertEqual(result["verdict"], "OBJECT")
        self.assertFalse(result["safety_object"])

    def test_minority_object_is_concerns(self):
        verdicts = [
            objecting("skeptic"),
            objecting("architect"),
            member("pragmatist"),
            member("guardian"),
            member("historian"),
        ]
        result = cc.aggregate_verdicts(self._normalize(verdicts))
        self.assertEqual(result["verdict"], "ENDORSE_WITH_CONCERNS")
        self.assertEqual(len(result["objecting_members"]), 2)

    def test_reduced_council_strict_majority(self):
        # 1 of 2 objecting is NOT strictly more than half -> concerns.
        two = self._normalize([objecting("pragmatist"), member("guardian")])
        self.assertEqual(cc.aggregate_verdicts(two)["verdict"], "ENDORSE_WITH_CONCERNS")
        # 2 of 3 objecting IS a strict majority -> OBJECT.
        three = self._normalize(
            [objecting("pragmatist"), objecting("skeptic"), member("guardian")]
        )
        self.assertEqual(cc.aggregate_verdicts(three)["verdict"], "OBJECT")

    def test_concerns_flattened_and_none_filtered(self):
        verdicts = self._normalize(
            [
                member(
                    "historian",
                    "ENDORSE_WITH_CONCERNS",
                    discrepancies=["reinvents util.py helper"],
                    feedback=["none"],
                ),
                member("skeptic", feedback=["ignored: endorse feedback"]),
            ]
        )
        result = cc.aggregate_verdicts(verdicts)
        self.assertEqual(result["verdict"], "ENDORSE_WITH_CONCERNS")
        self.assertEqual(result["concerns"], ["[historian] reinvents util.py helper"])


class AggregateExpectTests(unittest.TestCase):
    """--expect: the convened composition must report exactly once each (fail closed)."""

    def test_reduced_council_ok(self):
        payload = json.dumps([member("guardian"), member("pragmatist")])
        code, out = run_main(["aggregate", "--expect", "pragmatist,guardian"], payload)
        self.assertEqual(code, 0)
        self.assertEqual(out["verdict"], "ENDORSE")
        self.assertEqual(out["expected_members"], ["pragmatist", "guardian"])

    def test_full_council_ok(self):
        payload = json.dumps([member(m) for m in cc.MEMBERS])
        code, out = run_main(["aggregate", "--expect", ",".join(cc.MEMBERS)], payload)
        self.assertEqual(code, 0)
        self.assertEqual(out["expected_members"], list(cc.MEMBERS))

    def test_missing_member_exits_2(self):
        payload = json.dumps([member("pragmatist")])
        code, out = run_main(["aggregate", "--expect", "pragmatist,guardian"], payload)
        self.assertEqual(code, 2)
        self.assertIn("guardian", out["error"])

    def test_unexpected_member_exits_2(self):
        payload = json.dumps([member("pragmatist"), member("guardian"), member("historian")])
        code, out = run_main(["aggregate", "--expect", "pragmatist,guardian"], payload)
        self.assertEqual(code, 2)
        self.assertIn("historian", out["error"])

    def test_duplicate_verdict_exits_2(self):
        payload = json.dumps([member("pragmatist"), member("guardian"), member("guardian")])
        code, out = run_main(["aggregate", "--expect", "pragmatist,guardian"], payload)
        self.assertEqual(code, 2)
        self.assertIn("duplicate", out["error"])

    def test_unknown_name_in_expect_exits_2(self):
        payload = json.dumps([member("guardian")])
        code, out = run_main(["aggregate", "--expect", "jester,guardian"], payload)
        self.assertEqual(code, 2)
        self.assertIn("jester", out["error"])

    def test_duplicate_name_in_expect_exits_2(self):
        payload = json.dumps([member("guardian")])
        code, out = run_main(["aggregate", "--expect", "guardian,guardian"], payload)
        self.assertEqual(code, 2)
        self.assertIn("duplicate", out["error"])

    def test_empty_expect_exits_2(self):
        payload = json.dumps([member("guardian")])
        code, out = run_main(["aggregate", "--expect", " , "], payload)
        self.assertEqual(code, 2)
        self.assertIn("at least one", out["error"])

    def test_expect_tolerates_whitespace_and_order(self):
        payload = json.dumps([member("pragmatist"), member("guardian")])
        code, out = run_main(["aggregate", "--expect", " guardian , pragmatist "], payload)
        self.assertEqual(code, 0)
        self.assertEqual(out["expected_members"], ["pragmatist", "guardian"])

    def test_without_expect_unchanged(self):
        # No --expect: duplicates/subsets aggregate as before (no completeness check).
        payload = json.dumps([member("guardian"), member("guardian")])
        code, out = run_main(["aggregate"], payload)
        self.assertEqual(code, 0)
        self.assertNotIn("expected_members", out)


class ValidateSliceStatusTests(unittest.TestCase):
    def _done(self, **overrides):
        obj = {
            "version": 1,
            "id": "s3",
            "status": "DONE",
            "branch": "spec-loop/run/s3",
            "commits": {"base": "abc1234", "head": "def5678"},
            "council": {"verdict": "ENDORSE", "detail": "5/5"},
            "tests": {"command": "pytest", "result": "34/34 pass"},
            "review": "approve",
            "quality": {"status": "PASS", "detail": "all under thresholds"},
            "open_escalations": [],
        }
        obj.update(overrides)
        return obj

    def test_valid_done(self):
        self.assertEqual(cc.validate_slice_status(self._done()), [])

    def test_valid_split(self):
        obj = {
            "version": 1,
            "id": "s3",
            "status": "SPLIT",
            "split": {"children": 2, "proposal": "slice-s3-split.json"},
        }
        self.assertEqual(cc.validate_slice_status(obj), [])

    def test_valid_needs_decision_minimal(self):
        obj = {"version": 1, "id": "s4", "status": "NEEDS_DECISION"}
        self.assertEqual(cc.validate_slice_status(obj), [])

    def test_not_a_dict(self):
        self.assertTrue(cc.validate_slice_status([1]))

    def test_bad_version_id_status(self):
        errors = cc.validate_slice_status({"version": 2, "id": "", "status": "WIP"})
        joined = " ".join(errors)
        self.assertIn("version", joined)
        self.assertIn("id", joined)
        self.assertIn("status", joined)

    def test_done_requires_evidence_fields(self):
        errors = cc.validate_slice_status(
            {"version": 1, "id": "s1", "status": "DONE"}
        )
        joined = " ".join(errors)
        for needle in ("branch", "commits", "tests", "quality"):
            self.assertIn(needle, joined)

    def test_done_rejects_bad_quality_status(self):
        errors = cc.validate_slice_status(self._done(quality={"status": "GREAT"}))
        self.assertIn("quality.status", " ".join(errors))

    def test_split_requires_children_and_proposal(self):
        errors = cc.validate_slice_status(
            {"version": 1, "id": "s2", "status": "SPLIT", "split": {"children": 1}}
        )
        self.assertIn("SPLIT requires", " ".join(errors))

    def test_open_escalations_must_be_strings(self):
        errors = cc.validate_slice_status(self._done(open_escalations=[{"t": 1}]))
        self.assertIn("open_escalations", " ".join(errors))

    # --- optional run-metrics instrumentation fields (run_metrics.py) ------

    def test_metrics_fields_absent_still_validates(self):
        # Back-compat is permanent: a legacy sidecar with none of the
        # started_at/finished_at/wave/counters fields is valid.
        self.assertEqual(cc.validate_slice_status(self._done()), [])

    def test_metrics_fields_valid_shapes_accepted(self):
        obj = self._done(
            started_at="2026-07-14T10:10:00Z",
            finished_at="2026-07-14T11:10:00+00:00",
            wave=0,
            counters={"review_confirmed": 2, "fix_passes": 0,
                      "fail_closed": 1},
        )
        self.assertEqual(cc.validate_slice_status(obj), [])

    def test_metrics_timestamps_must_look_iso(self):
        errors = cc.validate_slice_status(
            self._done(started_at="yesterday", finished_at=12345))
        joined = " ".join(errors)
        self.assertIn("started_at", joined)
        self.assertIn("finished_at", joined)

    def test_wave_must_be_non_negative_int(self):
        for bad in (-1, True, "1", 1.5):
            errors = cc.validate_slice_status(self._done(wave=bad))
            self.assertIn("wave", " ".join(errors), repr(bad))

    def test_counters_values_must_be_non_negative_ints(self):
        errors = cc.validate_slice_status(
            self._done(counters={"fix_passes": -1, "fail_closed": "2"}))
        joined = " ".join(errors)
        self.assertIn("counters.fix_passes", joined)
        self.assertIn("counters.fail_closed", joined)

    def test_counters_must_be_an_object(self):
        errors = cc.validate_slice_status(self._done(counters=[1, 2]))
        self.assertIn("counters must be an object", " ".join(errors))


class CliTests(unittest.TestCase):
    def test_validate_member_ok(self):
        code, out = run_main(["validate-member"], reply_with(member("guardian")))
        self.assertEqual(code, 0)
        self.assertEqual(out["member"], "guardian")

    def test_validate_member_uses_last_block(self):
        text = reply_with(member("skeptic")) + reply_with(objecting("skeptic"))
        code, out = run_main(["validate-member"], text)
        self.assertEqual(code, 0)
        self.assertEqual(out["verdict"], "OBJECT")

    def test_validate_member_no_block(self):
        code, out = run_main(["validate-member"], "prose only, no fenced block")
        self.assertEqual(code, 1)
        self.assertFalse(out["valid"])

    def test_validate_member_bad_json(self):
        code, out = run_main(["validate-member"], "```json\n{not json}\n```")
        self.assertEqual(code, 1)
        self.assertIn("invalid JSON", out["errors"][0])

    def test_validate_member_schema_violation(self):
        code, out = run_main(["validate-member"], reply_with(member(verdict="OBJECT")))
        self.assertEqual(code, 1)
        self.assertFalse(out["valid"])

    def test_aggregate_ok(self):
        payload = json.dumps([member(m) for m in cc.MEMBERS])
        code, out = run_main(["aggregate"], payload)
        self.assertEqual(code, 0)
        self.assertEqual(out["verdict"], "ENDORSE")

    def test_aggregate_malformed_json_exits_2(self):
        code, out = run_main(["aggregate"], "{not json")
        self.assertEqual(code, 2)
        self.assertIn("invalid JSON", out["error"])

    def test_aggregate_empty_array_exits_2(self):
        code, out = run_main(["aggregate"], "[]")
        self.assertEqual(code, 2)
        self.assertIn("non-empty", out["error"])

    def test_aggregate_invalid_member_exits_2(self):
        code, out = run_main(["aggregate"], json.dumps([{"member": "x"}]))
        self.assertEqual(code, 2)
        self.assertIn("verdict[0]", out["error"])

    def test_validate_slice_status_stdin(self):
        obj = {"version": 1, "id": "s1", "status": "BLOCKED"}
        code, out = run_main(["validate-slice-status"], json.dumps(obj))
        self.assertEqual(code, 0)
        self.assertEqual(out, {"valid": True, "id": "s1", "status": "BLOCKED"})

    def test_validate_slice_status_file(self):
        import os
        import tempfile

        obj = {"version": 1, "id": "s9", "status": "NEEDS_DECISION"}
        fd, path = tempfile.mkstemp(suffix=".json")
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(obj, fh)
            code, out = run_main(["validate-slice-status", "--file", path])
            self.assertEqual(code, 0)
            self.assertTrue(out["valid"])
        finally:
            os.unlink(path)

    def test_validate_slice_status_missing_file(self):
        code, out = run_main(
            ["validate-slice-status", "--file", "/nonexistent/x.json"]
        )
        self.assertEqual(code, 1)
        self.assertIn("cannot read", out["errors"][0])

    def test_validate_slice_status_invalid(self):
        code, out = run_main(["validate-slice-status"], json.dumps({"id": "s1"}))
        self.assertEqual(code, 1)
        self.assertFalse(out["valid"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
