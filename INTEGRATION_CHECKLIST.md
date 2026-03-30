# Integration Checklist

Manual review checklist for integration PRs. Use alongside the automated CI checks.

> **Building an integration?** See the [Integrations SDK documentation](https://github.com/Autohive-AI/integrations-sdk/tree/master/docs/manual) for the full tutorial, config.json schema, and code patterns. Start with [Building Your First Integration](https://github.com/Autohive-AI/integrations-sdk/blob/master/docs/manual/building_your_first_integration.md) or copy the [starter template](https://github.com/Autohive-AI/integrations-sdk/tree/master/samples/template).

---

## CI Checks Summary

These checks run automatically on every PR. See `scripts/docs/` for detailed documentation on each script.

| Check | Script | What It Validates |
|-------|--------|-------------------|
| Structure | [`validate_integration.py`](scripts/docs/validate_integration.md) | Folder name, required files, config.json schema, `__init__.py` minimality, requirements.txt, tests/, icon, unused scopes |
| Code quality | [`check_code.py`](scripts/docs/check_code.md) | Syntax, imports, JSON validity, ruff lint, ruff format, bandit security, pip-audit CVEs, config-code sync |
| README update | [`check_readme.py`](scripts/docs/check_readme.md) | Main repo README.md was updated with the new integration |
| Conventional commits | `conv-commits.yml` | PR title follows conventional commit format |

### Running Locally

```bash
# Validate structure and config
python scripts/validate_integration.py my-integration

# Run all code quality checks
python scripts/check_code.py my-integration
```

### Auto-Fixing Common CI Failures

```bash
# Auto-fix lint issues (unused imports, style)
ruff check --fix my-integration

# Auto-format code
ruff format my-integration
```

### Lint Configuration

The repo's `ruff.toml` enforces rules `E` (pycodestyle errors), `F` (pyflakes), and `W` (pycodestyle warnings) with these per-file suppressions:

| File | Suppressed | Why |
|------|-----------|-----|
| `__init__.py` | `F401` (unused import) | Import-and-re-export is the expected pattern |
| `tests/context.py` | `F401`, `E402` | Import-after-path-setup is the expected pattern |

Other files that need intentional "unused" imports must use `# noqa: F401` inline.

### Advisory Warnings (Non-Blocking)

The structure check produces warnings (not errors) for these cases:

| Warning | Explanation |
|---------|-------------|
| `Integration.load()` not found | The check looks for the literal string `Integration.load()`. Using `Integration.load(config_path)` triggers this warning — that's expected for multi-file integrations. |
| Missing `__init__.py` | Optional for modular integrations with an `actions/` subdirectory |
| Missing top-level `display_name` | Recommended but not required |
| Missing `display_name` on actions | Recommended but not required |
| Potentially unused OAuth scopes | Heuristic check — verify manually |

---

## Manual Review Checklist

These items require human judgment and aren't fully covered by automated checks.

### Scope Validation (OAuth Integrations)

**Remove unused scopes.** For each scope in `auth.scopes`:

- [ ] Verify it's required by at least one implemented action
- [ ] Check the service's API docs to confirm which endpoints need which scopes
- [ ] Remove scopes for features that aren't implemented
- [ ] Document why each remaining scope is needed (in README or code comments)

```
Example — if scopes are ["read:sites", "write:sites", "delete:sites", "read:users"]
but only list_sites and create_site are implemented:

  read:sites    → KEEP (used by list_sites)
  write:sites   → KEEP (used by create_site)
  delete:sites  → REMOVE (no delete action)
  read:users    → REMOVE (no user actions)
```

### Code Review

- [ ] No hardcoded API keys or secrets
- [ ] No hardcoded test values in production code
- [ ] No debug `print()` statements in production code
- [ ] No commented-out code blocks
- [ ] No TODO comments that should be resolved before merge
- [ ] No unused functions or classes
- [ ] Constants (BASE_URL, API_VERSION) defined at module level
- [ ] Helper functions are well-named and documented
- [ ] Error handling is reasonable (not swallowing exceptions silently)
- [ ] All actions return `ActionResult`
- [ ] All imported packages listed in `requirements.txt`, no unnecessary dependencies

### Tests

- [ ] Each action has at least one test
- [ ] Tests use realistic inputs (not just empty dicts)
- [ ] Tests include assertions on expected output structure
- [ ] Auth structure in tests matches `config.json` fields schema
- [ ] `tests/__init__.py` contains no actual test code (keep empty or minimal)
- [ ] Tested with real API credentials (not just mocks)
- [ ] Pagination verified if applicable

### Documentation

- [ ] Integration `README.md` documents all actions with inputs/outputs
- [ ] Auth setup instructions are clear (where to find API keys, etc.)
- [ ] README includes API information (docs URL, base URL, rate limits) where relevant
- [ ] README includes troubleshooting section for common errors
- [ ] Main repo `README.md` updated with new integration entry (alphabetical order, include description and auth type)

### File Cleanup

- [ ] No `.pyc` files or `__pycache__/` directories committed
- [ ] No `.env` files committed
- [ ] No IDE-specific files (`.vscode/`, `.idea/`)
- [ ] No `.zip` files or test output files committed

### Git Hygiene

- [ ] Only integration-related files are staged (no unrelated changes)
- [ ] No sensitive data in commits
- [ ] Branch name follows convention (e.g., `feat/my-integration`)

---

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Uppercase folder name (`Netlify/`) | Use lowercase (`netlify/`) |
| Non-empty `__init__.py` with logic | Keep minimal — only import and `__all__` |
| Unused OAuth scopes | Remove scopes not used by any action |
| Missing icon | Add `icon.png` or `icon.svg` (512×512 pixels) |
| Missing or incomplete README | Document all actions, auth setup, inputs/outputs |
| Not updating main repo README | Add integration entry in alphabetical order |
| Unpinned SDK version | Use `autohive-integrations-sdk~=1.0.2` |
| Sync functions for action handlers | Must be `async def execute()` |

---

*Last updated: March 2026*
