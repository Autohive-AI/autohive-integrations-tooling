# Autohive Integrations Tooling

Validation tools and CI/CD workflows for Autohive integrations.

**Requires: Python 3.13+**

## What's Included

| File | Description |
|------|-------------|
| `scripts/validate_integration.py` | Structure and config validation ([docs](scripts/docs/validate_integration.md)) |
| `scripts/check_code.py` | Syntax, import, JSON, lint, format, security, dependency, and config sync checks ([docs](scripts/docs/check_code.md)) |
| `scripts/check_imports.py` | Import availability checker ([docs](scripts/docs/check_imports.md)) |
| `scripts/check_readme.py` | README update verification ([docs](scripts/docs/check_readme.md)) |
| `scripts/check_config_sync.py` | Config-code sync checker ([docs](scripts/docs/check_config_sync.md)) |
| `scripts/get_changed_dirs.py` | Changed directory detection ([docs](scripts/docs/get_changed_dirs.md)) |
| `.github/workflows/validate-integration.yml` | PR validation pipeline |
| `.github/workflows/self-test.yml` | Regression guard for tooling scripts |
| `.github/workflows/conv-commits.yml` | Conventional commit enforcement |
| `requirements-dev.txt` | Dev tool dependencies (ruff, bandit, pip-audit) |
| `ruff.toml` | Ruff linter and formatter configuration |
| `CONTRIBUTING.md` | Contributor guide |
| `INTEGRATION_CHECKLIST.md` | Manual review checklist |
| `tests/examples/` | Test fixtures for validation scripts |

## CI Pipeline

```mermaid
flowchart TB
    subgraph triggers["Triggers"]
        PR["Pull Request → master/main"]
        PUSH_SCRIPTS["Push (scripts/, tests/ changed)"]
        PUSH_MAIN["Push → master/main"]
    end

    subgraph wf1["validate-integration.yml"]
        direction TB
        GCD["get_changed_dirs.py\n─────────────────\ngit diff → extract top-level dirs\nfilter out .github, scripts, tests"]
        GCD -->|"dirs (space-separated)"| COND{dirs empty?}
        COND -->|Yes| SKIP[Skip all checks]
        COND -->|No| VI["validate_integration.py\n─────────────────\n① Folder name\n② Required files\n③ config.json schema\n④ __init__.py minimality\n⑤ requirements.txt\n⑥ tests/ folder\n⑦ Main Python file\n⑧ Unused scopes"]
        VI --> CC["check_code.py\n─────────────────\n① pip install requirements.txt\n② py_compile.compile() all .py\n③ check_imports() on entry_point\n④ json.load() all .json\n⑤ ruff check all .py\n⑥ ruff format --check\n⑦ bandit security scan\n⑧ pip-audit requirements.txt\n⑨ check_config_sync"]
        CC --> CR["check_readme.py\n─────────────────\ngit diff: new files added?\nREADME.md also changed?"]
    end

    subgraph ci_detail["check_code.py internals"]
        direction LR
        CC2["check_code.py"] -->|"imports as function"| CI["check_imports.py\n─────────────────\nAST parse → walk nodes\nfind_spec() for modules\nresolve relative imports\n--verify-names: hasattr()"]
    end

    subgraph wf2["self-test.yml"]
        direction TB
        ST["Run scripts against\ntests/examples/\n─────────────────\ngood-integration ✅\nBad-Integration ✗\nauto-discovery skip\nvalid/invalid imports\nrelative imports\nname verification\nexit codes"]
    end

    subgraph wf3["conv-commits.yml"]
        direction TB
        PRT["Validate PR Title\n(semantic-pull-request action)"]
        CMT["Validate Push Commits\n(regex: type(scope)?: desc)"]
    end

    PR --> wf1
    PR --> wf2
    PR --> wf3
    PUSH_SCRIPTS --> wf2
    PUSH_MAIN --> wf3
```

## Setup

```bash
uv python install 3.13
uv venv --python 3.13
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows
uv pip install -r requirements-dev.txt
```

## Local Testing

```bash
# Validate structure and config
python scripts/validate_integration.py my-integration

# Run code quality checks (syntax, imports, JSON, lint, format, security, deps, config sync)
python scripts/check_code.py my-integration

# Check all imports in a file
python scripts/check_imports.py my-integration/main.py

# Validate all integrations (auto-discovers at repo root)
python scripts/validate_integration.py
```

## Integration Requirements

See `INTEGRATION_CHECKLIST.md` for full details.

### Required Files
- `config.json` - Integration configuration
- `{name}.py` - Main implementation
- `__init__.py` - Package init (minimal)
- `requirements.txt` - Dependencies (must include `autohive-integrations-sdk`)
- `README.md` - Documentation
- `icon.png` or `icon.svg` - Integration icon (512x512 pixels)
- `tests/` - Test folder with `__init__.py`, `context.py`, and `test_*.py`

## Integrations

<!-- Add your integration here when submitting a PR -->
| Integration | Description | Auth Type |
|-------------|-------------|-----------|
