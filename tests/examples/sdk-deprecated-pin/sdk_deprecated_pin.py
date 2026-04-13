from autohive_integrations_sdk import Integration, ExecutionContext, ActionHandler, ActionResult
from typing import Dict, Any

sdk_deprecated_pin = Integration.load()


@sdk_deprecated_pin.action("get_data")
class GetDataAction(ActionHandler):
    async def execute(self, inputs: Dict[str, Any], context: ExecutionContext):
        return ActionResult(data={"result": True})
