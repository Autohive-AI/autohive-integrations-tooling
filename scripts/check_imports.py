#!/usr/bin/env python3
"""
Import Availability Checker

This script validates that all imports in a Python file can be resolved
in the current Python environment. It uses AST (Abstract Syntax Tree)
parsing to extract import statements without executing the code.

How it works:
    1. Reads the Python source file
    2. Parses it into an AST (no code execution)
    3. Walks the AST to find all Import and ImportFrom nodes
    4. For each import, checks if the top-level module is available
       using importlib.util.find_spec()
    5. Reports any missing modules

Supported import styles:
    - `import module`           -> checks 'module'
    - `import module.submodule` -> checks 'module' (top-level only)
    - `from module import name` -> checks 'module'
    - `from pkg.sub import x`   -> checks 'pkg' (top-level only)

Limitations:
    - Only checks if the top-level package exists, not submodules
    - Relative imports (from . import x) are skipped (node.module is None)
    - Does not verify that specific names exist within modules

Usage:
    python scripts/check_imports.py <file.py>

Exit codes:
    0 - All imports are available
    1 - One or more imports are missing or an error occurred

Examples:
    $ python scripts/check_imports.py my_integration/main.py
    Missing module: some_unknown_package

    $ python scripts/check_imports.py my_integration/main.py
    (no output = success)
"""

import ast
import sys
import importlib.util
from typing import List


def check_imports(filepath: str) -> bool:
    """
    Check if all imports in a Python file are available in the current environment.

    This function parses the given Python file using the AST module to extract
    all import statements. For each import, it checks whether the top-level
    module can be found using importlib.util.find_spec().

    Args:
        filepath: Path to the Python file to check.

    Returns:
        True if all imports are available, False if any are missing or on error.

    Note:
        - Only the top-level module is checked (e.g., for 'os.path', only 'os' is verified)
        - Relative imports (from . import x) are skipped since they depend on package context
        - The file is parsed but never executed, making this safe for untrusted code
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            source_code = f.read()

        # Parse source into AST - this validates syntax without executing code
        tree = ast.parse(source_code)

        errors: List[str] = []

        # Walk all nodes in the AST looking for import statements
        for node in ast.walk(tree):

            # Handle: import module / import module.submodule / import mod as alias
            if isinstance(node, ast.Import):
                for alias in node.names:
                    # Extract top-level module (e.g., 'requests' from 'requests.auth')
                    top_level_module = alias.name.split('.')[0]

                    # Check if module exists in current Python environment
                    if importlib.util.find_spec(top_level_module) is None:
                        errors.append(f"Missing module: {alias.name}")

            # Handle: from module import name / from pkg.sub import name
            elif isinstance(node, ast.ImportFrom):
                # node.module is None for relative imports like "from . import x"
                if node.module:
                    # Extract top-level module
                    top_level_module = node.module.split('.')[0]

                    if importlib.util.find_spec(top_level_module) is None:
                        errors.append(f"Missing module: {node.module}")

        # Report all missing modules
        if errors:
            for error in errors:
                print(error)
            return False

        return True

    except SyntaxError as e:
        print(f"Syntax error in {filepath}: {e}")
        return False
    except FileNotFoundError:
        print(f"File not found: {filepath}")
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: check_imports.py <file.py>")
        sys.exit(1)

    filepath = sys.argv[1]

    if check_imports(filepath):
        sys.exit(0)  # Success - all imports available
    else:
        sys.exit(1)  # Failure - missing imports or error
