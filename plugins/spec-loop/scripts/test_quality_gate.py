#!/usr/bin/env python3
"""Tests for the objective code-quality gate (stdlib unittest).

Covers the PURE diff parser on embedded fixture text, config loading (defaults /
loaded / disabled / malformed), the pure metric primitives (parameter counting,
branch counting, nesting depth, CRAP, cognitive approximation), the builtin
heuristic function extraction for python and brace languages, backend CSV/JSON
parsing and backend+heuristic merging with per-metric sourcing (cognitive is
NEVER attributed to a tool), coverage parsing (cobertura + lcov) and CRAP
assembly, custom-gate evaluation (metric-form evaluated here, command-form
deferred to the skill), threshold pass/fail + report shape, and main()'s exit
codes. Backends are exercised by mocking shutil.which / subprocess.run so the
suite passes whether or not lizard/radon are installed. Standard library only;
no live network. Real git is used only in a tiny throwaway repo for the
end-to-end path.

Usage:
    python3 -m unittest discover -s plugins/spec-loop/scripts -p 'test_quality_gate.py'
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import quality_gate as qg  # noqa: E402


# --------------------------------------------------------------------------
# parse_diff — pure, embedded fixtures
# --------------------------------------------------------------------------

class TestParseDiff(unittest.TestCase):
    def test_single_file_added_range(self):
        diff = (
            "diff --git a/foo.py b/foo.py\n"
            "index 111..222 100644\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -1,0 +2,3 @@\n"
            "+a\n+b\n+c\n"
        )
        self.assertEqual(qg.parse_diff(diff), {"foo.py": [(2, 4)]})

    def test_hunk_without_count_is_single_line(self):
        # `+5` with no ,count means exactly one added line at 5.
        diff = (
            "--- a/x.js\n"
            "+++ b/x.js\n"
            "@@ -5 +5 @@\n"
            "-old\n+new\n"
        )
        self.assertEqual(qg.parse_diff(diff), {"x.js": [(5, 5)]})

    def test_multiple_hunks_and_files(self):
        diff = (
            "--- a/a.py\n+++ b/a.py\n"
            "@@ -1,0 +1,2 @@\n+x\n+y\n"
            "@@ -10,0 +20,1 @@\n+z\n"
            "--- a/b.py\n+++ b/b.py\n"
            "@@ -1,0 +3,1 @@\n+q\n"
        )
        self.assertEqual(
            qg.parse_diff(diff),
            {"a.py": [(1, 2), (20, 20)], "b.py": [(3, 3)]})

    def test_deleted_file_is_skipped(self):
        # A file whose new path is /dev/null contributes no range.
        diff = (
            "--- a/gone.py\n"
            "+++ /dev/null\n"
            "@@ -1,3 +0,0 @@\n-a\n-b\n-c\n"
        )
        self.assertEqual(qg.parse_diff(diff), {})

    def test_pure_deletion_hunk_contributes_no_range(self):
        # `+0,0` (zero new lines) is a deletion within an otherwise-live file.
        diff = (
            "--- a/f.py\n+++ b/f.py\n"
            "@@ -5,2 +4,0 @@\n-a\n-b\n"
        )
        self.assertEqual(qg.parse_diff(diff), {})

    def test_b_prefix_stripped(self):
        diff = "--- a/dir/x.py\n+++ b/dir/x.py\n@@ -1 +1 @@\n-a\n+b\n"
        self.assertEqual(qg.parse_diff(diff), {"dir/x.py": [(1, 1)]})

    def test_empty_diff(self):
        self.assertEqual(qg.parse_diff(""), {})


class TestSpanHelpers(unittest.TestCase):
    def test_overlap_true_and_false(self):
        self.assertTrue(qg._spans_overlap(1, 5, 5, 9))
        self.assertTrue(qg._spans_overlap(3, 4, 1, 10))
        self.assertFalse(qg._spans_overlap(1, 5, 6, 9))

    def test_intersects_changed(self):
        self.assertTrue(qg._intersects_changed(10, 20, [(1, 2), (15, 16)]))
        self.assertFalse(qg._intersects_changed(10, 20, [(1, 2), (30, 40)]))


# --------------------------------------------------------------------------
# Config loading
# --------------------------------------------------------------------------

class TestLoadConfig(unittest.TestCase):
    def test_missing_path_uses_defaults(self):
        cfg, src = qg.load_config("/nonexistent/quality-gate.json")
        self.assertEqual(src, "defaults")
        self.assertEqual(cfg["thresholds"], qg.DEFAULT_THRESHOLDS)
        self.assertTrue(cfg["enabled"])

    def test_none_path_uses_defaults(self):
        cfg, src = qg.load_config(None)
        self.assertEqual(src, "defaults")

    def test_loaded_merges_partial_thresholds_over_defaults(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"enabled": True,
                       "thresholds": {"cyclomatic_complexity": 5},
                       "custom_gates": [{"name": "g", "metric": "x",
                                         "threshold": 1}]}, fh)
            path = fh.name
        self.addCleanup(os.unlink, path)
        cfg, src = qg.load_config(path)
        self.assertEqual(src, "loaded")
        self.assertEqual(cfg["thresholds"]["cyclomatic_complexity"], 5)
        # untouched keys keep their default value
        self.assertEqual(cfg["thresholds"]["method_lines"],
                         qg.DEFAULT_THRESHOLDS["method_lines"])
        self.assertEqual(len(cfg["custom_gates"]), 1)

    def test_disabled_flag_preserved(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"enabled": False}, fh)
            path = fh.name
        self.addCleanup(os.unlink, path)
        cfg, _ = qg.load_config(path)
        self.assertFalse(cfg["enabled"])

    def test_malformed_json_is_hard_error(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write("{not json")
            path = fh.name
        self.addCleanup(os.unlink, path)
        with self.assertRaises(qg.GateError):
            qg.load_config(path)

    def test_non_object_json_is_hard_error(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump([1, 2, 3], fh)
            path = fh.name
        self.addCleanup(os.unlink, path)
        with self.assertRaises(qg.GateError):
            qg.load_config(path)


# --------------------------------------------------------------------------
# Pure metric primitives
# --------------------------------------------------------------------------

class TestCountParams(unittest.TestCase):
    def test_zero_params(self):
        self.assertEqual(qg._count_params("def f():"), 0)

    def test_simple_params(self):
        self.assertEqual(qg._count_params("def f(a, b, c):"), 3)

    def test_drops_leading_self(self):
        self.assertEqual(qg._count_params("def m(self, a, b):"), 2)

    def test_drops_leading_cls(self):
        self.assertEqual(qg._count_params("def m(cls, a):"), 1)

    def test_nested_generics_not_split(self):
        # a comma inside Dict[str, int] must not inflate the count
        self.assertEqual(
            qg._count_params("def f(a: Dict[str, int], b: List[int]):"), 2)

    def test_no_parens_returns_zero(self):
        self.assertEqual(qg._count_params("x = 1"), 0)


class TestBranchCount(unittest.TestCase):
    def test_base_path_only(self):
        self.assertEqual(qg._branch_count("x = 1\nreturn x\n"), 1)

    def test_counts_keywords_and_operators(self):
        code = "if a and b:\n    for i in x:\n        while y or z:\n            pass"
        # base 1 + if + for + while + and(&&-equivalent via 'and'? no) ...
        # 'and'/'or' are words not counted by ops regex; && || ? are. Here:
        # if, for, while -> 3 branch words; no &&/||/? -> total 1+3 = 4
        self.assertEqual(qg._branch_count(code), 4)

    def test_counts_boolean_operators_and_ternary(self):
        code = "return a && b || (c ? d : e)"
        # base 1 + && + || + ? -> 4
        self.assertEqual(qg._branch_count(code), 4)

    def test_else_if_counts_once(self):
        code = "if a {} else if b {}"
        # base 1 + two `if` words (leading + the one inside `else if`); the
        # `else if` is NOT separately counted as an op -> 3, not 4.
        self.assertEqual(qg._branch_count(code), 3)

    def test_word_boundary_avoids_identifiers(self):
        # 'ifield' / 'forum' must not be counted as if/for
        self.assertEqual(qg._branch_count("ifield = forum + whilehouse\n"), 1)


class TestNesting(unittest.TestCase):
    def test_python_nesting_by_indent(self):
        lines = [
            "    if a:",           # base_indent 4, level 0
            "        if b:",       # level 1
            "            x = 1",   # level 2
        ]
        self.assertEqual(qg._nesting_depth_python(lines, 4), 2)

    def test_brace_nesting(self):
        # outer function brace is depth 1 (discounted); one nested block -> 1
        self.assertEqual(qg._nesting_depth_braces("{ if (x) { y; } }"), 1)

    def test_brace_nesting_two_levels(self):
        self.assertEqual(
            qg._nesting_depth_braces("{ if(x){ while(y){ z; } } }"), 2)


class TestCrapScore(unittest.TestCase):
    def test_full_coverage_equals_complexity(self):
        # CRAP with 100% coverage collapses to the complexity itself
        self.assertAlmostEqual(qg.crap_score(10, 1.0), 10)

    def test_zero_coverage(self):
        # comp^2 * 1 + comp
        self.assertAlmostEqual(qg.crap_score(5, 0.0), 30)

    def test_partial_coverage(self):
        # 4^2 * (0.5)^3 + 4 = 16*0.125 + 4 = 6
        self.assertAlmostEqual(qg.crap_score(4, 0.5), 6)


class TestCognitiveApprox(unittest.TestCase):
    def test_nested_branches_weighted_more(self):
        flat = ["    if a:", "    if b:"]
        nested = ["    if a:", "        if b:"]
        flat_score = qg._cognitive_approx(flat, "python", 4)
        nested_score = qg._cognitive_approx(nested, "python", 4)
        self.assertGreater(nested_score, flat_score)

    def test_brace_language_weights_by_depth(self):
        lines = ["if (a) {", "    if (b) {", "    }", "}"]
        self.assertGreater(qg._cognitive_approx(lines, "cbrace", 0), 0)


# --------------------------------------------------------------------------
# Builtin heuristic extraction
# --------------------------------------------------------------------------

class TestAnalyzeBuiltinPython(unittest.TestCase):
    SOURCE = (
        "class Foo:\n"
        "    def small(self, a):\n"
        "        return a\n"
        "\n"
        "    def big(self, a, b, c, d, e):\n"
        "        if a:\n"
        "            for i in b:\n"
        "                if c:\n"
        "                    while d:\n"
        "                        return e\n"
        "        return 0\n"
    )

    def test_extracts_functions_intersecting_changed_ranges(self):
        # change only touches the `big` function (lines 5-11)
        findings, cls = qg.analyze_builtin("m.py", self.SOURCE, [(5, 11)])
        names = {f["function"] for f in findings}
        self.assertIn("big", names)
        self.assertNotIn("small", names)  # outside the changed range

    def test_metrics_reasonable(self):
        findings, cls = qg.analyze_builtin("m.py", self.SOURCE, [(1, 11)])
        big = next(f for f in findings if f["function"] == "big")
        m = big["metrics"]
        self.assertEqual(m["parameter_count"], 5)      # a,b,c,d,e (self dropped)
        self.assertGreaterEqual(m["cyclomatic_complexity"], 4)  # if/for/if/while
        self.assertGreaterEqual(m["nesting_depth"], 3)
        self.assertIn("cognitive_complexity", m)
        self.assertGreater(m["method_lines"], 0)

    def test_class_finding_counts_nonblank_lines(self):
        _, cls = qg.analyze_builtin("m.py", self.SOURCE, [(1, 11)])
        self.assertIsNotNone(cls)
        self.assertEqual(cls["class_lines"], qg._nonblank(self.SOURCE.splitlines()))

    def test_unsupported_extension_yields_nothing(self):
        findings, cls = qg.analyze_builtin("data.txt", "whatever\n", [(1, 1)])
        self.assertEqual(findings, [])
        self.assertIsNone(cls)


class TestAnalyzeBuiltinCbrace(unittest.TestCase):
    SOURCE = (
        "function outer(a, b) {\n"
        "    if (a) {\n"
        "        return b && a || c;\n"
        "    }\n"
        "    return 0;\n"
        "}\n"
    )

    def test_extracts_brace_function(self):
        findings, _ = qg.analyze_builtin("m.js", self.SOURCE, [(1, 6)])
        names = {f["function"] for f in findings}
        self.assertIn("outer", names)

    def test_control_keyword_not_treated_as_function(self):
        # `if (a) {` must not register as a function named `if`
        findings, _ = qg.analyze_builtin("m.js", self.SOURCE, [(1, 6)])
        self.assertNotIn("if", {f["function"] for f in findings})

    def test_params_and_complexity(self):
        findings, _ = qg.analyze_builtin("m.js", self.SOURCE, [(1, 6)])
        outer = next(f for f in findings if f["function"] == "outer")
        self.assertEqual(outer["metrics"]["parameter_count"], 2)
        # base + if + && + || -> >= 4
        self.assertGreaterEqual(outer["metrics"]["cyclomatic_complexity"], 4)

    def test_arrow_function_detected(self):
        src = "const handler = (x, y) => {\n    return x + y;\n}\n"
        findings, _ = qg.analyze_builtin("m.ts", src, [(1, 3)])
        self.assertIn("handler", {f["function"] for f in findings})


class TestMatchBraceEnd(unittest.TestCase):
    def test_balances_nested_braces(self):
        lines = ["f() {", "  { }", "}"]
        self.assertEqual(qg._match_brace_end(lines, 0), 2)

    def test_unbalanced_returns_none(self):
        lines = ["f() {", "  x"]
        self.assertIsNone(qg._match_brace_end(lines, 0))


# --------------------------------------------------------------------------
# Backend parsing + merge
# --------------------------------------------------------------------------

class TestLizardCsvParse(unittest.TestCase):
    def test_parses_rows(self):
        # nloc,ccn,token,param,length,location,file,func,long,start,end
        csv_text = (
            '12,7,80,3,20,"foo@5-24@m.py",m.py,foo,"foo(a,b,c)",5,24\n'
            'bad,row\n'
        )
        recs = qg._parse_lizard_csv(csv_text)
        self.assertEqual(len(recs), 1)
        r = recs[0]
        self.assertEqual(r["file"], "m.py")
        self.assertEqual(r["function"], "foo")
        self.assertEqual(r["cyclomatic_complexity"], 7)
        self.assertEqual(r["method_lines"], 12)
        self.assertEqual(r["parameter_count"], 3)
        self.assertEqual((r["line_start"], r["line_end"]), (5, 24))


class TestRadonJsonParse(unittest.TestCase):
    def test_parses_function_and_method_blocks(self):
        data = json.dumps({
            "m.py": [
                {"type": "f", "name": "foo", "lineno": 3, "endline": 20,
                 "complexity": 9},
                {"type": "m", "name": "bar", "lineno": 25, "endline": 30,
                 "complexity": 4},
                {"type": "c", "name": "Klass", "lineno": 1, "complexity": 2},
            ]
        })
        recs = qg._parse_radon_json(data)
        names = {r["function"] for r in recs}
        self.assertEqual(names, {"foo", "bar"})   # class block excluded
        foo = next(r for r in recs if r["function"] == "foo")
        self.assertEqual(foo["cyclomatic_complexity"], 9)

    def test_malformed_json_yields_empty(self):
        self.assertEqual(qg._parse_radon_json("not json"), [])


class TestBackendUnavailableReturnsEmpty(unittest.TestCase):
    def test_run_lizard_empty_files(self):
        self.assertEqual(qg.run_lizard([], "."), [])

    def test_run_lizard_missing_binary(self):
        with mock.patch("quality_gate.subprocess.run",
                        side_effect=FileNotFoundError("lizard")):
            self.assertEqual(qg.run_lizard(["m.py"], "."), [])

    def test_run_radon_nonzero_exit_returns_empty(self):
        with mock.patch("quality_gate.subprocess.run") as m:
            m.return_value = mock.Mock(returncode=2, stdout="", stderr="boom")
            self.assertEqual(qg.run_radon(["m.py"], "."), [])


class TestMergeBackendAndHeuristic(unittest.TestCase):
    def test_backend_owns_measured_cognitive_from_heuristic(self):
        backend = [{"file": "m.py", "function": "foo",
                    "line_start": 5, "line_end": 20,
                    "cyclomatic_complexity": 7, "method_lines": 12,
                    "parameter_count": 3}]
        heur = [{"function": "foo", "line_start": 5, "line_end": 20,
                 "metrics": {"cyclomatic_complexity": 6, "method_lines": 11,
                             "parameter_count": 3, "cognitive_complexity": 8,
                             "nesting_depth": 2}}]
        merged = qg._merge_backend_and_heuristic(backend, heur, "m.py")
        self.assertEqual(len(merged), 1)
        m = merged[0]
        # backend value wins for the metric it measured
        self.assertEqual(m["metrics"]["cyclomatic_complexity"], 7)
        self.assertEqual(m["metric_sources"]["cyclomatic_complexity"], "lizard")
        # cognitive ALWAYS comes from the heuristic, never the tool
        self.assertEqual(m["metrics"]["cognitive_complexity"], 8)
        self.assertEqual(m["metric_sources"]["cognitive_complexity"],
                         "builtin-heuristic")
        # nesting also from heuristic (lizard doesn't measure it)
        self.assertEqual(m["metric_sources"]["nesting_depth"],
                         "builtin-heuristic")

    def test_radon_backend_name_when_no_method_lines(self):
        backend = [{"file": "m.py", "function": "foo",
                    "line_start": 5, "line_end": 20,
                    "cyclomatic_complexity": 9}]
        merged = qg._merge_backend_and_heuristic(backend, [], "m.py")
        self.assertEqual(merged[0]["source"], "radon")
        self.assertEqual(merged[0]["metric_sources"]["cyclomatic_complexity"],
                         "radon")

    def test_no_matching_heuristic_still_reports_backend_metrics(self):
        backend = [{"file": "m.py", "function": "orphan",
                    "line_start": 1, "line_end": 3,
                    "cyclomatic_complexity": 4, "method_lines": 2,
                    "parameter_count": 1}]
        merged = qg._merge_backend_and_heuristic(backend, [], "m.py")
        self.assertNotIn("cognitive_complexity", merged[0]["metrics"])


# --------------------------------------------------------------------------
# Coverage parsing + CRAP assembly
# --------------------------------------------------------------------------

class TestCoverageParsing(unittest.TestCase):
    def test_cobertura(self):
        xml = (
            '<coverage><packages><package><classes>'
            '<class filename="src/m.py"><lines>'
            '<line number="1" hits="1"/>'
            '<line number="2" hits="0"/>'
            '<line number="3" hits="1"/>'
            '</lines></class>'
            '</classes></package></packages></coverage>'
        )
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "coverage.xml")
            Path(path).write_text(xml)
            cov = qg.parse_coverage(path, d)
        self.assertIn("src/m.py", cov)
        self.assertAlmostEqual(cov["src/m.py"], 2 / 3)

    def test_lcov(self):
        lcov = (
            "SF:src/m.py\n"
            "DA:1,1\nDA:2,0\nDA:3,4\n"
            "end_of_record\n"
        )
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "lcov.info")
            Path(path).write_text(lcov)
            cov = qg.parse_coverage(path, d)
        self.assertAlmostEqual(cov["src/m.py"], 2 / 3)

    def test_malformed_xml_yields_empty(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "coverage.xml")
            Path(path).write_text("<not-closed>")
            self.assertEqual(qg.parse_coverage(path, d), {})

    def test_none_path_yields_empty(self):
        self.assertEqual(qg.parse_coverage(None, "."), {})


class TestFindCoverage(unittest.TestCase):
    def test_explicit_path_when_exists(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "cov.xml")
            Path(p).write_text("x")
            self.assertEqual(qg.find_coverage(p, d), p)

    def test_explicit_missing_returns_none(self):
        self.assertIsNone(qg.find_coverage("/nope/cov.xml", "."))

    def test_probes_repo_root(self):
        with tempfile.TemporaryDirectory() as d:
            Path(os.path.join(d, "coverage.xml")).write_text("x")
            self.assertEqual(qg.find_coverage(None, d),
                             os.path.join(d, "coverage.xml"))

    def test_no_report_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(qg.find_coverage(None, d))


class TestCrapAssembly(unittest.TestCase):
    def test_crap_finding_emitted_with_coverage(self):
        func_m = [{"file": "m.py", "function": "foo",
                   "metrics": {"cyclomatic_complexity": 5},
                   "source": "builtin-heuristic"}]
        findings, skipped = [], []
        qg._append_crap_findings(func_m, 30, {"m.py": 0.0}, findings, skipped)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["metric"], "crap_score")
        self.assertAlmostEqual(findings[0]["value"], 30)  # comp^2 + comp at 0 cov

    def test_missing_file_coverage_noted_once(self):
        func_m = [
            {"file": "m.py", "function": "a",
             "metrics": {"cyclomatic_complexity": 3}, "source": "x"},
            {"file": "m.py", "function": "b",
             "metrics": {"cyclomatic_complexity": 4}, "source": "x"},
        ]
        findings, skipped = [], []
        qg._append_crap_findings(func_m, 30, {"other.py": 1.0}, findings,
                                 skipped)
        self.assertEqual(findings, [])
        crap_skips = [s for s in skipped if s.get("metric") == "crap_score"]
        self.assertEqual(len(crap_skips), 1)  # noted once for the file

    def test_coverage_for_matches_by_basename(self):
        cov = {"deep/nested/m.py": 0.5}
        self.assertEqual(qg._coverage_for("other/m.py", cov), 0.5)


# --------------------------------------------------------------------------
# Threshold evaluation + custom gates
# --------------------------------------------------------------------------

class TestEvaluate(unittest.TestCase):
    def _func(self, **metrics):
        return {"file": "m.py", "function": "foo", "metrics": metrics,
                "source": "builtin-heuristic"}

    def test_pass_and_fail_findings(self):
        fm = [self._func(cyclomatic_complexity=5, method_lines=200)]
        findings, _ = qg.evaluate(fm, [], qg.DEFAULT_THRESHOLDS, {}, False)
        by_metric = {f["metric"]: f for f in findings}
        self.assertTrue(by_metric["cyclomatic_complexity"]["pass"])   # 5 <= 10
        self.assertFalse(by_metric["method_lines"]["pass"])           # 200 > 50

    def test_crap_skipped_when_no_coverage(self):
        fm = [self._func(cyclomatic_complexity=5)]
        _, skipped = qg.evaluate(fm, [], qg.DEFAULT_THRESHOLDS, {}, False)
        self.assertTrue(any(s.get("metric") == "crap_score"
                            and s["reason"] == "no coverage report"
                            for s in skipped))

    def test_class_lines_evaluated(self):
        cm = [{"file": "m.py", "class_lines": 400,
               "source": "builtin-heuristic"}]
        findings, _ = qg.evaluate([], cm, qg.DEFAULT_THRESHOLDS, {}, False)
        cl = next(f for f in findings if f["metric"] == "class_lines")
        self.assertFalse(cl["pass"])   # 400 > 300
        self.assertIsNone(cl["function"])

    def test_missing_cognitive_metric_noted_once(self):
        # a backend-only function that never got a cognitive value
        fm = [{"file": "m.py", "function": "a",
               "metrics": {"cyclomatic_complexity": 3}, "source": "lizard"},
              {"file": "m.py", "function": "b",
               "metrics": {"cyclomatic_complexity": 4}, "source": "lizard"}]
        _, skipped = qg.evaluate(fm, [], qg.DEFAULT_THRESHOLDS, {}, False)
        cog = [s for s in skipped if s.get("metric") == "cognitive_complexity"]
        self.assertEqual(len(cog), 1)


class TestCustomGates(unittest.TestCase):
    def _func(self, **metrics):
        return {"file": "m.py", "function": "foo", "metrics": metrics,
                "source": "builtin-heuristic"}

    def test_metric_form_evaluated_here(self):
        fm = [self._func(cyclomatic_complexity=12)]
        gates = [{"name": "tight-cc", "metric": "cyclomatic_complexity",
                  "threshold": 8}]
        findings, skipped = qg.evaluate_custom_gates(gates, fm, [])
        self.assertEqual(len(findings), 1)
        self.assertFalse(findings[0]["pass"])   # 12 > 8
        self.assertEqual(findings[0]["gate"], "tight-cc")

    def test_command_form_deferred_to_skill(self):
        gates = [{"name": "no-todos", "command": "! grep -r TODO",
                  "pass_when": "exit 0"}]
        findings, skipped = qg.evaluate_custom_gates(gates, [], [])
        self.assertEqual(findings, [])
        self.assertEqual(len(skipped), 1)
        self.assertIn("command-form", skipped[0]["reason"])
        self.assertEqual(skipped[0]["gate"], "no-todos")

    def test_metric_not_measured_is_skipped(self):
        gates = [{"name": "g", "metric": "halstead", "threshold": 1}]
        findings, skipped = qg.evaluate_custom_gates(gates, [], [])
        self.assertEqual(findings, [])
        self.assertIn("not measured", skipped[0]["reason"])

    def test_malformed_gate_skipped(self):
        gates = [{"name": "g"}]  # neither command nor metric+threshold
        findings, skipped = qg.evaluate_custom_gates(gates, [], [])
        self.assertEqual(findings, [])
        self.assertIn("malformed", skipped[0]["reason"])


# --------------------------------------------------------------------------
# Report shape
# --------------------------------------------------------------------------

class TestBuildReport(unittest.TestCase):
    def test_pass_when_all_findings_pass(self):
        findings = [qg._finding("m.py", "f", "cyclomatic_complexity", 3, 10,
                                "builtin-heuristic")]
        report = qg.build_report("BASE", "HEAD", "defaults",
                                 ["builtin-heuristic"], findings, [])
        self.assertTrue(report["summary"]["pass"])
        self.assertEqual(report["summary"]["failures"], [])
        self.assertEqual(report["version"], 1)
        self.assertEqual(report["base"], "BASE")

    def test_fail_lists_failures(self):
        findings = [
            qg._finding("m.py", "f", "method_lines", 90, 50, "lizard"),
            qg._finding("m.py", "f", "cyclomatic_complexity", 3, 10, "lizard"),
        ]
        report = qg.build_report("B", "H", "loaded", ["lizard"], findings, [])
        self.assertFalse(report["summary"]["pass"])
        self.assertEqual(len(report["summary"]["failures"]), 1)
        self.assertEqual(report["summary"]["failures"][0]["metric"],
                         "method_lines")


# --------------------------------------------------------------------------
# main() / run_gate — exit codes, disabled gate (git mocked or real)
# --------------------------------------------------------------------------

class TestMainDisabledGate(unittest.TestCase):
    def test_disabled_gate_short_circuits_exit_zero(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump({"enabled": False}, fh)
            path = fh.name
        self.addCleanup(os.unlink, path)
        with mock.patch("sys.stdout") as out:
            rc = qg.main(["--config", path, "--base", "HEAD~1"])
        self.assertEqual(rc, 0)
        printed = "".join(c.args[0] for c in out.write.call_args_list if c.args)
        self.assertIn("gate disabled", printed)

    def test_git_failure_exits_two(self):
        with mock.patch("quality_gate.git_changed_ranges",
                        side_effect=qg.GateError("bad ref")), \
             mock.patch("sys.stderr"):
            rc = qg.main(["--base", "nope"])
        self.assertEqual(rc, 2)


class TestRunGateExitCodes(unittest.TestCase):
    """Drive run_gate with git + backends mocked so a failing metric yields the
    report (main maps it to exit 1) and a clean one yields pass."""

    def _args(self, **over):
        ns = mock.Mock()
        ns.config = None
        ns.base = "BASE"
        ns.head = "HEAD"
        ns.repo_dir = "."
        ns.coverage = None
        for k, v in over.items():
            setattr(ns, k, v)
        return ns

    def test_failing_metric_makes_main_return_one(self):
        # One changed file whose sole function is far over method_lines.
        long_body = "def big():\n" + "\n".join(
            f"    x{i} = {i}" for i in range(60))
        with tempfile.TemporaryDirectory() as d:
            Path(os.path.join(d, "big.py")).write_text(long_body + "\n")
            with mock.patch("quality_gate.git_changed_ranges",
                            return_value={"big.py": [(1, 61)]}), \
                 mock.patch("quality_gate._lizard_available",
                            return_value=False), \
                 mock.patch("quality_gate._radon_available",
                            return_value=False), \
                 mock.patch("sys.stdout"):
                rc = qg.main(["--base", "BASE", "--repo-dir", d])
        self.assertEqual(rc, 1)

    def test_clean_change_returns_zero(self):
        with tempfile.TemporaryDirectory() as d:
            Path(os.path.join(d, "ok.py")).write_text(
                "def tiny(a):\n    return a\n")
            with mock.patch("quality_gate.git_changed_ranges",
                            return_value={"ok.py": [(1, 2)]}), \
                 mock.patch("quality_gate._lizard_available",
                            return_value=False), \
                 mock.patch("quality_gate._radon_available",
                            return_value=False), \
                 mock.patch("sys.stdout"):
                rc = qg.main(["--base", "BASE", "--repo-dir", d])
        self.assertEqual(rc, 0)


class TestEndToEndRealGit(unittest.TestCase):
    """Exercises the full git -> parse_diff -> builtin measure -> report path
    against a REAL throwaway repo (no git mock), so the diff-parsing and
    changed-range intersection are validated end-to-end."""

    def _git(self, *args):
        subprocess.run(["git", *args], cwd=self._tmp, check=True,
                       capture_output=True, text=True)

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="quality_gate_realgit_")
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        self._git("init", "-q")
        self._git("config", "user.email", "t@example.com")
        self._git("config", "user.name", "Test")
        Path(self._tmp, "m.py").write_text("def a():\n    return 1\n")
        self._git("add", "m.py")
        self._git("commit", "-q", "-m", "base")
        # Add an over-complex function in the second commit.
        Path(self._tmp, "m.py").write_text(
            "def a():\n    return 1\n\n"
            "def b(p, q, r, s, t):\n"
            "    if p:\n"
            "        if q:\n"
            "            if r:\n"
            "                if s:\n"
            "                    return t\n"
            "    return 0\n"
        )
        self._git("commit", "-q", "-am", "add b")

    def test_reports_changed_function_over_thresholds(self):
        with mock.patch("sys.stdout") as out:
            rc = qg.main(["--base", "HEAD~1", "--repo-dir", self._tmp])
        printed = "".join(c.args[0] for c in out.write.call_args_list if c.args)
        report = json.loads(printed)
        funcs = {f["function"] for f in report["findings"]}
        self.assertIn("b", funcs)          # the changed function is measured
        self.assertNotIn("a", funcs)       # the unchanged function is not
        # parameter_count 5 > 4 and nesting_depth 4 > 3 -> failures -> exit 1
        self.assertEqual(rc, 1)
        self.assertFalse(report["summary"]["pass"])
        self.assertTrue(report["summary"]["failures"])


if __name__ == "__main__":
    unittest.main()
