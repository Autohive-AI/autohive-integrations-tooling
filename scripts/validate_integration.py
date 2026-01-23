#!/usr/bin/env python3
"""
Integration Structure Validator

This script validates that integrations follow the required folder structure
and conventions. Run this before submitting a PR to catch common issues.

Usage:
    python scripts/validate_integration.py [integration_folder ...]

    If no folders specified, validates all integration folders.
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# Fix Windows console encoding for unicode characters
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# Folders to skip during validation
SKIP_FOLDERS = {
    '.github',
    '.git',
    'scripts',
    'template-structure',
    '__pycache__',
    '.vscode',
    '.idea',
    'node_modules',
}

# Files to skip at root level
SKIP_FILES = {
    'README.md',
    'INTEGRATION_CHECKLIST.md',
    '.gitignore',
    'LICENSE',
}


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

    def __init__(self, integration_path: Path):
        self.path = integration_path
        self.name = integration_path.name
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
        self._check_main_python_file()
        self._check_unused_scopes()

        return len(self.errors) == 0

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
            ('__init__.py', 'Python package init file'),
            ('requirements.txt', 'Python dependencies file'),
            ('README.md', 'Integration documentation'),
        ]

        for filename, description in required_files:
            if not (self.path / filename).exists():
                self.add_error(f"Missing required file: {filename} ({description})")

        # Check for icon (png or svg)
        has_icon = (self.path / 'icon.png').exists() or (self.path / 'icon.svg').exists()
        if not has_icon:
            self.add_error("Missing required file: icon.png or icon.svg (Integration icon)")

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

        # Check name matches folder
        if 'name' in self.config:
            config_name = self.config['name'].lower().replace('_', '-')
            folder_name = self.name.lower().replace('_', '-')
            if config_name != folder_name:
                self.add_warning(f"config.json 'name' ({self.config['name']}) doesn't match folder name ({self.name})")

        # Check entry_point exists
        if 'entry_point' in self.config:
            entry_point = self.config['entry_point']
            if not (self.path / entry_point).exists():
                self.add_error(f"entry_point file does not exist: {entry_point}")

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

    def _check_requirements_txt(self):
        """Check requirements.txt has SDK dependency."""
        req_path = self.path / 'requirements.txt'
        if not req_path.exists():
            return

        with open(req_path, 'r', encoding='utf-8') as f:
            content = f.read()

        if 'autohive-integrations-sdk' not in content:
            self.add_error("requirements.txt must include 'autohive-integrations-sdk'")
        elif 'autohive-integrations-sdk~=1.0' not in content and 'autohive-integrations-sdk==' not in content:
            self.add_warning("requirements.txt should pin SDK version (e.g., autohive-integrations-sdk~=1.0.2)")

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
        required_test_files = [
            ('__init__.py', 'Test package init (can be empty)'),
            ('context.py', 'Test context/import setup'),
        ]

        for filename, description in required_test_files:
            if not (tests_path / filename).exists():
                self.add_error(f"Missing tests/{filename} ({description})")

        # Check for at least one test file
        test_files = list(tests_path.glob('test_*.py'))
        if not test_files:
            self.add_error("Missing test file: tests/test_*.py")

    def _check_main_python_file(self):
        """Check main Python file structure."""
        if 'entry_point' not in self.config:
            return

        main_file = self.path / self.config['entry_point']
        if not main_file.exists():
            return  # Already reported

        with open(main_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Check for required imports
        required_imports = [
            ('Integration', 'from autohive_integrations_sdk'),
            ('ActionHandler', 'from autohive_integrations_sdk'),
        ]

        for item, source in required_imports:
            if item not in content:
                self.add_warning(f"Main file may be missing import: {item} ({source})")

        # Check for Integration.load()
        if 'Integration.load()' not in content:
            self.add_warning("Main file should use 'Integration.load()' to load the integration")

        # Check for action decorators matching config
        if 'actions' in self.config:
            for action_name in self.config['actions'].keys():
                decorator_pattern = f'@\\w+\\.action\\(["\']?{action_name}["\']?\\)'
                if not re.search(decorator_pattern, content):
                    self.add_warning(f"Action '{action_name}' defined in config but no matching @integration.action decorator found")

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
        if item.is_dir() and item.name not in SKIP_FOLDERS and not item.name.startswith('.'):
            # Check if it looks like an integration (has config.json or main py file)
            if (item / 'config.json').exists() or list(item.glob('*.py')):
                folders.append(item)
    return sorted(folders)


def main():
    """Main entry point."""
    root_path = Path(__file__).parent.parent

    # Get folders to validate
    if len(sys.argv) > 1:
        # Validate specific folders passed as arguments
        folders = []
        for folder_name in sys.argv[1:]:
            folder_name = folder_name.strip()
            if not folder_name:
                continue
            folder_path = root_path / folder_name
            if folder_path.exists() and folder_path.is_dir():
                if folder_name not in SKIP_FOLDERS:
                    folders.append(folder_path)
            else:
                print(f"⚠️ Folder not found: {folder_name}")
    else:
        # Validate all integration folders
        folders = get_integration_folders(root_path)

    if not folders:
        print("No integration folders to validate.")
        sys.exit(0)

    print(f"Validating {len(folders)} integration(s)...")

    total_errors = 0
    total_warnings = 0

    for folder in folders:
        validator = IntegrationValidator(folder)
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
        sys.exit(1)
    elif total_warnings > 0:
        print("\n⚠️ Validation passed with warnings - please review")
        sys.exit(0)
    else:
        print("\n✅ All validations passed!")
        sys.exit(0)


if __name__ == '__main__':
    main()
