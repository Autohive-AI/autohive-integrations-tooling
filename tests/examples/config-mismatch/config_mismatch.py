from autohive_integrations_sdk import Integration, ExecutionContext, ActionHandler, ActionResult
from typing import Dict, Any

app = Integration.load()


@app.action("get_data")
class GetDataAction(ActionHandler):
    async def execute(self, inputs: Dict[str, Any], context: ExecutionContext):
        limit = inputs["limit"]
        secret = inputs.get("undocumented_param")
        return ActionResult(data={"result": True}, cost_usd=0.0)


@app.action("missing_in_config")
class MissingInConfigAction(ActionHandler):
    async def execute(self, inputs: Dict[str, Any], context: ExecutionContext):
        return ActionResult(data={"result": True}, cost_usd=0.0)
