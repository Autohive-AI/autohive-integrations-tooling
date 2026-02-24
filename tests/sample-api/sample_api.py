from autohive_integrations_sdk import Integration, ExecutionContext, ActionHandler, ActionResult
from typing import Dict, Any

sample_api = Integration.load()

BASE_URL = "https://api.sample.com/v1"


def get_headers(context: ExecutionContext) -> Dict[str, str]:
    """Build request headers with authentication."""
    credentials = context.auth.get("credentials", {})
    api_key = credentials.get("api_key", "")
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


@sample_api.action("list_items")
class ListItemsAction(ActionHandler):
    """Retrieves a list of items from the API."""

    async def execute(self, inputs: Dict[str, Any], context: ExecutionContext):
        try:
            limit = inputs.get("limit", 10)
            headers = get_headers(context)

            response = await context.fetch(f"{BASE_URL}/items?limit={limit}", method="GET", headers=headers)

            return ActionResult(data={"result": True, "items": response.get("items", [])}, cost_usd=0.0)
        except Exception as e:
            return ActionResult(data={"result": False, "error": str(e)}, cost_usd=0.0)


@sample_api.action("get_item")
class GetItemAction(ActionHandler):
    """Retrieves a single item by ID."""

    async def execute(self, inputs: Dict[str, Any], context: ExecutionContext):
        try:
            item_id = inputs.get("item_id")
            headers = get_headers(context)

            response = await context.fetch(f"{BASE_URL}/items/{item_id}", method="GET", headers=headers)

            return ActionResult(data={"result": True, "item": response}, cost_usd=0.0)
        except Exception as e:
            return ActionResult(data={"result": False, "error": str(e)}, cost_usd=0.0)
