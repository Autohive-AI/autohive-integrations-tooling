import asyncio
from context import sample_api
from autohive_integrations_sdk import ExecutionContext


async def test_list_items():
    """Test list_items action."""
    auth = {
        "credentials": {"api_key": "test_key"}
    }

    async with ExecutionContext(auth=auth) as context:
        try:
            result = await sample_api.execute_action(
                "list_items",
                {"limit": 5},
                context
            )

            data = result.data
            assert "result" in data
            print(f"List Items Result: {data}")
        except Exception as e:
            print(f"Error: {e}")


async def test_get_item():
    """Test get_item action."""
    auth = {
        "credentials": {"api_key": "test_key"}
    }

    async with ExecutionContext(auth=auth) as context:
        try:
            result = await sample_api.execute_action(
                "get_item",
                {"item_id": "123"},
                context
            )

            data = result.data
            assert "result" in data
            print(f"Get Item Result: {data}")
        except Exception as e:
            print(f"Error: {e}")


async def run_all_tests():
    """Run all tests."""
    tests = [
        ("test_list_items", test_list_items),
        ("test_get_item", test_get_item),
    ]

    for name, test_func in tests:
        print(f"\nRunning {name}...")
        await test_func()

    print("\nAll tests completed!")


if __name__ == "__main__":
    asyncio.run(run_all_tests())
