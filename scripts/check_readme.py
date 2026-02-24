#!/usr/bin/env python3
"""
README Update Checker

Requires: Python 3.13+

This script checks that the main README.md is updated when new integrations
are added. It compares the current branch against a base ref (e.g.,
origin/main) to detect newly added files in integration directories, and
verifies that README.md was also modified.

How it works:
    1. Runs `git diff` against the base ref to check if README.md changed
    2. For each specified directory, checks for newly added files (--diff-filter=A)
    3. If new files exist in an integration dir but README.md was not updated,
       the check fails

Exit codes:
    0 - README is up to date (or no new integrations)
    1 - New integration detected but README not updated
    2 - Missing arguments (handled by argparse)

Usage:
    python scripts/check_readme.py <base_ref> <dir> [dir ...]

Examples:
    python scripts/check_readme.py origin/main my-new-integration
    python scripts/check_readme.py origin/main integration-a integration-b
"""

import argparse
import subprocess
import sys
from pathlib import Path


def check_readme(base_ref: str, dirs: list[str]) -> int:
    """Check that README.md is updated when new integration files are added.

    Returns 0 if the check passes, 1 if it fails.
    """
    readme_diff = subprocess.run(
        ["git", "diff", "--name-only", base_ref, "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    readme_changed = "README.md" in readme_diff.stdout.splitlines()

    failed = False
    for d in dirs:
        if not Path(d).is_dir():
            continue

        added_diff = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=A", base_ref, "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        new_files = [f for f in added_diff.stdout.splitlines() if f.startswith(f"{d}/")]

        if new_files and not readme_changed:
            print(f"❌ NEW INTEGRATION DETECTED: '{d}'")
            print()
            print("   But main README.md was NOT updated!")
            print()
            print("   Fix: Add your integration to the main README.md file")
            print("   Example:")
            print(f"   | {d} | Your description | Auth Type |")
            print()
            failed = True

    print("========================================")
    if failed:
        print("❌ README CHECK FAILED")
        print("========================================")
        return 1
    print("✅ README CHECK PASSED")
    print("========================================")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check that the main README.md is updated when new integrations are added.",
    )
    parser.add_argument("base_ref", help="Git ref to diff against (e.g., origin/main)")
    parser.add_argument("dirs", nargs="+", metavar="dir", help="Integration directories to check")
    args = parser.parse_args()
    return check_readme(args.base_ref, args.dirs)


if __name__ == "__main__":
    sys.exit(main())
