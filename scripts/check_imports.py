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
    - `import module.submodule` -> checks 'module.submodule' (full path)
    - `from module import name` -> checks 'module'
    - `from pkg.sub import x`   -> checks 'pkg.sub' (full path)

Limitations:
    - Relative imports (from . import x) are skipped (node.module is None)
    - Does not verify that specific names exist within modules

Usage:
    python scripts/check_imports.py <file.py>

Exit codes:
    0 - All imports are available
    1 - One or more imports are missing
    2 - An error occurred during processing (file not found, syntax error, etc.)

Examples:
    $ python scripts/check_imports.py my_integration/main.py
    Missing module: some_unknown_package

    $ python scripts/check_imports.py my_integration/main.py
    (no output = success)
"""

import ast
import sys
import importlib.util
from typing import List, Optional


def is_module_available(module_name: str) -> bool:
    """
    Check if a module (including submodules) is available.

    Attempts to find the module spec for the full module path.
    For submodules, first imports the parent package to ensure
    lazy-loaded submodules can be found.

    Args:
        module_name: Full module path (e.g., 'requests.auth' or 'os.path').

    Returns:
        True if the module is available, False otherwise.
    """
    try:
        # For submodules, we need to import the parent first
        # because some packages use lazy loading
        if '.' in module_name:
            parts = module_name.split('.')
            # Try to import parent packages progressively
            for i in range(1, len(parts)):
                parent = '.'.join(parts[:i])
                try:
                    __import__(parent)
                except ImportError:
                    return False

        spec = importlib.util.find_spec(module_name)
        return spec is not None
    except (ModuleNotFoundError, ValueError, AttributeError, ImportError):
        return False


def check_imports(filepath: str) -> int:
    """
    Check if all imports in a Python file are available in the current environment.

    This function parses the given Python file using the AST module to extract
    all import statements. For each import, it checks whether the full module
    path can be found using importlib.util.find_spec().

    Args:
        filepath: Path to the Python file to check.

    Returns:
        Exit code: 0 if all imports available, 1 if missing imports, 2 if error occurred.

    Note:
        - Full module paths are checked (e.g., 'os.path' is verified, not just 'os')
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
                    # Check full module path (e.g., 'requests.auth')
                    if not is_module_available(alias.name):
                        errors.append(f"Missing module: {alias.name}")

            # Handle: from module import name / from pkg.sub import name
            elif isinstance(node, ast.ImportFrom):
                # node.module is None for relative imports like "from . import x"
                if node.module:
                    # Check full module path
                    if not is_module_available(node.module):
                        errors.append(f"Missing module: {node.module}")

        # Report all missing modules
        if errors:
            for error in errors:
                print(error)
            return 1  # Missing imports

        return 0  # Success - all imports available

    except SyntaxError as e:
        print(f"Syntax error in {filepath}: {e}")
        return 2  # Processing error
    except FileNotFoundError:
        print(f"File not found: {filepath}")
        return 2  # Processing error
    except Exception as e:
        print(f"Error: {e}")
        return 2  # Processing error


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: check_imports.py <file.py>")
        sys.exit(2)  # Usage error is a processing error

    filepath = sys.argv[1]
    sys.exit(check_imports(filepath))
