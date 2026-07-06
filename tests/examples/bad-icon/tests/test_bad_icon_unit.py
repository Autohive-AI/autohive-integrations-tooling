from autohive_integrations_sdk import ExecutionContext

import pytest

from .context import bad_icon


pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


AUTH = {"auth_type": "Custom", "credentials": {"api_key": "test_key"}}


async def test_get_data():
    """Test get_data action."""
    async with ExecutionContext(auth=AUTH) as context:
        result = await bad_icon.execute_action("get_data", {}, context)
        data = result.result.data
        assert "result" in data
