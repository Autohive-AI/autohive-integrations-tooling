#!/usr/bin/env python3
"""
Import Availability Checker

Requires: Python 3.12+

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
    - `from . import sibling`   -> resolves to absolute path and checks
    - `from ..pkg import x`     -> resolves to absolute path and checks

Options:
    --verify-names  Enable name verification (imports modules, may execute code)

Usage:
    python scripts/check_imports.py <file.py>
    python scripts/check_imports.py --verify-names <file.py>

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

import argparse
import ast
import importlib
import importlib.util
import sys
from pathlib import Path
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


def find_package_root(filepath: Path) -> Optional[Path]:
    """
    Find the root of the Python package containing the given file.

    Walks up the directory tree looking for the topmost directory
    that still contains an __init__.py file.

    Args:
        filepath: Path to a Python file.

    Returns:
        Path to the package root directory, or None if not in a package.
    """
    filepath = filepath.resolve()
    current = filepath.parent
    package_root = None

    while current != current.parent:
        init_file = current / "__init__.py"
        if init_file.exists():
            package_root = current
            current = current.parent
        else:
            break

    return package_root


def get_package_name(filepath: Path, package_root: Path) -> str:
    """
    Determine the full package name for a file within a package.

    Args:
        filepath: Path to the Python file.
        package_root: Path to the package root directory.

    Returns:
        Dotted package name (e.g., 'mypackage.subpackage.module').
    """
    filepath = filepath.resolve()
    relative = filepath.relative_to(package_root.parent)

    # Remove .py extension and convert path to dotted name
    parts = list(relative.parts)
    if parts[-1].endswith('.py'):
        parts[-1] = parts[-1][:-3]

    return '.'.join(parts)


def resolve_relative_import(
    filepath: Path,
    level: int,
    module: Optional[str]
) -> tuple[Optional[str], Optional[Path]]:
    """
    Resolve a relative import to an absolute module path.

    Args:
        filepath: Path to the file containing the import.
        level: Number of dots in the relative import (1 for '.', 2 for '..', etc.).
        module: The module part after the dots (e.g., 'sibling' in 'from . import sibling'),
                or None for 'from . import x'.

    Returns:
        Tuple of (absolute module path, path to check for file existence).
        Returns (None, None) if resolution fails.
    """
    filepath = Path(filepath).resolve()
    package_root = find_package_root(filepath)

    if package_root is None:
        return None, None

    # Get the current package path
    current_package = get_package_name(filepath, package_root)
    package_parts = current_package.split('.')

    # Remove the module name (last part) to get the package
    package_parts = package_parts[:-1]

    # Go up 'level' directories (level=1 means current package, level=2 means parent, etc.)
    # level > len(package_parts) means we're trying to go above the package root
    if level > len(package_parts):
        return None, None

    # Slice to get the base package after going up 'level' directories
    # e.g., ['mypackage', 'sub'] with level=1 -> ['mypackage', 'sub']
    #       ['mypackage', 'sub'] with level=2 -> ['mypackage']
    base_parts = package_parts[:len(package_parts) - level + 1]

    if module:
        base_parts.append(module)

    # base_parts can be empty if level equals len(package_parts) and no module specified
    # This means "from . import x" at the top-level package with no target module
    if not base_parts:
        return None, None

    # Calculate the file path for this module
    module_path = package_root.parent
    for part in base_parts:
        module_path = module_path / part

    return '.'.join(base_parts), module_path


def is_relative_import_valid(module_path: Path) -> bool:
    """
    Check if a resolved relative import points to an existing module.

    Args:
        module_path: Path to the expected module location.

    Returns:
        True if the module exists as a .py file or package directory.
    """
    # Check if it's a package (directory with __init__.py)
    if module_path.is_dir() and (module_path / "__init__.py").exists():
        return True

    # Check if it's a module file
    py_file = module_path.with_suffix('.py')
    if py_file.is_file():
        return True

    return False


def verify_imported_names(module_name: str, names: List[str]) -> List[str]:
    """
    Verify that specific names exist within a module.

    WARNING: This function imports the module, which executes module-level code.
    Only use with trusted code.

    Args:
        module_name: The module to import and check.
        names: List of names that should exist in the module.

    Returns:
        List of missing names (empty if all exist).
    """
    missing = []
    try:
        module = importlib.import_module(module_name)
        for name in names:
            if not hasattr(module, name):
                missing.append(f"{module_name}.{name}")
    except ImportError:
        # Module itself is missing - handled elsewhere
        pass
    except Exception:
        # Other errors during import - skip name verification
        pass
    return missing


def check_imports(filepath: str, verify_names: bool = False) -> int:
    """
    Check if all imports in a Python file are available in the current environment.

    This function parses the given Python file using the AST module to extract
    all import statements. For each import, it checks whether the full module
    path can be found using importlib.util.find_spec().

    Args:
        filepath: Path to the Python file to check.
        verify_names: If True, also verify that imported names exist within modules.
                      WARNING: This imports modules and may execute code.

    Returns:
        Exit code: 0 if all imports available, 1 if missing imports, 2 if error occurred.

    Note:
        - Full module paths are checked (e.g., 'os.path' is verified, not just 'os')
        - Relative imports are resolved to absolute paths when possible
        - Without verify_names, the file is parsed but never executed (safe for untrusted code)
        - With verify_names, modules are imported which may execute arbitrary code
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
                # Handle relative imports (level > 0 means dots present)
                if node.level > 0:
                    if node.module:
                        # from ..module import name - check the module
                        resolved_name, resolved_path = resolve_relative_import(
                            Path(filepath), node.level, node.module
                        )
                        if resolved_path is None:
                            continue
                        if not is_relative_import_valid(resolved_path):
                            errors.append(f"Missing module: {resolved_name} (relative import)")
                    else:
                        # from . import name - each name is a module to check
                        for alias in node.names:
                            resolved_name, resolved_path = resolve_relative_import(
                                Path(filepath), node.level, alias.name
                            )
                            if resolved_path is None:
                                continue
                            if not is_relative_import_valid(resolved_path):
                                errors.append(f"Missing module: {resolved_name} (relative import)")
                else:
                    # Absolute import
                    if node.module:
                        if not is_module_available(node.module):
                            errors.append(f"Missing module: {node.module}")
                        elif verify_names:
                            # Verify that imported names exist in the module
                            names = [alias.name for alias in node.names]
                            missing = verify_imported_names(node.module, names)
                            for name in missing:
                                errors.append(f"Missing name: {name}")

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


def main() -> int:
    """Parse arguments and run import checking."""
    parser = argparse.ArgumentParser(
        description="Check if all imports in a Python file are available.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exit codes:
  0  All imports are available
  1  One or more imports are missing
  2  An error occurred during processing

Examples:
  %(prog)s my_integration/main.py
  %(prog)s --verify-names my_integration/main.py
        """
    )
    parser.add_argument(
        "filepath",
        help="Path to the Python file to check"
    )
    parser.add_argument(
        "--verify-names",
        action="store_true",
        help="Verify that imported names exist within modules. "
             "WARNING: This imports modules and may execute code."
    )

    args = parser.parse_args()
    return check_imports(args.filepath, verify_names=args.verify_names)


if __name__ == "__main__":
    sys.exit(main())
