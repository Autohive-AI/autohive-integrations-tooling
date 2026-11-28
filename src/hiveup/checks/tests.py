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

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from hiveup.core.deployment import is_deployment_source, is_excluded_development_path
from hiveup.core.discovery import is_ignored_top_level_dir
from hiveup.core.environment import EnvironmentBuildError, IntegrationEnvironment, prepare_environment
from hiveup.render.text import ANSI_ESCAPE, format_table

# Fix Windows console encoding for unicode characters
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

PYTEST_PROJECT_FILES = ("conftest.py", "pyproject.toml", "pytest.ini", "tox.ini", "setup.cfg")


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
        p
        for p in Path(".").iterdir()
        if p.is_dir() and not is_ignored_top_level_dir(p) and (p / "config.json").exists()
    )


def run_integration_tests(integration_dir: Path, test_files: list[Path]) -> tuple[int, str]:
    """Run pytest in an integration's isolated environment."""
    environment = prepare_environment(integration_dir, include_test_tools=True)
    return _run_integration_tests(environment, integration_dir, test_files)


def _run_integration_tests(
    environment: IntegrationEnvironment,
    integration_dir: Path,
    test_files: list[Path],
) -> tuple[int, str]:
    integration_dir = integration_dir.resolve()
    test_files = [test_file.resolve() for test_file in test_files]
    _stage_sdk_config(environment, integration_dir)

    for source in integration_dir.rglob("*"):
        relative = source.relative_to(integration_dir)
        if source.is_symlink() and not is_excluded_development_path(relative):
            raise EnvironmentBuildError(f"Deployment source cannot be a symlink: {relative.as_posix()}")

    with tempfile.TemporaryDirectory(prefix="hiveup-tests-") as temporary:
        temporary_root = Path(temporary)
        for filename in PYTEST_PROJECT_FILES:
            source = integration_dir.parent / filename
            if source.is_file():
                shutil.copyfile(source, temporary_root / filename)
        test_root = temporary_root / integration_dir.name
        _stage_test_workspace(integration_dir, test_root)
        if not integration_dir.name.isidentifier() and (test_root / "__init__.py").is_file():
            (test_root / "__init__.py").unlink()
        staged_tests = [test_root / test_file.relative_to(integration_dir) for test_file in test_files]
        return _execute_tests(environment, test_root, staged_tests)


def _stage_test_workspace(integration_dir: Path, test_root: Path) -> None:
    test_root.mkdir()
    for source in integration_dir.rglob("*"):
        relative = source.relative_to(integration_dir)
        if relative.parts[0] in {"test", "tests"}:
            if source.is_file():
                destination = test_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            continue
        if source.is_file() and not source.is_symlink() and is_deployment_source(relative):
            destination = test_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)


def _execute_tests(
    environment: IntegrationEnvironment,
    integration_dir: Path,
    test_files: list[Path],
) -> tuple[int, str]:
    coverage_config = integration_dir.parent / ".hiveup-coveragerc"
    coverage_config.write_text(
        "[run]\nomit =\n    */test/*\n    */tests/*\n",
        encoding="utf-8",
    )
    cmd = [
        str(environment.python),
        "-m",
        "pytest",
        "--import-mode=importlib",
        "-m",
        "unit",
        "--tb=short",
        "--no-header",
        "-q",
        "--override-ini",
        "markers=unit: isolated integration unit test",
        "--cov",
        str(integration_dir),
        "--cov-config",
        str(coverage_config),
        "--cov-report=term-missing:skip-covered",
        *[str(f) for f in test_files],
    ]

    child_environment = os.environ.copy()
    child_environment["PYTHONPATH"] = os.pathsep.join(
        (str(integration_dir.parent.resolve()), str(integration_dir.resolve()))
    )
    result = subprocess.run(
        cmd,
        cwd=integration_dir,
        env=child_environment,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout + result.stderr


def _stage_sdk_config(environment: IntegrationEnvironment, integration_dir: Path) -> None:
    """Mirror deployment config placement for SDK versions that infer it from their install path."""
    config = integration_dir / "config.json"
    if not config.is_file():
        return

    script = (
        "from importlib.util import find_spec; "
        "from pathlib import Path; "
        "spec = find_spec('autohive_integrations_sdk'); "
        "assert spec is not None and spec.origin is not None; "
        "print(Path(spec.origin).resolve().parents[2] / 'config.json')"
    )
    result = subprocess.run(
        [str(environment.python), "-c", script],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        output = (result.stderr or result.stdout).strip() or "Autohive integrations SDK is not installed"
        raise EnvironmentBuildError(f"Could not prepare SDK configuration: {output}")

    target = Path(result.stdout.strip())
    shutil.copyfile(config, target)


def parse_results(output: str) -> tuple[int, int, str]:
    """Parse pytest output for passed count, failed count, and coverage."""
    output = ANSI_ESCAPE.sub("", output)
    summary = next(
        (
            line
            for line in reversed(output.splitlines())
            if re.match(
                r"^=*\s*\d+\s+(?:passed|failed|errors?|skipped|deselected|xfailed|xpassed|warnings?|rerun)\b", line
            )
        ),
        "",
    )
    counts = {status: int(count) for count, status in re.findall(r"\b(\d+) (passed|failed)\b", summary)}
    coverage = re.findall(r"^[ \t]*TOTAL(?:\s+\d+){2,}\s+(\d+(?:\.\d+)?%)[ \t]*$", output, re.MULTILINE)
    return counts.get("passed", 0), counts.get("failed", 0), coverage[-1] if coverage else "n/a"


def format_test_table(rows: list[tuple[str, str, str, str, str]]) -> str:
    """Format test rows and their aggregate, independently of the output destination."""
    total_passed = sum(int(r[1].split("/")[0]) for r in rows if "/" in r[1])
    total_total = sum(int(r[1].split("/")[1]) for r in rows if "/" in r[1])
    all_passed = not any(r[4] in {"fail", "failed", "error"} for r in rows)
    total_status = "✅ All passed" if all_passed else "❌ Some failed"
    total_tests = f"{total_passed}/{total_total}" if any("/" in r[1] for r in rows) else "n/a"
    return format_table(
        ("Integration", "Tests", "Coverage", "Status"),
        [row[:4] for row in rows],
        right_align=(1, 2, 3),
        total_row=("Total", total_tests, "", total_status),
    )


def print_table(rows: list[tuple[str, str, str, str, str]], failed_outputs: dict[str, str]) -> None:
    """Print a formatted results table."""
    print()
    print(format_test_table(rows))
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
        try:
            exit_code, output = run_integration_tests(d, test_files)
        except EnvironmentBuildError as exc:
            rows.append((d.name, "n/a", "n/a", "❌ Environment failed", "fail"))
            failed_outputs[d.name] = str(exc)
            continue
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
