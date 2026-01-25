# Relative Imports Test

Test cases for validating relative import resolution.

## Package Structure

```
mypackage/
├── __init__.py
├── utils.py
└── subpackage/
    ├── __init__.py
    ├── valid_relative.py
    └── invalid_relative.py
```

## Files

| File | Expected Result | Description |
|------|-----------------|-------------|
| `mypackage/subpackage/valid_relative.py` | Exit 0 (pass) | Uses valid relative imports like `from .. import utils` |
| `mypackage/subpackage/invalid_relative.py` | Exit 1 (fail) | Uses invalid relative imports to non-existent modules |

## Running Tests

```bash
# Should pass (exit 0)
python scripts/check_imports.py tests/examples/relative-imports/mypackage/subpackage/valid_relative.py

# Should fail (exit 1)
python scripts/check_imports.py tests/examples/relative-imports/mypackage/subpackage/invalid_relative.py
```

## How Resolution Works

1. Find the package root by walking up directories looking for `__init__.py`
2. Determine the current module's package path
3. Apply the relative level (number of dots) to navigate up
4. Append the target module name
5. Check if the resolved absolute path exists
