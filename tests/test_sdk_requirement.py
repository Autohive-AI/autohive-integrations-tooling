import json
from pathlib import Path

import pytest

from hiveup.packaging import PackageBuildError, build_package
from hiveup.sdk_requirement import MINIMUM_SDK_VERSION, SdkRequirementError, read_sdk_requirement


@pytest.mark.parametrize(
    "requirement",
    [
        "autohive-integrations-sdk~=1.0.2",
        "autohive_integrations_sdk==1.0.2",
        "Autohive.Integrations.SDK>=1.0.2",
        "autohive-integrations-sdk>=1.0.2,<3",
        "autohive-integrations-sdk~=2.0.1",
    ],
)
def test_read_sdk_requirement_accepts_supported_lower_bounds(tmp_path: Path, requirement: str) -> None:
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(f"requests==2.32.0\n{requirement}\n", encoding="utf-8")

    parsed = read_sdk_requirement(requirements)

    assert parsed.version >= MINIMUM_SDK_VERSION


@pytest.mark.parametrize(
    ("requirement", "message"),
    [
        ("requests==2.32.0", "must include autohive-integrations-sdk>=1.0.2"),
        ("autohive-integrations-sdk", "must declare a stable minimum version"),
        ("autohive-integrations-sdk<=2.0.1", "must declare a stable minimum version"),
        ("autohive-integrations-sdk~=1.0.1", "allows an SDK below the required minimum 1.0.2"),
        ("autohive-integrations-sdk>=1.0", "allows an SDK below the required minimum 1.0.2"),
        ("autohive-integrations-sdk>=1.0.2rc1", "must declare a stable minimum version"),
    ],
)
def test_read_sdk_requirement_rejects_missing_or_unsupported_lower_bounds(
    tmp_path: Path,
    requirement: str,
    message: str,
) -> None:
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(f"{requirement}\n", encoding="utf-8")

    with pytest.raises(SdkRequirementError, match=message):
        read_sdk_requirement(requirements)


def test_build_package_enforces_sdk_floor_when_other_validation_is_skipped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    integration = _integration(tmp_path, "autohive-integrations-sdk~=1.0.1")
    install_called = False

    def install_dependencies(*_args) -> None:
        nonlocal install_called
        install_called = True

    monkeypatch.setattr("hiveup.packaging.install_dependencies", install_dependencies)

    with pytest.raises(PackageBuildError, match="required minimum 1.0.2"):
        build_package(integration, tmp_path / "demo.zip")

    assert install_called is False
    assert not (tmp_path / "demo.zip").exists()


def _integration(root: Path, sdk_requirement: str) -> Path:
    integration = root / "demo"
    integration.mkdir()
    (integration / "config.json").write_text(
        json.dumps({"name": "Demo", "version": "1.0.0", "entry_point": "demo.py"}),
        encoding="utf-8",
    )
    (integration / "demo.py").write_text("VALUE = 1\n", encoding="utf-8")
    (integration / "icon.png").write_bytes(b"png")
    (integration / "requirements.txt").write_text(f"{sdk_requirement}\n", encoding="utf-8")
    return integration
