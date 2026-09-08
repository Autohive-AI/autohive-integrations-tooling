from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from hiveup.checks.version import check_version_bump


def test_requirements_change_requires_version_bump(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repository = tmp_path / "repository"
    integration = repository / "example"
    integration.mkdir(parents=True)
    (integration / "config.json").write_text(
        json.dumps({"name": "Example", "version": "1.0.0", "actions": {}}),
        encoding="utf-8",
    )
    (integration / "requirements.txt").write_text("example-package==1.0.0\n", encoding="utf-8")
    _git(repository, "init", "-q")
    _git(repository, "config", "user.email", "test@example.com")
    _git(repository, "config", "user.name", "Test")
    _git(repository, "add", ".")
    _git(repository, "commit", "-q", "-m", "base")
    base_ref = _git(repository, "rev-parse", "HEAD", capture=True)

    (integration / "requirements.txt").write_text("example-package==2.0.0\n", encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-q", "-m", "change dependency")
    monkeypatch.chdir(repository)

    assert check_version_bump(base_ref, ["example"]) == 1


def test_documentation_change_does_not_require_version_bump(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repository = tmp_path / "repository"
    integration = repository / "example"
    integration.mkdir(parents=True)
    (integration / "config.json").write_text(
        json.dumps({"name": "Example", "version": "1.0.0", "actions": {}}),
        encoding="utf-8",
    )
    (integration / "README.md").write_text("# Example\n", encoding="utf-8")
    _git(repository, "init", "-q")
    _git(repository, "config", "user.email", "test@example.com")
    _git(repository, "config", "user.name", "Test")
    _git(repository, "add", ".")
    _git(repository, "commit", "-q", "-m", "base")
    base_ref = _git(repository, "rev-parse", "HEAD", capture=True)

    (integration / "README.md").write_text("# Example\n\nMore documentation.\n", encoding="utf-8")
    _git(repository, "add", ".")
    _git(repository, "commit", "-q", "-m", "update docs")
    monkeypatch.chdir(repository)

    assert check_version_bump(base_ref, ["example"]) == 0


def _git(repository: Path, *arguments: str, capture: bool = False) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=capture,
        text=True,
    )
    return result.stdout.strip() if capture else ""
