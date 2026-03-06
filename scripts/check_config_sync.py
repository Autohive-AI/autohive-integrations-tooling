#!/usr/bin/env python3
"""
Config-Code Sync Checker

Requires: Python 3.13+

This script validates that config.json and the integration's Python code
are in sync. It uses AST parsing to extract action decorators and input
parameter access patterns from the code, then cross-references them
against the config.json action definitions and input schemas.

Checks performed:
    1. Actions in config.json have matching @integration.action() decorators
    2. Decorators in code have matching config.json entries
    3. Input parameters accessed in code exist in the input_schema
    4. Input schema properties are actually used in code
    5. Required/optional consistency between schema and code access patterns

How it determines required vs optional from code:
    - inputs["key"]       -> required (raises KeyError if missing)
    - inputs.get("key")   -> optional (returns None/default if missing)

Usage:
    python scripts/check_config_sync.py <dir> [dir ...]

Exit codes:
    0 - Config and code are in sync (possibly with warnings)
    1 - Mismatches found
    2 - An error occurred (file not found, syntax error, etc.)

Examples:
    python scripts/check_config_sync.py my-integration
    python scripts/check_config_sync.py my-integration another-api
"""

import argparse
import ast
import json
import sys
from pathlib import Path


def extract_actions_from_code(filepath: Path) -> dict[str, dict] | None:
    """Parse a Python file and extract action definitions with their input params.

    Finds all @xxx.action("name") decorated classes, locates their execute()
    method, and extracts inputs["key"] and inputs.get("key") calls.

    Args:
        filepath: Path to the Python entry point file.

    Returns:
        Dict mapping action names to their parameter info:
            {"action_name": {"direct": {"key1"}, "get": {"key2"}}}
        Returns None on parse errors.
    """
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (SyntaxError, OSError):
        return None

    actions: dict[str, dict] = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        # Find @xxx.action("name") decorators
        action_name = None
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "action"
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
                and isinstance(decorator.args[0].value, str)
            ):
                action_name = decorator.args[0].value
                break

        if action_name is None:
            continue

        # Find the execute method
        direct_params: set[str] = set()
        get_params: set[str] = set()

        for item in node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if item.name != "execute":
                continue

            # Walk the execute method for inputs access
            for subnode in ast.walk(item):
                # inputs["key"]
                if (
                    isinstance(subnode, ast.Subscript)
                    and isinstance(subnode.value, ast.Name)
                    and subnode.value.id == "inputs"
                    and isinstance(subnode.slice, ast.Constant)
                    and isinstance(subnode.slice.value, str)
                ):
                    direct_params.add(subnode.slice.value)

                # inputs.get("key") or inputs.get("key", default)
                if (
                    isinstance(subnode, ast.Call)
                    and isinstance(subnode.func, ast.Attribute)
                    and subnode.func.attr == "get"
                    and isinstance(subnode.func.value, ast.Name)
                    and subnode.func.value.id == "inputs"
                    and subnode.args
                    and isinstance(subnode.args[0], ast.Constant)
                    and isinstance(subnode.args[0].value, str)
                ):
                    get_params.add(subnode.args[0].value)

            break  # Only check the first execute method

        actions[action_name] = {"direct": direct_params, "get": get_params}

    return actions


def extract_actions_from_config(config: dict) -> dict[str, dict]:
    """Extract action definitions and schema info from config.json.

    Args:
        config: Parsed config.json dict.

    Returns:
        Dict mapping action names to their schema info:
            {"action_name": {"properties": {"key1", "key2"}, "required": {"key1"}}}
    """
    actions: dict[str, dict] = {}
    config_actions = config.get("actions", {})

    for action_name, action_config in config_actions.items():
        schema = action_config.get("input_schema", {})
        properties = set(schema.get("properties", {}).keys())
        required = set(schema.get("required", []))
        actions[action_name] = {"properties": properties, "required": required}

    return actions


def check_config_sync(dir_path: str) -> int:
    """Check that config.json and code are in sync for an integration directory.

    Args:
        dir_path: Path to the integration directory.

    Returns:
        0 if in sync, 1 if mismatches found, 2 on errors.
    """
    path = Path(dir_path)
    config_path = path / "config.json"

    if not config_path.is_file():
        print(f"No config.json found in {dir_path}")
        return 2

    try:
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Error reading config.json: {e}")
        return 2

    entry_point = config.get("entry_point")
    if not entry_point:
        print("No entry_point defined in config.json")
        return 2

    entry_file = path / entry_point
    if not entry_file.is_file():
        print(f"Entry point not found: {entry_file}")
        return 2

    code_actions: dict[str, dict] = {}
    for pyfile in sorted(path.rglob("*.py")):
        file_actions = extract_actions_from_code(pyfile)
        if file_actions is not None:
            code_actions.update(file_actions)

    config_actions = extract_actions_from_config(config)

    errors: list[str] = []
    warnings: list[str] = []

    # Check 1: Actions in config but not in code
    for action_name in config_actions:
        if action_name not in code_actions:
            errors.append(
                f"Action '{action_name}' defined in config.json but no "
                f'@action("{action_name}") decorator found in code'
            )

    # Check 2: Actions in code but not in config
    for action_name in code_actions:
        if action_name not in config_actions:
            errors.append(f"Action '{action_name}' has @action decorator in code but is not defined in config.json")

    # Check 3-5: Input parameter cross-validation (only for actions in both)
    for action_name in code_actions:
        if action_name not in config_actions:
            continue

        code = code_actions[action_name]
        schema = config_actions[action_name]

        code_params = code["direct"] | code["get"]
        schema_props = schema["properties"]
        schema_required = schema["required"]

        # Params in code but not in schema
        for param in code_params - schema_props:
            warnings.append(
                f"Action '{action_name}': parameter '{param}' accessed in code but not defined in input_schema"
            )

        # Params in schema but not used in code
        for param in schema_props - code_params:
            warnings.append(
                f"Action '{action_name}': parameter '{param}' defined in input_schema but never accessed in code"
            )

        # Required in schema but accessed with .get() in code (inconsistent)
        for param in schema_required & code["get"] - code["direct"]:
            warnings.append(
                f"Action '{action_name}': parameter '{param}' is required "
                f"in schema but accessed with inputs.get() (safe for missing)"
            )

        # Not required in schema but accessed with inputs["key"] (will crash)
        # Skip if also accessed via .get() (likely guarded)
        for param in code["direct"] - schema_required - code["get"]:
            if param in schema_props:
                warnings.append(
                    f"Action '{action_name}': parameter '{param}' is optional "
                    f'in schema but accessed with inputs["{param}"] (will '
                    f"raise KeyError if not provided)"
                )

    # Report results
    if errors:
        for error in errors:
            print(f"❌ {error}")
    if warnings:
        for warning in warnings:
            print(f"⚠️  {warning}")

    if errors:
        return 1
    return 0


def main() -> int:
    """Parse arguments and run config-code sync check."""
    parser = argparse.ArgumentParser(
        description="Check that config.json and code are in sync.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Exit codes:
  0  Config and code are in sync (possibly with warnings)
  1  Mismatches found
  2  An error occurred

Examples:
  %(prog)s my-integration
  %(prog)s my-integration another-api
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
        print(f"Config sync: {dir_path}")
        print(f"{'=' * 60}")

        result = check_config_sync(dir_path)
        if result == 0:
            print("✅ Config and code are in sync")
        if result > exit_code:
            exit_code = result

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
