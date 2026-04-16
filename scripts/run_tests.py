#!/usr/bin/env python3
"""
Integration Test Runner

Runs pytest unit tests for integration directories that have test_*_unit.py files.

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
        p
        for p in Path(".").iterdir()
        if p.is_dir() and p.name not in SKIP_FOLDERS and (p / "config.json").exists()
    )


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

    # Build pytest command
    test_file_args = []
    cov_args = []
    for d, files in testable:
        cov_args.extend(["--cov", str(d)])
        for f in files:
            test_file_args.append(str(f))

    cmd = [
        sys.executable, "-m", "pytest",
        "--import-mode=importlib",
        "-m", "unit",
        "-v",
        "--tb=short",
        "--no-header",
        *cov_args,
        "--cov-report=term-missing:skip-covered",
        *test_file_args,
    ]

    print(f"🧪 Running unit tests for: {', '.join(d.name for d, _ in testable)}")
    print()

    result = subprocess.run(cmd)

    print()
    if result.returncode == 0:
        print(f"✅ Tests passed for {len(testable)} integration(s)")
    else:
        print(f"❌ Tests failed (exit code {result.returncode})")

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
