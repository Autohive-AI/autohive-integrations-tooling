"""
Discord Integration for Autohive

Provides actions for sending messages and retrieving server information
via the Discord REST API.
"""

from typing import Any, Dict

from autohive_integrations_sdk import ActionHandler, ActionResult, ExecutionContext, Integration

discord = Integration.load()

DISCORD_API_BASE = "https://discord.com/api/v10"


def get_bot_token(context: ExecutionContext) -> str:
    """Extract bot token from execution context."""
    return context.auth.get("credentials", {}).get("bot_token", "")


@discord.action("send_message")
class SendMessageAction(ActionHandler):
    """Send a message to a Discord channel."""

    async def execute(self, inputs: Dict[str, Any], context: ExecutionContext):
        channel_id = inputs["channel_id"]
        content = inputs["content"]
        token = get_bot_token(context)

        response = await context.fetch(
            f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
            method="POST",
            headers={
                "Authorization": f"Bot {token}",
                "Content-Type": "application/json",
            },
            body={"content": content},
        )

        return ActionResult(
            data={
                "id": response.get("id", ""),
                "channel_id": response.get("channel_id", ""),
                "content": response.get("content", ""),
            },
            cost_usd=0.0,
        )


@discord.action("get_guild_info")
class GetGuildInfoAction(ActionHandler):
    """Retrieve information about a Discord server (guild)."""

    async def execute(self, inputs: Dict[str, Any], context: ExecutionContext):
        guild_id = inputs["guild_id"]
        token = get_bot_token(context)

        response = await context.fetch(
            f"{DISCORD_API_BASE}/guilds/{guild_id}",
            method="GET",
            headers={"Authorization": f"Bot {token}"},
            params={"with_counts": "true"},
        )

        return ActionResult(
            data={
                "id": response.get("id", ""),
                "name": response.get("name", ""),
                "member_count": response.get("approximate_member_count", 0),
            },
            cost_usd=0.0,
        )
