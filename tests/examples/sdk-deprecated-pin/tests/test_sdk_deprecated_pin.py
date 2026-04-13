import asyncio
from context import sdk_deprecated_pin
from autohive_integrations_sdk import ExecutionContext


async def test_get_data():
    result = await sdk_deprecated_pin.execute_action(
        "get_data",
        {},
        ExecutionContext(auth={}, settings={})
    )
    assert result.data["result"] is True


if __name__ == "__main__":
    asyncio.run(test_get_data())
    print("All tests passed!")
