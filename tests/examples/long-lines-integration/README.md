# Long Lines Integration

Test fixture with Python lines between 89–120 characters to verify that `check_code.py` applies the tooling repo's `ruff.toml` config (line-length = 120) rather than ruff's default (88).

## Actions

### Get Data
**Description:** Retrieves data from the API

**Inputs:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| limit | integer | No | Maximum number of items (default: 10) |

**Outputs:**
| Field | Type | Description |
|-------|------|-------------|
| result | boolean | Success indicator |
| data | array | The returned data |
| error | string | Error message if failed |
