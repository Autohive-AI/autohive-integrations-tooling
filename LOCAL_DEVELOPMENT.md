# Local Development Guide

How to use the validation tools locally while developing an integration.

## Setup

```bash
uv python install 3.13
uv venv --python 3.13
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows
uv pip install -r requirements-dev.txt
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for full setup instructions and project conventions.

## Development Workflow

When building an integration, run the checks in this order. This matches what CI does on your PR.

### 1. Validate structure and config

```bash
python scripts/validate_integration.py my-integration
```

Run this **first** — it catches structural problems before you waste time on code quality checks. It validates:

- Folder name is lowercase
- All required files exist (`config.json`, `__init__.py`, `requirements.txt`, `README.md`, `icon.png`/`icon.svg`)
- `config.json` has the required fields and valid schema
- `__init__.py` is minimal (only import + `__all__`)
- `requirements.txt` includes `autohive-integrations-sdk`
- `tests/` folder has `__init__.py`, `context.py`, and at least one `test_*.py`
- Icon is exactly 512x512 pixels
- OAuth scopes are actually used (heuristic)

### 2. Run all code quality checks

```bash
python scripts/check_code.py my-integration
```

This is the comprehensive check — it runs 9 steps in sequence:

1. Installs your `requirements.txt` dependencies
2. Checks Python syntax (`py_compile`)
3. Verifies all imports resolve (`check_imports`)
4. Validates all JSON files parse correctly
5. Lints with `ruff check`
6. Checks formatting with `ruff format --check`
7. Scans for security issues with `bandit`
8. Audits dependencies for known CVEs with `pip-audit`
9. Cross-validates `config.json` against your code (`check_config_sync`)

### 3. Fix common issues

```bash
# Auto-fix lint issues
ruff check --fix --config /path/to/autohive-integrations-tooling/ruff.toml my-integration

# Auto-format code
ruff format --config /path/to/autohive-integrations-tooling/ruff.toml my-integration
```

> **Note:** Point `--config` to `ruff.toml` in this tooling repo. If you're working inside the tooling repo, use `--config ruff.toml`. If your integration lives in a separate repo, use the full path to the tooling repo's `ruff.toml`.

Then re-run `check_code.py` to confirm everything passes.

## Running Individual Tools

You don't always need the full suite. Use individual scripts when working on specific issues.

### Check imports only

```bash
# Check a single file
python scripts/check_imports.py my-integration/my_integration.py

# Also verify that imported names exist (imports modules — use with trusted code only)
python scripts/check_imports.py --verify-names my-integration/my_integration.py
```

### Check config-code sync only

```bash
python scripts/check_config_sync.py my-integration
```

Useful when you've added or renamed actions and want to verify `config.json` matches your `@action` decorators and `inputs` access patterns.

### Check multiple integrations

All scripts accept multiple directories:

```bash
python scripts/validate_integration.py integration-a integration-b
python scripts/check_code.py integration-a integration-b
python scripts/check_config_sync.py integration-a integration-b
```

### Auto-discover all integrations

```bash
# Validates every integration folder at the repo root
python scripts/validate_integration.py
```

### Check what CI would check on your branch

```bash
# See which integration dirs changed compared to main
python scripts/get_changed_dirs.py origin/main

# Run the full CI pipeline locally against those dirs
DIRS=$(python scripts/get_changed_dirs.py origin/main)
python scripts/validate_integration.py $DIRS
python scripts/check_code.py $DIRS
python scripts/check_readme.py origin/main $DIRS
python scripts/check_version_bump.py origin/main $DIRS
```

## Typical Iteration Cycle

```
1. Edit code
2. ruff format --config path/to/ruff.toml my-integration   (auto-format)
3. ruff check --fix --config path/to/ruff.toml my-integration  (auto-fix lint)
4. python scripts/check_code.py my-integration            (full check)
5. Fix any remaining issues
6. Repeat from 1
```

Once everything passes, run `validate_integration.py` for a final structure check before pushing.

## What CI Runs on Your PR

The `validate-integration.yml` workflow uses the composite action defined in `action.yml` to run three checks on every PR:

| Step | Script | What It Does |
|------|--------|-------------|
| 1 | `get_changed_dirs.py` | Detects which integration folders changed |
| 2 | `validate_integration.py` | Structure and config validation |
| 3 | `check_code.py` | Syntax, imports, JSON, lint, format, security, deps, config sync |
| 4 | `check_readme.py` | Checks that the main README.md was updated for new integrations |
| 5 | `check_version_bump.py` | Checks that config.json version was incremented, recommends bump level |

If no integration directories changed (only `scripts/`, `tests/`, etc.), steps 2–5 are skipped.

Results are posted as a sticky PR comment showing ✅ Passed, ⚠️ Passed with warnings, or ❌ Failed for each check.

Other repositories can use the same action — see [Usage as GitHub Action](README.md#usage-as-github-action) in the README.

## Documentation Map

### For integration developers

| Document | Purpose |
|----------|---------|
| [CONTRIBUTING.md](CONTRIBUTING.md) | **Start here.** Setup, project conventions, folder structure, commit format, PR process. |
| [INTEGRATION_CHECKLIST.md](INTEGRATION_CHECKLIST.md) | Detailed checklist to review before submitting a PR. Covers every required file, config field, and common mistake. |
| [LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md) | This file. How to use the validation tools locally during development. |
| [README.md](README.md) | Repository overview, CI pipeline diagram, file listing, integrations table. |

### Script reference (in `scripts/docs/`)

Detailed documentation for each validation script — usage, arguments, exit codes, how it works, CI integration.

| Document | Script | When to read it |
|----------|--------|-----------------|
| [validate_integration.md](scripts/docs/validate_integration.md) | `validate_integration.py` | Understanding what structure/config checks are performed and why |
| [check_code.md](scripts/docs/check_code.md) | `check_code.py` | Understanding the 9 code quality checks and their failure output |
| [check_imports.md](scripts/docs/check_imports.md) | `check_imports.py` | Understanding how imports are resolved (AST parsing, relative imports, `--verify-names`) |
| [check_config_sync.md](scripts/docs/check_config_sync.md) | `check_config_sync.py` | Understanding how config.json is cross-validated against code (AST-based action and input detection) |
| [check_readme.md](scripts/docs/check_readme.md) | `check_readme.py` | Understanding the README update requirement for new integrations |
| [check_version_bump.md](scripts/docs/check_version_bump.md) | `check_version_bump.py` | Understanding the version bump requirement and bump-level recommendations |
| [get_changed_dirs.md](scripts/docs/get_changed_dirs.md) | `get_changed_dirs.py` | Understanding how CI detects which integrations to validate |

### Test fixtures (in `tests/examples/`)

Used by `self-test.yml` to regression-test the validation scripts. Also useful as references.

| Fixture | Purpose |
|---------|---------|
| `good-integration/` | **Working reference** — passes all validation checks |
| `Bad-Integration/` | Deliberately invalid (uppercase name, missing files, bad config) |
| `bad-icon/` | Valid structure but wrong icon size (100x100 instead of 512x512) |
| `config-mismatch/` | Deliberate config↔code mismatches (missing actions, undocumented params) |
| `netlify/` | Real-world-style integration with multiple actions and OAuth auth |
| `submodule-imports/` | Import checker fixtures (valid and invalid submodule imports) |
| `relative-imports/` | Import checker fixtures (valid and invalid relative imports) |
| `name-verification/` | Import checker fixtures for `--verify-names` flag |
