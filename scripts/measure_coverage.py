#!/usr/bin/env python3
"""Deterministic, stdlib-only line-coverage gate for scripts/*.py.

Runs the project's unittest suite in-process under the standard-library
``trace`` module, computes per-file executed-vs-executable line ratios (with an
audited OMIT manifest subtracted), prints a report, and exits non-zero if any
per-file floor or the total floor is breached.

Design notes
------------
* STDLIB ONLY. Uses ``trace`` for executed lines and ``code.co_lines()`` (via
  ``compile``) for the executable-line denominator — bytecode-derived truth,
  not a regex heuristic. No coverage.py / pytest / third-party.
* DETERMINISTIC. Floors are fixed integers (percentages) set BELOW the measured
  coverable maxima by a >=5-point margin (see PER_FILE_FLOORS), so a minor
  executable-set drift between the local interpreter and CI's python 3.12 cannot
  make a floor unreachable and wedge CI with a false red.
* The tool measures the product modules only; ``measure_coverage.py`` itself and
  the ``test_*.py`` files are excluded from the MEASURED set — the tool's own
  logic is covered by ``scripts/test_measure_coverage.py``.

Coverage semantics: this gate measures RUNTIME line coverage with CORRECTED
attribution. Inside ``tracer.runfunc`` it first re-imports the target modules
(replacing them in ``sys.modules``) and only THEN discovers and runs the suite —
so lines that execute only at import time (module-level constants, ``import``
statements, ``def``/``class`` header lines, decorators) run under the tracer and
ARE counted, while the discovered test modules still bind and ``mock.patch`` the
same freshly-traced module objects (single module identity — the ordering is
load-bearing; discovering before the re-import splits identity and breaks the
patches). A module's percentage therefore reflects lines the suite actually
reaches, and a fully-exercised module reads at ~100%. The only lines that remain
uncounted are ones that genuinely never run under a unit test — the
``if __name__ == "__main__"`` process-entry shims and the blocking
``serve_forever()`` daemon tail — which the audited OMIT manifest removes from both
numerator and denominator (it may not zero out a file; see ``validate_omit``).

Anti-false-green guards: the gate refuses to report coverage unless the suite
actually ran a plausible number of tests (``MIN_TESTS``), and the OMIT manifest
cannot zero out a file — omitted lines must be real executable lines and OMIT may
not remove more than ``MAX_OMIT_FRACTION`` of a file's executable lines.

Usage: python3 scripts/measure_coverage.py
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import trace
import unittest
from dataclasses import dataclass, field
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
OMIT_FILE = SCRIPTS_DIR / "coverage_omit.txt"

# Recursion guard. This tool runs the whole scripts/test_*.py suite under trace —
# which includes test_measure_coverage's seam test, and that test invokes this tool
# in a subprocess. Without a guard the subprocess would run the suite again → fork
# bomb. We set this env var while the traced suite runs so the seam test detects it
# is *inside* a tool run and skips spawning another one.
ACTIVE_ENV = "MEASURE_COVERAGE_ACTIVE"

# Anti-false-green: the suite must run at least this many tests or the gate
# refuses to report (an empty/collapsed discovery makes wasSuccessful() True).
# Set well below the current 313-test suite so ordinary test churn doesn't trip
# it, but a wholesale discovery collapse (the 313->12 identity-split regression,
# or an empty discovery) does.
MIN_TESTS = 150

# Anti-false-green: OMIT may not remove more than this fraction of any one
# file's executable lines — a runaway range can't collapse a file to 0/0=100%.
MAX_OMIT_FRACTION = 0.25

# Product modules that count toward coverage (basename -> relpath key).
TARGET_FILES = (
    "scripts/dashboard_launcher.py",
    "scripts/dashboard_server.py",
    "scripts/pr_resolver.py",
    "scripts/release.py",
    "scripts/validate_marketplace.py",
)

# Importable module names for the targets (``scripts/release.py`` -> ``release``),
# used to re-import them fresh under trace so their import-time-only lines count.
TARGET_MODULES = tuple(Path(t).stem for t in TARGET_FILES)

# Per-file and total floors (integer percent). A file must not be able to hide
# behind the total, so both gates apply.
#
# Baseline measured on 2026-07-01 with THIS tool (corrected seam: targets re-
# imported AND the suite discovered INSIDE the tracer, re-import first) on the
# 313-test suite, minus the OMIT manifest — the true coverable maxima:
#   launcher 100.0% (239/239), server 100.0% (369/369), pr_resolver 100.0%
#   (274/274), release 100.0% (125/125), validate_marketplace 100.0% (207/207);
#   TOTAL 100.0% (1214/1214).
#
# MARGIN RATIONALE (≥5 percentage points, rounded DOWN). Those maxima are from a
# LOCAL interpreter; CI runs python 3.12, and co_lines() attribution can drift
# across versions on decorators, multi-line calls, and match statements. No py3.12
# is available locally to validate, so every floor is set conservatively below the
# coverable-max — never at it — so a minor executable-set drift cannot wedge CI
# with a false red. pr_resolver additionally carries a documented py3.12 preview of
# ~85.4% (roughly 40 lines that go unhit on 3.12 but are hit locally); its floor is
# set from THAT lower figure minus the margin (a real, healthy floor — not a bug,
# and not chased in this slice), not from the optimistic local 100%. The TOTAL floor
# likewise sits well under the py3.12 aggregate that pr_resolver drags down.
PER_FILE_FLOORS = {
    "scripts/dashboard_launcher.py": 95,   # local 100% - 5
    "scripts/dashboard_server.py": 95,     # local 100% - 5
    "scripts/pr_resolver.py": 80,          # py3.12 preview 85.4% - 5 (not local 100%)
    "scripts/release.py": 95,              # local 100% - 5
    "scripts/validate_marketplace.py": 94, # local 100% - ~6 (extra head-room)
}
TOTAL_FLOOR = 90  # py3.12 aggregate ~96-97% (pr_resolver-dragged) - margin


@dataclass
class FileStat:
    executed: int
    executable: int

    @property
    def pct(self) -> float:
        if self.executable == 0:
            return 100.0
        return 100.0 * self.executed / self.executable


@dataclass
class GateResult:
    passed: bool
    breaches: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Pure helpers (unit-tested in test_measure_coverage.py)
# --------------------------------------------------------------------------- #
def executable_lines(source: str, filename: str) -> set[int]:
    """Return the set of source lines the interpreter can land on.

    Compiles the source and walks every nested code object via ``co_consts``,
    unioning each object's ``co_lines()`` line numbers. Synthetic entries
    (``None`` and the module-prologue ``lineno == 0`` that ``co_lines()`` emits)
    are dropped so the denominator is real, version-stable source lines only.
    """
    top = compile(source, filename, "exec")
    lines: set[int] = set()
    stack = [top]
    while stack:
        code = stack.pop()
        for _start, _end, lineno in code.co_lines():
            if lineno is not None and lineno >= 1:
                lines.add(lineno)
        for const in code.co_consts:
            if hasattr(const, "co_lines"):
                stack.append(const)
    return lines


def normalize_key(path: str) -> str | None:
    """Map any path trace reports to a repo-relative ``scripts/<name>.py`` key.

    Returns ``None`` for paths outside ``scripts/`` (stdlib, site-packages),
    which the caller ignores.
    """
    p = Path(path)
    parts = p.parts
    if "scripts" in parts:
        idx = len(parts) - 1 - parts[::-1].index("scripts")
        rel = Path(*parts[idx:])
        return rel.as_posix()
    return None


def _parse_line_range(line_range: str, raw: str) -> tuple[int, int]:
    """Parse ``START`` or ``START-END`` into an inclusive (start, end) pair."""
    try:
        if "-" in line_range:
            start_s, end_s = line_range.split("-", 1)
            start, end = int(start_s), int(end_s)
        else:
            start = end = int(line_range)
    except ValueError as exc:
        raise ValueError(f"malformed OMIT line range: {raw!r}") from exc
    if start < 1 or end < start:
        raise ValueError(f"invalid OMIT line range: {raw!r}")
    return start, end


def _parse_omit_line(raw: str) -> tuple[str, range] | None:
    """Parse one manifest line into ``(relpath, line_range)``, or None to skip.

    Raises ``ValueError`` on a malformed entry or one missing a rationale.
    """
    stripped = raw.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if "#" not in raw:
        raise ValueError(f"OMIT entry missing '# rationale': {raw!r}")
    spec, rationale = raw.split("#", 1)
    if not rationale.strip():
        raise ValueError(f"OMIT entry has empty rationale: {raw!r}")
    spec = spec.strip()
    if ":" not in spec:
        raise ValueError(f"malformed OMIT entry (expected path:range): {raw!r}")
    relpath, line_range = spec.rsplit(":", 1)
    start, end = _parse_line_range(line_range, raw)
    return relpath.strip(), range(start, end + 1)


def parse_omit(text: str) -> dict[str, set[int]]:
    """Parse the OMIT manifest into ``{relpath: {lineno, ...}}``.

    Each data line must be ``scripts/<file>.py:START[-END]  # rationale``.
    Blank lines and full-line ``#`` comments are ignored. A malformed entry, or
    one missing a rationale, raises ``ValueError`` — the manifest must stay
    auditable and cannot silently grow into a place to hide untested code.
    """
    result: dict[str, set[int]] = {}
    for raw in text.splitlines():
        parsed = _parse_omit_line(raw)
        if parsed is None:
            continue
        relpath, lines = parsed
        result.setdefault(relpath, set()).update(lines)
    return result


def apply_omit(
    executable: set[int], executed: set[int], omit: set[int]
) -> tuple[set[int], set[int]]:
    """Remove omitted lines from both the executable and executed sets."""
    return executable - omit, executed - omit


@dataclass
class FileLines:
    """The line facts about one target file that ``validate_omit`` checks against."""
    relpath: str
    executable: set[int]
    line_count: int


def validate_omit(target: FileLines, omit: set[int]) -> None:
    """Guard the OMIT manifest against range typos that would zero out a file.

    A manifest entry may legitimately be a *range* that spans a mix of executable
    and non-executable lines (e.g. a ``__main__`` shim or a ``try/finally`` tail);
    subtracting the non-executable ones is a harmless no-op. What must fail loudly
    is (a) a range that OVERSHOOTS the file (names a line number past end-of-file —
    a stale/fat-fingered range), or (b) an OMIT that removes more than
    ``MAX_OMIT_FRACTION`` of the file's *executable* lines — either can silently
    turn a real coverage regression into a 0/0 = 100% pass.
    """
    if not omit:
        return
    overshoot = {ln for ln in omit if ln > target.line_count}
    if overshoot:
        raise ValueError(
            f"OMIT for {target.relpath} names line(s) {sorted(overshoot)} past "
            f"end-of-file ({target.line_count} lines) — stale or overshooting range?"
        )
    executable = target.executable
    omitted_executable = omit & executable
    if executable and len(omitted_executable) > MAX_OMIT_FRACTION * len(executable):
        raise ValueError(
            f"OMIT for {target.relpath} removes {len(omitted_executable)}/"
            f"{len(executable)} executable lines (> {MAX_OMIT_FRACTION:.0%}) — "
            "refusing to let OMIT collapse a file."
        )


def evaluate(
    per_file: dict[str, FileStat],
    floors: dict[str, int],
    total_floor: int,
) -> GateResult:
    """Compare per-file and total coverage to their floors.

    Fails if any file is below its per-file floor or the aggregate is below the
    total floor. Files with zero executable lines (all OMITted) count as full.
    """
    breaches: list[str] = []
    for relpath, stat in per_file.items():
        floor = floors.get(relpath, 0)
        if stat.pct + 1e-9 < floor:
            breaches.append(
                f"{relpath}: {stat.pct:.1f}% < floor {floor}% "
                f"({stat.executed}/{stat.executable})"
            )
    total = FileStat(
        executed=sum(s.executed for s in per_file.values()),
        executable=sum(s.executable for s in per_file.values()),
    )
    if total.pct + 1e-9 < total_floor:
        breaches.append(
            f"TOTAL: {total.pct:.1f}% < floor {total_floor}% "
            f"({total.executed}/{total.executable})"
        )
    return GateResult(passed=not breaches, breaches=breaches)


# --------------------------------------------------------------------------- #
# I/O shell: run the suite under trace, build stats, report, exit
# --------------------------------------------------------------------------- #
def _reimport_targets() -> None:
    """Re-import each target module fresh so its import-time lines run under trace.

    ``sys.modules`` is likely already populated (importing this tool or discovering
    tests can pull the targets in); popping and re-importing forces the module-level
    body — constants, ``import``/``def``/``class`` headers, decorators — to execute
    again, this time while the tracer is counting. Critically this must run BEFORE
    ``discover()`` so each test module's own ``import <target> as ...`` binds to the
    freshly-traced object left in ``sys.modules`` (single module identity), keeping
    every ``mock.patch`` site aimed at the object the suite actually exercises.
    """
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    for name in TARGET_MODULES:
        sys.modules.pop(name, None)
        importlib.import_module(name)


def _discover_suite() -> unittest.TestSuite:
    """Discover the same suite CI runs: scripts/test_*.py."""
    return unittest.TestLoader().discover(
        str(SCRIPTS_DIR), pattern="test_*.py", top_level_dir=str(SCRIPTS_DIR)
    )


def _run_under_trace() -> tuple[bool, int, dict]:
    """Run the suite under trace.Trace; return (suite_passed, tests_run, counts).

    The load-bearing ordering happens INSIDE ``tracer.runfunc``: (1) re-import the
    targets fresh, then (2) discover the suite, then (3) run it. Doing the re-import
    and discovery both under trace — re-import first — means the traced module
    objects are the same ones the discovered test modules bind and patch, so
    import-time lines are counted without splitting module identity.

    If any step raises (e.g. a test crashes the interpreter under trace), the
    original exception propagates rather than surfacing as a confusing KeyError —
    a suite that could not run must fail loudly, never pass.
    """
    tracer = trace.Trace(count=1, trace=0)
    runner = unittest.TextTestRunner(stream=sys.stderr, verbosity=1)
    result_holder: dict[str, unittest.TestResult] = {}

    def _run() -> None:
        _reimport_targets()
        suite = _discover_suite()
        result_holder["result"] = runner.run(suite)

    prior = os.environ.get(ACTIVE_ENV)
    os.environ[ACTIVE_ENV] = "1"
    try:
        tracer.runfunc(_run)
    finally:
        if prior is None:
            os.environ.pop(ACTIVE_ENV, None)
        else:
            os.environ[ACTIVE_ENV] = prior
    results = tracer.results()
    result = result_holder["result"]
    return result.wasSuccessful(), result.testsRun, results.counts


def _build_stats(counts: dict) -> dict[str, FileStat]:
    """Turn trace counts + source into per-target FileStat, minus OMIT."""
    omit = parse_omit(OMIT_FILE.read_text())

    # Executed lines per target relpath.
    executed: dict[str, set[int]] = {t: set() for t in TARGET_FILES}
    for (abs_path, lineno), hits in counts.items():
        key = normalize_key(abs_path)
        if key in executed and hits > 0 and lineno >= 1:
            executed[key].add(lineno)

    stats: dict[str, FileStat] = {}
    for relpath in TARGET_FILES:
        source = (SCRIPTS_DIR.parent / relpath).read_text()
        executable = executable_lines(source, relpath)
        run = executed[relpath] & executable
        file_omit = omit.get(relpath, set())
        validate_omit(
            FileLines(relpath, executable, source.count("\n") + 1), file_omit
        )
        executable, run = apply_omit(executable, run, file_omit)
        stats[relpath] = FileStat(executed=len(run), executable=len(executable))
    return stats


def _print_report(stats: dict[str, FileStat], result: GateResult) -> None:
    print("coverage report (stdlib trace; scripts/*.py minus OMIT manifest)")
    print(f"  {'file':40s} {'cov':>7s} {'run/able':>12s} {'floor':>6s}")
    for relpath, stat in sorted(stats.items()):
        floor = PER_FILE_FLOORS.get(relpath, 0)
        print(
            f"  {relpath:40s} {stat.pct:6.1f}% "
            f"{stat.executed:5d}/{stat.executable:<6d} {floor:5d}%"
        )
    total = FileStat(
        executed=sum(s.executed for s in stats.values()),
        executable=sum(s.executable for s in stats.values()),
    )
    print(
        f"  {'TOTAL':40s} {total.pct:6.1f}% "
        f"{total.executed:5d}/{total.executable:<6d} {TOTAL_FLOOR:5d}%"
    )
    if result.passed:
        print("PASS: all per-file and total floors met.")
    else:
        print("FAIL: coverage floors breached:")
        for b in result.breaches:
            print(f"  - {b}")


def _emit_probe(suite_passed: bool, tests_run: int, counts: dict) -> None:
    """Emit a one-shot machine-readable line for the seam test (COVPROBE=1 only).

    Reports whether the corrected seam kept the suite green, how many tests ran,
    which ``release.py`` lines were counted (so a caller can confirm an import-time-
    only line is now attributed), and whether module identity held — i.e. the
    discovered ``test_pr_resolver`` bound the very object left in ``sys.modules`` by
    the under-trace re-import. Purely observational; no effect on the gate result.
    """
    release_executed = sorted(
        lineno
        for (abs_path, lineno), hits in counts.items()
        if normalize_key(abs_path) == "scripts/release.py" and hits > 0 and lineno >= 1
    )
    pr_mod = sys.modules.get("pr_resolver")
    test_mod = sys.modules.get("test_pr_resolver")
    identity_holds = bool(
        pr_mod is not None
        and test_mod is not None
        and getattr(test_mod, "pr", None) is pr_mod
    )
    payload = {
        "passed": suite_passed,
        "tests_run": tests_run,
        "release_executed": release_executed,
        "identity_holds": identity_holds,
    }
    print("COVPROBE " + json.dumps(payload))


def main() -> int:
    suite_passed, tests_run, counts = _run_under_trace()
    if os.environ.get("COVPROBE") == "1":
        _emit_probe(suite_passed, tests_run, counts)
    if not suite_passed:
        print("FAIL: unittest suite did not pass — coverage not measured.",
              file=sys.stderr)
        return 1
    # Anti-false-green: an empty/collapsed discovery yields wasSuccessful()==True
    # over 0 tests. Refuse to measure coverage against a suite that barely ran.
    if tests_run < MIN_TESTS:
        print(f"FAIL: only {tests_run} tests ran (expected >= {MIN_TESTS}); "
              "test discovery may have collapsed — coverage not measured.",
              file=sys.stderr)
        return 1
    stats = _build_stats(counts)
    result = evaluate(stats, PER_FILE_FLOORS, TOTAL_FLOOR)
    print(f"suite: {tests_run} tests passed")
    _print_report(stats, result)
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
