"""The checks on the file fields of an action schema."""

import json
import shutil
from pathlib import Path

import pytest

from hiveup.checks.structure import FILE_SCHEMA_ID, file_field_problems, is_file_reference
from hiveup.cli import run_validation
from hiveup.sdk_requirement import SdkRequirement, sdk_requirement_warnings

EXAMPLES = Path(__file__).parent / "examples"
FILE_REF = {"$ref": FILE_SCHEMA_ID}
LEGACY_FILE = {
    "type": "object",
    "properties": {"content": {"type": "string"}, "name": {"type": "string"}, "contentType": {"type": "string"}},
    "required": ["content", "name", "contentType"],
}


def problems(schema: dict, *, is_input: bool = True, sdk_major: int | None = 3) -> list[tuple[str, str]]:
    return file_field_problems(
        schema, "input_schema" if is_input else "output_schema", is_input=is_input, sdk_major=sdk_major
    )


def schema_with(properties: dict) -> dict:
    return {"type": "object", "properties": properties}


# ── The file reference ───────────────────────────────────────────────────────


def test_file_reference_is_accepted_on_sdk_3_under_any_property_name() -> None:
    schema = schema_with(
        {
            "invoice": {"$ref": FILE_SCHEMA_ID, "description": "The invoice PDF"},
            "attachments": {"type": "array", "items": FILE_REF},
            "rows": {"type": "array", "items": schema_with({"scan": FILE_REF})},
        }
    )

    assert problems(schema) == []
    assert problems(schema, is_input=False) == []
    assert is_file_reference(FILE_REF) and not is_file_reference({"$ref": "#/definitions/file"})


@pytest.mark.parametrize("sdk_major", [1, 2])
def test_file_reference_on_an_sdk_before_3_is_an_error(sdk_major: int) -> None:
    found = problems(schema_with({"invoice": FILE_REF}), sdk_major=sdk_major)

    assert found == [
        (
            "error",
            f"input_schema.properties.invoice uses the file reference {FILE_SCHEMA_ID}, which needs "
            "autohive-integrations-sdk~=3.0.0 or later",
        )
    ]


def test_file_reference_is_not_checked_against_an_sdk_version_that_is_not_known() -> None:
    assert problems(schema_with({"invoice": FILE_REF}), sdk_major=None) == []


@pytest.mark.parametrize(
    "reference",
    [
        "https://cdn.autohive.com/schemas/sdk/file/v2.json",
        "https://cdn.autohive.com/schemas/sdk/files/v1.json",
        "https://schemas.autohive.com/sdk/file/v1.json",
        "http://cdn.autohive.com/schemas/sdk/file/v1.json",
        "https://CDN.autohive.com/schemas/sdk/file/v1.json",
    ],
)
@pytest.mark.parametrize("sdk_major", [None, 2, 3])
def test_unknown_autohive_reference_is_an_error(reference: str, sdk_major: int | None) -> None:
    found = problems(schema_with({"invoice": {"$ref": reference}}), sdk_major=sdk_major)

    assert found == [
        (
            "error",
            f"input_schema.properties.invoice has the unknown reference {reference}. "
            f"The file reference is {FILE_SCHEMA_ID}",
        )
    ]


def test_other_references_are_left_alone() -> None:
    schema = {
        "type": "object",
        "definitions": {"address": {"type": "object"}},
        "properties": {
            "home": {"$ref": "#/definitions/address"},
            "other": {"$ref": "https://example.com/schemas/thing.json"},
        },
    }

    assert problems(schema) == []
    assert problems(schema, sdk_major=2) == []


@pytest.mark.parametrize(
    ("schema", "path"),
    [
        (schema_with({"doc": {"anyOf": [{"type": "null"}, FILE_REF]}}), "input_schema.properties.doc.anyOf[1]"),
        ({"type": "object", "additionalProperties": FILE_REF}, "input_schema.additionalProperties"),
        (
            {
                "type": "object",
                "definitions": {"upload": FILE_REF},
                "properties": {"doc": {"$ref": "#/definitions/upload"}},
            },
            "input_schema.definitions.upload",
        ),
        (
            schema_with({"pair": {"type": "array", "items": [{"type": "string"}, FILE_REF]}}),
            "input_schema.properties.pair.items[1]",
        ),
        (
            schema_with({"doc": {"allOf": [schema_with({"scan": FILE_REF})]}}),
            "input_schema.properties.doc.allOf[0].properties.scan",
        ),
    ],
)
def test_file_reference_where_the_platform_does_not_look_is_a_warning(schema: dict, path: str) -> None:
    found = problems(schema)

    assert found == [
        (
            "warning",
            f"{path} declares a file where the platform does not look for one. Declare a file as a "
            "property of an object, or as the items of an array property",
        )
    ]


# ── The older file convention on SDK 3 ───────────────────────────────────────


def test_legacy_file_input_on_sdk_3_is_an_error() -> None:
    found = problems(schema_with({"file": LEGACY_FILE}))

    assert [severity for severity, _ in found] == ["error"]
    assert found[0][1].startswith("input_schema.properties.file uses the older file convention")
    assert f'Declare the field as {{"$ref": "{FILE_SCHEMA_ID}"}}' in found[0][1]


@pytest.mark.parametrize(
    "files_schema",
    [
        {"type": "array", "items": LEGACY_FILE},
        {"type": "array", "items": {"type": "object", "format": "file"}},
        {"type": "array", "items": {"additionalProperties": True}},
        {"type": "array"},
    ],
)
def test_files_input_array_without_reference_items_on_sdk_3_is_an_error(files_schema: dict) -> None:
    found = problems(schema_with({"files": files_schema}))

    assert [severity for severity, _ in found] == ["error"]
    assert found[0][1].startswith("input_schema.properties.files is an array named 'files'")


def test_files_input_array_of_references_on_sdk_3_is_accepted() -> None:
    assert problems(schema_with({"files": {"type": "array", "items": FILE_REF}})) == []


def test_legacy_file_input_nested_in_an_array_of_objects_on_sdk_3_is_an_error() -> None:
    schema = schema_with({"attachments": {"type": "array", "items": schema_with({"file": LEGACY_FILE})}})

    found = problems(schema)

    assert [severity for severity, _ in found] == ["error"]
    assert found[0][1].startswith("input_schema.properties.attachments.items.properties.file uses the older")


def test_legacy_shape_under_another_input_name_on_sdk_3_is_left_alone() -> None:
    """The platform treats only 'file' and 'files' as files, so another name holds ordinary data."""
    assert (
        problems(schema_with({"attachment": LEGACY_FILE, "items": {"type": "array", "items": {"type": "string"}}}))
        == []
    )


def test_legacy_file_output_on_sdk_3_is_a_warning() -> None:
    found = problems(schema_with({"file": LEGACY_FILE, "export": LEGACY_FILE}), is_input=False)

    assert [severity for severity, _ in found] == ["warning", "warning"]
    assert found[0][1].startswith("output_schema.properties.file returns a file with the older file convention")


def test_output_array_named_files_on_sdk_3_is_left_alone() -> None:
    """An output named 'files' is often a listing, not file content."""
    listing = {"type": "array", "items": schema_with({"id": {"type": "string"}, "name": {"type": "string"}})}

    assert problems(schema_with({"files": listing}), is_input=False) == []


@pytest.mark.parametrize("sdk_major", [None, 1, 2])
def test_older_file_convention_is_not_reported_before_sdk_3(sdk_major: int | None) -> None:
    schema = schema_with({"file": LEGACY_FILE, "files": {"type": "array", "items": LEGACY_FILE}})

    assert problems(schema, sdk_major=sdk_major) == []
    assert problems(schema, is_input=False, sdk_major=sdk_major) == []


def test_values_that_are_not_schemas_are_ignored() -> None:
    schema = {
        "type": "object",
        "default": {"$ref": "https://cdn.autohive.com/schemas/other.json"},
        "examples": [{"file": LEGACY_FILE}],
        "properties": {"note": "not a schema"},
    }

    assert problems(schema) == []
    assert file_field_problems("not a schema", "input_schema", is_input=True, sdk_major=3) == []


# ── Through the structure check ──────────────────────────────────────────────


def integration(tmp_path: Path, sdk_requirement: str, input_schema: dict, output_schema: dict) -> Path:
    path = tmp_path / "file-fields"
    shutil.copytree(EXAMPLES / "good-integration", path)
    config_path = path / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["actions"]["get_data"]["input_schema"] = input_schema
    config["actions"]["get_data"]["output_schema"] = output_schema
    config_path.write_text(json.dumps(config), encoding="utf-8")
    (path / "requirements.txt").write_text(f"{sdk_requirement}\n", encoding="utf-8")
    return path


def structure_messages(path: Path) -> tuple[str, list[tuple[str, str]]]:
    result = run_validation([path], only={"structure"}).results[0]
    return result.status, [(message.severity, message.message) for message in result.messages]


def test_structure_accepts_file_references_on_sdk_3(tmp_path: Path) -> None:
    path = integration(
        tmp_path,
        "autohive-integrations-sdk~=3.0.0",
        schema_with({"invoice": FILE_REF}),
        schema_with({"receipt": FILE_REF}),
    )

    status, messages = structure_messages(path)

    assert status != "failed", messages
    assert not [message for _, message in messages if "file" in message.lower() or "SDK major" in message]


def test_structure_rejects_a_file_reference_on_sdk_2(tmp_path: Path) -> None:
    path = integration(
        tmp_path,
        "autohive-integrations-sdk~=2.1.0",
        schema_with({"invoice": FILE_REF}),
        schema_with({"receipt": FILE_REF}),
    )

    status, messages = structure_messages(path)

    assert status == "failed"
    errors = [message for severity, message in messages if severity == "error"]
    assert errors == [
        f"Action 'get_data' input_schema.properties.invoice uses the file reference {FILE_SCHEMA_ID}, which needs "
        "autohive-integrations-sdk~=3.0.0 or later",
        f"Action 'get_data' output_schema.properties.receipt uses the file reference {FILE_SCHEMA_ID}, which needs "
        "autohive-integrations-sdk~=3.0.0 or later",
    ]


def test_structure_reports_the_older_convention_on_sdk_3(tmp_path: Path) -> None:
    path = integration(
        tmp_path,
        "autohive-integrations-sdk~=3.0.0",
        schema_with({"file": LEGACY_FILE}),
        schema_with({"file": LEGACY_FILE}),
    )

    status, messages = structure_messages(path)

    assert status == "failed"
    assert [severity for severity, message in messages if "older file convention" in message] == ["error", "warning"]


def test_structure_keeps_the_older_convention_valid_on_sdk_2(tmp_path: Path) -> None:
    path = integration(
        tmp_path,
        "autohive-integrations-sdk~=2.1.0",
        schema_with({"file": LEGACY_FILE}),
        schema_with({"file": LEGACY_FILE}),
    )

    status, messages = structure_messages(path)

    assert status != "failed", messages
    assert not [message for _, message in messages if "file convention" in message or "file reference" in message]


def test_structure_reports_an_unknown_reference_when_the_sdk_requirement_cannot_be_read(tmp_path: Path) -> None:
    reference = "https://cdn.autohive.com/schemas/sdk/file/v9.json"
    path = integration(tmp_path, "requests==2.32.0", schema_with({"invoice": {"$ref": reference}}), schema_with({}))

    _, messages = structure_messages(path)

    assert (
        "error",
        f"Action 'get_data' input_schema.properties.invoice has the unknown reference {reference}. "
        f"The file reference is {FILE_SCHEMA_ID}",
    ) in messages


# ── The SDK major version ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("version", "unknown"), [((2, 1, 0), False), ((3, 0, 0), False), ((3, 4, 1), False), ((4, 0, 0), True)]
)
def test_sdk_major_version_3_is_known(version: tuple[int, int, int], unknown: bool) -> None:
    requirement = SdkRequirement(operator="~=", version_text=".".join(str(part) for part in version), version=version)

    warnings = sdk_requirement_warnings(requirement)

    assert bool([warning for warning in warnings if "Unknown SDK major version" in warning]) is unknown
    if unknown:
        assert "expected major version 1, 2, 3" in warnings[0]
    assert not [warning for warning in warnings if "below the recommended" in warning]
