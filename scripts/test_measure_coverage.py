"""Unit tests for measure_coverage.py's pure logic.

Covers executable-line detection, path-key normalization, OMIT-manifest
parsing, OMIT application, and the threshold pass/fail decision — the parts
that decide whether the coverage gate is honest. The trace-driven suite
runner (I/O shell) is exercised end-to-end by running the tool in CI.

Usage: python3 -m unittest scripts.test_measure_coverage
       (or) python3 scripts/test_measure_coverage.py
"""
import os
import textwrap
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure_coverage as mc  # noqa: E402


class ExecutableLinesTests(unittest.TestCase):
    def test_returns_landable_lines_for_simple_snippet(self):
        src = textwrap.dedent(
            """\
            x = 1
            y = 2
            def f():
                return x + y
            """
        )
        lines = mc.executable_lines(src, "synthetic.py")
        # Every statement line is landable.
        self.assertIn(1, lines)
        self.assertIn(2, lines)
        self.assertIn(3, lines)
        self.assertIn(4, lines)

    def test_never_includes_line_zero_or_negative(self):
        # co_lines() emits a synthetic lineno 0 for the module prologue.
        src = "a = 1\nb = 2\n"
        lines = mc.executable_lines(src, "synthetic.py")
        self.assertNotIn(0, lines)
        self.assertFalse(any(n < 1 for n in lines))

    def test_includes_nested_function_body_lines(self):
        src = textwrap.dedent(
            """\
            def outer():
                def inner():
                    return 42
                return inner()
            """
        )
        lines = mc.executable_lines(src, "synthetic.py")
        self.assertIn(3, lines)  # the nested return, only reachable via co_consts walk


class NormalizeKeyTests(unittest.TestCase):
    def test_absolute_path_maps_to_scripts_relpath(self):
        abs_path = "/anywhere/on/disk/repo/scripts/dashboard_server.py"
        self.assertEqual(mc.normalize_key(abs_path), "scripts/dashboard_server.py")

    def test_already_relative_scripts_path_is_stable(self):
        self.assertEqual(
            mc.normalize_key("scripts/release.py"), "scripts/release.py"
        )

    def test_non_scripts_path_returns_none(self):
        self.assertIsNone(mc.normalize_key("/usr/lib/python3.12/trace.py"))


class ParseOmitTests(unittest.TestCase):
    def test_parses_single_line_and_range_with_rationale(self):
        text = textwrap.dedent(
            """\
            # a comment
            scripts/release.py:194-195   # main shim
            scripts/pr_resolver.py:488   # single line

            """
        )
        omit = mc.parse_omit(text)
        self.assertEqual(omit["scripts/release.py"], {194, 195})
        self.assertEqual(omit["scripts/pr_resolver.py"], {488})

    def test_ignores_comments_and_blank_lines(self):
        text = "# only comments\n\n   \n"
        self.assertEqual(mc.parse_omit(text), {})

    def test_raises_on_entry_missing_rationale(self):
        with self.assertRaises(ValueError):
            mc.parse_omit("scripts/release.py:194-195\n")

    def test_raises_on_malformed_entry(self):
        with self.assertRaises(ValueError):
            mc.parse_omit("this is not a valid entry  # rationale\n")


class ApplyOmitTests(unittest.TestCase):
    def test_subtracts_omitted_lines_from_both_sets(self):
        executable = {1, 2, 3, 4, 5}
        executed = {1, 2, 3}
        omit = {5, 4}
        new_exec, new_run = mc.apply_omit(executable, executed, omit)
        self.assertEqual(new_exec, {1, 2, 3})
        self.assertEqual(new_run, {1, 2, 3})

    def test_omitting_an_executed_line_removes_it_from_numerator(self):
        executable = {1, 2, 3}
        executed = {1, 2, 3}
        new_exec, new_run = mc.apply_omit(executable, executed, {2})
        self.assertEqual(new_exec, {1, 3})
        self.assertEqual(new_run, {1, 3})


class EvaluateTests(unittest.TestCase):
    def _stats(self, executed, executable):
        return mc.FileStat(executed=executed, executable=executable)

    def test_all_floors_met_passes(self):
        per_file = {
            "scripts/a.py": self._stats(9, 10),   # 90%
            "scripts/b.py": self._stats(7, 10),   # 70%
        }
        floors = {"scripts/a.py": 80, "scripts/b.py": 60}
        result = mc.evaluate(per_file, floors, total_floor=70)
        self.assertTrue(result.passed)
        self.assertEqual(result.breaches, [])

    def test_per_file_floor_breach_fails_even_if_total_ok(self):
        per_file = {
            "scripts/a.py": self._stats(10, 10),  # 100%
            "scripts/b.py": self._stats(1, 10),   # 10% — bare file
        }
        floors = {"scripts/a.py": 90, "scripts/b.py": 60}
        # total = 11/20 = 55%
        result = mc.evaluate(per_file, floors, total_floor=50)
        self.assertFalse(result.passed)
        self.assertTrue(any("scripts/b.py" in b for b in result.breaches))

    def test_total_floor_breach_fails(self):
        per_file = {"scripts/a.py": self._stats(5, 10)}  # 50%
        floors = {"scripts/a.py": 40}
        result = mc.evaluate(per_file, floors, total_floor=60)
        self.assertFalse(result.passed)
        self.assertTrue(any("TOTAL" in b for b in result.breaches))

    def test_file_with_zero_executable_lines_is_treated_as_full(self):
        # A file all of whose lines are OMITted must not divide by zero.
        per_file = {"scripts/a.py": self._stats(0, 0)}
        floors = {"scripts/a.py": 50}
        result = mc.evaluate(per_file, floors, total_floor=50)
        self.assertTrue(result.passed)


if __name__ == "__main__":
    unittest.main()
