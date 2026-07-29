import asyncio
from context import old_fetch
from autohive_integrations_sdk import ExecutionContext


async def test_get_data():
    result = await old_fetch.execute_action(
        "get_data",
        {"url": "https://example.com"},
        ExecutionContext(auth={}, settings={})
    )
    assert result.data["result"] is True


if __name__ == "__main__":
    asyncio.run(test_get_data())
    print("All tests passed!")
