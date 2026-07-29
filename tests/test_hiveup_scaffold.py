import json
import struct
import sys
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

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

    result = CliRunner().invoke(app, ["create", "Sample Integration", "--auth-type", auth_type])

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


def test_scaffold_rejects_invalid_auth_before_writing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["create", "sample", "--auth-type", "invalid"])

    assert result.exit_code == 2
    assert "Unsupported auth type: invalid" in result.output
    assert not (tmp_path / "sample").exists()


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
            "requirements.txt",
            "sample.py",
        } <= set(archive.namelist())
        assert not any(name.startswith("tests/") for name in archive.namelist())
