from typing import Dict, Any
from pathlib import Path

from autohive_integrations_sdk import Integration, ExecutionContext, ActionHandler, ActionResult

bad_icon = Integration.load(Path(__file__).with_name("config.json"))


@bad_icon.action("get_data")
class GetDataAction(ActionHandler):
    """Retrieves data from the API."""

    async def execute(self, inputs: Dict[str, Any], context: ExecutionContext):
        return ActionResult(data={"result": True}, cost_usd=0.0)
