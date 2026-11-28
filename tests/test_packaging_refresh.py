"""Exercise dependency refresh with a local wheel index and the real pip resolver."""

import json
import zipfile
from pathlib import Path

import pytest

from hiveup.packaging import PackageBuildError, build_package


def _wheel(index: Path, name: str, version: str, tag: str = "py3-none-any") -> None:
    normalized = name.replace("-", "_")
    metadata = f"{normalized}-{version}.dist-info"
    with zipfile.ZipFile(index / f"{normalized}-{version}-{tag}.whl", "w") as archive:
        archive.writestr(f"{normalized}/__init__.py", f'__version__ = "{version}"\n')
        archive.writestr(
            f"{metadata}/METADATA",
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
        )
        archive.writestr(
            f"{metadata}/WHEEL",
            f"Wheel-Version: 1.0\nGenerator: refresh-test\nRoot-Is-Purelib: true\nTag: {tag}\n",
        )
        archive.writestr(f"{metadata}/RECORD", "")


@pytest.fixture
def package_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    index = tmp_path / "wheels"
    index.mkdir()
    _wheel(index, "autohive-integrations-sdk", "2.1.0")
    monkeypatch.setenv("PIP_NO_INDEX", "1")
    monkeypatch.setenv("PIP_FIND_LINKS", str(index))
    integration = tmp_path / "demo"
    integration.mkdir()
    config = {"name": "Demo", "version": "1.0.0", "entry_point": "demo.py"}
    (integration / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (integration / "demo.py").write_text("VALUE = 1\n", encoding="utf-8")
    (integration / "icon.png").write_bytes(b"png")
    (integration / "requirements.txt").write_text("autohive-integrations-sdk~=2.1.0\n", encoding="utf-8")
    return integration, index


@pytest.mark.parametrize(("requirement", "expected_version"), [("~=1.0", "1.1.0"), ("==1.0.0", "1.0.0")])
def test_repackage_resolves_fresh_dependencies_within_declared_constraints(
    tmp_path: Path, package_fixture: tuple[Path, Path], requirement: str, expected_version: str
) -> None:
    integration, index = package_fixture
    _wheel(index, "demo-runtime", "1.0.0")
    with (integration / "requirements.txt").open("a", encoding="utf-8") as requirements:
        requirements.write(f"demo-runtime{requirement}\n")
    archive_path = tmp_path / "demo.zip"
    build_package(integration, archive_path)
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.read("dependencies/demo_runtime/__init__.py") == b'__version__ = "1.0.0"\n'

    # A version bump triggers a rebuild even though application code and requirements are unchanged.
    _wheel(index, "demo-runtime", "1.1.0")
    config = json.loads((integration / "config.json").read_text(encoding="utf-8"))
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


def test_package_resolves_every_lambda_compatible_manylinux_floor(
    tmp_path: Path, package_fixture: tuple[Path, Path]
) -> None:
    integration, index = package_fixture
    platforms = [f"manylinux_2_{minor}_x86_64" for minor in range(5, 35)]
    platforms += ["manylinux1_x86_64", "manylinux2010_x86_64", "manylinux2014_x86_64"]
    tags = [f"cp313-cp313-{platform}" for platform in platforms]
    tags += ["cp310-abi3-manylinux_2_28_x86_64", "py3-none-any"]
    with (integration / "requirements.txt").open("a", encoding="utf-8") as requirements:
        for number, tag in enumerate(tags):
            name = f"runtime-{number}"
            _wheel(index, name, "1.0.0", tag)
            requirements.write(f"{name}==1.0.0\n")

    archive_path = tmp_path / "demo.zip"
    build_package(integration, archive_path)

    with zipfile.ZipFile(archive_path) as archive:
        for number in range(len(tags)):
            assert archive.read(f"dependencies/runtime_{number}/__init__.py") == b'__version__ = "1.0.0"\n'


@pytest.mark.parametrize("floor", [27, 28])
def test_package_selects_newer_compatible_wheel_instead_of_legacy_fallback(
    tmp_path: Path, package_fixture: tuple[Path, Path], floor: int
) -> None:
    integration, index = package_fixture
    _wheel(index, "demo-runtime", "1.0.0", "cp313-cp313-manylinux2014_x86_64")
    _wheel(index, "demo-runtime", "2.0.0", f"cp313-cp313-manylinux_2_{floor}_x86_64")
    _wheel(index, "demo-runtime", "3.0.0", "cp313-cp313-manylinux_2_35_x86_64")
    _wheel(index, "demo-runtime", "4.0.0rc1", "cp313-cp313-manylinux_2_34_x86_64")
    with (integration / "requirements.txt").open("a", encoding="utf-8") as requirements:
        requirements.write("demo-runtime\n")

    archive_path = tmp_path / "demo.zip"
    build_package(integration, archive_path)

    with zipfile.ZipFile(archive_path) as archive:
        assert archive.read("dependencies/demo_runtime/__init__.py") == b'__version__ = "2.0.0"\n'
        assert "dependencies/demo_runtime-2.0.0.dist-info/METADATA" in archive.namelist()
        assert not any("demo_runtime-1.0.0" in name or "demo_runtime-3.0.0" in name for name in archive.namelist())


@pytest.mark.parametrize(
    "tag",
    [
        "cp313-cp313-manylinux_2_35_x86_64",
        "cp313-cp313-manylinux_3_0_x86_64",
        "cp313-cp313-manylinux_2_34_aarch64",
        "cp313-cp313-manylinux2014_i686",
        "cp314-cp314-manylinux_2_34_x86_64",
        "cp313-cp313t-manylinux_2_34_x86_64",
        "cp313-cp313-musllinux_1_2_x86_64",
        "cp313-cp313-linux_x86_64",
        "cp313-cp313-macosx_14_0_arm64",
        "cp313-cp313-win_amd64",
    ],
)
def test_package_rejects_incompatible_wheels_without_replacing_existing_archive(
    tmp_path: Path, package_fixture: tuple[Path, Path], tag: str
) -> None:
    integration, index = package_fixture
    _wheel(index, "demo-runtime", "1.0.0", tag)
    with (integration / "requirements.txt").open("a", encoding="utf-8") as requirements:
        requirements.write("demo-runtime==1.0.0\n")
    archive_path = tmp_path / "demo.zip"
    archive_path.write_bytes(b"existing deployment archive")

    with pytest.raises(PackageBuildError, match="compatible wheels"):
        build_package(integration, archive_path)

    assert archive_path.read_bytes() == b"existing deployment archive"
    assert not (integration / "dependencies").exists()
