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
    1 - Missing base_ref argument

Examples:
    scripts/get_changed_dirs.py origin/main
    scripts/get_changed_dirs.py HEAD~1
"""

import argparse
import subprocess
import sys
from pathlib import PurePosixPath

SKIP_DIRS = frozenset({".github", "scripts", "tests", "template-structure"})


def get_changed_dirs(base_ref: str) -> list[str]:
    """Return sorted, deduplicated integration directory names changed since *base_ref*."""
    result = subprocess.run(
        ["git", "diff", "--name-only", base_ref, "HEAD"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []

    dirs: set[str] = set()
    for line in result.stdout.splitlines():
        path = PurePosixPath(line)
        if len(path.parts) < 2:
            continue
        top_dir = path.parts[0]
        if top_dir not in SKIP_DIRS:
            dirs.add(top_dir)

    return sorted(dirs)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Get changed integration directories from a git diff.",
    )
    parser.add_argument(
        "base_ref",
        help="Git ref to diff against (e.g., origin/main, HEAD~1)",
    )
    args = parser.parse_args()

    changed = get_changed_dirs(args.base_ref)
    if changed:
        print(" ".join(changed))

    return 0


if __name__ == "__main__":
    sys.exit(main())
