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
* DETERMINISTIC. Floors are fixed integers (percentages) captured from a real
  baseline measurement and rounded DOWN for a safety margin, so a minor
  executable-set drift between the local interpreter and CI's python 3.12
  cannot make a floor unreachable and wedge CI with a false red.
* The tool measures the product modules only; ``measure_coverage.py`` itself and
  the ``test_*.py`` files are excluded from the MEASURED set — the tool's own
  logic is covered by ``scripts/test_measure_coverage.py``.

Usage: python3 scripts/measure_coverage.py
"""
from __future__ import annotations

import sys
import trace
import unittest
from dataclasses import dataclass, field
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
OMIT_FILE = SCRIPTS_DIR / "coverage_omit.txt"

# Product modules that count toward coverage (basename -> relpath key).
TARGET_FILES = (
    "scripts/dashboard_launcher.py",
    "scripts/dashboard_server.py",
    "scripts/pr_resolver.py",
    "scripts/release.py",
    "scripts/validate_marketplace.py",
)

# Per-file and total floors (integer percent), captured from a real baseline
# measurement and rounded DOWN for a py3.12-vs-local safety margin. A file must
# not be able to hide behind the total, so both gates apply.
# Baseline measured on 2026-07-01 with THIS tool (stdlib trace + co_lines()
# denominator) on the 188-test suite:
#   launcher 65.7% (157/239), server 45.0% (166/369), pr_resolver 80.7% (221/274),
#   release 0.0% (0/125), validate_marketplace 53.9% (111/206); TOTAL 54.0% (655/1213).
# Floors are these numbers rounded DOWN (~2-3 pts margin) so the gate stays green
# and deterministic on CI's python 3.12 despite any minor executable-set drift.
# (The 72.4% figure recorded at intake used a different, smaller denominator; this
# co_lines()-based denominator is larger and more honest, so the percentages differ.
# Later slices raise coverage and the final slice ratchets these floors up.)
PER_FILE_FLOORS = {
    "scripts/dashboard_launcher.py": 63,
    "scripts/dashboard_server.py": 42,
    "scripts/pr_resolver.py": 78,
    "scripts/release.py": 0,
    "scripts/validate_marketplace.py": 51,
}
TOTAL_FLOOR = 51


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


def parse_omit(text: str) -> dict[str, set[int]]:
    """Parse the OMIT manifest into ``{relpath: {lineno, ...}}``.

    Each data line must be ``scripts/<file>.py:START[-END]  # rationale``.
    Blank lines and full-line ``#`` comments are ignored. A malformed entry, or
    one missing a rationale, raises ``ValueError`` — the manifest must stay
    auditable and cannot silently grow into a place to hide untested code.
    """
    result: dict[str, set[int]] = {}
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "#" not in raw:
            raise ValueError(f"OMIT entry missing '# rationale': {raw!r}")
        spec, rationale = raw.split("#", 1)
        if not rationale.strip():
            raise ValueError(f"OMIT entry has empty rationale: {raw!r}")
        spec = spec.strip()
        if ":" not in spec:
            raise ValueError(f"malformed OMIT entry (expected path:range): {raw!r}")
        relpath, line_range = spec.rsplit(":", 1)
        relpath = relpath.strip()
        try:
            if "-" in line_range:
                start_s, end_s = line_range.split("-", 1)
                start, end = int(start_s), int(end_s)
            else:
                start = end = int(line_range)
        except ValueError:
            raise ValueError(f"malformed OMIT line range: {raw!r}")
        if start < 1 or end < start:
            raise ValueError(f"invalid OMIT line range: {raw!r}")
        result.setdefault(relpath, set()).update(range(start, end + 1))
    return result


def apply_omit(
    executable: set[int], executed: set[int], omit: set[int]
) -> tuple[set[int], set[int]]:
    """Remove omitted lines from both the executable and executed sets."""
    return executable - omit, executed - omit


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
    total_executed = 0
    total_executable = 0
    for relpath, stat in per_file.items():
        total_executed += stat.executed
        total_executable += stat.executable
        floor = floors.get(relpath, 0)
        if stat.pct + 1e-9 < floor:
            breaches.append(
                f"{relpath}: {stat.pct:.1f}% < floor {floor}% "
                f"({stat.executed}/{stat.executable})"
            )
    total_pct = 100.0 if total_executable == 0 else 100.0 * total_executed / total_executable
    if total_pct + 1e-9 < total_floor:
        breaches.append(
            f"TOTAL: {total_pct:.1f}% < floor {total_floor}% "
            f"({total_executed}/{total_executable})"
        )
    return GateResult(passed=not breaches, breaches=breaches)


# --------------------------------------------------------------------------- #
# I/O shell: run the suite under trace, build stats, report, exit
# --------------------------------------------------------------------------- #
def _load_suite() -> unittest.TestSuite:
    """Discover the same suite CI runs: scripts/test_*.py."""
    return unittest.defaultTestLoader.discover(
        str(SCRIPTS_DIR), pattern="test_*.py", top_level_dir=str(SCRIPTS_DIR)
    )


def _run_under_trace(suite: unittest.TestSuite) -> tuple[bool, dict]:
    """Run the suite under trace.Trace; return (suite_passed, counts)."""
    tracer = trace.Trace(count=1, trace=0)
    runner = unittest.TextTestRunner(stream=sys.stderr, verbosity=1)
    result_holder: dict[str, unittest.TestResult] = {}

    def _run() -> None:
        result_holder["result"] = runner.run(suite)

    tracer.runfunc(_run)
    results = tracer.results()
    suite_passed = result_holder["result"].wasSuccessful()
    return suite_passed, results.counts


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
    total_run = sum(s.executed for s in stats.values())
    total_able = sum(s.executable for s in stats.values())
    total_pct = 100.0 if total_able == 0 else 100.0 * total_run / total_able
    print(
        f"  {'TOTAL':40s} {total_pct:6.1f}% "
        f"{total_run:5d}/{total_able:<6d} {TOTAL_FLOOR:5d}%"
    )
    if result.passed:
        print("PASS: all per-file and total floors met.")
    else:
        print("FAIL: coverage floors breached:")
        for b in result.breaches:
            print(f"  - {b}")


def main(argv: list[str] | None = None) -> int:
    suite = _load_suite()
    suite_passed, counts = _run_under_trace(suite)
    if not suite_passed:
        print("FAIL: unittest suite did not pass — coverage not measured.",
              file=sys.stderr)
        return 1
    stats = _build_stats(counts)
    result = evaluate(stats, PER_FILE_FLOORS, TOTAL_FLOOR)
    _print_report(stats, result)
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
