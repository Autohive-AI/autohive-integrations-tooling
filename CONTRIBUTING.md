# Contributing

Thank you for contributing to Autohive Integrations! This guide covers validating and submitting integrations.

## Building an Integration

For how to build an integration, see the **[Integrations SDK documentation](https://github.com/Autohive-AI/integrations-sdk/tree/master/docs/manual)**:

- [Building Your First Integration](https://github.com/Autohive-AI/integrations-sdk/blob/master/docs/manual/building_your_first_integration.md) — end-to-end tutorial
- [Integration Structure](https://github.com/Autohive-AI/integrations-sdk/blob/master/docs/manual/integration_structure.md) — file layout and config.json schema
- [Starter Template](https://github.com/Autohive-AI/integrations-sdk/tree/master/samples/template) — copy this to begin

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python version and package manager)
- Git

## Setup

```bash
git clone https://github.com/autohive-ai/autohive-integrations-tooling.git
cd autohive-integrations-tooling

uv python install 3.13
uv venv --python 3.13
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows
uv pip install -r requirements-dev.txt
```

## Validating Your Integration

Run these before submitting a PR:

```bash
# Validate structure and config
python scripts/validate_integration.py my-integration

# Run all code quality checks (syntax, imports, JSON, lint, format, security, deps, config sync, fetch pattern)
python scripts/check_code.py my-integration

# Run unit tests when the integration has test_*_unit.py files
python scripts/run_tests.py my-integration
```

### What Gets Checked

| Check | Tool | What It Does |
|-------|------|-------------|
| Structure | `validate_integration.py` | Folder name, required files, config.json schema, tests/ |
| Syntax | `py_compile` | Valid Python syntax |
| Imports | `check_imports.py` | All imports resolvable |
| JSON | `json.load` | All JSON files parseable |
| Lint | `ruff check` | Code quality (unused imports, undefined names, style) |
| Format | `ruff format` | Consistent code formatting |
| Security | `bandit` | No hardcoded secrets, unsafe eval/exec |
| Dependencies | `pip-audit` | No known CVEs in requirements.txt |
| Config sync | `check_config_sync.py` | Config.json actions and input schemas match code |
| Fetch pattern | `check_fetch_pattern.py` | SDK 2.x `context.fetch()` responses are accessed via `.data` |
| Unit tests | `run_tests.py` | Runs `test_*_unit.py` files with each integration's own dependencies |

### Auto-Fixing Common Issues

```bash
# Auto-fix lint issues
ruff check --fix --config /path/to/autohive-integrations-tooling/ruff.toml my-integration

# Auto-format code
ruff format --config /path/to/autohive-integrations-tooling/ruff.toml my-integration
```

> **Note:** Point `--config` to `ruff.toml` in this tooling repo. If you're working inside the tooling repo, use `--config ruff.toml`. If your integration lives in a separate repo, use the full path to the tooling repo's `ruff.toml`.

## Commit Conventions

This project uses [Conventional Commits](https://www.conventionalcommits.org/). PR titles and commit messages must follow the format:

```
type(scope)?: description
```

**Types:** `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`

**Examples:**
```
feat: add Netlify integration
fix(netlify): handle rate limit errors
docs: update Netlify README with auth setup
```

## Pull Request Process

1. **Run validation locally** — `validate_integration.py`, `check_code.py`, and `run_tests.py` when unit tests exist
2. **Update the main README.md** — add your integration to the integrations table
3. **Use a conventional commit PR title** — CI enforces this
4. **One integration per PR** — keep PRs focused

### CI Checks

Your PR will automatically run:

- **Structure Check** — validates folder structure and config.json
- **Code Check** — syntax, imports, JSON, lint, format, security, dependency audit, config sync, fetch pattern
- **Tests** — runs `test_*_unit.py` files with pytest and coverage
- **README Check** — verifies the main README.md was updated
- **Version Check** — verifies config.json version was incremented, recommends bump level
- **Conventional Commits** — validates PR title format

Results are posted as a sticky PR comment with a summary table and expandable output for each check.

All checks must pass before merge.

## Getting Help

- Review the [Integration Checklist](INTEGRATION_CHECKLIST.md) for the manual review checklist
- See `scripts/docs/` for detailed documentation on each validation script
- See `tests/examples/good-integration/` for a complete working example
