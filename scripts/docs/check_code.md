# check_code.py

Runs code quality checks on one or more integration directories.

## Overview

This script performs seven sequential code quality checks on each given integration directory:

1. **Python syntax check** — uses `py_compile.compile()` directly to catch syntax errors
2. **Import availability check** — imports `check_imports()` as a function to verify modules exist
3. **JSON validity check** — uses `json.load()` directly to ensure all `.json` files are parseable
4. **Lint check** — runs `ruff check` to catch code quality issues (undefined names, unused imports, style errors)
5. **Format check** — runs `ruff format --check` to enforce consistent code formatting
6. **Security scan** — runs `bandit` to flag hardcoded secrets, unsafe eval/exec, insecure HTTP calls
7. **Dependency vulnerability scan** — runs `pip-audit` to check requirements.txt for packages with known CVEs

Before running checks, it installs the integration's dependencies from `requirements.txt` so that import checks can find third-party packages.

## Usage

```bash
python scripts/check_code.py <dir> [dir ...]
```

### Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `dir` | Yes (one or more) | Path to an integration directory to check |

### Exit Codes

| Code | Meaning |
|------|---------|
| `0`  | All checks passed for all directories |
| `1`  | One or more checks failed (includes nonexistent directories) |
| `2`  | No directories provided (usage error) |

### Examples

```bash
# Check a single integration
python scripts/check_code.py my-integration

# Check multiple integrations
python scripts/check_code.py my-integration another-api

# Combine with get_changed_dirs.py
python scripts/check_code.py $(python scripts/get_changed_dirs.py origin/main)
```

## Checks Performed

### 1. Dependency Installation

```bash
pip install -r <dir>/requirements.txt -q
```

- Runs only if `requirements.txt` exists
- Uses `-q` (quiet) to reduce output noise
- Failures are silently ignored (`|| true`) to allow checks to continue

### 2. Python Syntax Check

```bash
python -m py_compile <file.py>
```

- Finds all `.py` files recursively in the directory using `find`
- Uses `py_compile` module to check syntax without executing code
- Reports each file with syntax errors individually
- Uses null-delimited file discovery (`find -print0`) to handle filenames with spaces

**On failure:**
```
🐍 Checking Python syntax...
   ❌ my-integration/broken_file.py

   Fix: Check the Python files above for syntax errors
   Run locally: python -m py_compile <file.py>
```

### 3. Import Availability Check

```bash
python scripts/check_imports.py <dir>/<entry_point>
```

- Reads `entry_point` from `config.json` to determine the main Python file
- Calls `check_imports()` directly as a function (see [check_imports.md](check_imports.md)) to verify all imports
- Skips gracefully if `config.json` or the entry point file doesn't exist

**On failure:**
```
📥 Checking imports...
   ❌ Import errors in my-integration/main.py

   Fix: Install missing packages in requirements.txt
   Or check if package name is spelled correctly
```

### 4. JSON Validity Check

```bash
python -m json.tool <file.json>
```

- Finds all `.json` files recursively in the directory
- Uses Python's built-in `json.tool` module to validate syntax
- Reports each invalid JSON file individually
- Uses null-delimited file discovery for safe filename handling

**On failure:**
```
📄 Checking JSON files...
   ❌ my-integration/config.json

   Fix: Check for missing commas, quotes, or brackets
   Validate at: https://jsonlint.com/
```

### 5. Lint Check (ruff)

```bash
ruff check <dir>
```

- Runs [ruff](https://docs.astral.sh/ruff/) linter on all Python files in the directory
- Checks for pyflakes errors (F), pycodestyle errors (E), and pycodestyle warnings (W)
- Configuration is defined in `ruff.toml` at the repository root
- Ruff is installed automatically if not already available

**On failure:**
```
🔍 Linting with ruff...
   my-integration/main.py:5:1: F401 `os` imported but unused

   ❌ Lint errors found

   Fix: Run 'ruff check --fix' to auto-fix some issues
```

### 6. Format Check (ruff format)

```bash
ruff format --check <dir>
```

- Checks that all Python files are formatted consistently
- Uses the same ruff tool (already installed for linting)
- Does not modify files — only reports which files would be reformatted

**On failure:**
```
🎨 Checking formatting with ruff...
   Would reformat: my-integration/main.py

   ❌ Formatting issues found

   Fix: Run 'ruff format' to auto-format
```

### 7. Security Scan (bandit)

```bash
bandit -r <dir> -s B101 -q
```

- Runs [bandit](https://bandit.readthedocs.io/) security linter on all Python files
- Flags hardcoded passwords, use of `eval`/`exec`, insecure HTTP calls, and other security anti-patterns
- Skips B101 (assert_used) since test files use assertions
- Uses `-q` (quiet) to only show findings

**On failure:**
```
🔒 Scanning for security issues with bandit...
   >> Issue: [B105:hardcoded_password_string] Possible hardcoded password: 'secret123'
      Severity: Low   Confidence: Medium
      Location: my-integration/main.py:15:0

   ❌ Security issues found

   Fix: Review flagged code for security risks
   Run locally: bandit -r <dir> -s B101
```

### 8. Dependency Vulnerability Scan (pip-audit)

```bash
pip-audit -r <dir>/requirements.txt
```

- Runs [pip-audit](https://github.com/pypa/pip-audit) against the integration's requirements.txt
- Checks all listed dependencies for known CVEs (Common Vulnerabilities and Exposures)
- Only runs if `requirements.txt` exists

**On failure:**
```
🛡️ Checking dependencies for vulnerabilities with pip-audit...
   Name    Version ID             Fix Versions
   ------- ------- -------------- ------------
   requests 2.25.0 PYSEC-2023-XXX 2.31.0

   ❌ Vulnerable dependencies found

   Fix: Update affected packages in requirements.txt
```

## How It Works

```mermaid
flowchart TD
    A[For each directory] --> B{requirements.txt exists?}
    B -->|Yes| C[pip install dependencies]
    B -->|No| D[Skip]
    C --> D
    D --> E[Find all .py files]
    E --> F[py_compile each file]
    F --> G{Syntax OK?}
    G -->|No| H[Mark FAILED]
    G -->|Yes| I[Read entry_point from config.json]
    H --> I
    I --> J[Run check_imports.py on entry point]
    J --> K{Imports OK?}
    K -->|No| H
    K -->|Yes| L[Find all .json files]
    L --> M[Validate each with json.tool]
    M --> N{JSON OK?}
    N -->|No| H
    N -->|Yes| R[Run ruff check on directory]
    R --> S{Lint OK?}
    S -->|No| H
    S -->|Yes| T[Run ruff format --check]
    T --> U{Format OK?}
    U -->|No| H
    U -->|Yes| V[Run bandit security scan]
    V --> W{Security OK?}
    W -->|No| H
    W -->|Yes| X{requirements.txt exists?}
    X -->|No| A
    X -->|Yes| Y[Run pip-audit on requirements.txt]
    Y --> Z{Deps OK?}
    Z -->|No| H
    Z -->|Yes| A
    A --> O{Any failures?}
    O -->|Yes| P[Exit 1]
    O -->|No| Q[Exit 0]
```

## Output Format

The script produces formatted output with emoji indicators for each check:

```
----------------------------------------
Checking: my-integration
----------------------------------------

📦 Installing dependencies...

🐍 Checking Python syntax...
   ✅ Syntax OK

📥 Checking imports...
   ✅ Imports OK

📄 Checking JSON files...
   ✅ JSON files OK

🔍 Linting with ruff...
   ✅ Lint OK

🎨 Checking formatting with ruff...
   ✅ Formatting OK

🔒 Scanning for security issues with bandit...
   ✅ Security OK

🛡️ Checking dependencies for vulnerabilities with pip-audit...
   ✅ Dependencies OK

========================================
✅ CODE CHECK PASSED
========================================
```

## Dependencies

- **Python** — for `py_compile`, `json`, and `check_imports`
- **pip** — for installing integration dependencies
- **check_imports** — imported as a module for import validation
- **ruff** — installed automatically for linting and formatting (configured via `ruff.toml`)
- **bandit** — installed automatically for security scanning
- **pip-audit** — installed automatically for dependency vulnerability checking

## Integration with CI

Called by the `validate-integration.yml` workflow (on pull requests):

```yaml
- name: Code Check
  if: steps.changed.outputs.dirs != ''
  run: python scripts/check_code.py ${{ steps.changed.outputs.dirs }}
```

Also exercised by the `self-test.yml` workflow against test examples in `tests/examples/` as a regression guard.
