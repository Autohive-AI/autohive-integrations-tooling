import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from validate_integration import IntegrationValidator  # noqa: E402


def _validate_auth(config: dict) -> IntegrationValidator:
    validator = IntegrationValidator(Path("custom-auth"))
    validator.config = config
    validator._validate_auth_config()
    return validator


def test_custom_auth_without_required_is_valid() -> None:
    validator = _validate_auth(
        {
            "auth": {
                "type": "custom",
                "fields": {
                    "type": "object",
                    "properties": {
                        "api_key": {"type": "string"},
                    },
                },
            }
        }
    )

    assert validator.errors == []
    assert validator.warnings == []


def test_custom_auth_empty_required_array_is_allowed() -> None:
    validator = _validate_auth(
        {
            "auth": {
                "type": "custom",
                "fields": {
                    "type": "object",
                    "properties": {
                        "api_key": {"type": "string"},
                    },
                    "required": [],
                },
            }
        }
    )

    assert validator.errors == []
    assert validator.warnings == []


def test_custom_auth_non_empty_required_array_is_rejected() -> None:
    validator = _validate_auth(
        {
            "auth": {
                "type": "custom",
                "fields": {
                    "type": "object",
                    "properties": {
                        "api_key": {"type": "string"},
                    },
                    "required": ["api_key"],
                },
            }
        }
    )

    messages = [error.message for error in validator.errors]
    assert messages == [
        "Custom auth fields must not define a non-empty auth.fields.required array. "
        "Credential collection and presence are handled by the platform connection flow; "
        "define auth.fields.properties only."
    ]
    assert validator.warnings == []
