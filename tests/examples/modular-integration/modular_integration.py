from pathlib import Path

from autohive_integrations_sdk import Integration

modular_integration = Integration.load(Path(__file__).with_name("config.json"))

import actions  # noqa: E402, F401
