#!/usr/bin/env python3
"""
Fetch Pattern Checker

Requires: Python 3.13+

This script validates that integrations use the correct context.fetch()
return-value pattern for their pinned SDK version.

SDK 2.0.0 changed context.fetch() to return a FetchResponse object with
.status, .headers, and .data attributes. Integrations pinned to SDK >=2.0
must access the response body via .data — using the raw return value
directly (e.g., response["key"] or response.get("key")) will fail.

Checks performed:
    1. Parse SDK version from requirements.txt
    2. AST-walk Python files for context.fetch() calls
    3. Track the variable assigned from each fetch call
    4. If SDK >= 2.0: warn when the variable is used directly as a
       dict (subscript, .get(), isinstance(), or passed where .data
       is expected)

Usage:
    python scripts/check_fetch_pattern.py <dir> [dir ...]

Exit codes:
    0 - All checks passed (possibly with warnings)
    1 - Fetch pattern errors found
    2 - An error occurred (file not found, etc.)

Examples:
    python scripts/check_fetch_pattern.py my-integration
    python scripts/check_fetch_pattern.py integration-a integration-b
"""

import argparse
import ast
import re
import sys
from pathlib import Path


def parse_sdk_major_version(requirements_path: Path) -> int | None:
    """Extract the SDK major version from a requirements.txt file.

    Args:
        requirements_path: Path to requirements.txt.

    Returns:
        Major version as int, or None if SDK not found / unpinned.
    """
    if not requirements_path.is_file():
        return None

    content = requirements_path.read_text(encoding="utf-8")
    match = re.search(
        r"autohive-integrations-sdk\s*(?:~=|==)\s*(\d+)\.\d+(?:\.\d+)?",
        content,
    )
    if match:
        return int(match.group(1))
    return None


def find_fetch_variables(tree: ast.AST) -> dict[str, int]:
    """Find variables assigned from context.fetch() calls.

    Looks for patterns like:
        response = await context.fetch(...)
        data = await context.fetch(...)

    Args:
        tree: Parsed AST.

    Returns:
        Dict mapping variable name to the line number of the assignment.
    """
    fetch_vars: dict[str, int] = {}

    for node in ast.walk(tree):
        # Match: var = await context.fetch(...)
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue

        value = node.value
        # Unwrap await
        if isinstance(value, ast.Await):
            value = value.value

        if not isinstance(value, ast.Call):
            continue

        func = value.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "fetch"
            and isinstance(func.value, ast.Name)
            and func.value.id == "context"
        ):
            fetch_vars[node.targets[0].id] = node.lineno

    return fetch_vars


def check_direct_usage(tree: ast.AST, fetch_vars: dict[str, int]) -> list[str]:
    """Check if fetch return variables are used directly without .data.

    Detects patterns that would break with SDK 2.0's FetchResponse:
        - response["key"]         (subscript)
        - response.get("key")     (.get() call)
        - isinstance(response, list)  (type check on raw value)

    Args:
        tree: Parsed AST.
        fetch_vars: Dict of variable names assigned from context.fetch().

    Returns:
        List of error messages.
    """
    errors: list[str] = []
    var_names = set(fetch_vars.keys())

    for node in ast.walk(tree):
        # response["key"]
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id in var_names
        ):
            errors.append(
                f'Line {node.lineno}: {node.value.id}["..."] — '
                f"use {node.value.id}.data[\"...\"] with SDK 2.x"
            )

        # response.get("key")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in var_names
        ):
            errors.append(
                f"Line {node.lineno}: {node.func.value.id}.get(...) — "
                f"use {node.func.value.id}.data.get(...) with SDK 2.x"
            )

        # isinstance(response, list/dict)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "isinstance"
            and len(node.args) >= 1
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id in var_names
        ):
            errors.append(
                f"Line {node.lineno}: isinstance({node.args[0].id}, ...) — "
                f"use isinstance({node.args[0].id}.data, ...) with SDK 2.x"
            )

    return errors


def check_fetch_pattern(dir_path: str) -> int:
    """Check fetch usage patterns for an integration directory.

    Args:
        dir_path: Path to the integration directory.

    Returns:
        0 if patterns are correct, 1 if issues found, 2 on errors.
    """
    path = Path(dir_path)
    req_path = path / "requirements.txt"

    major = parse_sdk_major_version(req_path)
    if major is None:
        # No parseable SDK pin — skip check
        return 0

    if major < 2:
        # SDK 1.x — old pattern is fine, nothing to check
        return 0

    # SDK >= 2.x — check for old-style direct usage
    all_errors: list[str] = []

    for pyfile in sorted(path.rglob("*.py")):
        # Skip test files and __pycache__
        rel = pyfile.relative_to(path)
        if "__pycache__" in rel.parts:
            continue

        try:
            source = pyfile.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (SyntaxError, OSError):
            continue

        fetch_vars = find_fetch_variables(tree)
        if not fetch_vars:
            continue

        errors = check_direct_usage(tree, fetch_vars)
        if errors:
            all_errors.append(f"\n  {pyfile}:")
            for error in errors:
                all_errors.append(f"    {error}")

    if all_errors:
        print(
            "SDK 2.x requires using response.data to access the response body. "
            "context.fetch() now returns a FetchResponse object."
        )
        for line in all_errors:
            print(line)
        return 1

    return 0


def main() -> int:
    """Parse arguments and run fetch pattern check."""
    parser = argparse.ArgumentParser(
        description="Check context.fetch() usage patterns match SDK version.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Exit codes:
  0  Patterns are correct (possibly with warnings)
  1  Pattern issues found
  2  An error occurred

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

    exit_code = 0
    for dir_path in args.dirs:
        print(f"\n{'=' * 60}")
        print(f"Fetch pattern: {dir_path}")
        print(f"{'=' * 60}")

        result = check_fetch_pattern(dir_path)
        if result == 0:
            print("✅ Fetch patterns OK")
        if result > exit_code:
            exit_code = result

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
