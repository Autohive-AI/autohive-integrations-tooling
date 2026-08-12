import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hiveup.cli import app
from hiveup.release import ReleaseManifestError, load_release_integrations, write_release_manifest


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


def test_load_release_integrations_resolves_paths_and_stable_source_ids(tmp_path: Path) -> None:
    _integration(tmp_path, "renamed-folder", "Original Identity")
    _integration(tmp_path, "container", "Container")
    config = tmp_path / ".github" / "autohive-release.json"
    config.parent.mkdir()
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "integrations": {
                    "renamed-folder": {"source_id": "stable-id"},
                    "container": {"package_type": "container"},
                },
            }
        ),
        encoding="utf-8",
    )

    selected = load_release_integrations(tmp_path, "stable-id,container")

    assert [(item.source_path, item.source_id, item.package_type) for item in selected] == [
        ("renamed-folder", "stable-id", "preserve"),
        ("container", "Container", "container"),
    ]


def test_load_release_integrations_rejects_stale_overrides(tmp_path: Path) -> None:
    _integration(tmp_path, "demo", "Demo")
    config = tmp_path / ".github" / "autohive-release.json"
    config.parent.mkdir()
    config.write_text('{"integrations":{"old-name":{}}}', encoding="utf-8")

    with pytest.raises(ReleaseManifestError, match="missing integration directories: old-name"):
        load_release_integrations(tmp_path, "all")


def test_load_release_integrations_rejects_duplicate_source_identity(tmp_path: Path) -> None:
    _integration(tmp_path, "first", "Same")
    _integration(tmp_path, "second", "same")

    with pytest.raises(ReleaseManifestError, match="duplicate source identity"):
        load_release_integrations(tmp_path, "all")


def test_load_release_integrations_rejects_unsafe_asset_path(tmp_path: Path) -> None:
    _integration(tmp_path, "Unsafe Folder", "Demo")

    with pytest.raises(ReleaseManifestError, match="must use lowercase"):
        load_release_integrations(tmp_path, "all")


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
        workflow_run_id="99",
    )

    assert manifest["schemaVersion"] == 1
    assert manifest["workflowRunId"] == "99"
    assert manifest["repository"] == {
        "owner": "Autohive-AI",
        "name": "autohive-integrations",
        "commitSha": "a" * 40,
    }
    assert manifest["assets"][0]["sha256"] == hashlib.sha256(content).hexdigest()
    assert manifest["assets"][0]["size"] == len(content)
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
            "--workflow-run-id",
            "99",
        ],
    )

    assert result.exit_code == 2
    assert "packaged asset not found" in result.output
