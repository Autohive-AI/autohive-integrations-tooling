import os
import importlib.util
import subprocess
import sys
import time
from pathlib import Path

import hiveup.core.environment as environment
from hiveup.checks import static
from hiveup.checks import tests as test_checks


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
    requirements = integration / "requirements.txt"
    requirements.write_text("example-package==1.0\n", encoding="utf-8")
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
    requirements.write_text("example-package==2.0\n", encoding="utf-8")
    changed = environment.prepare_environment(integration)

    assert first.path == second.path
    assert changed.path != first.path
    assert first.created is True
    assert second.created is False
    assert changed.created is True
    assert len(builds) == 2
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


def test_import_check_resolves_modules_beside_test_file(tmp_path: Path, monkeypatch) -> None:
    integration = tmp_path / "demo"
    tests_dir = integration / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "context.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tests_dir / "test_demo_unit.py").write_text("from context import VALUE\n", encoding="utf-8")
    isolated = environment.IntegrationEnvironment(tmp_path / "env", Path(sys.executable), "key", created=False)
    monkeypatch.setattr(static, "prepare_environment", lambda *args, **kwargs: isolated)
    monkeypatch.setattr(static, "module_available", lambda *args: False)

    report = static.check_imports_all(integration)

    assert report.status == "passed"


def test_integration_tests_run_with_isolated_interpreter(tmp_path: Path, monkeypatch) -> None:
    integration = tmp_path / "demo"
    test_file = integration / "tests" / "test_demo_unit.py"
    test_file.parent.mkdir(parents=True)
    test_file.touch()
    isolated_python = tmp_path / "cache" / "bin" / "python"
    isolated = environment.IntegrationEnvironment(tmp_path / "cache", isolated_python, "key", created=False)
    prepared = []
    commands = []

    def prepare(path: Path, *, include_test_tools: bool):
        prepared.append((path, include_test_tools))
        return isolated

    def run(command, **kwargs):
        commands.append((command, kwargs))
        return type("Result", (), {"returncode": 0, "stdout": "1 passed\n", "stderr": ""})()

    monkeypatch.setattr(test_checks, "prepare_environment", prepare)
    monkeypatch.setattr(test_checks, "_stage_sdk_config", lambda *args: None)
    monkeypatch.setattr(test_checks.subprocess, "run", run)

    exit_code, output = test_checks.run_integration_tests(integration, [test_file])

    assert exit_code == 0
    assert output == "1 passed\n"
    assert prepared == [(integration, True)]
    assert commands[0][0][0:3] == [str(isolated_python), "-m", "pytest"]
    assert ["--override-ini", "markers=unit: isolated integration unit test"] == commands[0][0][9:11]
    assert str(integration) in commands[0][0]
    assert str(test_file) in commands[0][0]
    assert commands[0][1]["cwd"] == integration
    assert commands[0][1]["env"]["PYTHONPATH"].split(os.pathsep) == [
        str(integration.parent.resolve()),
        str(integration.resolve()),
    ]


def test_integration_tests_stage_config_where_installed_sdk_expects_it(tmp_path: Path, monkeypatch) -> None:
    integration = tmp_path / "demo"
    integration.mkdir()
    config = integration / "config.json"
    config.write_text('{"name": "demo"}\n', encoding="utf-8")
    environment_root = tmp_path / "cache"
    sdk_root = environment_root / "lib" / "python3.13"
    sdk_root.mkdir(parents=True)
    isolated = environment.IntegrationEnvironment(
        environment_root,
        environment_root / "bin" / "python",
        "key",
        created=False,
    )

    def run(command, **kwargs):
        assert command[0] == str(isolated.python)
        assert command[1] == "-c"
        return type(
            "Result",
            (),
            {"returncode": 0, "stdout": f"{sdk_root / 'config.json'}\n", "stderr": ""},
        )()

    monkeypatch.setattr(test_checks.subprocess, "run", run)

    test_checks._stage_sdk_config(isolated, integration)

    assert (sdk_root / "config.json").read_bytes() == config.read_bytes()


def test_integration_tests_do_not_collect_hyphenated_root_as_package(tmp_path: Path, monkeypatch) -> None:
    integration = tmp_path / "hyphenated-integration"
    tests_dir = integration / "tests"
    tests_dir.mkdir(parents=True)
    (tmp_path / "conftest.py").write_text(
        "import pytest\n\n@pytest.fixture\ndef shared_value():\n    return 1\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\nasyncio_mode = "auto"\n',
        encoding="utf-8",
    )
    (integration / "__init__.py").write_text("from .demo import VALUE\n", encoding="utf-8")
    (integration / "demo.py").write_text("VALUE = 1\n", encoding="utf-8")
    test_file = tests_dir / "test_demo_unit.py"
    test_file.write_text(
        "import pytest\n\n"
        "pytestmark = pytest.mark.unit\n\n"
        "async def test_demo(shared_value):\n"
        "    assert shared_value == 1\n",
        encoding="utf-8",
    )
    isolated = environment.IntegrationEnvironment(tmp_path / "cache", Path(sys.executable), "key", created=False)
    monkeypatch.setattr(test_checks, "_stage_sdk_config", lambda *args: None)

    exit_code, output = test_checks._run_integration_tests(isolated, integration, [test_file])

    assert exit_code == 0, output
    assert "1 passed" in output
    assert (integration / "__init__.py").is_file()


def test_integration_tests_resolve_paths_before_changing_working_directory(tmp_path: Path, monkeypatch) -> None:
    integration = Path("relative-integration")
    test_file = integration / "tests" / "test_demo_unit.py"
    isolated = environment.IntegrationEnvironment(tmp_path / "cache", Path(sys.executable), "key", created=False)
    executed = []
    monkeypatch.setattr(test_checks, "_stage_sdk_config", lambda *args: None)
    monkeypatch.setattr(
        test_checks,
        "_execute_tests",
        lambda selected, root, tests: executed.append((selected, root, tests)) or (0, ""),
    )

    result = test_checks._run_integration_tests(isolated, integration, [test_file])

    assert result == (0, "")
    assert executed == [(isolated, integration.resolve(), [test_file.resolve()])]


def test_test_check_reports_isolated_environment_failure(tmp_path: Path, monkeypatch) -> None:
    integration = tmp_path / "demo"
    tests_dir = integration / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_demo_unit.py").touch()

    def fail(*args, **kwargs):
        raise environment.EnvironmentBuildError("dependency resolution failed")

    monkeypatch.setattr(static, "run_integration_tests", fail)

    report = static.check_tests(integration)

    assert report.status == "error"
    assert report.raw_output == "dependency resolution failed"
    assert report.messages[0].message == "dependency resolution failed"


def test_sdk_pins_and_modules_are_isolated_between_integrations(tmp_path: Path, monkeypatch) -> None:
    sdk_v1 = tmp_path / "sdk-v1"
    sdk_v2 = tmp_path / "sdk-v2"
    sdk_v1.mkdir()
    sdk_v2.mkdir()
    (sdk_v1 / "requirements.txt").write_text("autohive-integrations-sdk~=1.0.2\n", encoding="utf-8")
    (sdk_v2 / "requirements.txt").write_text("autohive-integrations-sdk~=2.0.1\n", encoding="utf-8")
    monkeypatch.setenv("HIVEUP_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(environment.shutil, "which", lambda name: None)

    def install(path: Path, *, integration_dir: Path, requirements: Path | None, include_test_tools: bool) -> None:
        assert requirements is not None
        assert include_test_tools is False
        module = "sdk_v1_only" if "~=1.0.2" in requirements.read_text(encoding="utf-8") else "sdk_v2_only"
        purelib = subprocess.run(
            [
                str(environment._environment_python(path)),
                "-c",
                "import sysconfig; print(sysconfig.get_path('purelib'))",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        (Path(purelib) / f"{module}.py").write_text(f"INTEGRATION = {integration_dir.name!r}\n", encoding="utf-8")

    monkeypatch.setattr(environment, "_install_dependencies", install)

    v1_environment = environment.prepare_environment(sdk_v1)
    v2_environment = environment.prepare_environment(sdk_v2)

    assert v1_environment.key != v2_environment.key
    assert environment.module_available(v1_environment, "sdk_v1_only")
    assert not environment.module_available(v1_environment, "sdk_v2_only")
    assert environment.module_available(v2_environment, "sdk_v2_only")
    assert not environment.module_available(v2_environment, "sdk_v1_only")
    assert importlib.util.find_spec("sdk_v1_only") is None
    assert importlib.util.find_spec("sdk_v2_only") is None
