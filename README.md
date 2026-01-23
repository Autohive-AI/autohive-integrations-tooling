# Autohive Integrations Tooling

Validation tools and CI/CD workflows for Autohive integrations.

## What's Included

| File | Description |
|------|-------------|
| `.github/workflows/validate-integration.yml` | GitHub Action for PR validation |
| `scripts/validate_integration.py` | Structure validation script |
| `scripts/check_imports.py` | Import validation script |
| `INTEGRATION_CHECKLIST.md` | Manual review checklist |
| `good-integration/` | Example valid integration |

## How It Works

When you create a PR with a new integration:

1. **Structure Check** - Validates folder structure, required files
2. **Code Check** - Validates syntax, imports, JSON files
3. **README Check** - Ensures main README is updated

## Local Testing

```bash
# Test a specific integration
python scripts/validate_integration.py my-integration

# Test all integrations
python scripts/validate_integration.py
```

## Integration Requirements

See `INTEGRATION_CHECKLIST.md` for full details.

### Required Files
- `config.json` - Integration configuration
- `{name}.py` - Main implementation
- `__init__.py` - Package init (minimal)
- `requirements.txt` - Dependencies
- `README.md` - Documentation
- `icon.png` or `icon.svg` - Integration icon
- `tests/` - Test folder

## Integrations

| Integration | Description | Auth Type |
|-------------|-------------|-----------|
| good-integration | Example valid integration | Custom |
| sample-api | Sample API integration for testing | Custom |
