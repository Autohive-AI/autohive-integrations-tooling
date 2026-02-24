# Autohive Integrations Tooling

Validation tools and CI/CD workflows for Autohive integrations.

**Requires: Python 3.13+**

## What's Included

| File | Description |
|------|-------------|
| `scripts/validate_integration.py` | Structure and config validation ([docs](scripts/docs/validate_integration.md)) |
| `scripts/check_code.py` | Syntax, import, and JSON checks ([docs](scripts/docs/check_code.md)) |
| `scripts/check_imports.py` | Import availability checker ([docs](scripts/docs/check_imports.md)) |
| `scripts/check_readme.py` | README update verification ([docs](scripts/docs/check_readme.md)) |
| `scripts/get_changed_dirs.py` | Changed directory detection ([docs](scripts/docs/get_changed_dirs.md)) |
| `.github/workflows/validate-integration.yml` | PR validation pipeline |
| `.github/workflows/self-test.yml` | Regression guard for tooling scripts |
| `.github/workflows/conv-commits.yml` | Conventional commit enforcement |
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
        VI --> CC["check_code.py\n─────────────────\n① pip install requirements.txt\n② py_compile.compile() all .py\n③ check_imports() on entry_point\n④ json.load() all .json"]
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

## Local Testing

```bash
# Validate structure and config
python scripts/validate_integration.py my-integration

# Run code quality checks (syntax, imports, JSON)
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
- `icon.png` or `icon.svg` - Integration icon
- `tests/` - Test folder with `__init__.py`, `context.py`, and `test_*.py`

## Integrations

| Integration | Description | Auth Type |
|-------------|-------------|-----------|
| good-integration | Example valid integration | Custom |
| sample-api | Sample API integration for testing | Custom |
