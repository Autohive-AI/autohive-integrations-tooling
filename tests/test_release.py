import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hiveup.cli import app
from hiveup.release import (
    ReleaseManifestError,
    load_release_integrations,
    load_version_bumped_integrations,
    write_release_manifest,
)


def _integration(root: Path, path: str, name: str, *, version: str = "1.2.3") -> None:
    directory = root / path
    directory.mkdir(parents=True)
    (directory / "config.json").write_text(
        json.dumps(
            {
                "name": name,
                "display_name": f"{name} display",
                "version": version,
                "entry_point": "demo.py",
                "description": "demo",
                "actions": {},
            }
        ),
        encoding="utf-8",
    )


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def test_load_release_integrations_resolves_paths_and_package_types(tmp_path: Path) -> None:
    _integration(tmp_path, "renamed-folder", "Original Identity")
    _integration(tmp_path, "container", "Container")
    config = tmp_path / ".github" / "autohive-release.json"
    config.parent.mkdir()
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "integrations": {
                    "container": {"package_type": "container"},
                },
            }
        ),
        encoding="utf-8",
    )

    selected = load_release_integrations(tmp_path, "renamed-folder,container")

    assert [(item.source_path, item.package_type) for item in selected] == [
        ("renamed-folder", "preserve"),
        ("container", "container"),
    ]


def test_load_release_integrations_rejects_stale_overrides(tmp_path: Path) -> None:
    _integration(tmp_path, "demo", "Demo")
    config = tmp_path / ".github" / "autohive-release.json"
    config.parent.mkdir()
    config.write_text('{"integrations":{"old-name":{}}}', encoding="utf-8")

    with pytest.raises(ReleaseManifestError, match="missing integration directories: old-name"):
        load_release_integrations(tmp_path, "all")


def test_load_release_integrations_allows_duplicate_config_names_because_paths_are_identity(tmp_path: Path) -> None:
    _integration(tmp_path, "first", "Same")
    _integration(tmp_path, "second", "same")

    selected = load_release_integrations(tmp_path, "all")

    assert [item.source_path for item in selected] == ["first", "second"]


def test_load_release_integrations_rejects_unsafe_asset_path(tmp_path: Path) -> None:
    _integration(tmp_path, "Unsafe Folder", "Demo")

    with pytest.raises(ReleaseManifestError, match="must use lowercase"):
        load_release_integrations(tmp_path, "all")


def test_load_release_integrations_rejects_deprecated_source_id_configuration(tmp_path: Path) -> None:
    _integration(tmp_path, "alpha", "Alpha Integration")
    config = tmp_path / ".github" / "autohive-release.json"
    config.parent.mkdir()
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "integrations": {
                    "alpha": {"source_id": "deprecated"},
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ReleaseManifestError, match="unsupported release configuration.*source_id"):
        load_release_integrations(tmp_path, "all")


def test_load_release_integrations_rejects_non_string_package_type(tmp_path: Path) -> None:
    _integration(tmp_path, "alpha", "Alpha Integration")
    config = tmp_path / ".github" / "autohive-release.json"
    config.parent.mkdir()
    config.write_text(
        json.dumps({"integrations": {"alpha": {"package_type": ["zip"]}}}),
        encoding="utf-8",
    )

    with pytest.raises(ReleaseManifestError, match="package_type for 'alpha' must be one of"):
        load_release_integrations(tmp_path, "all")


def test_load_version_bumped_integrations_returns_only_newer_versions(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    _integration(tmp_path, "changed", "Changed", version="1.0.0")
    _integration(tmp_path, "unchanged", "Unchanged", version="2.0.0")
    changed_config = tmp_path / "changed" / "config.json"
    value = json.loads(changed_config.read_text(encoding="utf-8"))
    value["description"] = "Unicode combining mark: \u034d"
    changed_config.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "base")
    base_ref = _git(tmp_path, "rev-parse", "HEAD")

    value = json.loads(changed_config.read_text(encoding="utf-8"))
    value["version"] = "1.1.0"
    changed_config.write_text(json.dumps(value), encoding="utf-8")
    _integration(tmp_path, "new-source", "New source", version="1.0.0")

    changed = load_version_bumped_integrations(tmp_path, base_ref)

    assert [item.source_path for item in changed] == ["changed", "new-source"]


def test_write_release_manifest_hashes_assets_and_records_provenance(tmp_path: Path) -> None:
    _integration(tmp_path, "demo", "Demo")
    selected = load_release_integrations(tmp_path, "all")
    artifacts = tmp_path / "dist"
    artifacts.mkdir()
    content = b"package bytes"
    (artifacts / "demo.zip").write_bytes(content)
    output = artifacts / "autohive-manifest.json"

    manifest = write_release_manifest(
        selected,
        artifacts,
        output,
        owner="Autohive-AI",
        repository="autohive-integrations",
        commit_sha="a" * 40,
        previous_commit_sha="b" * 40,
        workflow_run_id="99",
    )

    assert manifest["schemaVersion"] == 3
    assert manifest["releaseKind"] == "incremental"
    assert manifest["workflowRunId"] == "99"
    assert manifest["repository"] == {
        "owner": "Autohive-AI",
        "name": "autohive-integrations",
        "commitSha": "a" * 40,
        "previousCommitSha": "b" * 40,
    }
    assert manifest["assets"][0]["sha256"] == hashlib.sha256(content).hexdigest()
    assert manifest["assets"][0]["size"] == len(content)
    assert "sourceId" not in manifest["assets"][0]
    assert json.loads(output.read_text(encoding="utf-8")) == manifest


@pytest.mark.parametrize(
    ("commit_sha", "workflow_run_id", "message"),
    [
        ("abc123", "99", "full 40-character"),
        ("a" * 40, "not-a-run", "positive GitHub Actions run ID"),
    ],
)
def test_write_release_manifest_rejects_incomplete_provenance(
    tmp_path: Path,
    commit_sha: str,
    workflow_run_id: str,
    message: str,
) -> None:
    _integration(tmp_path, "demo", "Demo")
    selected = load_release_integrations(tmp_path, "all")
    artifacts = tmp_path / "dist"
    artifacts.mkdir()
    (artifacts / "demo.zip").write_bytes(b"package")

    with pytest.raises(ReleaseManifestError, match=message):
        write_release_manifest(
            selected,
            artifacts,
            artifacts / "manifest.json",
            owner="Autohive-AI",
            repository="autohive-integrations",
            commit_sha=commit_sha,
            previous_commit_sha="b" * 40,
            workflow_run_id=workflow_run_id,
        )


def test_release_plan_cli_rejects_unknown_selection(tmp_path: Path) -> None:
    _integration(tmp_path, "demo", "Demo")

    result = CliRunner().invoke(
        app,
        ["release-plan", "--repository-root", str(tmp_path), "--selection", "missing"],
    )

    assert result.exit_code == 2
    assert "unknown integration selection: missing" in result.output


def test_release_manifest_cli_requires_every_selected_asset(tmp_path: Path) -> None:
    _integration(tmp_path, "demo", "Demo")

    result = CliRunner().invoke(
        app,
        [
            "release-manifest",
            "--repository-root",
            str(tmp_path),
            "--artifacts",
            str(tmp_path / "dist"),
            "--output",
            str(tmp_path / "manifest.json"),
            "--owner",
            "Autohive-AI",
            "--repository",
            "autohive-integrations",
            "--commit-sha",
            "a" * 40,
            "--previous-commit-sha",
            "b" * 40,
            "--workflow-run-id",
            "99",
        ],
    )

    assert result.exit_code == 2
    assert "packaged asset not found" in result.output
