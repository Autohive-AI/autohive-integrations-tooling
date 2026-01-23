#!/usr/bin/env python3
"""Check if all imports in a Python file are available."""

import ast
import sys
import importlib.util


def check_imports(filepath):
    """Check if all imports in the file are available."""
    try:
        with open(filepath, 'r') as f:
            tree = ast.parse(f.read())

        errors = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module = alias.name.split('.')[0]
                    if importlib.util.find_spec(module) is None:
                        errors.append(f"Missing module: {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    module = node.module.split('.')[0]
                    if importlib.util.find_spec(module) is None:
                        errors.append(f"Missing module: {node.module}")

        if errors:
            for e in errors:
                print(e)
            return False
        return True

    except Exception as e:
        print(f"Error: {e}")
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: check_imports.py <file.py>")
        sys.exit(1)

    filepath = sys.argv[1]
    if check_imports(filepath):
        sys.exit(0)
    else:
        sys.exit(1)
