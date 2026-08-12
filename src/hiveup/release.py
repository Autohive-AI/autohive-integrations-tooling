"""Build and verify metadata for GitHub-hosted integration releases."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PACKAGE_TYPES = {"preserve", "zip", "container"}
SAFE_SOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,127}$")
SAFE_SOURCE_PATH = re.compile(r"^[a-z0-9][a-z0-9._-]{0,254}$")
FULL_COMMIT_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
WORKFLOW_RUN_ID = re.compile(r"^[1-9][0-9]*$")


class ReleaseManifestError(RuntimeError):
    """Raised when release configuration or artifacts are unsafe or invalid."""


@dataclass(frozen=True)
class ReleaseIntegration:
    source_id: str
    source_path: str
    config_name: str
    display_name: str
    version: str
    package_type: str


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

    discovered: list[ReleaseIntegration] = []
    seen_source_ids: dict[str, str] = {}
    paths_with_configs: set[str] = set()
    for directory in sorted(repository_root.iterdir(), key=lambda path: path.name.casefold()):
        config_path = directory / "config.json"
        if not directory.is_dir() or directory.is_symlink() or not config_path.is_file() or config_path.is_symlink():
            continue
        source_path = directory.name
        if not SAFE_SOURCE_PATH.fullmatch(source_path):
            raise ReleaseManifestError(
                f"integration directory '{source_path}' must use lowercase letters, numbers, '.', '_', or '-'"
            )
        paths_with_configs.add(source_path)
        override = overrides.get(source_path, {})
        if not isinstance(override, dict):
            raise ReleaseManifestError(f"release configuration for '{source_path}' must be an object")
        config = _load_json_object(config_path, "integration config")
        config_name = _required_string(config, "name", config_path)
        version = _required_string(config, "version", config_path)
        display_name = config.get("display_name") or config_name
        if not isinstance(display_name, str) or not display_name.strip():
            raise ReleaseManifestError(f"display_name must be a non-empty string in {config_path}")
        source_id = override.get("source_id", config_name)
        if not isinstance(source_id, str) or not SAFE_SOURCE_ID.fullmatch(source_id):
            raise ReleaseManifestError(
                f"source identity for '{source_path}' must be 1-128 letters, numbers, spaces, '.', '_', or '-'"
            )
        package_type = override.get("package_type", "preserve")
        if package_type not in PACKAGE_TYPES:
            raise ReleaseManifestError(
                f"package_type for '{source_path}' must be one of: {', '.join(sorted(PACKAGE_TYPES))}"
            )
        source_id_key = source_id.casefold()
        if source_id_key in seen_source_ids:
            raise ReleaseManifestError(
                f"duplicate source identity '{source_id}' for '{seen_source_ids[source_id_key]}' and '{source_path}'"
            )
        seen_source_ids[source_id_key] = source_path
        discovered.append(
            ReleaseIntegration(
                source_id=source_id,
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

    tokens = _selection_tokens(selection)
    if tokens == ["all"]:
        return discovered

    by_path = {integration.source_path.casefold(): integration for integration in discovered}
    by_source_id = {integration.source_id.casefold(): integration for integration in discovered}
    selected: list[ReleaseIntegration] = []
    selected_ids: set[str] = set()
    for token in tokens:
        integration = by_path.get(token.casefold()) or by_source_id.get(token.casefold())
        if integration is None:
            raise ReleaseManifestError(f"unknown integration selection: {token}")
        key = integration.source_id.casefold()
        if key not in selected_ids:
            selected.append(integration)
            selected_ids.add(key)
    return selected


def write_release_manifest(
    integrations: list[ReleaseIntegration],
    artifacts_directory: Path,
    output_path: Path,
    *,
    owner: str,
    repository: str,
    commit_sha: str,
    workflow_run_id: str,
) -> dict[str, Any]:
    """Hash packaged ZIPs and write the schema consumed by Autohive."""

    if not integrations:
        raise ReleaseManifestError("at least one integration is required")
    for label, value in (("owner", owner), ("repository", repository), ("commit_sha", commit_sha)):
        if not value or not value.strip():
            raise ReleaseManifestError(f"{label} is required")
    if not FULL_COMMIT_SHA.fullmatch(commit_sha):
        raise ReleaseManifestError("commit_sha must be a full 40-character Git commit SHA")
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
                "sourceId": integration.source_id,
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
        "schemaVersion": 1,
        "repository": {"owner": owner, "name": repository, "commitSha": commit_sha},
        "assets": assets,
    }
    manifest["workflowRunId"] = workflow_run_id

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def _load_configuration(repository_root: Path, configuration_path: Path | None) -> dict[str, Any]:
    path = configuration_path or repository_root / ".github" / "autohive-release.json"
    if not path.is_absolute():
        path = repository_root / path
    if not path.exists():
        return {}
    configuration = _load_json_object(path, "release configuration")
    schema_version = configuration.get("schema_version", 1)
    if schema_version != 1:
        raise ReleaseManifestError("release configuration schema_version must be 1")
    return configuration


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseManifestError(f"could not read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReleaseManifestError(f"{label} must contain a JSON object: {path}")
    return value


def _required_string(value: dict[str, Any], key: str, path: Path) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip():
        raise ReleaseManifestError(f"{key} must be a non-empty string in {path}")
    return result


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
