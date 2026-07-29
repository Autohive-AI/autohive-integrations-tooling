"""Build deployment-compatible integration packages."""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

TARGET_PLATFORM = "manylinux2014_x86_64"
TARGET_PYTHON_VERSION = "3.13"
EXCLUDED_DIRECTORIES = {
    ".git",
    ".github",
    ".hiveup",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dependencies",
    "dist",
    "env",
    "node_modules",
    "test",
    "tests",
    "venv",
}
EXCLUDED_FILES = {".coverage"}
SUPPORTED_ICON_SUFFIXES = {".jpeg", ".jpg", ".png"}


class PackageBuildError(RuntimeError):
    """Raised when an integration package cannot be built."""


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
    """Write an integration and staged dependencies directly to a deployment ZIP root."""

    package_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in _package_files(directory, package_path):
            archive.write(path, path.relative_to(directory).as_posix())
        if dependencies:
            for path in sorted(dependencies.rglob("*")):
                if path.is_file() and not path.is_symlink():
                    archive.write(path, f"dependencies/{path.relative_to(dependencies).as_posix()}")


def _package_files(directory: Path, package_path: Path) -> list[Path]:
    output = package_path.resolve()
    files = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(directory)
        if EXCLUDED_DIRECTORIES.intersection(relative.parts[:-1]):
            continue
        if path.resolve() == output or path.name in EXCLUDED_FILES or path.suffix.lower() in {".pyc", ".zip"}:
            continue
        if path.stem.casefold() == "icon" and path.suffix.lower() not in SUPPORTED_ICON_SUFFIXES:
            continue
        files.append(path)
    return files
