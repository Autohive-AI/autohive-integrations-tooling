# Name Verification Test

Test cases for validating that imported names exist within modules.

## Files

| File | Expected Result (default) | Expected Result (--verify-names) | Description |
|------|---------------------------|----------------------------------|-------------|
| `valid_names.py` | Exit 0 (pass) | Exit 0 (pass) | All imported names exist |
| `invalid_names.py` | Exit 0 (pass) | Exit 1 (fail) | Names don't exist in modules |

## Running Tests

```bash
# Without --verify-names: both pass (only checks module existence)
python scripts/check_imports.py tests/examples/name-verification/valid_names.py
python scripts/check_imports.py tests/examples/name-verification/invalid_names.py

# With --verify-names: invalid_names.py fails
python scripts/check_imports.py --verify-names tests/examples/name-verification/valid_names.py
python scripts/check_imports.py --verify-names tests/examples/name-verification/invalid_names.py
```

## Security Warning

The `--verify-names` flag imports modules to check for name existence.
This means module-level code will be executed. Only use with trusted code.
