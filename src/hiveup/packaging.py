"""Build deployment-compatible integration packages."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TARGET_PLATFORM = "manylinux2014_x86_64"
TARGET_PYTHON_VERSION = "3.13"


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
