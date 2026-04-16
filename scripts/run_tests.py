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


def install_integration_deps(integration_dir: Path) -> bool:
    """Install an integration's requirements.txt. Returns True on success."""
    req_file = integration_dir / "requirements.txt"
    if not req_file.is_file():
        return True

    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(req_file), "-q"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"   ❌ Failed to install dependencies for {integration_dir.name}")
        if result.stderr.strip():
            for line in result.stderr.strip().splitlines():
                print(f"      {line}")
        return False
    return True


def run_integration_tests(integration_dir: Path, test_files: list[Path]) -> int:
    """Run pytest for a single integration. Returns the pytest exit code."""
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "--import-mode=importlib",
        "-m",
        "unit",
        "-v",
        "--tb=short",
        "--no-header",
        "--cov",
        str(integration_dir),
        "--cov-report=term-missing:skip-covered",
        *[str(f) for f in test_files],
    ]

    return subprocess.run(cmd).returncode


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

    print(f"🧪 Running unit tests for: {', '.join(d.name for d, _ in testable)}")
    print()

    # Run each integration separately with its own dependencies
    failed = []
    passed = []
    for d, test_files in testable:
        print(f"{'=' * 60}")
        print(f"  {d.name}")
        print(f"{'=' * 60}")

        if not install_integration_deps(d):
            failed.append(d.name)
            continue

        exit_code = run_integration_tests(d, test_files)
        if exit_code == 0:
            passed.append(d.name)
        else:
            failed.append(d.name)
        print()

    # Summary
    print("=" * 60)
    if passed:
        print(f"✅ Tests passed: {', '.join(passed)}")
    if failed:
        print(f"❌ Tests failed: {', '.join(failed)}")
    print("=" * 60)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
