"""Unit tests for measure_coverage.py's pure logic.

Covers executable-line detection, path-key normalization, OMIT-manifest
parsing, OMIT application, and the threshold pass/fail decision — the parts
that decide whether the coverage gate is honest. The trace-driven suite
runner (I/O shell) is exercised end-to-end by running the tool in CI.

The corrected run-under-trace seam is exercised end-to-end in ``TracedRunTests``
by invoking the real tool in a clean subprocess (never in-process — see that
class's docstring for why).

Usage: python3 -m unittest scripts.test_measure_coverage
       (or) python3 scripts/test_measure_coverage.py
"""
import json
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

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


class ValidateOmitTests(unittest.TestCase):
    def test_omit_of_real_executable_lines_within_cap_is_ok(self):
        target = mc.FileLines("scripts/x.py", set(range(1, 21)), line_count=40)
        # 4 lines = 20% <= 25% cap
        mc.validate_omit(target, {1, 2, 3, 4})

    def test_range_spanning_non_executable_lines_is_ok(self):
        # A range like a __main__ shim (551-552) legitimately covers a mix of
        # executable and non-executable lines; the non-executable ones are no-ops.
        # 551 is executable, 552 is not; only 1 of 100 executable lines is omitted.
        target = mc.FileLines("scripts/x.py", set(range(1, 100)) | {551}, 560)
        mc.validate_omit(target, {551, 552})

    def test_omit_past_end_of_file_raises(self):
        target = mc.FileLines("scripts/x.py", {1, 2, 3}, line_count=10)
        with self.assertRaises(ValueError):
            mc.validate_omit(target, {99})

    def test_omit_exceeding_executable_fraction_cap_raises(self):
        # 6 of 10 executable lines omitted = 60% > 25% cap
        target = mc.FileLines("scripts/x.py", set(range(1, 11)), line_count=20)
        with self.assertRaises(ValueError):
            mc.validate_omit(target, set(range(1, 7)))

    def test_empty_omit_is_noop(self):
        target = mc.FileLines("scripts/x.py", {1, 2, 3}, line_count=10)
        mc.validate_omit(target, set())


# One shared subprocess run of the real tool, reused across the seam assertions.
# Run in a CLEAN interpreter (never in-process): the corrected seam re-imports the
# targets to trace their import-time lines, and doing that inside the running suite
# would swap sys.modules out from under sibling test modules that already bound the
# target via `import <target> as ...` (the exact 310->12 identity split we guard
# against). A subprocess is also precisely how CI invokes the tool.
_SEAM_RESULT: dict | None = None


def _run_tool_with_probe() -> dict:
    """Run measure_coverage.py in a subprocess with a one-shot probe attached.

    The probe (COVPROBE=1) makes the tool, after its real run under trace, emit a
    single machine-readable JSON line reporting whether the suite passed, how many
    tests ran, whether the release.py import-time-only line was counted, and whether
    module identity held — without changing the tool's normal behavior or output.
    """
    global _SEAM_RESULT
    if _SEAM_RESULT is not None:
        return _SEAM_RESULT
    scripts_dir = Path(mc.__file__).resolve().parent
    env = {**os.environ, "COVPROBE": "1"}
    proc = subprocess.run(
        [sys.executable, str(scripts_dir / "measure_coverage.py")],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(scripts_dir.parent),
    )
    probe_line = next(
        (ln for ln in proc.stdout.splitlines() if ln.startswith("COVPROBE ")),
        None,
    )
    assert probe_line is not None, (
        "tool did not emit COVPROBE line; stdout tail:\n"
        + "\n".join(proc.stdout.splitlines()[-5:])
        + "\nstderr tail:\n"
        + "\n".join(proc.stderr.splitlines()[-5:])
    )
    _SEAM_RESULT = {
        "returncode": proc.returncode,
        "probe": json.loads(probe_line[len("COVPROBE "):]),
        "stdout": proc.stdout,
    }
    return _SEAM_RESULT


class TracedRunTests(unittest.TestCase):
    """Cover the run-under-trace seam: the corrected tool must re-import the
    targets AND discover the suite INSIDE the tracer, in that order, so import-
    time-only lines get counted and every test module binds to the same traced
    module object each ``mock.patch`` targets.

    Runs the real tool once in a clean subprocess (see ``_run_tool_with_probe``)
    and asserts against its one-shot probe — the ordering these lock in is exactly
    what a prior regression broke (310 -> 12 tests when the suite was discovered
    against a stale module identity).

    Recursion guard: the tool runs THIS suite under trace, so these tests are also
    discovered inside the tool's own run. When that happens (mc.ACTIVE_ENV set) we
    skip — otherwise each would spawn another tool subprocess and fork-bomb. The
    real assertions run only in the ordinary top-level ``unittest`` invocation.
    """

    def setUp(self):
        if os.environ.get(mc.ACTIVE_ENV) == "1":
            self.skipTest("inside a measure_coverage run; seam asserted at top level")

    def test_suite_still_green_and_meets_min_tests(self):
        r = _run_tool_with_probe()
        self.assertTrue(
            r["probe"]["passed"], "suite must run green under the corrected seam"
        )
        self.assertGreaterEqual(
            r["probe"]["tests_run"],
            mc.MIN_TESTS,
            "corrected seam must still discover the full suite, not collapse it",
        )

    def test_import_time_only_line_is_now_counted(self):
        # release.py line 39 (PLUGIN_MANIFEST = "...") is a module-level constant:
        # executable, but only ever runs at import. The old import-before-trace
        # tool left it in the denominator yet never the numerator. The corrected
        # tool re-imports under trace, so it must now be COUNTED as executed.
        r = _run_tool_with_probe()
        self.assertIn(
            39,
            r["probe"]["release_executed"],
            "import-time-only constant must be counted by the corrected tool",
        )

    def test_module_identity_holds_after_corrected_run(self):
        # test_pr_resolver does `import pr_resolver as pr` and patches against `pr`.
        # If discovery ran against a stale/duplicate identity, patches would miss.
        # The probe reports whether sys.modules['pr_resolver'] IS the object the
        # discovered test module bound.
        r = _run_tool_with_probe()
        self.assertTrue(
            r["probe"]["identity_holds"],
            "discovered test module must bind the same traced target object",
        )


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
