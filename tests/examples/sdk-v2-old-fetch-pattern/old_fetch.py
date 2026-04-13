from autohive_integrations_sdk import Integration, ExecutionContext, ActionHandler, ActionResult
from typing import Dict, Any

old_fetch = Integration.load()


@old_fetch.action("get_data")
class GetDataAction(ActionHandler):
    async def execute(self, inputs: Dict[str, Any], context: ExecutionContext):
        url = inputs["url"]
        response = await context.fetch(url)
        items = response.get("items", [])
        return ActionResult(data={"result": True, "data": response})
