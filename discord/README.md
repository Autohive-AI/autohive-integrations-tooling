# Discord Integration for Autohive

Send messages and retrieve server information from your Discord workspace via the Discord REST API.

## Setup & Authentication

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application and navigate to the **Bot** section
3. Click **Reset Token** to generate a bot token
4. Enable the **Server Members Intent** under Privileged Gateway Intents
5. Invite the bot to your server using the OAuth2 URL Generator with the `bot` scope and required permissions
6. Copy the bot token and enter it in Autohive

## Actions

### Send Message
**Description:** Send a message to a Discord channel

**Inputs:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| channel_id | string | Yes | The ID of the channel to send the message to |
| content | string | Yes | The message content to send |

**Outputs:**
| Field | Type | Description |
|-------|------|-------------|
| id | string | The ID of the sent message |
| channel_id | string | The channel the message was sent to |
| content | string | The content of the sent message |

### Get Server Info
**Description:** Retrieve information about a Discord server (guild)

**Inputs:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| guild_id | string | Yes | The ID of the Discord server |

**Outputs:**
| Field | Type | Description |
|-------|------|-------------|
| id | string | The server ID |
| name | string | The server name |
| member_count | integer | Approximate number of members |

## API Information

- **Documentation:** https://discord.com/developers/docs/reference
- **Base URL:** https://discord.com/api/v10

## Version History

- **1.0.0** - Initial release
