#!/usr/bin/env python3
"""
Changed Integration Directory Detector

Requires: Python 3.13+

This script identifies which integration directories have changed
relative to a given git base ref. It diffs HEAD against the provided
ref and extracts the top-level directory names, excluding infrastructure
folders (.github, scripts, tests, template-structure).

Usage:
    scripts/get_changed_dirs.py <base_ref>

Arguments:
    base_ref  Git ref to diff against (e.g., origin/main, HEAD~1)

Output:
    Space-separated list of changed integration directory names.

Exit codes:
    0 - Success (may output empty string if no integration dirs changed)
    2 - An error occurred (invalid git ref, missing arguments)

Examples:
    scripts/get_changed_dirs.py origin/main
    scripts/get_changed_dirs.py HEAD~1
"""

import argparse
import subprocess
import sys
from pathlib import Path, PurePosixPath

SKIP_DIRS = frozenset({".github", "scripts", "tests", "template-structure"})


def get_changed_dirs(base_ref: str) -> tuple[list[str], list[str]] | None:
    """Return integration directory names changed since *base_ref*.

    Returns a tuple of (existing_dirs, renamed_dirs) where renamed_dirs are
    directories that appear in the diff but no longer exist on disk (i.e. the
    old side of a rename). Returns None if the git command fails.
    """
    result = subprocess.run(
        ["git", "diff", "--name-only", base_ref, "HEAD"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None

    dirs: set[str] = set()
    for line in result.stdout.splitlines():
        path = PurePosixPath(line)
        if len(path.parts) < 2:
            continue
        top_dir = path.parts[0]
        if top_dir not in SKIP_DIRS:
            dirs.add(top_dir)

    existing = sorted(d for d in dirs if Path(d).is_dir())
    renamed = sorted(d for d in dirs if not Path(d).is_dir())
    return existing, renamed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Get changed integration directories from a git diff.",
    )
    parser.add_argument(
        "base_ref",
        help="Git ref to diff against (e.g., origin/main, HEAD~1)",
    )
    args = parser.parse_args()

    result = get_changed_dirs(args.base_ref)
    if result is None:
        print(f"Error: git diff failed for ref '{args.base_ref}'", file=sys.stderr)
        return 2

    existing, renamed = result

    if renamed:
        print(
            f"⚠️ Detected renamed/removed directories (skipping): {', '.join(renamed)}",
            file=sys.stderr,
        )

    if existing:
        print(" ".join(existing))

    return 0


if __name__ == "__main__":
    sys.exit(main())
