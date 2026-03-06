# Slack Integration for Autohive

Send messages and manage channels in your Slack workspace via the Slack Web API.

## Setup & Authentication

1. Create a Slack app at https://api.slack.com/apps
2. Add the following Bot Token Scopes: `chat:write`, `channels:read`
3. Install the app to your workspace
4. Copy the Bot User OAuth Token (starts with `xoxb-`)
5. Enter the token in Autohive

## Actions

### Send Message
**Description:** Send a message to a Slack channel

**Inputs:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| channel | string | Yes | Channel ID or name (e.g. `C1234567890` or `#general`) |
| text | string | Yes | Message text |

**Outputs:**
| Field | Type | Description |
|-------|------|-------------|
| ok | boolean | Whether the message was sent successfully |
| ts | string | Timestamp of the sent message |

### List Channels
**Description:** List all public channels in the workspace

**Inputs:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| limit | integer | No | Maximum number of channels to return (default: 100) |

**Outputs:**
| Field | Type | Description |
|-------|------|-------------|
| channels | array | List of channels with id, name, is_member, num_members |

## API Information

- **Documentation:** https://api.slack.com/methods
- **Base URL:** https://slack.com/api

## Version History

- **1.0.0** - Initial release
