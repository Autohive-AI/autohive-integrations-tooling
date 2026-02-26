from autohive_integrations_sdk import Integration, ExecutionContext, ActionHandler, ActionResult
from typing import Dict, Any

bad_icon = Integration.load()


@bad_icon.action("get_data")
class GetDataAction(ActionHandler):
    """Retrieves data from the API."""

    async def execute(self, inputs: Dict[str, Any], context: ExecutionContext):
        return ActionResult(data={"result": True}, cost_usd=0.0)
