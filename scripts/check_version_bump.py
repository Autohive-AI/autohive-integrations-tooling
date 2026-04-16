#!/usr/bin/env python3
"""
Version Bump Checker

Requires: Python 3.13+

This script checks that integration version numbers are incremented when
changes are made. It compares the current config.json version against the
base ref to detect missing or incorrect version bumps, and recommends the
appropriate bump level (major, minor, patch) based on what changed.

Heuristics for recommended bump level:
    major - Auth config changed, actions removed, entry_point changed
    minor - New actions added, new config fields added
    patch - Only code, tests, requirements, or docs changed

Exit codes:
    0 - Version check passed
    1 - Version bump missing or not incremented
    2 - An error occurred (invalid git ref)

Usage:
    python scripts/check_version_bump.py <base_ref> <dir> [dir ...]

Examples:
    python scripts/check_version_bump.py origin/master my-integration
    python scripts/check_version_bump.py origin/master integration-a integration-b
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def parse_version(version_str: str) -> tuple[int, ...] | None:
    """Parse a semver string into a tuple of ints. Returns None on failure."""
    try:
        parts = tuple(int(p) for p in version_str.split("."))
        if len(parts) != 3:
            return None
        return parts
    except (ValueError, AttributeError):
        return None


def get_base_config(base_ref: str, dir_name: str) -> dict | None:
    """Retrieve config.json from the base ref via git show.

    Returns None if the file doesn't exist on the base ref (new integration).
    """
    result = subprocess.run(
        ["git", "show", f"{base_ref}:{dir_name}/config.json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def get_changed_files(base_ref: str, dir_name: str) -> list[str] | None:
    """Return list of changed files within a directory relative to base_ref."""
    result = subprocess.run(
        ["git", "diff", "--name-only", base_ref, "HEAD", "--", f"{dir_name}/"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return [f for f in result.stdout.splitlines() if f.strip()]


def get_diff_stats(base_ref: str, dir_name: str) -> dict | None:
    """Analyse the code diff and return signals for bump classification.

    Returns a dict with keys:
        py_files_added   - number of new .py files (excluding tests)
        py_files_deleted - number of deleted .py files (excluding tests)
        classes_added    - count of added `class …:` lines
        classes_removed  - count of removed `class …:` lines
        funcs_added      - count of added `def …(` lines
        funcs_removed    - count of removed `def …(` lines
        only_tests_docs  - True if every changed file is in tests/, README, or docs
    Returns None on git error.
    """
    # --- file-level stats (added / deleted) ---
    for diff_filter, key_suffix in [("A", "added"), ("D", "deleted")]:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"--diff-filter={diff_filter}", base_ref, "HEAD", "--", f"{dir_name}/"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        files = [f for f in result.stdout.splitlines() if f.strip()]
        py_files = [f for f in files if f.endswith(".py") and "/tests/" not in f and not f.endswith("test_.py")]
        if key_suffix == "added":
            py_files_added = len(py_files)
        else:
            py_files_deleted = len(py_files)

    # --- line-level stats from unified diff of .py files ---
    result = subprocess.run(
        ["git", "diff", "-U0", base_ref, "HEAD", "--", f"{dir_name}/*.py", f"{dir_name}/**/*.py"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None

    func_pattern = re.compile(r"^\s*def\s+\w+\s*\(")
    class_pattern = re.compile(r"^\s*class\s+\w+")

    funcs_added = funcs_removed = 0
    classes_added = classes_removed = 0

    for line in result.stdout.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            content = line[1:]
            if func_pattern.match(content):
                funcs_added += 1
            if class_pattern.match(content):
                classes_added += 1
        elif line.startswith("-") and not line.startswith("---"):
            content = line[1:]
            if func_pattern.match(content):
                funcs_removed += 1
            if class_pattern.match(content):
                classes_removed += 1

    # --- check if only tests / docs changed ---
    all_changed = get_changed_files(base_ref, dir_name) or []
    non_test_doc = [
        f
        for f in all_changed
        if not ("/tests/" in f or f.endswith("README.md") or f.endswith(".md") or f.endswith("requirements.txt"))
    ]
    # config.json is handled separately so exclude it here
    non_test_doc = [f for f in non_test_doc if not f.endswith("config.json")]
    only_tests_docs = len(non_test_doc) == 0

    # Check if non-test/doc changes are formatting-only (whitespace changes)
    only_formatting = False
    if non_test_doc:
        ws_diff = subprocess.run(
            ["git", "diff", "-w", "--name-only", base_ref, "HEAD", "--", *non_test_doc],
            capture_output=True,
            text=True,
        )
        only_formatting = ws_diff.returncode == 0 and not ws_diff.stdout.strip()

    return {
        "py_files_added": py_files_added,
        "py_files_deleted": py_files_deleted,
        "classes_added": classes_added,
        "classes_removed": classes_removed,
        "funcs_added": funcs_added,
        "funcs_removed": funcs_removed,
        "only_tests_docs": only_tests_docs,
        "only_formatting": only_formatting,
    }


def recommend_bump(
    base_config: dict,
    current_config: dict,
    changed_files: list[str],
    dir_name: str,
    *,
    base_ref: str = "",
) -> str:
    """Recommend major, minor, or patch based on what changed.

    Heuristics (checked in order, first match wins):

    Config-level signals:
        major - auth changed, actions removed, entry_point changed
        minor - new actions added, action schemas changed

    Code-level signals (from git diff):
        major - .py files deleted, classes/functions removed
        minor - new .py files added, new classes/functions added

    Fallback:
        patch - everything else (tests, docs, requirements, small edits)
    """
    # --- Config-level: Major signals ---
    base_auth = base_config.get("auth")
    curr_auth = current_config.get("auth")
    if base_auth != curr_auth:
        return "major"

    if base_config.get("entry_point") != current_config.get("entry_point"):
        return "major"

    base_actions = set(base_config.get("actions", {}).keys())
    curr_actions = set(current_config.get("actions", {}).keys())
    removed_actions = base_actions - curr_actions
    if removed_actions:
        return "major"

    # --- Config-level: Minor signals ---
    new_actions = curr_actions - base_actions
    if new_actions:
        return "minor"

    # Check if existing action schemas changed (new fields, changed descriptions)
    for action_name in base_actions & curr_actions:
        base_action = base_config["actions"][action_name]
        curr_action = current_config["actions"][action_name]
        if base_action != curr_action:
            return "minor"

    # --- Code-level signals ---
    if base_ref:
        stats = get_diff_stats(base_ref, dir_name)
        if stats:
            # Only tests, docs, or requirements changed — always patch
            if stats["only_tests_docs"]:
                return "patch"

            # Only formatting/whitespace changes in source files — always patch
            if stats["only_formatting"]:
                return "patch"

            # Major: source files or public symbols removed
            if stats["py_files_deleted"] > 0:
                return "major"
            if stats["classes_removed"] > 0 or stats["funcs_removed"] > 0:
                return "major"

            # Minor: new source files or public symbols added
            if stats["py_files_added"] > 0:
                return "minor"
            if stats["classes_added"] > 0 or stats["funcs_added"] > 0:
                return "minor"

    # --- Default to patch ---
    return "patch"


def check_version_bump(base_ref: str, dirs: list[str]) -> int:
    """Check that versions are bumped for changed integrations.

    Returns 0 on success, 1 on failure, 2 on git errors.
    """
    failed = False

    for d in dirs:
        dir_path = Path(d)
        if not dir_path.is_dir():
            print(f"⚠️ Directory not found (renamed or removed?): {d} — skipping")
            continue

        config_path = dir_path / "config.json"
        if not config_path.exists():
            print(f"⚠️ No config.json in {d} — skipping version check")
            continue

        try:
            with open(config_path, encoding="utf-8") as f:
                current_config = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"❌ Could not read {d}/config.json: {e}")
            failed = True
            continue

        current_version_str = current_config.get("version")
        current_version = parse_version(current_version_str) if current_version_str else None

        # New integration — just check that a valid version exists
        base_config = get_base_config(base_ref, d)
        if base_config is None:
            if current_version is None:
                print(f"❌ {d}: New integration must have a valid semver 'version' in config.json (e.g. \"1.0.0\")")
                failed = True
            else:
                print(f"✅ {d}: New integration with version {current_version_str}")
            continue

        # Existing integration — check for version bump
        base_version_str = base_config.get("version")
        base_version = parse_version(base_version_str) if base_version_str else None

        if current_version is None:
            print(f"❌ {d}: config.json must have a valid semver 'version' (e.g. \"1.0.0\")")
            failed = True
            continue

        if base_version is None:
            # Base had no valid version — any valid version now is fine
            print(f"✅ {d}: Version set to {current_version_str}")
            continue

        changed_files = get_changed_files(base_ref, d)
        if changed_files is None:
            print(f"Error: git diff failed for ref '{base_ref}'")
            return 2

        if not changed_files:
            # No changes in this dir — nothing to check
            continue

        # If only tests, docs, or requirements changed, version bump is optional
        diff_stats = get_diff_stats(base_ref, d)
        no_bump_needed = (
            diff_stats
            and current_version_str == base_version_str
            and (diff_stats["only_tests_docs"] or diff_stats["only_formatting"])
        )
        if no_bump_needed:
            actions_same = base_config.get("actions") == current_config.get("actions")
            auth_same = base_config.get("auth") == current_config.get("auth")
            if actions_same and auth_same:
                if diff_stats["only_tests_docs"]:
                    reason = "only tests/docs changed"
                else:
                    reason = "only formatting/whitespace changed"
                print(f"✅ {d}: No version bump needed ({reason})")
                continue

        # Only config.json changed with no version diff is still a problem,
        # but if nothing meaningful changed we skip
        if current_version_str == base_version_str:
            recommendation = recommend_bump(base_config, current_config, changed_files, d, base_ref=base_ref)
            print(f"❌ {d}: Version not incremented ({base_version_str} → {current_version_str})")
            print()

            base_major, base_minor, base_patch = base_version
            if recommendation == "major":
                suggested = f"{base_major + 1}.0.0"
                reason = "breaking changes detected (auth, removed actions, entry_point, or code removed)"
            elif recommendation == "minor":
                suggested = f"{base_major}.{base_minor + 1}.0"
                reason = "new features detected (new actions, schema changes, or new functions/classes)"
            else:
                suggested = f"{base_major}.{base_minor}.{base_patch + 1}"
                reason = "code changes detected (bug fixes, docs, or dependency updates)"

            print(f"   Recommended: {base_version_str} → {suggested} ({recommendation} bump)")
            print(f"   Reason: {reason}")
            print()
            print(f"   Changed files:")
            for f in changed_files:
                print(f"     - {f}")
            print()
            failed = True
            continue

        if current_version <= base_version:
            print(f"❌ {d}: Version must be greater than {base_version_str} (found {current_version_str})")
            failed = True
            continue

        # Version was bumped — show what happened and recommend if the bump level seems off
        recommendation = recommend_bump(base_config, current_config, changed_files, d, base_ref=base_ref)
        actual_bump = _detect_bump_level(base_version, current_version)

        bump_note = ""
        if _bump_rank(actual_bump) < _bump_rank(recommendation):
            bump_note = f" (⚠️ consider a {recommendation} bump — {_bump_reason(recommendation)})"

        print(f"✅ {d}: {base_version_str} → {current_version_str} ({actual_bump} bump){bump_note}")

    print()
    print("========================================")
    if failed:
        print("❌ VERSION CHECK FAILED")
        print("========================================")
        return 1
    print("✅ VERSION CHECK PASSED")
    print("========================================")
    return 0


def _detect_bump_level(base: tuple[int, ...], current: tuple[int, ...]) -> str:
    """Detect whether the version change was major, minor, or patch."""
    if current[0] > base[0]:
        return "major"
    if current[1] > base[1]:
        return "minor"
    return "patch"


def _bump_rank(level: str) -> int:
    """Return a numeric rank for bump levels (higher = more significant)."""
    return {"patch": 0, "minor": 1, "major": 2}.get(level, 0)


def _bump_reason(level: str) -> str:
    """Return a short reason string for a recommended bump level."""
    return {
        "major": "breaking changes detected (removed code, auth, or actions)",
        "minor": "new features detected (new functions, classes, or actions)",
        "patch": "code changes detected",
    }.get(level, "")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check that integration versions are bumped when changes are made.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Exit codes:
  0  Version check passed
  1  Version bump missing or not incremented
  2  An error occurred (invalid git ref)

Examples:
  %(prog)s origin/master my-integration
  %(prog)s origin/master integration-a integration-b
""",
    )
    parser.add_argument("base_ref", help="Git ref to diff against (e.g., origin/master)")
    parser.add_argument("dirs", nargs="+", metavar="dir", help="Integration directories to check")
    args = parser.parse_args()
    return check_version_bump(args.base_ref, args.dirs)


if __name__ == "__main__":
    sys.exit(main())
