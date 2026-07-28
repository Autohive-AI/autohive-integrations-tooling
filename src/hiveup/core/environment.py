"""Cached, isolated Python environments for integrations."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

CACHE_SCHEMA = 1
CACHE_MAX_AGE_DAYS = 30
MARKER_NAME = ".hiveup-environment.json"
TEST_REQUIREMENTS = ("pytest>=9.0", "pytest-asyncio>=0.23", "pytest-cov>=4.0")


class EnvironmentBuildError(RuntimeError):
    """Raised when an integration environment cannot be prepared."""


@dataclass(frozen=True)
class IntegrationEnvironment:
    """A prepared integration environment."""

    path: Path
    python: Path
    key: str
    created: bool


def prepare_environment(integration_dir: Path, *, include_test_tools: bool = False) -> IntegrationEnvironment:
    """Create or reuse an environment matching an integration's requirements."""

    integration_dir = integration_dir.resolve()
    requirements = integration_dir / "requirements.txt"
    key = environment_key(integration_dir, include_test_tools=include_test_tools)
    cache_root = environment_cache_root()
    cache_root.mkdir(parents=True, exist_ok=True)
    _cleanup_stale_environments(cache_root)

    target = cache_root / key
    if _is_valid_environment(target, key):
        target.touch()
        return IntegrationEnvironment(target, _environment_python(target), key, created=False)

    if target.exists():
        shutil.rmtree(target)

    temporary = cache_root / f".{key}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    try:
        _create_environment(temporary)
        _install_dependencies(
            temporary,
            integration_dir=integration_dir,
            requirements=requirements if requirements.is_file() else None,
            include_test_tools=include_test_tools,
        )
        marker = {
            "schema": CACHE_SCHEMA,
            "key": key,
            "python": str(Path(sys.executable).resolve()),
            "integration": str(integration_dir),
            "requirements_sha256": _requirements_hash(requirements),
            "test_tools": include_test_tools,
        }
        (temporary / MARKER_NAME).write_text(json.dumps(marker, sort_keys=True), encoding="utf-8")

        try:
            temporary.rename(target)
        except FileExistsError:
            if not _is_valid_environment(target, key):
                raise
    except (OSError, subprocess.SubprocessError) as exc:
        raise EnvironmentBuildError(str(exc)) from exc
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)

    if not _is_valid_environment(target, key):
        raise EnvironmentBuildError("Environment creation did not produce a usable Python interpreter")
    return IntegrationEnvironment(target, _environment_python(target), key, created=True)


def environment_key(integration_dir: Path, *, include_test_tools: bool = False) -> str:
    """Return the stable cache key for an integration environment."""

    integration_dir = integration_dir.resolve()
    requirements = integration_dir / "requirements.txt"
    payload = {
        "schema": CACHE_SCHEMA,
        "python": str(Path(sys.executable).resolve()),
        "python_cache_tag": sys.implementation.cache_tag,
        "python_version": list(sys.version_info[:3]),
        "integration": str(integration_dir),
        "requirements_sha256": _requirements_hash(requirements),
        "test_requirements": list(TEST_REQUIREMENTS) if include_test_tools else [],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:32]


def environment_cache_root() -> Path:
    """Return HiveUp's platform-appropriate environment cache directory."""

    override = os.environ.get("HIVEUP_CACHE_DIR")
    if override:
        return Path(override).expanduser().resolve() / "envs"
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        base = Path(os.environ["LOCALAPPDATA"])
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "hiveup" / "envs"


def _create_environment(path: Path) -> None:
    uv = shutil.which("uv")
    if uv:
        _run([uv, "venv", "--no-project", "--python", sys.executable, str(path)])
    else:
        _run([sys.executable, "-m", "venv", str(path)])


def _install_dependencies(
    path: Path,
    *,
    integration_dir: Path,
    requirements: Path | None,
    include_test_tools: bool,
) -> None:
    packages = list(TEST_REQUIREMENTS) if include_test_tools else []
    if requirements is None and not packages:
        return

    uv = shutil.which("uv")
    if uv:
        command = [uv, "pip", "install", "--python", str(_environment_python(path))]
    else:
        command = [str(_environment_python(path)), "-m", "pip", "install", "-q"]
    if requirements:
        command.extend(["-r", str(requirements)])
    command.extend(packages)
    _run(command, cwd=integration_dir)


def _run(command: list[str], *, cwd: Path | None = None) -> None:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    if result.returncode == 0:
        return
    output = (result.stderr or result.stdout).strip() or "command failed"
    raise EnvironmentBuildError(output)


def _requirements_hash(requirements: Path) -> str:
    content = requirements.read_bytes() if requirements.is_file() else b""
    return hashlib.sha256(content).hexdigest()


def _environment_python(path: Path) -> Path:
    if os.name == "nt":
        return path / "Scripts" / "python.exe"
    return path / "bin" / "python"


def _is_valid_environment(path: Path, key: str) -> bool:
    marker_path = path / MARKER_NAME
    if not _environment_python(path).is_file() or not marker_path.is_file():
        return False
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    return marker.get("schema") == CACHE_SCHEMA and marker.get("key") == key


def _cleanup_stale_environments(cache_root: Path, *, now: float | None = None) -> None:
    cutoff = (now or time.time()) - CACHE_MAX_AGE_DAYS * 24 * 60 * 60
    for candidate in cache_root.iterdir():
        if not candidate.is_dir() or candidate.name.startswith("."):
            continue
        try:
            if candidate.stat().st_mtime < cutoff:
                shutil.rmtree(candidate)
        except OSError:
            continue
