import json
import struct
import sys
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

import hiveup.cli as cli
from hiveup.cli import app
from hiveup.checks import static
from hiveup.checks import tests as test_checks
from hiveup.core.environment import IntegrationEnvironment


@pytest.mark.parametrize(
    ("auth_type", "expected_auth_type"),
    [("none", None), ("custom", "custom"), ("platform", "platform")],
)
def test_create_generates_sdk_v2_scaffold(
    tmp_path: Path,
    monkeypatch,
    auth_type: str,
    expected_auth_type: str | None,
) -> None:
    monkeypatch.chdir(tmp_path)
    command = ["create", "Sample Integration", "--auth-type", auth_type]
    if auth_type == "platform":
        command.extend(["--auth-provider", "github"])

    result = CliRunner().invoke(app, command)

    assert result.exit_code == 0
    integration = tmp_path / "sample-integration"
    assert {path.relative_to(integration).as_posix() for path in integration.rglob("*") if path.is_file()} == {
        ".gitignore",
        "README.md",
        "__init__.py",
        "config.json",
        "icon.png",
        "requirements.txt",
        "sample_integration.py",
        "tests/__init__.py",
        "tests/conftest.py",
        "tests/test_sample_integration_unit.py",
    }
    config = json.loads((integration / "config.json").read_text(encoding="utf-8"))
    assert config["name"] == "sample-integration"
    assert config["display_name"] == "Sample Integration"
    assert config["version"] == "1.0.0"
    assert config["entry_point"] == "sample_integration.py"
    assert config["actions"]["get_data"]["output_schema"]["type"] == "object"
    if expected_auth_type is None:
        assert "auth" not in config
    else:
        assert config["auth"]["type"] == expected_auth_type
    if auth_type == "platform":
        assert config["auth"] == {"type": "platform", "provider": "github"}

    module = (integration / "sample_integration.py").read_text(encoding="utf-8")
    assert "sample_integration = Integration.load(" in module
    assert "class GetDataAction(ActionHandler):" in module
    assert "context: ExecutionContext) -> ActionResult:" in module
    tests = (integration / "tests" / "test_sample_integration_unit.py").read_text(encoding="utf-8")
    assert "pytest.mark.unit" in tests
    assert "async def test_get_data(mock_context):" in tests
    assert "ExecutionContext" not in tests
    conftest = (integration / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert "def mock_context():" in conftest
    assert "AsyncMock" in conftest

    readme = (integration / "README.md").read_text(encoding="utf-8")
    for heading in ("## Description", "## Authentication", "## Actions", "## Requirements", "## Development"):
        assert heading in readme
    assert (integration / "requirements.txt").read_text(encoding="utf-8") == (
        "autohive-integrations-sdk~=2.0.1\n"
    )
    icon = (integration / "icon.png").read_bytes()
    assert icon[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", icon[16:24]) == (512, 512)


def test_init_generates_scaffold_in_current_directory(tmp_path: Path, monkeypatch) -> None:
    integration = tmp_path / "existing-directory"
    integration.mkdir()
    monkeypatch.chdir(integration)

    result = CliRunner().invoke(app, ["init", "--name", "Display Name"])

    assert result.exit_code == 0
    config = json.loads((integration / "config.json").read_text(encoding="utf-8"))
    assert config["name"] == "existing-directory"
    assert config["display_name"] == "Display Name"
    assert config["entry_point"] == "existing_directory.py"


@pytest.mark.parametrize(("name", "target"), [("123 sample", "123-sample"), ("class", "class")])
def test_create_rejects_names_that_are_invalid_python_identifiers(
    tmp_path: Path,
    monkeypatch,
    name: str,
    target: str,
) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["create", name])

    assert result.exit_code == 2
    assert "does not produce a valid Python identifier" in result.output
    assert not (tmp_path / target).exists()


def test_scaffold_rejects_nonempty_target_without_force(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "sample"
    target.mkdir()
    existing = target / "notes.txt"
    existing.write_text("keep me", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["create", "sample"])

    assert result.exit_code == 2
    assert "Directory is not empty" in result.output
    assert existing.read_text(encoding="utf-8") == "keep me"
    assert set(target.iterdir()) == {existing}


def test_force_replaces_only_scaffold_owned_files(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "sample"
    target.mkdir()
    unknown = target / "notes.txt"
    unknown.write_text("keep me", encoding="utf-8")
    config = target / "config.json"
    config.write_text("old config", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["create", "sample", "--force"])

    assert result.exit_code == 0
    assert "Files: 9 created, 1 replaced" in result.output
    assert unknown.read_text(encoding="utf-8") == "keep me"
    assert json.loads(config.read_text(encoding="utf-8"))["name"] == "sample"


def test_force_preflights_directory_conflicts_before_writing(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "sample"
    target.mkdir()
    config = target / "config.json"
    config.write_text("old config", encoding="utf-8")
    (target / "tests").write_text("not a directory", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["create", "sample", "--force"])

    assert result.exit_code == 2
    assert "Cannot create scaffold directory" in result.output
    assert config.read_text(encoding="utf-8") == "old config"


def test_scaffold_rolls_back_owned_files_after_write_failure(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "sample"
    target.mkdir()
    config = target / "config.json"
    config.write_text("old config", encoding="utf-8")
    unknown = target / "notes.txt"
    unknown.write_text("keep me", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    atomic_write = cli._atomic_write
    writes = 0

    def fail_during_write(path: Path, content: bytes) -> None:
        nonlocal writes
        writes += 1
        if writes == 3:
            raise OSError("disk full")
        atomic_write(path, content)

    monkeypatch.setattr(cli, "_atomic_write", fail_during_write)

    result = CliRunner().invoke(app, ["create", "sample", "--force"])

    assert result.exit_code == 2
    assert "Could not write scaffold: disk full" in result.output
    assert config.read_text(encoding="utf-8") == "old config"
    assert unknown.read_text(encoding="utf-8") == "keep me"
    assert set(target.iterdir()) == {config, unknown}


def test_scaffold_rejects_invalid_auth_before_writing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["create", "sample", "--auth-type", "invalid"])

    assert result.exit_code == 2
    assert "Unsupported auth type: invalid" in result.output
    assert not (tmp_path / "sample").exists()


def test_platform_scaffold_requires_explicit_provider_before_writing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["create", "sample", "--auth-type", "platform"])

    assert result.exit_code == 2
    assert "--auth-provider is required" in result.output
    assert not (tmp_path / "sample").exists()


def test_platform_scaffold_accepts_optional_scopes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "create",
            "sample",
            "--auth-type",
            "platform",
            "--auth-provider",
            "Google Docs",
            "--auth-scopes",
            "documents.read,documents.write",
        ],
    )

    assert result.exit_code == 0
    config = json.loads((tmp_path / "sample" / "config.json").read_text(encoding="utf-8"))
    assert config["auth"] == {
        "type": "platform",
        "provider": "Google Docs",
        "scopes": ["documents.read", "documents.write"],
    }


def test_auth_requires_explicit_operation_without_changing_config(tmp_path: Path) -> None:
    integration = tmp_path / "sample"
    integration.mkdir()
    config_path = integration / "config.json"
    original = b'{"name":"sample","auth":{"type":"custom"}}\n'
    config_path.write_bytes(original)

    result = CliRunner().invoke(app, ["auth", str(integration)])

    assert result.exit_code == 2
    assert "--auth-type is required" in result.output
    assert config_path.read_bytes() == original


def test_auth_none_explicitly_removes_auth(tmp_path: Path) -> None:
    integration = tmp_path / "sample"
    integration.mkdir()
    config_path = integration / "config.json"
    config_path.write_text('{"name":"sample","auth":{"type":"custom"}}\n', encoding="utf-8")

    result = CliRunner().invoke(app, ["auth", str(integration), "--auth-type", "none"])

    assert result.exit_code == 0
    assert json.loads(config_path.read_text(encoding="utf-8")) == {"name": "sample"}


def test_auth_preserves_custom_schema_and_unknown_config_fields(tmp_path: Path) -> None:
    integration = tmp_path / "sample"
    integration.mkdir()
    config_path = integration / "config.json"
    config = {
        "name": "sample",
        "extension": {"enabled": True},
        "auth": {
            "type": "custom",
            "title": "Account credentials",
            "documentation_url": "https://example.com/auth",
            "fields": {
                "type": "object",
                "properties": {"token": {"type": "string", "format": "password"}},
                "required": ["token"],
            },
        },
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")

    result = CliRunner().invoke(app, ["auth", str(integration), "--auth-type", "custom"])

    assert result.exit_code == 0
    assert json.loads(config_path.read_text(encoding="utf-8")) == config


def test_auth_updates_only_requested_platform_fields(tmp_path: Path) -> None:
    integration = tmp_path / "sample"
    integration.mkdir()
    config_path = integration / "config.json"
    config = {
        "name": "sample",
        "auth": {
            "type": "platform",
            "provider": "github",
            "scopes": ["repo"],
            "authorization_options": {"prompt": "consent"},
        },
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["auth", str(integration), "--auth-type", "platform", "--auth-scopes", "read:user,user:email"],
    )

    assert result.exit_code == 0
    updated = json.loads(config_path.read_text(encoding="utf-8"))
    assert updated["name"] == "sample"
    assert updated["auth"] == {
        "type": "platform",
        "provider": "github",
        "scopes": ["read:user", "user:email"],
        "authorization_options": {"prompt": "consent"},
    }


def test_auth_requires_provider_when_switching_to_platform(tmp_path: Path) -> None:
    integration = tmp_path / "sample"
    integration.mkdir()
    config_path = integration / "config.json"
    original = b'{"name":"sample","auth":{"type":"custom","fields":{"type":"object"}}}\n'
    config_path.write_bytes(original)

    result = CliRunner().invoke(app, ["auth", str(integration), "--auth-type", "platform"])

    assert result.exit_code == 2
    assert "--auth-provider is required" in result.output
    assert config_path.read_bytes() == original


def test_auth_invalid_json_leaves_file_unchanged(tmp_path: Path) -> None:
    integration = tmp_path / "sample"
    integration.mkdir()
    config_path = integration / "config.json"
    original = b"{not json\n"
    config_path.write_bytes(original)

    result = CliRunner().invoke(app, ["auth", str(integration), "--auth-type", "none"])

    assert result.exit_code == 2
    assert "Could not read config.json" in result.output
    assert config_path.read_bytes() == original


def test_structure_warns_for_noncanonical_unit_test_name_without_history(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert CliRunner().invoke(app, ["create", "sample"]).exit_code == 0
    unit_test = tmp_path / "sample" / "tests" / "test_sample_unit.py"
    unit_test.rename(unit_test.with_name("test_sample.py"))

    result = CliRunner().invoke(app, ["validate", str(tmp_path / "sample"), "--only", "structure"])

    assert result.exit_code == 0
    assert "passed with warnings" in result.output
    assert "Missing unit test file: tests/test_*_unit.py" in result.output


@pytest.mark.parametrize("command", [["create", "sample"], ["init", "--name", "Sample"]])
def test_fresh_scaffold_validates_tests_and_packages(tmp_path: Path, monkeypatch, command: list[str]) -> None:
    integration = tmp_path / "sample"
    if command[0] == "init":
        integration.mkdir()
        monkeypatch.chdir(integration)
    else:
        monkeypatch.chdir(tmp_path)

    isolated = IntegrationEnvironment(tmp_path / "environment", Path(sys.executable), "test", created=False)
    monkeypatch.setattr(static, "prepare_environment", lambda *args, **kwargs: isolated)
    monkeypatch.setattr(test_checks, "prepare_environment", lambda *args, **kwargs: isolated)

    def stage_dependencies(requirements: Path, target: Path) -> None:
        assert requirements == integration / "requirements.txt"
        target.mkdir(parents=True)
        (target / "sdk_dependency.py").write_text("VERSION = '2.0.1'\n", encoding="utf-8")

    monkeypatch.setattr("hiveup.packaging.install_dependencies", stage_dependencies)

    scaffold_result = CliRunner().invoke(app, command)
    validate_result = CliRunner().invoke(
        app,
        ["validate", str(integration), "--skip", "audit,readme,version"],
    )
    test_result = CliRunner().invoke(app, ["test", str(integration)])
    package_path = tmp_path / "sample.zip"
    package_result = CliRunner().invoke(
        app,
        ["package", str(integration), "--output", str(package_path)],
    )

    assert scaffold_result.exit_code == 0, scaffold_result.output
    assert validate_result.exit_code == 0, validate_result.output
    assert test_result.exit_code == 0, test_result.output
    assert package_result.exit_code == 0, package_result.output
    with zipfile.ZipFile(package_path) as archive:
        assert {
            "README.md",
            "__init__.py",
            "config.json",
            "dependencies/sdk_dependency.py",
            "icon.png",
            "sample.py",
        } <= set(archive.namelist())
        assert not any(name.startswith("tests/") for name in archive.namelist())
