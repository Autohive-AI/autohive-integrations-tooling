import asyncio
from context import bad_icon
from autohive_integrations_sdk import ExecutionContext


async def test_get_data():
    """Test get_data action."""
    auth = {"credentials": {"api_key": "test_key"}}

    async with ExecutionContext(auth=auth) as context:
        result = await bad_icon.execute_action("get_data", {}, context)
        data = result.data
        assert "result" in data


if __name__ == "__main__":
    asyncio.run(test_get_data())
