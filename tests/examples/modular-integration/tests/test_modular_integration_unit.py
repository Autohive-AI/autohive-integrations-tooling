from autohive_integrations_sdk import ExecutionContext, FetchResponse

import pytest

from .context import modular_integration


pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


AUTH = {"auth_type": "Custom", "credentials": {"api_key": "test_key"}}


async def test_get_data():
    """Test get_data action."""

    async def fake_fetch(*args, **kwargs):
        return FetchResponse(status=200, headers={}, data=[{"id": "item-1"}])

    async with ExecutionContext(auth=AUTH) as context:
        context.fetch = fake_fetch
        result = await modular_integration.execute_action("get_data", {"limit": 5}, context)

    assert result.result.data == {"result": True, "data": [{"id": "item-1"}]}
