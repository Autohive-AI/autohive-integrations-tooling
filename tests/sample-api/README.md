# Sample API Integration for Autohive

Sample API integration for testing the validation workflow.

## Setup & Authentication

1. Get your API key from the Sample API dashboard
2. Enter the API key in Autohive

## Actions

### List Items
**Description:** Retrieves a list of items from the API

**Inputs:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| limit | integer | No | Maximum number of items (default: 10) |

**Outputs:**
| Field | Type | Description |
|-------|------|-------------|
| result | boolean | Success indicator |
| items | array | List of items |
| error | string | Error message if failed |

### Get Item
**Description:** Retrieves a single item by ID

**Inputs:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| item_id | string | Yes | The ID of the item |

**Outputs:**
| Field | Type | Description |
|-------|------|-------------|
| result | boolean | Success indicator |
| item | object | The item data |
| error | string | Error message if failed |

## API Information

- **Base URL:** https://api.sample.com/v1
- **Authentication:** API Key (Bearer token)

## Version History

- **1.0.0** - Initial release
