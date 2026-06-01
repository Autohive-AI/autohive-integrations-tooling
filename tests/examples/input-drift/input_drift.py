from typing import Any, Dict

from autohive_integrations_sdk import ActionHandler, ActionResult, ExecutionContext, Integration

app = Integration.load()


@app.action("get_data")
class GetDataAction(ActionHandler):
    async def execute(self, inputs: Dict[str, Any], context: ExecutionContext):
        limit = inputs["limit"]
        optional_direct = inputs["optional_direct"]
        required_get = inputs.get("required_get")
        undocumented = inputs.get("undocumented_param")
        return ActionResult(
            data={
                "limit": limit,
                "optional_direct": optional_direct,
                "required_get": required_get,
                "undocumented": undocumented,
            },
            cost_usd=0.0,
        )
