import os
import sys
import time
from pathlib import Path

import hiveup.core.environment as environment
from hiveup.checks import static


def test_environment_key_tracks_requirements_and_test_tools(tmp_path: Path) -> None:
    integration = tmp_path / "demo"
    integration.mkdir()
    requirements = integration / "requirements.txt"
    requirements.write_text("example-package==1.0\n", encoding="utf-8")

    initial = environment.environment_key(integration)
    with_test_tools = environment.environment_key(integration, include_test_tools=True)
    requirements.write_text("example-package==2.0\n", encoding="utf-8")

    assert initial != with_test_tools
    assert initial != environment.environment_key(integration)


def test_prepare_environment_reuses_valid_cached_environment(tmp_path: Path, monkeypatch) -> None:
    integration = tmp_path / "demo"
    integration.mkdir()
    cache = tmp_path / "cache"
    monkeypatch.setenv("HIVEUP_CACHE_DIR", str(cache))
    builds = []

    def create(path: Path) -> None:
        python = environment._environment_python(path)
        python.parent.mkdir(parents=True)
        python.touch()
        builds.append(path)

    monkeypatch.setattr(environment, "_create_environment", create)
    monkeypatch.setattr(environment, "_install_dependencies", lambda *args, **kwargs: None)

    first = environment.prepare_environment(integration)
    second = environment.prepare_environment(integration)

    assert first.path == second.path
    assert first.created is True
    assert second.created is False
    assert len(builds) == 1
    assert first.path.parent == cache / "envs"


def test_prepare_environment_removes_expired_cache_entries(tmp_path: Path, monkeypatch) -> None:
    integration = tmp_path / "demo"
    integration.mkdir()
    cache_root = tmp_path / "cache" / "envs"
    expired = cache_root / "expired"
    expired.mkdir(parents=True)
    old = time.time() - (environment.CACHE_MAX_AGE_DAYS + 1) * 24 * 60 * 60
    os.utime(expired, (old, old))
    monkeypatch.setenv("HIVEUP_CACHE_DIR", str(tmp_path / "cache"))

    def create(path: Path) -> None:
        python = environment._environment_python(path)
        python.parent.mkdir(parents=True)
        python.touch()

    monkeypatch.setattr(environment, "_create_environment", create)
    monkeypatch.setattr(environment, "_install_dependencies", lambda *args, **kwargs: None)

    environment.prepare_environment(integration)

    assert not expired.exists()


def test_import_check_resolves_dependencies_with_isolated_environment(tmp_path: Path, monkeypatch) -> None:
    integration = tmp_path / "demo"
    integration.mkdir()
    (integration / "main.py").write_text("import isolated_dependency\n", encoding="utf-8")
    isolated = environment.IntegrationEnvironment(tmp_path / "env", Path(sys.executable), "key", created=False)
    prepared = []

    def prepare(path: Path, *, include_test_tools: bool):
        prepared.append((path, include_test_tools))
        return isolated

    monkeypatch.setattr(static, "prepare_environment", prepare)
    monkeypatch.setattr(
        static,
        "module_available",
        lambda selected, name: selected == isolated and name == "isolated_dependency",
    )

    report = static.check_imports_all(integration)

    assert report.status == "passed"
    assert prepared == [(integration, True)]


def test_import_check_does_not_use_cli_environment_for_dependencies(tmp_path: Path, monkeypatch) -> None:
    integration = tmp_path / "demo"
    integration.mkdir()
    (integration / "main.py").write_text("import pytest\n", encoding="utf-8")
    isolated = environment.IntegrationEnvironment(tmp_path / "env", Path(sys.executable), "key", created=False)
    monkeypatch.setattr(static, "prepare_environment", lambda *args, **kwargs: isolated)
    monkeypatch.setattr(static, "module_available", lambda selected, name: False)

    report = static.check_imports_all(integration)

    assert report.status == "failed"
    assert report.messages[0].message == "Missing module: pytest"
