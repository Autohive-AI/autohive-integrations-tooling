"""Exercise dependency refresh with a local wheel index and the real pip resolver."""

import json
import zipfile
from pathlib import Path

import pytest

from hiveup.packaging import build_package


def _wheel(index: Path, name: str, version: str) -> None:
    normalized = name.replace("-", "_")
    metadata = f"{normalized}-{version}.dist-info"
    with zipfile.ZipFile(index / f"{normalized}-{version}-py3-none-any.whl", "w") as archive:
        archive.writestr(f"{normalized}/__init__.py", f'__version__ = "{version}"\n')
        archive.writestr(
            f"{metadata}/METADATA",
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
        )
        archive.writestr(
            f"{metadata}/WHEEL",
            "Wheel-Version: 1.0\nGenerator: refresh-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr(f"{metadata}/RECORD", "")


@pytest.mark.parametrize(("requirement", "expected_version"), [("~=1.0", "1.1.0"), ("==1.0.0", "1.0.0")])
def test_repackage_resolves_fresh_dependencies_within_declared_constraints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, requirement: str, expected_version: str
) -> None:
    index = tmp_path / "wheels"
    index.mkdir()
    _wheel(index, "autohive-integrations-sdk", "2.0.1")
    _wheel(index, "demo-runtime", "1.0.0")
    monkeypatch.setenv("PIP_NO_INDEX", "1")
    monkeypatch.setenv("PIP_FIND_LINKS", str(index))
    integration = tmp_path / "demo"
    integration.mkdir()
    config = {"name": "Demo", "version": "1.0.0", "entry_point": "demo.py"}
    (integration / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (integration / "demo.py").write_text("VALUE = 1\n", encoding="utf-8")
    (integration / "icon.png").write_bytes(b"png")
    (integration / "requirements.txt").write_text(
        f"autohive-integrations-sdk~=2.0.1\ndemo-runtime{requirement}\n", encoding="utf-8"
    )
    archive_path = tmp_path / "demo.zip"
    build_package(integration, archive_path)
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.read("dependencies/demo_runtime/__init__.py") == b'__version__ = "1.0.0"\n'

    # A version bump triggers a rebuild even though application code and requirements are unchanged.
    _wheel(index, "demo-runtime", "1.1.0")
    config["version"] = "1.0.1"
    (integration / "config.json").write_text(json.dumps(config), encoding="utf-8")
    build_package(integration, archive_path)
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.read("dependencies/demo_runtime/__init__.py").decode() == f'__version__ = "{expected_version}"\n'
        assert json.loads(archive.read("config.json"))["version"] == "1.0.1"
        installed_metadata = [
            name
            for name in archive.namelist()
            if name.startswith("dependencies/demo_runtime-") and name.endswith("/METADATA")
        ]
        assert installed_metadata == [f"dependencies/demo_runtime-{expected_version}.dist-info/METADATA"]
    assert not (integration / "dependencies").exists()
