# Submodule Imports Test

Test cases for validating full submodule path checking.

## Files

| File | Expected Result | Description |
|------|-----------------|-------------|
| `valid_submodules.py` | Exit 0 (pass) | Uses real stdlib submodules like `os.path`, `collections.abc` |
| `invalid_submodules.py` | Exit 1 (fail) | Uses fake submodules like `os.nonexistent_submodule` |

## Running Tests

```bash
# Should pass (exit 0)
python scripts/check_imports.py tests/examples/submodule-imports/valid_submodules.py

# Should fail (exit 1)
python scripts/check_imports.py tests/examples/submodule-imports/invalid_submodules.py
```
