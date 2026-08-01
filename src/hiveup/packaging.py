"""Build deployment-compatible integration packages."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from hiveup.core.deployment import (
    is_deployment_source,
    is_excluded_development_path,
)

TARGET_PLATFORM = "manylinux2014_x86_64"
TARGET_PYTHON_VERSION = "3.13"
EXCLUDED_FILES = {".coverage", ".git", "requirements.txt"}
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
ZIP_FILE_MODE = 0o100644


class PackageBuildError(RuntimeError):
    """Raised when an integration package cannot be built."""


def build_package(directory: Path, package_path: Path) -> None:
    """Install dependencies externally and write a deployable integration archive."""

    _validate_package_output(directory, package_path)
    _validate_deployment_files(directory)
    requirements = directory / "requirements.txt"
    if not _is_regular_file(requirements):
        raise PackageBuildError(f"requirements.txt not found: {requirements}")

    with tempfile.TemporaryDirectory() as temporary_directory:
        dependencies = Path(temporary_directory) / "dependencies"
        install_dependencies(requirements, dependencies)
        write_package_zip(directory, package_path, dependencies if dependencies.exists() else None)


def _validate_deployment_files(directory: Path) -> None:
    config_path = directory / "config.json"
    if not _is_regular_file(config_path):
        raise PackageBuildError(f"config.json must be a regular, non-symlink file: {config_path}")
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise PackageBuildError(f"Could not read config.json: {exc}") from exc
    if not isinstance(config, dict):
        raise PackageBuildError("config.json must contain a JSON object")

    entry_point = config.get("entry_point")
    if not isinstance(entry_point, str) or not entry_point or Path(entry_point).name != entry_point:
        raise PackageBuildError("entry_point must name a Python file at the integration root")
    entry_path = directory / entry_point
    if not _is_regular_file(entry_path):
        raise PackageBuildError(f"entry_point must be a regular, non-symlink file: {entry_path}")

    icons = _root_icons(directory)
    if not icons:
        raise PackageBuildError("A regular, non-symlink icon.png, icon.jpg, or icon.jpeg is required")
    if len(icons) > 1:
        raise PackageBuildError(f"Exactly one integration icon is required; found: {_icon_names(icons)}")
    if not _is_regular_file(icons[0]):
        raise PackageBuildError(f"Integration icon must be a regular, non-symlink file: {icons[0]}")

    _reject_deployment_symlinks(directory)


def _is_regular_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _validate_package_output(directory: Path, package_path: Path) -> None:
    if package_path.suffix.casefold() != ".zip":
        raise PackageBuildError(f"Package output must use a .zip extension: {package_path}")

    output = package_path.resolve()
    protected = [directory / "requirements.txt"]
    protected.extend(
        path
        for path in directory.rglob("*")
        if path.is_file() and not path.is_symlink() and is_deployment_source(path.relative_to(directory))
    )
    if any(path.resolve() == output for path in protected):
        raise PackageBuildError(f"Package output cannot overwrite integration source: {package_path}")


def _root_icons(directory: Path) -> list[Path]:
    return sorted(
        path
        for path in directory.iterdir()
        if path.name.casefold() in {"icon.jpeg", "icon.jpg", "icon.png"}
    )


def _icon_names(icons: list[Path]) -> str:
    return ", ".join(path.name for path in icons)


def _reject_deployment_symlinks(directory: Path) -> None:
    for path in directory.rglob("*"):
        relative = path.relative_to(directory)
        if is_excluded_development_path(relative):
            continue
        if path.is_symlink():
            raise PackageBuildError(f"Deployment source cannot be a symlink: {relative.as_posix()}")


def install_dependencies(requirements: Path, target: Path) -> None:
    """Install deployment-compatible wheels into a package staging directory."""

    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "-r",
        str(requirements),
        "--platform",
        TARGET_PLATFORM,
        "--python-version",
        TARGET_PYTHON_VERSION,
        "--only-binary=:all:",
        "--target",
        str(target),
        "-q",
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode == 0:
        return

    output = (result.stderr or result.stdout).strip()
    detail = f"\n{output}" if output else ""
    raise PackageBuildError(
        f"Could not install dependencies for Python {TARGET_PYTHON_VERSION} on {TARGET_PLATFORM}. "
        f"All dependencies must provide compatible wheels.{detail}"
    )


def write_package_zip(directory: Path, package_path: Path, dependencies: Path | None) -> None:
    """Write an integration and staged dependencies atomically to a deployment ZIP root."""

    _validate_package_output(directory, package_path)
    package_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=package_path.parent,
        prefix=f".{package_path.name}.",
        suffix=".tmp",
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        with zipfile.ZipFile(
            temporary_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            package_files = [
                (path.relative_to(directory).as_posix(), path)
                for path in _package_files(directory, temporary_path)
            ]
            if dependencies:
                for path in dependencies.rglob("*"):
                    if path.is_file() and not path.is_symlink() and path.suffix.lower() != ".pyc":
                        package_files.append((f"dependencies/{path.relative_to(dependencies).as_posix()}", path))
            for archive_name, path in sorted(package_files):
                _write_file(archive, path, archive_name)
        temporary_path.replace(package_path)
    except OSError as exc:
        raise PackageBuildError(f"Could not write package {package_path}: {exc}") from exc
    finally:
        temporary_path.unlink(missing_ok=True)


def _package_files(directory: Path, package_path: Path) -> list[Path]:
    output = package_path.resolve()
    icons = _root_icons(directory)
    if len(icons) > 1:
        raise PackageBuildError(f"Exactly one integration icon is required; found: {_icon_names(icons)}")
    files = []
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if is_excluded_development_path(relative):
            continue
        if path.is_symlink():
            raise PackageBuildError(f"Deployment source cannot be a symlink: {relative.as_posix()}")
        if not path.is_file():
            continue
        if (
            path.resolve() == output
            or path.name in EXCLUDED_FILES
            or path.name == ".env"
            or path.name.startswith(".env.")
            or path.suffix.lower() in {".pyc", ".zip"}
        ):
            continue
        if not is_deployment_source(relative):
            continue
        files.append(path)
    return files
def _write_file(archive: zipfile.ZipFile, path: Path, archive_name: str) -> None:
    info = zipfile.ZipInfo(archive_name, date_time=ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = ZIP_FILE_MODE << 16
    archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
