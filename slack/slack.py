"""
Slack Integration for Autohive

Provides actions for sending messages and managing Slack channels
via the Slack Web API.
"""

from autohive_integrations_sdk import Integration, ActionHandler, ActionResult, ExecutionContext
from typing import Dict, Any

slack = Integration.load()

SLACK_API_BASE = "https://slack.com/api"


def get_bot_token(context: ExecutionContext) -> str:
    """Extract bot token from execution context."""
    return context.auth.get("credentials", {}).get("bot_token", "")


@slack.action("send_message")
class SendMessageAction(ActionHandler):
    """Send a message to a Slack channel."""

    async def execute(self, inputs: Dict[str, Any], context: ExecutionContext):
        channel = inputs["channel"]
        text = inputs["text"]
        token = get_bot_token(context)

        response = await context.fetch(
            f"{SLACK_API_BASE}/chat.postMessage",
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            body={"channel": channel, "text": text},
        )

        return ActionResult(
            data={"ok": response.get("ok", False), "ts": response.get("ts", "")},
            cost_usd=0.0,
        )


@slack.action("list_channels")
class ListChannelsAction(ActionHandler):
    """List all public channels in the workspace."""

    async def execute(self, inputs: Dict[str, Any], context: ExecutionContext):
        limit = inputs.get("limit", 100)
        token = get_bot_token(context)

        response = await context.fetch(
            f"{SLACK_API_BASE}/conversations.list",
            method="GET",
            headers={"Authorization": f"Bearer {token}"},
            params={"limit": limit, "types": "public_channel"},
        )

        channels = [
            {
                "id": ch.get("id", ""),
                "name": ch.get("name", ""),
                "is_member": ch.get("is_member", False),
                "num_members": ch.get("num_members", 0),
            }
            for ch in response.get("channels", [])
        ]

        return ActionResult(data={"channels": channels}, cost_usd=0.0)
