from autohive_integrations_sdk import Integration

modular_integration = Integration.load()

from .actions import GetDataAction  # noqa: E402, F401
