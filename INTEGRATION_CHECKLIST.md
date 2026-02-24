# Integration Checklist

Use this checklist to verify your new integration follows all conventions and is ready for PR review.

---

## Quick Summary

| Check | Description |
|-------|-------------|
| [Folder Structure](#1-folder-structure) | Correct files in correct locations |
| [config.json](#2-configjson-validation) | Valid schema, descriptions, scopes |
| [\_\_init\_\_.py](#3-initpy-files) | Must be minimal/empty |
| [Main Python File](#4-main-python-file) | Correct patterns and conventions |
| [Tests](#5-test-files) | Proper test structure |
| [Requirements](#6-requirementstxt) | SDK dependency present |
| [README](#7-readmemd-required) | Documentation complete |
| [Icon](#8-icon-required) | Integration icon present |
| [Main README Update](#9-main-readme-update-required) | Add integration to repo README |
| [Cleanup](#10-cleanup-checks) | No unused code or scopes |

---

## 1. Folder Structure

### Required Files
- [ ] Integration folder is **lowercase** (e.g., `netlify/`, `shopify-admin/`)
- [ ] `config.json` exists in root of integration folder
- [ ] `{integration_name}.py` exists (main implementation)
- [ ] `__init__.py` exists in root of integration folder
- [ ] `requirements.txt` exists
- [ ] `README.md` exists **(REQUIRED)**
- [ ] `icon.png` or `icon.svg` exists **(REQUIRED)**
- [ ] `tests/` folder exists with:
  - [ ] `tests/__init__.py` (can be empty)
  - [ ] `tests/context.py` (import setup)
  - [ ] `tests/test_{integration_name}.py` (test suite)

### Complete Folder Structure
```
integration-name/
├── __init__.py              (Required - minimal)
├── config.json              (Required - integration config)
├── {integration_name}.py    (Required - main implementation)
├── icon.png or icon.svg     (Required - integration icon)
├── requirements.txt         (Required - dependencies)
├── README.md                (Required - documentation)
└── tests/
    ├── __init__.py          (Required - can be empty)
    ├── context.py           (Required - import setup)
    └── test_{name}.py       (Required - test suite)
```

### Folder Naming Convention
```
# CORRECT
netlify/
shopify-admin/
google-sheets/

# WRONG
Netlify/
ShopifyAdmin/
GoogleSheets/
```

---

## 2. config.json Validation

### Required Top-Level Fields
- [ ] `"name"` - lowercase, matches folder name
- [ ] `"version"` - semantic version (e.g., `"1.0.0"`)
- [ ] `"description"` - clear, concise description
- [ ] `"entry_point"` - matches main Python file name exactly
- [ ] `"actions"` - at least one action defined

### Optional Top-Level Fields
- [ ] `"display_name"` - human-readable name
- [ ] `"supports_billing"` - boolean (default: false)
- [ ] `"supports_connected_account"` - boolean (default: false)
- [ ] `"polling_triggers"` - object (if needed)

---

### Auth Configuration

#### For Platform Auth (OAuth2)
- [ ] `auth.type` is `"platform"`
- [ ] `auth.provider` matches valid provider name
- [ ] `auth.scopes` is an array of strings
- [ ] **All scopes are actually USED** (see [Scope Validation](#scope-validation))

```json
"auth": {
  "type": "platform",
  "provider": "netlify",
  "scopes": ["read:sites", "write:sites"]
}
```

#### For Custom Auth (API Key/Token)
- [ ] `auth.type` is `"custom"`
- [ ] `auth.title` is descriptive
- [ ] `auth.fields.type` is `"object"`
- [ ] `auth.fields.properties` defines all credential fields
- [ ] `auth.fields.required` lists mandatory fields
- [ ] Each field has `type`, `label`, and `help_text`
- [ ] Password fields use `"format": "password"`

```json
"auth": {
  "type": "custom",
  "title": "API Token Authentication",
  "fields": {
    "type": "object",
    "properties": {
      "api_token": {
        "type": "string",
        "format": "password",
        "label": "API Token",
        "help_text": "Find your API token at https://example.com/settings"
      }
    },
    "required": ["api_token"]
  }
}
```

#### For No Auth (Public APIs)
- [ ] `auth` field is omitted entirely

---

### Action Configuration

For **each action** in `config.json`:

- [ ] Action key is `snake_case` (e.g., `list_customers`, `create_site`)
- [ ] `display_name` is human-readable
- [ ] `description` clearly explains what the action does
- [ ] `input_schema` is valid JSON Schema
- [ ] `output_schema` is valid JSON Schema
- [ ] `input_schema.required` lists all mandatory parameters
- [ ] All parameters have `type` and `description`
- [ ] Optional parameters have sensible `default` values
- [ ] Numeric parameters have `minimum`/`maximum` when appropriate

```json
"list_customers": {
  "display_name": "List Customers",
  "description": "Retrieves a list of customers from the account",
  "input_schema": {
    "type": "object",
    "properties": {
      "limit": {
        "type": "integer",
        "description": "Maximum number of customers to return",
        "default": 10,
        "minimum": 1,
        "maximum": 100
      }
    },
    "required": []
  },
  "output_schema": {
    "type": "object",
    "properties": {
      "result": {
        "type": "boolean",
        "description": "Whether the operation was successful"
      },
      "customers": {
        "type": "array",
        "description": "List of customer objects"
      },
      "error": {
        "type": "string",
        "description": "Error message if result is false"
      }
    }
  }
}
```

---

### Scope Validation

**CRITICAL: Remove unused scopes!**

- [ ] List all scopes in `auth.scopes`
- [ ] For each scope, verify it's required by at least one action
- [ ] Remove any scope that isn't used

#### How to Check:
1. Look at the API documentation for the service
2. Match each action's API endpoint to required scopes
3. Remove scopes that don't correspond to any implemented action

```
Example - If you have these scopes:
  ["read:sites", "write:sites", "delete:sites", "read:users"]

But only implement list_sites and create_site actions:
  - read:sites    -> KEEP (used by list_sites)
  - write:sites   -> KEEP (used by create_site)
  - delete:sites  -> REMOVE (no delete action)
  - read:users    -> REMOVE (no user actions)
```

---

## 3. __init__.py Files

### Root `__init__.py`

**Must be minimal!** Only import and export the integration.

- [ ] Contains only import statement and `__all__`
- [ ] No additional code, comments, or logic
- [ ] Import name matches the integration variable name

```python
# CORRECT
from .netlify import netlify

__all__ = ["netlify"]
```

```python
# WRONG - too much code
from .netlify import netlify
import logging

logger = logging.getLogger(__name__)
print("Loading netlify integration...")

__all__ = ["netlify"]
```

### `tests/__init__.py`

- [ ] File exists
- [ ] Can be completely empty OR minimal imports
- [ ] No test code in this file

```python
# CORRECT - empty file or just a comment
# Tests package
```

---

## 4. Main Python File

### File Naming
- [ ] File named `{integration_name}.py`
- [ ] Name matches `entry_point` in config.json
- [ ] Name uses `snake_case` (e.g., `shopify_admin.py`)

### Required Imports
- [ ] `Integration` from `autohive_integrations_sdk`
- [ ] `ExecutionContext` from `autohive_integrations_sdk`
- [ ] `ActionHandler` from `autohive_integrations_sdk`
- [ ] `ActionResult` from `autohive_integrations_sdk`
- [ ] `Dict, Any` from `typing`

```python
from autohive_integrations_sdk import (
    Integration,
    ExecutionContext,
    ActionHandler,
    ActionResult
)
from typing import Dict, Any
```

### Integration Loading
- [ ] Integration loaded using `Integration.load()`
- [ ] Variable name matches import in `__init__.py`

```python
netlify = Integration.load()
```

### Action Handlers

For **each action**:
- [ ] Decorator matches action key in config.json: `@integration.action("action_name")`
- [ ] Class name is PascalCase with "Action" suffix: `ActionNameAction`
- [ ] Class extends `ActionHandler`
- [ ] Has docstring describing the action
- [ ] Implements `async def execute(self, inputs: Dict[str, Any], context: ExecutionContext)`

```python
@netlify.action("list_sites")
class ListSitesAction(ActionHandler):
    """Lists all sites in the Netlify account."""

    async def execute(self, inputs: Dict[str, Any], context: ExecutionContext):
        # Implementation
```

### Authentication Handling

#### Platform Auth
- [ ] Uses `context.fetch()` directly (auth is automatic)
- [ ] Does NOT manually add Authorization header

```python
# CORRECT for platform auth
response = await context.fetch(url, method="GET")
```

#### Custom Auth
- [ ] Extracts credentials from `context.auth['credentials']`
- [ ] Builds Authorization header manually
- [ ] Handles missing credentials gracefully

```python
# CORRECT for custom auth
def get_headers(context: ExecutionContext) -> Dict[str, str]:
    credentials = context.auth.get("credentials", {})
    api_token = credentials.get("api_token", "")
    return {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json"
    }
```

### Return Values
- [ ] All actions return `ActionResult` (preferred) or `dict`
- [ ] Success response includes `"result": True`
- [ ] Error response includes `"result": False` and `"error"` message
- [ ] Uses try/except for error handling

```python
# CORRECT
try:
    response = await context.fetch(url, method="GET")
    return ActionResult(
        data={"result": True, "data": response},
        cost_usd=0.0
    )
except Exception as e:
    return ActionResult(
        data={"result": False, "error": str(e)},
        cost_usd=0.0
    )
```

### Code Quality
- [ ] No hardcoded API keys or secrets
- [ ] Constants defined at module level (BASE_URL, etc.)
- [ ] Helper functions are well-named and documented
- [ ] No unused imports
- [ ] No unused functions or classes
- [ ] Type hints on all function parameters

---

## 5. Test Files

### `tests/context.py`
- [ ] Sets up proper import path
- [ ] Imports the integration correctly

```python
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from integration_name import integration_name
```

### `tests/test_{integration_name}.py`
- [ ] Imports asyncio
- [ ] Imports from context.py
- [ ] Imports ExecutionContext from SDK

```python
import asyncio
from context import integration_name
from autohive_integrations_sdk import ExecutionContext
```

- [ ] Each action has at least one test function
- [ ] Test functions are `async def`
- [ ] Tests use `ExecutionContext` with proper auth structure
- [ ] Tests call `integration.execute_action(action_name, inputs, context)`
- [ ] Tests include assertions on expected output
- [ ] Tests handle exceptions with try/except
- [ ] Has `run_all_tests()` function to execute all tests
- [ ] Has `if __name__ == "__main__":` block

```python
async def test_list_sites():
    """Test listing sites."""
    auth = {
        "auth_type": "PlatformOauth2",
        "credentials": {"access_token": "test_token"}
    }

    async with ExecutionContext(auth=auth) as context:
        try:
            result = await integration.execute_action(
                "list_sites",
                {},
                context
            )

            data = result.data
            assert data.get('result') == True
            print(f"Sites: {data.get('sites', [])}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(run_all_tests())
```

### Auth Structure in Tests

#### Platform Auth
```python
auth = {
    "auth_type": "PlatformOauth2",
    "credentials": {"access_token": "your_token"}
}
```

#### Custom Auth
```python
auth = {
    "credentials": {"api_token": "your_token"}
}
```

---

## 6. requirements.txt

- [ ] File exists
- [ ] Contains `autohive-integrations-sdk~=1.0.2` (required)
- [ ] No unnecessary dependencies
- [ ] All imported packages are listed

```
# Standard format
autohive-integrations-sdk~=1.0.2

# With additional dependencies
autohive-integrations-sdk~=1.0.2
requests>=2.28.0
```

---

## 7. README.md (REQUIRED)

**Every integration MUST have a README.md file.**

### Required Sections
- [ ] Title with integration name
- [ ] Brief description
- [ ] Setup/Authentication instructions
- [ ] Actions list with descriptions
- [ ] Action Results format explanation
- [ ] API information (base URL, rate limits, docs link)

### Recommended Sections
- [ ] Detailed action documentation with examples
- [ ] Testing instructions
- [ ] Troubleshooting section
- [ ] Version history

### Template
```markdown
# {Integration Name} Integration for Autohive

Brief description of the integration.

## Description

Detailed explanation of what this integration does and its capabilities.

## Setup & Authentication

### For Platform Auth:
1. Click "Connect" in Autohive
2. Authorize with your {Service} account
3. Grant the requested permissions

### For Custom Auth:
1. Log in to your {Service} account
2. Navigate to Settings > API Keys
3. Generate a new API key
4. Copy the key and paste it in Autohive

## Action Results

All actions return a response with the following structure:
- `result` (boolean): Whether the operation was successful
- `error` (string, optional): Error message if result is false
- Action-specific data fields

## Actions

### action_name
**Description:** What it does

**Inputs:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| param1 | string | Yes | Description |
| param2 | integer | No | Description (default: 10) |

**Outputs:**
| Field | Type | Description |
|-------|------|-------------|
| result | boolean | Success indicator |
| data | array | The returned data |

**Example:**
```json
{
  "param1": "value"
}
```

## API Information

- **Documentation:** https://api.example.com/docs
- **Base URL:** https://api.example.com/v1
- **Rate Limits:** 100 requests per minute
- **Authentication:** OAuth2 / API Key

## Testing

```bash
cd integration-name
python -m pytest tests/ -v
```

## Troubleshooting

### Common Issues

**Error: "Invalid API Key"**
- Verify your API key is correct
- Check if the key has expired

## Version History

- **1.0.0** - Initial release
```

---

## 8. Icon (REQUIRED)

**Every integration MUST have an icon file.**

- [ ] `icon.png` OR `icon.svg` exists in integration root folder
- [ ] File is named exactly `icon.png` or `icon.svg`

```
# CORRECT
integration-name/
├── icon.png
└── ...

# OR
integration-name/
├── icon.svg
└── ...
```

---

## 9. Main README Update (REQUIRED)

**You MUST update the main repository README.md to include your new integration.**

### Steps
- [ ] Open the main `README.md` in the repository root
- [ ] Find the integrations list/table
- [ ] Add your new integration in alphabetical order
- [ ] Include: name, description, auth type, and status

### Example Entry
```markdown
| Integration | Description | Auth Type | Status |
|-------------|-------------|-----------|--------|
| ... | ... | ... | ... |
| Netlify | Deploy and manage web projects | Platform (OAuth2) | Active |
| ... | ... | ... | ... |
```

### Checklist
- [ ] Integration added to main README.md
- [ ] Entry is in alphabetical order
- [ ] Description matches config.json description
- [ ] Auth type is correct (Platform/Custom/None)
- [ ] Status is set appropriately

---

## 10. Cleanup Checks

### Unused Code
- [ ] No unused imports in any file
- [ ] No unused functions or classes
- [ ] No commented-out code blocks
- [ ] No TODO comments that should be resolved
- [ ] No debug print statements
- [ ] No hardcoded test values in production code

### Unused Scopes (CRITICAL)
- [ ] Review each scope in `auth.scopes`
- [ ] Verify each scope is required by at least one action
- [ ] Remove scopes for unimplemented features
- [ ] Document why each scope is needed (in README or comments)

### File Cleanup
- [ ] No `.pyc` files committed
- [ ] No `__pycache__` folders committed
- [ ] No `.env` files committed
- [ ] No IDE-specific files (`.vscode/`, `.idea/`)
- [ ] No test output files
- [ ] No `.zip` files committed

### Consistency
- [ ] Integration name is consistent across all files
- [ ] Variable names follow Python conventions
- [ ] String quotes are consistent (prefer double quotes for JSON-like data)
- [ ] Indentation is consistent (4 spaces for Python)

---

## 11. Pre-PR Final Checks

### Code Quality
- [ ] Run `python scripts/check_code.py <dir>` (syntax, imports, lint, format, security, deps)
- [ ] Run all tests locally
- [ ] Test with real API credentials
- [ ] Check for API error handling
- [ ] Verify pagination works (if applicable)

### Documentation
- [ ] Integration README.md is complete
- [ ] Main repository README.md is updated
- [ ] config.json descriptions are clear
- [ ] All actions are documented

### Assets
- [ ] icon.png or icon.svg is present

### Git
- [ ] Only integration-related files are staged
- [ ] No sensitive data in commits
- [ ] Commit messages are descriptive
- [ ] Branch name follows convention

---

## Common Mistakes to Avoid

| Mistake | Correct Approach |
|---------|-----------------|
| Uppercase folder name (`Netlify/`) | Use lowercase (`netlify/`) |
| Non-empty `__init__.py` with logic | Keep minimal - only import/export |
| Unused scopes in config | Remove scopes not used by actions |
| Missing error handling | Wrap API calls in try/except |
| Hardcoded credentials | Use `context.auth` |
| Missing `result` field in response | Always include `"result": true/false` |
| Sync functions for actions | Use `async def execute()` |
| Missing type hints | Add `Dict[str, Any]` to all params |
| Tests without assertions | Add assertions for expected output |
| Forgetting `cost_usd` in ActionResult | Include even if `0.0` |
| Missing icon | Add `icon.png` or `icon.svg` |
| Missing README.md | Create comprehensive documentation |
| Not updating main README | Add integration to repo README |

---

## Quick Validation Commands

```bash
# Check folder structure
ls -la your_integration/
ls -la your_integration/tests/

# Verify required files exist
test -f your_integration/config.json && echo "config.json OK" || echo "MISSING config.json"
test -f your_integration/__init__.py && echo "__init__.py OK" || echo "MISSING __init__.py"
test -f your_integration/README.md && echo "README.md OK" || echo "MISSING README.md"
test -f your_integration/requirements.txt && echo "requirements.txt OK" || echo "MISSING requirements.txt"
# Check for icon (png or svg)
(test -f your_integration/icon.png || test -f your_integration/icon.svg) && echo "icon OK" || echo "MISSING icon.png or icon.svg"

# Validate JSON syntax
python -m json.tool your_integration/config.json

# Run all code quality checks (syntax, imports, lint, format, security, deps)
python scripts/check_code.py your_integration

# Run tests
cd your_integration && python -m pytest tests/ -v

# Check for print statements
grep -r "print(" your_integration/*.py
```

---

## Checklist Summary for Quick Review

```
FOLDER STRUCTURE
[ ] Folder is lowercase
[ ] All required files exist:
    [ ] config.json
    [ ] {name}.py
    [ ] __init__.py
    [ ] requirements.txt
    [ ] README.md (REQUIRED)
    [ ] icon.png or icon.svg (REQUIRED)
    [ ] tests/ folder with test files

CONFIG.JSON
[ ] Valid JSON syntax
[ ] All required fields present
[ ] Auth type matches implementation
[ ] All scopes are used (no extras)
[ ] All actions have input/output schemas

CODE
[ ] __init__.py is minimal
[ ] Action handlers follow naming convention
[ ] All actions return ActionResult with result field
[ ] Error handling is implemented
[ ] No unused code or imports
[ ] No hardcoded credentials

TESTS
[ ] Tests exist for all actions
[ ] Tests use proper auth structure
[ ] Tests have assertions

DOCUMENTATION
[ ] Integration README.md is complete
[ ] Main repo README.md is updated

ASSETS
[ ] icon.png or icon.svg is present

CLEANUP
[ ] No debug code
[ ] No unnecessary files
[ ] No .zip, .pyc, __pycache__, .env files
```

---

*Last updated: January 2026*
