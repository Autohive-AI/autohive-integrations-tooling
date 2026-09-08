"""Build and verify metadata for GitHub-hosted integration releases."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PACKAGE_TYPES = {"preserve", "zip", "container"}
SAFE_SOURCE_PATH = re.compile(r"^[a-z0-9][a-z0-9._-]{0,250}$")
FULL_COMMIT_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
WORKFLOW_RUN_ID = re.compile(r"^[1-9][0-9]*$")
MAX_CONFIG_NAME_LENGTH = 255
MAX_DISPLAY_NAME_LENGTH = 255
MAX_VERSION_LENGTH = 64


class ReleaseManifestError(RuntimeError):
    """Raised when release configuration or artifacts are unsafe or invalid."""


@dataclass(frozen=True)
class ReleaseIntegration:
    source_path: str
    config_name: str
    display_name: str
    version: str
    package_type: str


def load_version_bumped_integrations(
    repository_root: Path,
    base_ref: str,
    configuration_path: Path | None = None,
) -> list[ReleaseIntegration]:
    """Return new integrations and integrations whose config version increased."""

    repository_root = repository_root.resolve()
    _verify_git_ref(repository_root, base_ref)
    configuration = _load_configuration(repository_root, configuration_path)
    overrides = configuration.get("integrations", {})
    if not isinstance(overrides, dict):
        raise ReleaseManifestError("release configuration 'integrations' must be an object")

    changed: list[ReleaseIntegration] = []
    for integration in _discover_release_integrations(repository_root, overrides):
        base_config = _git_json_object(
            repository_root,
            base_ref,
            f"{integration.source_path}/config.json",
        )
        if base_config is None:
            changed.append(integration)
            continue

        base_version_text = _required_string(
            base_config,
            "version",
            Path(f"{base_ref}:{integration.source_path}/config.json"),
        )
        base_version = _semantic_version(base_version_text, integration.source_path)
        current_version = _semantic_version(integration.version, integration.source_path)
        if current_version < base_version:
            raise ReleaseManifestError(
                f"{integration.source_path}: version decreased from {base_version_text} to {integration.version}"
            )
        if current_version > base_version:
            changed.append(integration)
    return changed


def load_release_integrations(
    repository_root: Path,
    selection: str,
    configuration_path: Path | None = None,
) -> list[ReleaseIntegration]:
    """Resolve a user selection to validated top-level integration directories."""

    repository_root = repository_root.resolve()
    configuration = _load_configuration(repository_root, configuration_path)
    overrides = configuration.get("integrations", {})
    if not isinstance(overrides, dict):
        raise ReleaseManifestError("release configuration 'integrations' must be an object")

    discovered = _discover_release_integrations(repository_root, overrides)

    tokens = _selection_tokens(selection)
    if tokens == ["all"]:
        return discovered

    by_path = {integration.source_path.casefold(): integration for integration in discovered}
    selected: list[ReleaseIntegration] = []
    selected_paths: set[str] = set()
    for token in tokens:
        integration = by_path.get(token.casefold())
        if integration is None:
            raise ReleaseManifestError(f"unknown integration selection: {token}")
        key = integration.source_path.casefold()
        if key not in selected_paths:
            selected.append(integration)
            selected_paths.add(key)
    return selected


def _discover_release_integrations(
    repository_root: Path,
    overrides: dict[str, Any],
) -> list[ReleaseIntegration]:
    discovered: list[ReleaseIntegration] = []
    paths_with_configs: set[str] = set()
    for directory in sorted(repository_root.iterdir(), key=lambda path: path.name.casefold()):
        config_path = directory / "config.json"
        if not directory.is_dir() or directory.is_symlink() or not config_path.is_file() or config_path.is_symlink():
            continue
        source_path = directory.name
        if not SAFE_SOURCE_PATH.fullmatch(source_path):
            raise ReleaseManifestError(
                f"integration directory '{source_path}' must use lowercase letters, numbers, '.', '_', or '-' "
                "and be at most 251 characters"
            )
        paths_with_configs.add(source_path)
        override = overrides.get(source_path, {})
        if not isinstance(override, dict):
            raise ReleaseManifestError(f"release configuration for '{source_path}' must be an object")
        config = _load_json_object(config_path, "integration config")
        config_name = _required_string(config, "name", config_path, max_length=MAX_CONFIG_NAME_LENGTH)
        version = _required_string(config, "version", config_path, max_length=MAX_VERSION_LENGTH)
        _semantic_version(version, source_path)
        display_name = config.get("display_name") or config_name
        if (
            not isinstance(display_name, str)
            or not display_name.strip()
            or len(display_name) > MAX_DISPLAY_NAME_LENGTH
            or _has_control_characters(display_name)
        ):
            raise ReleaseManifestError(
                f"display_name must be a non-empty string of at most {MAX_DISPLAY_NAME_LENGTH} characters in "
                f"{config_path}"
            )
        unsupported_keys = set(override) - {"package_type"}
        if unsupported_keys:
            raise ReleaseManifestError(
                f"unsupported release configuration for '{source_path}': {', '.join(sorted(unsupported_keys))}"
            )
        package_type = override.get("package_type", "preserve")
        if not isinstance(package_type, str) or package_type not in PACKAGE_TYPES:
            raise ReleaseManifestError(
                f"package_type for '{source_path}' must be one of: {', '.join(sorted(PACKAGE_TYPES))}"
            )
        discovered.append(
            ReleaseIntegration(
                source_path=source_path,
                config_name=config_name,
                display_name=display_name,
                version=version,
                package_type=package_type,
            )
        )

    stale_overrides = sorted(set(overrides) - paths_with_configs)
    if stale_overrides:
        raise ReleaseManifestError(
            "release configuration references missing integration directories: " + ", ".join(stale_overrides)
        )
    if not discovered:
        raise ReleaseManifestError(f"no integration directories found in {repository_root}")
    return discovered


def write_release_manifest(
    integrations: list[ReleaseIntegration],
    artifacts_directory: Path,
    output_path: Path,
    *,
    owner: str,
    repository: str,
    commit_sha: str,
    previous_commit_sha: str,
    workflow_run_id: str,
    release_kind: str = "incremental",
) -> dict[str, Any]:
    """Hash packaged ZIPs and write the schema consumed by Autohive."""

    if not integrations:
        raise ReleaseManifestError("at least one integration is required")
    for label, value in (
        ("owner", owner),
        ("repository", repository),
        ("commit_sha", commit_sha),
        ("previous_commit_sha", previous_commit_sha),
    ):
        if not value or not value.strip():
            raise ReleaseManifestError(f"{label} is required")
    if not FULL_COMMIT_SHA.fullmatch(commit_sha):
        raise ReleaseManifestError("commit_sha must be a full 40-character Git commit SHA")
    if not FULL_COMMIT_SHA.fullmatch(previous_commit_sha):
        raise ReleaseManifestError("previous_commit_sha must be a full 40-character Git commit SHA")
    if release_kind not in {"incremental", "snapshot"}:
        raise ReleaseManifestError("release_kind must be 'incremental' or 'snapshot'")
    if not WORKFLOW_RUN_ID.fullmatch(workflow_run_id):
        raise ReleaseManifestError("workflow_run_id must be a positive GitHub Actions run ID")

    artifacts_directory = artifacts_directory.resolve()
    assets: list[dict[str, Any]] = []
    for integration in integrations:
        asset_name = f"{integration.source_path}.zip"
        asset_path = artifacts_directory / asset_name
        if not asset_path.is_file() or asset_path.is_symlink():
            raise ReleaseManifestError(f"packaged asset not found: {asset_path}")
        assets.append(
            {
                "sourcePath": integration.source_path,
                "configName": integration.config_name,
                "displayName": integration.display_name,
                "version": integration.version,
                "packageType": integration.package_type,
                "assetName": asset_name,
                "size": asset_path.stat().st_size,
                "sha256": _sha256(asset_path),
            }
        )

    manifest: dict[str, Any] = {
        "schemaVersion": 3,
        "releaseKind": release_kind,
        "repository": {
            "owner": owner,
            "name": repository,
            "commitSha": commit_sha,
            "previousCommitSha": previous_commit_sha,
        },
        "assets": assets,
    }
    manifest["workflowRunId"] = workflow_run_id

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def _load_configuration(repository_root: Path, configuration_path: Path | None) -> dict[str, Any]:
    path = _configuration_path(repository_root, configuration_path)
    if not path.exists():
        return {}
    configuration = _load_json_object(path, "release configuration")
    schema_version = configuration.get("schema_version", 1)
    if schema_version != 1:
        raise ReleaseManifestError("release configuration schema_version must be 1")
    return configuration


def _configuration_path(repository_root: Path, configuration_path: Path | None) -> Path:
    path = configuration_path or repository_root / ".github" / "autohive-release.json"
    if not path.is_absolute():
        path = repository_root / path
    return path


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseManifestError(f"could not read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReleaseManifestError(f"{label} must contain a JSON object: {path}")
    return value


def _required_string(
    value: dict[str, Any],
    key: str,
    path: Path,
    *,
    max_length: int | None = None,
) -> str:
    result = value.get(key)
    if (
        not isinstance(result, str)
        or not result.strip()
        or (max_length is not None and len(result) > max_length)
        or _has_control_characters(result)
    ):
        length_requirement = f" of at most {max_length} characters" if max_length is not None else ""
        raise ReleaseManifestError(f"{key} must be a non-empty string{length_requirement} in {path}")
    return result


def _has_control_characters(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)


def _selection_tokens(selection: str) -> list[str]:
    tokens = [token.strip() for token in re.split(r"[,\r\n]+", selection) if token.strip()]
    if not tokens:
        raise ReleaseManifestError("selection must be 'all' or a comma/newline-separated list")
    if any(token.casefold() == "all" for token in tokens):
        if len(tokens) != 1:
            raise ReleaseManifestError("'all' cannot be combined with named integrations")
        return ["all"]
    return tokens


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_git_ref(repository_root: Path, ref: str) -> None:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
        cwd=repository_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        raise ReleaseManifestError(f"invalid base Git ref '{ref}'")


def _git_json_object(repository_root: Path, ref: str, path: str) -> dict[str, Any] | None:
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        cwd=repository_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ReleaseManifestError(f"could not read integration config {ref}:{path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReleaseManifestError(f"integration config must contain a JSON object: {ref}:{path}")
    return value


def _semantic_version(value: str, source_path: str) -> tuple[int, int, int]:
    if not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise ReleaseManifestError(f"{source_path}: version '{value}' must use semantic version x.y.z")
    major, minor, patch = value.split(".")
    return int(major), int(minor), int(patch)
