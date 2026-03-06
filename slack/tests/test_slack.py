"""
Tests for the Slack integration.

Uses mock credentials and responses — no real Slack workspace required.
"""

import asyncio
from context import slack

# Fake bot token used for testing only — not a real credential
FAKE_BOT_TOKEN = "xoxb-test-fake-token-not-real-1234567890"


class MockContext:
    """Mock ExecutionContext for testing."""

    def __init__(self, responses: dict):
        self.auth = {"credentials": {"bot_token": FAKE_BOT_TOKEN}}
        self._responses = responses

    async def fetch(self, url: str, method: str = "GET", **kwargs):
        key = f"{method} {url.split('slack.com/api/')[1]}"
        return self._responses.get(key, {})

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


async def test_send_message():
    """Test send_message action with a fake token and mock response."""
    context = MockContext(
        responses={
            "POST chat.postMessage": {
                "ok": True,
                "ts": "1234567890.123456",
            }
        }
    )

    result = await slack.execute_action(
        "send_message",
        {"channel": "C1234567890", "text": "Hello from tests!"},
        context,
    )

    assert result.data["ok"] is True
    assert result.data["ts"] == "1234567890.123456"
    print(f"send_message: {result.data}")


async def test_list_channels():
    """Test list_channels action with mock response."""
    context = MockContext(
        responses={
            "GET conversations.list": {
                "ok": True,
                "channels": [
                    {"id": "C1234567890", "name": "general", "is_member": True, "num_members": 42},
                    {"id": "C0987654321", "name": "random", "is_member": True, "num_members": 38},
                ],
            }
        }
    )

    result = await slack.execute_action(
        "list_channels",
        {"limit": 10},
        context,
    )

    assert len(result.data["channels"]) == 2
    assert result.data["channels"][0]["name"] == "general"
    print(f"list_channels: {result.data}")


async def run_all_tests():
    tests = [
        ("test_send_message", test_send_message),
        ("test_list_channels", test_list_channels),
    ]

    for name, test_func in tests:
        print(f"\nRunning {name}...")
        await test_func()

    print("\nAll tests completed!")


if __name__ == "__main__":
    asyncio.run(run_all_tests())
