#!/usr/bin/env python3
"""
Integration Structure Validator

Requires: Python 3.13+

This script validates that integrations follow the required folder structure
and conventions. Run this before submitting a PR to catch common issues.

Usage:
    python scripts/validate_integration.py [dir ...]

    If no directories specified, validates all integration folders.

Exit codes:
    0 - All validations passed (possibly with warnings)
    1 - One or more validation errors found
    2 - An error occurred (folder not found, missing arguments)

Examples:
    python scripts/validate_integration.py my-integration
    python scripts/validate_integration.py my-integration another-api
    python scripts/validate_integration.py
"""

import argparse
import ast
import json
import keyword
import re
import struct
import sys
from pathlib import Path
from typing import Dict, List

from hiveup.core.deployment import is_excluded_development_path
from hiveup.core.discovery import is_ignored_top_level_dir

# Fix Windows console encoding for unicode characters
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

JPEG_START_OF_FRAME_MARKERS = {
    0xC0,
    0xC1,
    0xC2,
    0xC3,
    0xC5,
    0xC6,
    0xC7,
    0xC9,
    0xCA,
    0xCB,
    0xCD,
    0xCE,
    0xCF,
}
RESERVED_ENTRY_POINT_MESSAGE = (
    "entry_point cannot be named main.py because that filename is reserved for the Autohive runtime wrapper"
)
ROOT_ENTRY_POINT_MESSAGE = "entry_point must be a Python file at the integration root"
ENTRY_POINT_IDENTIFIER_MESSAGE = (
    "entry_point filename stem must be a valid, non-keyword Python identifier; "
    "rename the file and update config.json"
)


def is_reserved_entry_point(entry_point: object) -> bool:
    """Return whether an entry-point path uses a runtime-reserved filename."""

    if not isinstance(entry_point, str):
        return False
    return entry_point.replace('\\', '/').rsplit('/', 1)[-1].casefold() == 'main.py'


def is_root_python_entry_point(entry_point: object) -> bool:
    """Return whether an entry point is a root-level relative Python filename."""

    if not isinstance(entry_point, str) or not entry_point:
        return False
    normalized = entry_point.replace('\\', '/')
    return '/' not in normalized and normalized.casefold().endswith('.py')


def has_valid_entry_point_identifier(entry_point: object) -> bool:
    """Return whether an entry-point filename can be imported and exported by stem."""

    if not is_root_python_entry_point(entry_point):
        return False
    stem = Path(entry_point).stem
    return stem.isidentifier() and not keyword.iskeyword(stem)


def _jpeg_dimensions(data: bytes) -> tuple[int, int]:
    if not data.startswith(b'\xff\xd8'):
        raise ValueError("not a valid JPEG file")

    offset = 2
    while offset + 4 <= len(data):
        if data[offset] != 0xFF:
            raise ValueError("not a valid JPEG file")
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            break

        marker = data[offset]
        offset += 1
        if marker in {0x01, *range(0xD0, 0xDA)}:
            continue
        if offset + 2 > len(data):
            break

        segment_length = struct.unpack('>H', data[offset : offset + 2])[0]
        if segment_length < 2 or offset + segment_length > len(data):
            raise ValueError("not a valid JPEG file")
        if marker in JPEG_START_OF_FRAME_MARKERS:
            if segment_length < 7:
                raise ValueError("not a valid JPEG file")
            height, width = struct.unpack('>HH', data[offset + 3 : offset + 7])
            return width, height
        offset += segment_length

    raise ValueError("could not determine JPEG dimensions")


def _is_integration_load(
    value: ast.expr | None,
    integration_names: set[str],
    sdk_module_names: set[str],
) -> bool:
    if not isinstance(value, ast.Call) or not isinstance(value.func, ast.Attribute) or value.func.attr != 'load':
        return False
    owner = value.func.value
    if isinstance(owner, ast.Name):
        return owner.id in integration_names
    return (
        isinstance(owner, ast.Attribute)
        and owner.attr == 'Integration'
        and isinstance(owner.value, ast.Name)
        and owner.value.id in sdk_module_names
    )


class ValidationError:
    """Represents a validation error."""
    def __init__(self, message: str, severity: str = "error"):
        self.message = message
        self.severity = severity  # "error" or "warning"

    def __str__(self):
        prefix = "❌" if self.severity == "error" else "⚠️"
        return f"{prefix} {self.message}"


class IntegrationValidator:
    """Validates an integration folder structure."""

    def __init__(self, integration_path: Path, *, allow_legacy_missing_unit_tests: bool = False):
        self.path = integration_path
        self.name = integration_path.name
        self.allow_legacy_missing_unit_tests = allow_legacy_missing_unit_tests
        self.errors: List[ValidationError] = []
        self.warnings: List[ValidationError] = []
        self.config: Dict = {}

    def add_error(self, message: str):
        """Add an error."""
        self.errors.append(ValidationError(message, "error"))

    def add_warning(self, message: str):
        """Add a warning."""
        self.warnings.append(ValidationError(message, "warning"))

    def validate(self) -> bool:
        """Run all validations. Returns True if no errors."""
        self._check_folder_name()
        self._check_required_files()
        self._check_config_json()
        self._check_init_py()
        self._check_requirements_txt()
        self._check_tests_folder()
        self._check_deployment_symlinks()
        self._check_main_python_file()
        self._check_unused_scopes()

        return len(self.errors) == 0

    def _check_deployment_symlinks(self):
        """Reject source symlinks that packaging cannot include."""
        for source in sorted(self.path.rglob('*')):
            relative = source.relative_to(self.path)
            if is_excluded_development_path(relative):
                continue
            if source.is_symlink():
                self.add_error(f"Deployment source cannot be a symlink: {relative.as_posix()}")

    def _check_folder_name(self):
        """Check that folder name is lowercase."""
        if self.name != self.name.lower():
            self.add_error(f"Folder name must be lowercase: '{self.name}' should be '{self.name.lower()}'")

        # Check for spaces or invalid characters
        if ' ' in self.name:
            self.add_error(f"Folder name cannot contain spaces: '{self.name}'")

        if not re.match(r'^[a-z][a-z0-9-]*$', self.name):
            self.add_warning(f"Folder name should only contain lowercase letters, numbers, and hyphens: '{self.name}'")

    def _check_required_files(self):
        """Check that all required files exist."""
        required_files = [
            ('config.json', 'Integration configuration file'),
            ('requirements.txt', 'Python dependencies file'),
            ('README.md', 'Integration documentation'),
        ]

        for filename, description in required_files:
            required_path = self.path / filename
            if not required_path.exists():
                self.add_error(f"Missing required file: {filename} ({description})")
            elif required_path.is_symlink() or not required_path.is_file():
                self.add_error(f"Required file must be a regular, non-symlink file: {filename}")

        # __init__.py is optional for modular integrations (those with an actions/
        # subdirectory) because adding it causes circular imports when action files
        # use absolute imports like 'from <integration> import <instance>'.
        has_actions_dir = (self.path / 'actions').is_dir()
        if not (self.path / '__init__.py').exists() and not has_actions_dir:
            self.add_warning("Missing __init__.py (required for package-style integrations, optional for modular integrations with actions/)")

        # Check for forbidden files
        if (self.path / 'integration.py').exists():
            self.add_error("Found 'integration.py' — integrations must not include a local integration.py file")

        supported_icon_names = {'icon.png', 'icon.jpg', 'icon.jpeg'}
        icon_path = next(
            (path for path in self.path.iterdir() if path.is_file() and path.name.lower() in supported_icon_names),
            None,
        )
        if icon_path is None:
            self.add_error("Missing required file: icon.png, icon.jpg, or icon.jpeg (Integration icon)")
        elif icon_path.is_symlink():
            self.add_error(f"Integration icon must be a regular, non-symlink file: {icon_path.name}")
        elif icon_path.suffix.lower() == '.png':
            self._check_icon_png_size(icon_path)
        else:
            self._check_icon_jpeg_size(icon_path)

    def _check_icon_png_size(self, path: Path):
        """Validate PNG icon is exactly 512x512."""
        try:
            data = path.read_bytes()
            if data[:8] != b'\x89PNG\r\n\x1a\n':
                self.add_error("icon.png is not a valid PNG file")
                return
            width, height = struct.unpack('>II', data[16:24])
            if width != 512 or height != 512:
                self.add_error(f"icon.png must be 512x512 pixels (found {width}x{height})")
        except Exception as e:
            self.add_error(f"Could not read icon.png: {e}")

    def _check_icon_jpeg_size(self, path: Path):
        """Validate JPEG icon is exactly 512x512."""
        try:
            width, height = _jpeg_dimensions(path.read_bytes())
            if width != 512 or height != 512:
                self.add_error(f"{path.name} must be 512x512 pixels (found {width}x{height})")
        except Exception as e:
            self.add_error(f"Could not read {path.name}: {e}")

    def _check_config_json(self):
        """Validate config.json structure."""
        config_path = self.path / 'config.json'
        if not config_path.exists():
            return  # Already reported in required files check

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
        except json.JSONDecodeError as e:
            self.add_error(f"config.json is not valid JSON: {e}")
            return

        # Check required top-level fields
        required_fields = ['name', 'version', 'description', 'entry_point', 'actions']
        for field in required_fields:
            if field not in self.config:
                self.add_error(f"config.json missing required field: '{field}'")

        # Check display_name is present and non-empty
        if 'display_name' not in self.config or not self.config['display_name'].strip():
            self.add_warning("config.json missing recommended field: 'display_name'")

        # Check entry_point exists
        if 'entry_point' in self.config:
            entry_point = self.config['entry_point']
            if is_reserved_entry_point(entry_point):
                self.add_error(RESERVED_ENTRY_POINT_MESSAGE)
            if not is_root_python_entry_point(entry_point):
                self.add_error(ROOT_ENTRY_POINT_MESSAGE)
            elif not has_valid_entry_point_identifier(entry_point):
                self.add_error(ENTRY_POINT_IDENTIFIER_MESSAGE)
            elif not (self.path / entry_point).exists():
                self.add_error(f"entry_point file does not exist: {entry_point}")
            elif (self.path / entry_point).is_symlink() or not (self.path / entry_point).is_file():
                self.add_error(f"entry_point must be a regular, non-symlink file: {entry_point}")

        # Check version format
        if 'version' in self.config:
            version = self.config['version']
            if not re.match(r'^\d+\.\d+\.\d+$', version):
                self.add_warning(f"Version should follow semantic versioning (x.y.z): '{version}'")

        # Check auth configuration
        self._validate_auth_config()

        # Check actions
        self._validate_actions_config()

    def _validate_auth_config(self):
        """Validate auth configuration in config.json."""
        if 'auth' not in self.config:
            return  # No auth is valid for public APIs

        auth = self.config['auth']
        auth_type = auth.get('type')

        if auth_type == 'platform':
            if 'provider' not in auth:
                self.add_error("Platform auth requires 'provider' field")
            if 'scopes' in auth and not isinstance(auth['scopes'], list):
                self.add_error("auth.scopes must be an array")

        elif auth_type == 'custom':
            if 'fields' not in auth:
                self.add_error("Custom auth requires 'fields' configuration")
            elif 'properties' not in auth.get('fields', {}):
                self.add_error("Custom auth fields must have 'properties' defined")

        elif auth_type is not None:
            self.add_warning(f"Unknown auth type: '{auth_type}'. Expected 'platform' or 'custom'")

    def _validate_actions_config(self):
        """Validate actions configuration in config.json."""
        if 'actions' not in self.config:
            return

        actions = self.config['actions']
        if not isinstance(actions, dict):
            self.add_error("'actions' must be an object")
            return

        if len(actions) == 0:
            self.add_error("At least one action must be defined")

        for action_name, action_config in actions.items():
            # Check action name format
            if action_name != action_name.lower():
                self.add_warning(f"Action name should be snake_case: '{action_name}'")

            # Check required action fields
            if 'display_name' not in action_config:
                self.add_warning(f"Action '{action_name}' missing 'display_name'")

            if 'description' not in action_config:
                self.add_warning(f"Action '{action_name}' missing 'description'")

            # Check schemas
            if 'input_schema' not in action_config:
                self.add_warning(f"Action '{action_name}' missing 'input_schema'")

            if 'output_schema' not in action_config:
                self.add_warning(f"Action '{action_name}' missing 'output_schema'")

    def _check_init_py(self):
        """Check that __init__.py is minimal."""
        init_path = self.path / '__init__.py'
        if not init_path.exists():
            return

        with open(init_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Remove comments and empty lines for analysis
        lines = [line.strip() for line in content.split('\n')
                 if line.strip() and not line.strip().startswith('#')]

        # Should only have import and __all__
        allowed_patterns = [
            r'^from\s+\.\w+\s+import\s+\w+',  # from .module import name
            r'^__all__\s*=',  # __all__ = [...]
        ]

        for line in lines:
            is_allowed = any(re.match(pattern, line) for pattern in allowed_patterns)
            if not is_allowed:
                self.add_warning(f"__init__.py should be minimal (only import and __all__). Found: '{line[:50]}...'")
                break

    # Minimum supported SDK versions per major release line.
    # Integrations pinning older versions will receive a deprecation warning.
    _MIN_SDK_VERSIONS = {
        1: (1, 1, 1),   # 1.x line: minimum 1.1.1
        2: (2, 0, 1),   # 2.x line: minimum 2.0.1
    }

    def _check_requirements_txt(self):
        """Check requirements.txt has SDK dependency with a supported version pin."""
        req_path = self.path / 'requirements.txt'
        if not req_path.exists():
            return

        with open(req_path, 'r', encoding='utf-8') as f:
            content = f.read()

        if 'autohive-integrations-sdk' not in content:
            self.add_error("requirements.txt must include 'autohive-integrations-sdk'")
            return

        # Extract version pin — accept ~= or == operators
        match = re.search(r'autohive-integrations-sdk\s*(~=|==)\s*(\d+\.\d+(?:\.\d+)?)', content)
        if not match:
            self.add_warning(
                "requirements.txt should pin SDK version "
                "(e.g., autohive-integrations-sdk~=2.0.1)"
            )
            return

        operator, version_str = match.group(1), match.group(2)
        parts = tuple(int(p) for p in version_str.split('.'))
        # Normalise to 3-part tuple
        while len(parts) < 3:
            parts = (*parts, 0)
        major = parts[0]

        min_version = self._MIN_SDK_VERSIONS.get(major)
        if min_version is None:
            self.add_warning(
                f"Unknown SDK major version {major} in requirements.txt — "
                f"expected major version {', '.join(str(v) for v in sorted(self._MIN_SDK_VERSIONS))}"
            )
        elif parts < min_version:
            min_str = '.'.join(str(v) for v in min_version)
            self.add_warning(
                f"SDK version {version_str} is deprecated — "
                f"upgrade to autohive-integrations-sdk{operator}{min_str} or later"
            )

    def _check_tests_folder(self):
        """Check tests folder structure."""
        tests_path = self.path / 'tests'

        if not tests_path.exists():
            self.add_error("Missing 'tests/' folder")
            return

        if not tests_path.is_dir():
            self.add_error("'tests' must be a directory")
            return

        # Check required test files
        if not (tests_path / '__init__.py').exists():
            self.add_error("Missing tests/__init__.py (Test package init — can be empty)")

        # Accept either context.py (legacy import setup) or conftest.py (pytest fixture setup)
        if not (tests_path / 'context.py').exists() and not (tests_path / 'conftest.py').exists():
            self.add_error("Missing tests/context.py or tests/conftest.py (test import/fixture setup)")

        # Unit-test execution discovers only files with the _unit.py suffix.
        test_files = list(tests_path.glob('test_*_unit.py'))
        if not test_files:
            message = "Missing unit test file: tests/test_*_unit.py"
            if self.allow_legacy_missing_unit_tests:
                self.add_warning(message)
            else:
                self.add_error(message)

    def _check_main_python_file(self):
        """Check main Python file and integration modules for required patterns."""
        if 'entry_point' not in self.config:
            return

        entry_point = self.config['entry_point']
        if not is_root_python_entry_point(entry_point) or not has_valid_entry_point_identifier(entry_point):
            return  # Already reported by the config check.
        main_file = self.path / entry_point
        if not main_file.exists():
            return  # Already reported

        self._check_entry_point_export(main_file)

        # Collect content from all .py files in the integration directory
        all_content = ""
        for pyfile in sorted(self.path.rglob("*.py")):
            with open(pyfile, 'r', encoding='utf-8') as f:
                all_content += f.read() + "\n"

        # Check for required imports across all Python files
        required_imports = [
            ('Integration', 'from autohive_integrations_sdk'),
            ('ActionHandler', 'from autohive_integrations_sdk'),
        ]

        for item, source in required_imports:
            if item not in all_content:
                self.add_warning(f"Integration may be missing import: {item} ({source})")

        # Check for Integration.load(...) across all Python files.
        if 'Integration.load' not in all_content:
            self.add_warning("Integration should use 'Integration.load(...)' to load the integration")

    def _check_entry_point_export(self, main_file: Path):
        """Check the runtime wrapper's expected integration export without importing code."""
        try:
            tree = ast.parse(main_file.read_text(encoding='utf-8'), filename=str(main_file))
        except (OSError, SyntaxError):
            return  # Reported by the syntax or file checks.

        integration_names = {'Integration'}
        sdk_module_names = {'autohive_integrations_sdk'}
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == 'autohive_integrations_sdk':
                integration_names.update(
                    alias.asname or alias.name
                    for alias in node.names
                    if alias.name == 'Integration'
                )
            elif isinstance(node, ast.Import):
                sdk_module_names.update(
                    alias.asname or alias.name
                    for alias in node.names
                    if alias.name == 'autohive_integrations_sdk'
                )

        expected_name = main_file.stem
        for node in tree.body:
            if isinstance(node, ast.Assign):
                defines_expected_name = any(
                    isinstance(target, ast.Name) and target.id == expected_name
                    for target in node.targets
                )
                value = node.value
            elif isinstance(node, ast.AnnAssign):
                defines_expected_name = isinstance(node.target, ast.Name) and node.target.id == expected_name
                value = node.value
            else:
                continue
            if defines_expected_name and _is_integration_load(value, integration_names, sdk_module_names):
                return

        self.add_error(
            f"entry point {main_file.name} must define "
            f"'{expected_name} = Integration.load(...)' at module scope"
        )

    def _check_unused_scopes(self):
        """Check for potentially unused scopes."""
        if 'auth' not in self.config:
            return

        auth = self.config['auth']
        if auth.get('type') != 'platform' or 'scopes' not in auth:
            return

        scopes = auth['scopes']
        actions = self.config.get('actions', {})

        # This is a basic heuristic check - we look for scope keywords in action names/descriptions
        # A more thorough check would require understanding the API documentation

        scope_keywords = {}
        for scope in scopes:
            # Extract keywords from scope (e.g., "read:sites" -> ["read", "sites"])
            keywords = re.split(r'[:\._-]', scope.lower())
            scope_keywords[scope] = keywords

        # Get action keywords
        action_text = ""
        for action_name, action_config in actions.items():
            action_text += f" {action_name} "
            action_text += f" {action_config.get('description', '')} "
            action_text += f" {action_config.get('display_name', '')} "
        action_text = action_text.lower()

        # Check each scope for potential usage
        potentially_unused = []
        for scope, keywords in scope_keywords.items():
            # Check if any meaningful keyword from the scope appears in action text
            meaningful_keywords = [k for k in keywords if len(k) > 3 and k not in ['read', 'write', 'admin', 'api']]
            if meaningful_keywords:
                found = any(keyword in action_text for keyword in meaningful_keywords)
                if not found:
                    potentially_unused.append(scope)

        if potentially_unused:
            self.add_warning(f"Potentially unused scopes (please verify): {', '.join(potentially_unused)}")

    def print_results(self):
        """Print validation results."""
        print(f"\n{'='*60}")
        print(f"Integration: {self.name}")
        print(f"{'='*60}")

        if not self.errors and not self.warnings:
            print("✅ All checks passed!")
            return

        if self.errors:
            print(f"\nErrors ({len(self.errors)}):")
            for error in self.errors:
                print(f"  {error}")

        if self.warnings:
            print(f"\nWarnings ({len(self.warnings)}):")
            for warning in self.warnings:
                print(f"  {warning}")


def get_integration_folders(root_path: Path) -> List[Path]:
    """Get all integration folders in the repository."""
    folders = []
    for item in root_path.iterdir():
        if item.is_dir() and not is_ignored_top_level_dir(item):
            # Check if it looks like an integration (has config.json or main py file)
            if (item / 'config.json').exists() or list(item.glob('*.py')):
                folders.append(item)
    return sorted(folders)


def validate(dirs: list[str]) -> int:
    """Validate the given integration directories.

    Args:
        dirs: List of directory names to validate. If empty, auto-discovers
              integration folders at the repository root.

    Returns:
        0 if all validations passed, 1 if errors found, 2 on processing errors.
    """
    if dirs:
        folders = []
        for folder_name in dirs:
            folder_path = Path(folder_name)
            if folder_path.exists() and folder_path.is_dir():
                if not is_ignored_top_level_dir(folder_path):
                    folders.append(folder_path)
            else:
                print(f"⚠️ Folder not found (renamed or removed?): {folder_name} — skipping")
    else:
        folders = get_integration_folders(Path.cwd())

    if not folders:
        print("No integration folders to validate.")
        return 0

    print(f"Validating {len(folders)} integration(s)...")

    total_errors = 0
    total_warnings = 0

    for folder in folders:
        # The compatibility CLI has no history input, so preserve the legacy
        # validator's permissive treatment of non-canonical test filenames.
        validator = IntegrationValidator(folder, allow_legacy_missing_unit_tests=True)
        validator.validate()
        validator.print_results()

        total_errors += len(validator.errors)
        total_warnings += len(validator.warnings)

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"Integrations validated: {len(folders)}")
    print(f"Total errors: {total_errors}")
    print(f"Total warnings: {total_warnings}")

    if total_errors > 0:
        print("\n❌ Validation FAILED - please fix errors before submitting PR")
        return 1
    elif total_warnings > 0:
        print("\n⚠️ Validation passed with warnings - please review")
        return 0
    else:
        print("\n✅ All validations passed!")
        return 0


def main() -> int:
    """Parse arguments and run validation."""
    parser = argparse.ArgumentParser(
        description="Validate integration folder structure and configuration.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Exit codes:
  0  All validations passed (possibly with warnings)
  1  One or more validation errors found
  2  An error occurred (folder not found)

Examples:
  %(prog)s my-integration
  %(prog)s my-integration another-api
  %(prog)s
""",
    )
    parser.add_argument(
        "dirs",
        nargs="*",
        metavar="dir",
        help="Integration directories to validate. If omitted, auto-discovers all.",
    )

    args = parser.parse_args()
    return validate(args.dirs)


if __name__ == '__main__':
    sys.exit(main())
