from autohive_integrations_sdk import ExecutionContext, FetchResponse

import pytest

from .context import sample_api


pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


AUTH = {"auth_type": "Custom", "credentials": {"api_key": "test_key"}}


async def test_list_items():
    """Test list_items action."""

    async def fake_fetch(*args, **kwargs):
        return FetchResponse(status=200, headers={}, data={"items": [{"id": "item-1"}]})

    async with ExecutionContext(auth=AUTH) as context:
        context.fetch = fake_fetch
        result = await sample_api.execute_action("list_items", {"limit": 5}, context)

    assert result.result.data == {"result": True, "items": [{"id": "item-1"}]}


async def test_get_item():
    """Test get_item action."""

    async def fake_fetch(*args, **kwargs):
        return FetchResponse(status=200, headers={}, data={"id": "123"})

    async with ExecutionContext(auth=AUTH) as context:
        context.fetch = fake_fetch
        result = await sample_api.execute_action("get_item", {"item_id": "123"}, context)

    assert result.result.data == {"result": True, "item": {"id": "123"}}
