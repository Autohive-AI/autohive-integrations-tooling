"""
Tests for the Discord integration.

Uses mock credentials and responses — no real Discord server required.
"""

import asyncio

from context import discord


class MockContext:
    """Mock ExecutionContext for testing."""

    def __init__(self, responses: dict):
        self.auth = {"credentials": {"bot_token": "test_token"}}  # nosec B105
        self._responses = responses

    async def fetch(self, url: str, method: str = "GET", **kwargs):
        key = f"{method} {url.split('discord.com/api/v10/')[1]}"
        return self._responses.get(key, {})

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


async def test_send_message():
    """Test send_message action with mock response."""
    context = MockContext(
        responses={
            "POST channels/C1234567890/messages": {
                "id": "9876543210",
                "channel_id": "C1234567890",
                "content": "Hello from tests!",
            }
        }
    )

    result = await discord.execute_action(
        "send_message",
        {"channel_id": "C1234567890", "content": "Hello from tests!"},
        context,
    )

    assert result.data["id"] == "9876543210"
    assert result.data["channel_id"] == "C1234567890"
    assert result.data["content"] == "Hello from tests!"
    print(f"send_message: {result.data}")


async def test_get_guild_info():
    """Test get_guild_info action with mock response."""
    context = MockContext(
        responses={
            "GET guilds/G1234567890": {
                "id": "G1234567890",
                "name": "Test Server",
                "approximate_member_count": 42,
            }
        }
    )

    result = await discord.execute_action(
        "get_guild_info",
        {"guild_id": "G1234567890"},
        context,
    )

    assert result.data["id"] == "G1234567890"
    assert result.data["name"] == "Test Server"
    assert result.data["member_count"] == 42
    print(f"get_guild_info: {result.data}")


async def run_all_tests():
    tests = [
        ("test_send_message", test_send_message),
        ("test_get_guild_info", test_get_guild_info),
    ]

    for name, test_func in tests:
        print(f"\nRunning {name}...")
        await test_func()

    print("\nAll tests completed!")


if __name__ == "__main__":
    asyncio.run(run_all_tests())
