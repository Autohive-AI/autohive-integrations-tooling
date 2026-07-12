#!/usr/bin/env python3
"""
Integration Test Runner

Runs pytest unit tests for integration directories that have test_*_unit.py files.
Each integration is tested separately with its own dependencies installed from its
requirements.txt, so SDK version pins are respected per integration.

Usage:
    python scripts/run_tests.py [dir ...]

    If no directories specified, scans all integration folders.

Exit codes:
    0 - All tests passed (or no tests found)
    1 - One or more test failures
    2 - An error occurred

Examples:
    python scripts/run_tests.py hackernews
    python scripts/run_tests.py hackernews bitly notion
    python scripts/run_tests.py
"""

import re
import subprocess
import sys
from pathlib import Path

# Fix Windows console encoding for unicode characters
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

SKIP_FOLDERS = {
    ".github",
    ".git",
    "scripts",
    "tests",
    "template-structure",
    "__pycache__",
    ".vscode",
    ".idea",
    "node_modules",
    ".venv",
    ".ruff_cache",
    ".pytest_cache",
    "tools",
}


def find_unit_test_files(integration_dir: Path) -> list[Path]:
    """Find all test_*_unit.py files in an integration's tests/ directory."""
    tests_dir = integration_dir / "tests"
    if not tests_dir.is_dir():
        return []
    return sorted(tests_dir.glob("test_*_unit.py"))


def get_integration_dirs(args: list[str]) -> list[Path]:
    """Resolve integration directories from CLI args or auto-detect."""
    if args:
        dirs = []
        for name in args:
            p = Path(name)
            if p.is_dir():
                dirs.append(p)
            else:
                print(f"❌ Directory not found: {name}")
                sys.exit(2)
        return dirs

    # Auto-detect: all subdirectories with a config.json
    return sorted(
        p for p in Path(".").iterdir() if p.is_dir() and p.name not in SKIP_FOLDERS and (p / "config.json").exists()
    )


def install_integration_deps(integration_dir: Path) -> tuple[bool, str]:
    """Install an integration's requirements.txt. Returns (success, error_output)."""
    req_file = integration_dir / "requirements.txt"
    if not req_file.is_file():
        return True, ""

    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(req_file), "-q"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, result.stderr.strip()
    return True, ""


def run_integration_tests(integration_dir: Path, test_files: list[Path]) -> tuple[int, str]:
    """Run pytest for a single integration. Returns (exit_code, output)."""
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "--import-mode=importlib",
        "-m",
        "unit",
        "--tb=short",
        "--no-header",
        "-q",
        "--cov",
        str(integration_dir),
        "--cov-report=term-missing:skip-covered",
        *[str(f) for f in test_files],
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, result.stdout + result.stderr


def parse_results(output: str) -> tuple[int, int, str]:
    """Parse pytest output for passed count, failed count, and coverage."""
    passed = failed = 0
    coverage = "n/a"

    # Match summary line e.g. "37 passed" or "2 failed, 35 passed"
    summary = re.search(r"(\d+) passed", output)
    if summary:
        passed = int(summary.group(1))
    fail_match = re.search(r"(\d+) failed", output)
    if fail_match:
        failed = int(fail_match.group(1))

    # Match coverage total e.g. "TOTAL   166   13   92%"
    cov_match = re.search(r"^TOTAL\s+\d+\s+\d+\s+(\d+%)", output, re.MULTILINE)
    if cov_match:
        coverage = cov_match.group(1)

    return passed, failed, coverage


def print_table(rows: list[tuple[str, str, str, str, str]], failed_outputs: dict[str, str]) -> None:
    """Print a formatted results table."""
    col_widths = [
        max(len(r[0]) for r in rows) + 2,
        8,   # Tests
        10,  # Coverage
        14,  # Status
    ]

    header = (
        f"{'Integration':<{col_widths[0]}}"
        f"{'Tests':>{col_widths[1]}}"
        f"{'Coverage':>{col_widths[2]}}"
        f"{'Status':>{col_widths[3]}}"
    )
    divider = "-" * len(header)

    print()
    print(header)
    print(divider)
    for name, tests, coverage, status, _ in rows:
        print(
            f"{name:<{col_widths[0]}}"
            f"{tests:>{col_widths[1]}}"
            f"{coverage:>{col_widths[2]}}"
            f"{status:>{col_widths[3]}}"
        )
    print(divider)

    # Total row
    total_passed = sum(int(r[1].split("/")[0]) for r in rows if "/" in r[1])
    total_total = sum(int(r[1].split("/")[1]) for r in rows if "/" in r[1])
    all_passed = all(r[4] == "pass" for r in rows)
    total_status = "✅ All passed" if all_passed else "❌ Some failed"
    print(
        f"{'Total':<{col_widths[0]}}"
        f"{f'{total_passed}/{total_total}':>{col_widths[1]}}"
        f"{'':>{col_widths[2]}}"
        f"{total_status:>{col_widths[3]}}"
    )
    print()

    # Print full output only for failures
    for name, _, _, _, outcome in rows:
        if outcome == "fail" and name in failed_outputs:
            print(f"{'=' * 60}")
            print(f"  {name} — failure detail")
            print(f"{'=' * 60}")
            print(failed_outputs[name])
            print()


def main() -> int:
    args = sys.argv[1:]
    dirs = get_integration_dirs(args)

    if not dirs:
        print("⚠️  No integration directories found")
        return 0

    # Collect which integrations have unit tests
    testable = []
    skipped = []
    for d in dirs:
        test_files = find_unit_test_files(d)
        if test_files:
            testable.append((d, test_files))
        else:
            skipped.append(d)

    if skipped:
        print(f"⚠️  No unit tests (test_*_unit.py) found in: {', '.join(d.name for d in skipped)}")

    if not testable:
        print("⚠️  No unit tests to run")
        return 0

    # Run each integration separately with its own dependencies
    rows = []
    failed_outputs = {}

    for d, test_files in testable:
        ok, err = install_integration_deps(d)
        if not ok:
            rows.append((d.name, "n/a", "n/a", "❌ Dep install failed", "fail"))
            failed_outputs[d.name] = err
            continue

        exit_code, output = run_integration_tests(d, test_files)
        passed, failed, coverage = parse_results(output)
        total = passed + failed
        tests_str = f"{passed}/{total}"

        if exit_code == 0:
            rows.append((d.name, tests_str, coverage, "✅ Passed", "pass"))
        else:
            rows.append((d.name, tests_str, coverage, "❌ Failed", "fail"))
            failed_outputs[d.name] = output

    print_table(rows, failed_outputs)

    any_failed = any(r[4] == "fail" for r in rows)
    if any_failed:
        print(f"❌ Tests failed: {', '.join(r[0] for r in rows if r[4] == 'fail')}")
    else:
        print(f"✅ Tests passed: {', '.join(r[0] for r in rows if r[4] == 'pass')}")

    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
