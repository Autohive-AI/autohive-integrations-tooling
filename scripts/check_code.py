#!/usr/bin/env python3
"""
Code Quality Checker

Requires: Python 3.13+

This script runs code quality checks on one or more integration directories.
It validates Python syntax, import availability, JSON file correctness,
and code quality via linting.

Checks performed per directory:
    1. Install dependencies from requirements.txt (via pip)
    2. Python syntax check (py_compile)
    3. Import availability check (check_imports)
    4. JSON validity check
    5. Lint check (ruff)

Usage:
    python scripts/check_code.py <dir> [dir ...]

Exit codes:
    0 - All checks passed
    1 - One or more checks failed
    2 - No directories provided (handled by argparse)

Examples:
    $ python scripts/check_code.py my-integration
    $ python scripts/check_code.py integration-a integration-b
"""

import argparse
import io
import json
import py_compile
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

# Allow importing check_imports from the same directory regardless of cwd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_imports import check_imports


def check_code(dirs: list[str]) -> int:
    """Run code quality checks on the given integration directories.

    Args:
        dirs: List of directory paths to check.

    Returns:
        0 if all checks passed, 1 if any check failed.
    """
    failed = False

    # Ensure ruff is available for linting
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "ruff", "-q"],
        capture_output=True,
    )

    for dir_name in dirs:
        dir_path = Path(dir_name)

        print("----------------------------------------")
        print(f"Checking: {dir_name}")
        print("----------------------------------------")
        print()

        if not dir_path.is_dir():
            print(f"   ❌ Directory not found: {dir_name}")
            print()
            failed = True
            continue

        # Install dependencies
        req_file = dir_path / "requirements.txt"
        if req_file.is_file():
            print("📦 Installing dependencies...")
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", str(req_file), "-q"],
            )
            print()

        # Syntax check
        print("🐍 Checking Python syntax...")
        syntax_ok = True
        for pyfile in sorted(dir_path.glob("**/*.py")):
            try:
                py_compile.compile(str(pyfile), doraise=True)
            except py_compile.PyCompileError:
                print(f"   ❌ {pyfile}")
                syntax_ok = False
                failed = True

        if syntax_ok:
            print("   ✅ Syntax OK")
        else:
            print()
            print("   Fix: Check the Python files above for syntax errors")
            print("   Run locally: python -m py_compile <file.py>")
        print()

        # Import check
        print("📥 Checking imports...")
        config_path = dir_path / "config.json"
        if config_path.is_file():
            with open(config_path, encoding="utf-8") as f:
                config = json.load(f)
            entry_point = config.get("entry_point", "")
            entry_file = dir_path / entry_point if entry_point else None

            if entry_file and entry_file.is_file():
                buf = io.StringIO()
                with redirect_stdout(buf):
                    result = check_imports(str(entry_file))
                if result != 0:
                    for line in buf.getvalue().splitlines():
                        print(f"   {line}")
                    print(f"   ❌ Import errors in {entry_file}")
                    print()
                    print("   Fix: Install missing packages in requirements.txt")
                    print("   Or check if package name is spelled correctly")
                    failed = True
                else:
                    print("   ✅ Imports OK")
            else:
                print("   ⚠️ No entry point found, skipping")
        else:
            print("   ⚠️ No config.json found, skipping")
        print()

        # JSON check
        print("📄 Checking JSON files...")
        json_ok = True
        for jsonfile in sorted(dir_path.glob("**/*.json")):
            try:
                with open(jsonfile, encoding="utf-8") as f:
                    json.load(f)
            except (json.JSONDecodeError, OSError):
                print(f"   ❌ {jsonfile}")
                json_ok = False
                failed = True

        if json_ok:
            print("   ✅ JSON files OK")
        else:
            print()
            print("   Fix: Check for missing commas, quotes, or brackets")
            print("   Validate at: https://jsonlint.com/")
        print()

        # Lint check
        print("🔍 Linting with ruff...")
        ruff_result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", str(dir_path)],
            capture_output=True,
            text=True,
        )
        if ruff_result.returncode != 0:
            for line in ruff_result.stdout.splitlines():
                print(f"   {line}")
            print(f"   ❌ Lint errors found")
            print()
            print("   Fix: Run 'ruff check --fix' to auto-fix some issues")
            failed = True
        else:
            print("   ✅ Lint OK")
        print()

    print("========================================")
    if failed:
        print("❌ CODE CHECK FAILED")
        print("========================================")
        return 1
    print("✅ CODE CHECK PASSED")
    print("========================================")
    return 0


def main() -> int:
    """Parse arguments and run code quality checks."""
    parser = argparse.ArgumentParser(
        description="Run code quality checks on integration directories.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Exit codes:
  0  All checks passed
  1  One or more checks failed

Examples:
  %(prog)s my-integration
  %(prog)s integration-a integration-b
""",
    )
    parser.add_argument(
        "dirs",
        nargs="+",
        metavar="dir",
        help="Integration directories to check",
    )

    args = parser.parse_args()
    return check_code(args.dirs)


if __name__ == "__main__":
    sys.exit(main())
