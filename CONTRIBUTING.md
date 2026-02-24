# Contributing

Thank you for contributing to Autohive Integrations! This guide covers everything you need to set up, build, validate, and submit an integration.

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

## Integration Structure

Every integration must follow this folder structure:

```
my-integration/
├── __init__.py              # Minimal — only import and __all__
├── config.json              # Integration configuration
├── my_integration.py        # Main implementation (entry_point)
├── icon.png or icon.svg     # Integration icon
├── requirements.txt         # Dependencies (must include autohive-integrations-sdk)
├── README.md                # Documentation
└── tests/
    ├── __init__.py          # Can be empty
    ├── context.py           # Import setup
    └── test_my_integration.py
```

See `INTEGRATION_CHECKLIST.md` for the full checklist with examples.

## Creating an Integration

1. **Create a branch** following conventional naming:
   ```bash
   git checkout -b feat/my-integration
   ```

2. **Create your integration folder** (lowercase, hyphens for separators):
   ```bash
   mkdir my-integration
   ```

3. **Add the required files** — refer to `tests/examples/good-integration/` as a working reference.

4. **Key conventions:**
   - Folder name must be lowercase (e.g., `my-integration`, not `MyIntegration`)
   - `config.json` must include `name`, `version`, `description`, `entry_point`, and `actions`
   - `__init__.py` should only contain the import and `__all__`
   - `requirements.txt` must include `autohive-integrations-sdk`
   - Action names should be `snake_case`

## Validating Your Integration

Run these before submitting a PR:

```bash
# Validate structure and config
python scripts/validate_integration.py my-integration

# Run all code quality checks (syntax, imports, JSON, lint, format, security, deps)
python scripts/check_code.py my-integration
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

### Auto-fixing Common Issues

```bash
# Auto-fix lint issues
ruff check --fix my-integration

# Auto-format code
ruff format my-integration
```

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

1. **Run validation locally** — both `validate_integration.py` and `check_code.py`
2. **Update the main README.md** — add your integration to the integrations table
3. **Use a conventional commit PR title** — CI enforces this
4. **One integration per PR** — keep PRs focused

### CI Checks

Your PR will automatically run:

- **Structure Check** — validates folder structure and config.json
- **Code Check** — syntax, imports, JSON, lint, format, security, dependency audit
- **README Check** — verifies the main README.md was updated
- **Conventional Commits** — validates PR title format

All checks must pass before merge.

## Getting Help

- Review `tests/examples/good-integration/` for a complete working example
- See `INTEGRATION_CHECKLIST.md` for the detailed review checklist
- Check `scripts/docs/` for documentation on each validation script
