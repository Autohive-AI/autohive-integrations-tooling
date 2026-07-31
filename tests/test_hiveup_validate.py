import sys
import json
import os
import shutil
import struct
import subprocess
import tomllib
import zipfile
from pathlib import Path
from unittest.mock import Mock

from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import hiveup.cli as cli  # noqa: E402
from hiveup.cli import _emit_github_annotations, _report_dirs, _write_github_outputs, app, run_validation  # noqa: E402
from hiveup import __version__  # noqa: E402
from hiveup.checks.readme import check_readme  # noqa: E402
from hiveup.checks.static import _legacy_check  # noqa: E402
from hiveup.checks.structure import (  # noqa: E402
    ENTRY_POINT_IDENTIFIER_MESSAGE,
    RESERVED_ENTRY_POINT_MESSAGE,
    ROOT_ENTRY_POINT_MESSAGE,
    validate as validate_structure,
)
from hiveup.core.discovery import changed_integrations, discover_integrations  # noqa: E402
from hiveup.core.results import CheckMessage, CheckResult, ValidationReport  # noqa: E402
from hiveup.packaging import (  # noqa: E402
    TARGET_PLATFORM,
    TARGET_PYTHON_VERSION,
    PackageBuildError,
    build_package,
    install_dependencies,
    write_package_zip,
)
from hiveup.render.console import render_report  # noqa: E402


EXAMPLES = Path(__file__).resolve().parent / "examples"
ROOT = Path(__file__).resolve().parents[1]


def test_package_identity_and_version_have_one_source_of_truth() -> None:
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert metadata["project"]["name"] == "hiveup"
    assert metadata["project"]["dynamic"] == ["version"]
    assert "version" not in metadata["project"]
    assert metadata["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "hiveup.__version__"}
    assert __version__ == "2.4.0a1"


def test_validate_static_checks_pass_good_integration() -> None:
    report = run_validation(
        [EXAMPLES / "good-integration"],
        only={"syntax", "imports", "json", "sync", "fetch"},
    )

    assert report.exit_code() == 0
    assert {(result.check, result.status) for result in report.results} == {
        ("syntax", "passed"),
        ("imports", "passed"),
        ("json", "passed"),
        ("sync", "passed"),
        ("fetch", "passed"),
    }


def test_validate_reports_config_sync_failures() -> None:
    report = run_validation([EXAMPLES / "config-mismatch"], only={"sync"})

    assert report.exit_code() == 1
    assert report.results[0].check == "sync"
    assert report.results[0].status == "failed"
    assert any("defined in config.json" in message.message for message in report.results[0].messages)


def test_legacy_check_exception_is_processing_error_and_validation_continues(tmp_path: Path) -> None:
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "broken.py").write_text("VALUE = 1\n", encoding="utf-8")
    (broken / "config.json").write_text(
        json.dumps({"entry_point": "broken.py", "actions": []}),
        encoding="utf-8",
    )

    report = run_validation([broken, EXAMPLES / "good-integration"], only={"sync"})

    assert report.exit_code() == 2
    assert [(result.integration, result.status) for result in report.results] == [
        ("broken", "error"),
        ("good-integration", "passed"),
    ]
    assert report.results[0].messages[0].message == "'list' object has no attribute 'items'"


def test_validate_rejects_unknown_check() -> None:
    report = run_validation([EXAMPLES / "good-integration"], only={"not-a-check"})

    assert report.exit_code() == 2
    assert report.results[0].check == "selection"
    assert "Unknown check" in report.results[0].messages[0].message


def test_explicit_missing_directory_is_processing_error(tmp_path: Path) -> None:
    report = run_validation([tmp_path / "missing-integration"], only={"structure"})

    assert report.exit_code() == 2
    assert report.results[0].check == "discovery"
    assert "does not exist" in report.results[0].messages[0].message


def test_explicit_skipped_directory_is_validated_instead_of_silently_dropped(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()

    report = run_validation([docs], only={"structure"})

    assert report.exit_code() == 1
    assert len(report.results) == 1
    assert report.results[0].integration == "docs"
    assert report.results[0].status == "failed"
    assert any("Missing required file: config.json" in message.message for message in report.results[0].messages)


def test_discovery_includes_candidate_dir_missing_config(tmp_path: Path) -> None:
    candidate = tmp_path / "new-integration"
    candidate.mkdir()
    (candidate / "main.py").write_text("print('hello')\n", encoding="utf-8")

    assert discover_integrations(tmp_path) == [candidate.resolve()]


def test_discovery_scans_children_when_repository_root_has_python_files(tmp_path: Path) -> None:
    (tmp_path / "conftest.py").write_text("ROOT_FIXTURE = True\n", encoding="utf-8")
    (tmp_path / "setup.py").write_text("# Repository tooling\n", encoding="utf-8")
    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    alpha.mkdir()
    beta.mkdir()
    (alpha / "config.json").write_text("{}\n", encoding="utf-8")
    (beta / "config.json").write_text("{}\n", encoding="utf-8")

    assert discover_integrations(tmp_path) == [alpha.resolve(), beta.resolve()]


def test_discovery_selects_root_when_it_has_integration_config(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text("{}\n", encoding="utf-8")
    child = tmp_path / "nested"
    child.mkdir()
    (child / "config.json").write_text("{}\n", encoding="utf-8")

    assert discover_integrations(tmp_path) == [tmp_path.resolve()]


def test_changed_discovery_includes_new_top_level_dir_without_config(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=tmp_path, check=True)
    base_ref = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    candidate = tmp_path / "new-integration"
    candidate.mkdir()
    (candidate / "main.py").write_text("print('hello')\n", encoding="utf-8")
    subprocess.run(["git", "add", "new-integration/main.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add integration"], cwd=tmp_path, check=True)

    assert changed_integrations(tmp_path, base_ref) == [candidate.resolve()]


def test_changed_discovery_ignores_changes_made_only_on_base_branch(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "config.json").write_text("{}\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=tmp_path, check=True)
    subprocess.run(["git", "switch", "-q", "-c", "feature"], cwd=tmp_path, check=True)
    feature = tmp_path / "feature-integration"
    feature.mkdir()
    (feature / "config.json").write_text("{}\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "feature change"], cwd=tmp_path, check=True)
    subprocess.run(["git", "switch", "-q", "main"], cwd=tmp_path, check=True)
    (shared / "config.json").write_text('{"base": true}\n', encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base-only change"], cwd=tmp_path, check=True)
    subprocess.run(["git", "switch", "-q", "feature"], cwd=tmp_path, check=True)

    assert changed_integrations(tmp_path, "main") == [feature.resolve()]


def test_readme_check_ignores_readme_change_made_only_on_base_branch(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=tmp_path, check=True)
    subprocess.run(["git", "switch", "-q", "-c", "feature"], cwd=tmp_path, check=True)
    integration = tmp_path / "new-integration"
    integration.mkdir()
    (integration / "config.json").write_text("{}\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add integration"], cwd=tmp_path, check=True)
    subprocess.run(["git", "switch", "-q", "main"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("base branch update\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "update readme on base"], cwd=tmp_path, check=True)
    subprocess.run(["git", "switch", "-q", "feature"], cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)

    exit_code = check_readme("main", ["new-integration"])

    assert exit_code == 1
    assert "README.md was NOT updated" in capsys.readouterr().out


def test_import_check_does_not_execute_local_package_init(tmp_path: Path) -> None:
    integration = tmp_path / "side-effect-integration"
    package = integration / "provider"
    package.mkdir(parents=True)
    marker = tmp_path / "import-side-effect"
    (package / "__init__.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n",
        encoding="utf-8",
    )
    (package / "client.py").write_text("VALUE = 1\n", encoding="utf-8")
    (integration / "main.py").write_text("import provider.client\n", encoding="utf-8")

    report = run_validation([integration], only={"imports"})

    assert report.exit_code() == 0
    assert not marker.exists()


def test_import_processing_error_uses_exit_code_2(tmp_path: Path) -> None:
    integration = tmp_path / "bad-python"
    integration.mkdir()
    (integration / "main.py").write_text("import os\nif True print('bad')\n", encoding="utf-8")

    report = run_validation([integration], only={"imports"})

    assert report.exit_code() == 2
    assert report.results[0].status == "error"


def test_ruff_config_is_bundled_package_data() -> None:
    from hiveup.checks.static import RUFF_CONFIG

    assert RUFF_CONFIG.is_file()
    assert RUFF_CONFIG.parent.name == "data"


def test_validate_json_output_is_valid_json() -> None:
    report = run_validation([EXAMPLES / "good-integration"], only={"json"})

    encoded = json.dumps(report.to_dict())

    assert json.loads(encoded)["exit_code"] == 0


def test_console_renders_raw_unit_test_failure_output(capsys) -> None:
    report = ValidationReport(
        [
            CheckResult(
                check="tests",
                integration="demo",
                status="failed",
                messages=[CheckMessage("error", "Unit tests failed", fix_hint="Run: hiveup test demo")],
                raw_output="FAILED tests/test_demo_unit.py::test_demo\nAssertionError: expected 2, got 1",
            )
        ]
    )

    render_report(report)

    output = capsys.readouterr().out
    assert "FAILED tests/test_demo_unit.py::test_demo" in output
    assert "AssertionError: expected 2, got 1" in output


def test_git_based_checks_work_outside_repo_cwd(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "README.md").write_text("# Integrations\n", encoding="utf-8")
    integration = repo / "demo"
    integration.mkdir()
    (integration / "config.json").write_text(
        json.dumps(
            {
                "name": "demo",
                "version": "1.0.0",
                "description": "Demo",
                "entry_point": "demo.py",
                "actions": {},
            }
        ),
        encoding="utf-8",
    )
    (integration / "demo.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
    base_ref = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    config = json.loads((integration / "config.json").read_text(encoding="utf-8"))
    config["version"] = "1.0.1"
    (integration / "config.json").write_text(json.dumps(config), encoding="utf-8")
    subprocess.run(["git", "add", "demo/config.json"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "bump"], cwd=repo, check=True)

    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)

    report = run_validation([integration], base_ref=base_ref, only={"readme", "version"})

    assert report.exit_code() == 0
    assert {(result.check, result.status) for result in report.results} == {
        ("readme", "passed"),
        ("version", "passed"),
    }


def test_successful_legacy_check_only_reports_actual_warnings(tmp_path: Path) -> None:
    def legacy_output() -> int:
        print("✅ CHECK PASSED")
        print("⚠️ consider a larger version bump")
        return 0

    result = _legacy_check("version", tmp_path, legacy_output)

    assert result.status == "warning"
    assert [message.message for message in result.messages] == ["⚠️ consider a larger version bump"]
    assert "✅ CHECK PASSED" in result.raw_output


def test_existing_integration_without_canonical_unit_tests_warns_with_base_ref(tmp_path: Path) -> None:
    integration, base_ref = _git_integration_without_canonical_tests(tmp_path, existing=True)

    report = run_validation([integration], base_ref=base_ref, only={"structure"})

    assert report.exit_code() == 0
    assert report.results[0].status == "warning"
    assert any("Missing unit test file" in message.message for message in report.results[0].messages)


def test_new_integration_without_canonical_unit_tests_fails_with_base_ref(tmp_path: Path) -> None:
    integration, base_ref = _git_integration_without_canonical_tests(tmp_path, existing=False)

    report = run_validation([integration], base_ref=base_ref, only={"structure"})

    assert report.exit_code() == 1
    assert report.results[0].status == "failed"
    assert any("Missing unit test file" in message.message for message in report.results[0].messages)


def test_integration_without_canonical_unit_tests_warns_without_base_ref(tmp_path: Path) -> None:
    integration, _ = _git_integration_without_canonical_tests(tmp_path, existing=True)

    report = run_validation([integration], only={"structure"})

    assert report.exit_code() == 0
    assert report.results[0].status == "warning"
    assert any("Missing unit test file" in message.message for message in report.results[0].messages)


def test_structure_reports_unresolvable_base_ref_as_processing_error(tmp_path: Path) -> None:
    integration, _ = _git_integration_without_canonical_tests(tmp_path, existing=True)

    report = run_validation([integration], base_ref="does-not-exist", only={"structure"})

    assert report.exit_code() == 2
    assert report.results[0].status == "error"
    assert report.results[0].messages[0].message == (
        "base-ref 'does-not-exist' not resolvable — check fetch-depth or ref name"
    )


def test_legacy_structure_cli_warns_for_noncanonical_unit_test_name(tmp_path: Path, capsys) -> None:
    integration, _ = _git_integration_without_canonical_tests(tmp_path, existing=True)

    exit_code = validate_structure([str(integration)])

    assert exit_code == 0
    assert "Missing unit test file: tests/test_*_unit.py" in capsys.readouterr().out


def test_github_outputs_include_legacy_action_keys(tmp_path: Path) -> None:
    report = run_validation([EXAMPLES / "good-integration"], only={"structure", "json"})
    output_file = tmp_path / "github-output.txt"

    _write_github_outputs(output_file, report, comment_file=tmp_path / "comment.md", dirs="good-integration")
    output = output_file.read_text(encoding="utf-8")

    assert "directories<<EOF_directories\ngood-integration" in output
    assert "structure_result<<EOF_structure_result\nsuccess" in output
    assert "code_result<<EOF_code_result\nsuccess" in output
    assert "tests_result<<EOF_tests_result\nskipped" in output
    assert "readme_result<<EOF_readme_result\nskipped" in output
    assert "version_result<<EOF_version_result\nskipped" in output
    assert "comment_path<<EOF_comment_path" in output


def test_github_outputs_report_run_errors_in_every_group(tmp_path: Path) -> None:
    report = ValidationReport(
        [
            CheckResult(
                check="discovery",
                integration=str(tmp_path),
                status="error",
                messages=[CheckMessage("error", "Integration directory does not exist: missing")],
            )
        ]
    )
    output_file = tmp_path / "github-output.txt"

    _write_github_outputs(output_file, report, comment_file=tmp_path / "comment.md", dirs="")
    output = output_file.read_text(encoding="utf-8")

    for group in ("structure", "code", "tests", "readme", "version"):
        assert f"{group}_result<<EOF_{group}_result\nfailure" in output
        assert f"{group}_output<<EOF_{group}_output" in output
    assert output.count("Integration directory does not exist: missing") == 5


def test_ci_writes_failure_comment_and_outputs_when_discovery_fails(tmp_path: Path) -> None:
    comment_file = tmp_path / "comment.md"
    output_file = tmp_path / "github-output.txt"

    result = CliRunner().invoke(
        app,
        [
            "ci",
            str(tmp_path / "missing"),
            "--comment-file",
            str(comment_file),
            "--output-file",
            str(output_file),
        ],
    )

    assert result.exit_code == 2
    assert comment_file.is_file()
    comment = comment_file.read_text(encoding="utf-8")
    assert "❌ Failed" in comment
    assert "Integration directory does not exist" in comment
    output = output_file.read_text(encoding="utf-8")
    assert f"comment_path<<EOF_comment_path\n{comment_file}" in output
    assert "structure_result<<EOF_structure_result\nfailure" in output


def test_ci_uses_explicit_pull_request_head_for_comment_metadata(tmp_path: Path, monkeypatch) -> None:
    integration = tmp_path / "demo"
    integration.mkdir()
    comment_file = tmp_path / "comment.md"
    report = ValidationReport(
        [CheckResult(check="json", integration="demo", status="passed")],
        directories=[str(integration)],
    )
    rendered = {}
    requested_refs = []
    monkeypatch.setattr(cli, "run_validation", lambda *args, **kwargs: report)

    def commit_subject(ref: str = "HEAD") -> str:
        requested_refs.append(ref)
        return "pull request head subject"

    def render(report, *, commit: str, commit_msg: str, dirs: str) -> str:
        rendered.update(commit=commit, commit_msg=commit_msg, dirs=dirs)
        return "comment"

    monkeypatch.setattr(cli, "_git_commit_subject", commit_subject)
    monkeypatch.setattr(cli, "render_markdown", render)
    monkeypatch.setenv("GITHUB_SHA", "synthetic-merge-sha")

    result = CliRunner().invoke(
        app,
        ["ci", str(integration), "--commit", "pull-request-head-sha", "--comment-file", str(comment_file)],
    )

    assert result.exit_code == 0
    assert requested_refs == ["pull-request-head-sha"]
    assert rendered == {
        "commit": "pull-request-head-sha",
        "commit_msg": "pull request head subject",
        "dirs": str(integration),
    }


def test_ci_leaves_comment_path_empty_when_no_comment_was_written(tmp_path: Path, monkeypatch) -> None:
    comment_file = tmp_path / "comment.md"
    output_file = tmp_path / "github-output.txt"
    monkeypatch.setattr(cli, "run_validation", lambda *args, **kwargs: ValidationReport([]))

    result = CliRunner().invoke(
        app,
        [
            "ci",
            "--base-ref",
            "HEAD",
            "--comment-file",
            str(comment_file),
            "--output-file",
            str(output_file),
        ],
    )

    assert result.exit_code == 0
    assert not comment_file.exists()
    output = output_file.read_text(encoding="utf-8")
    assert "comment_path<<EOF_comment_path\n\nEOF_comment_path" in output
    assert str(comment_file) not in output
    for group in ("structure", "code", "tests", "readme", "version"):
        assert f"{group}_result<<EOF_{group}_result\nskipped" in output


def test_github_directories_output_preserves_distinct_repository_paths(tmp_path: Path, monkeypatch) -> None:
    first = tmp_path / "foo" / "shared"
    second = tmp_path / "bar" / "shared"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    report = run_validation([Path("foo/shared"), Path("bar/shared")], only={"json"})

    assert [result.integration for result in report.results] == ["shared", "shared"]
    assert _report_dirs(report) == "foo/shared bar/shared"


def test_github_annotations_include_validation_failures(capsys) -> None:
    report = run_validation([EXAMPLES / "bad-icon"], only={"structure"})

    _emit_github_annotations(report)

    output = capsys.readouterr().out
    assert "::error ::icon.png must be 512x512 pixels" in output


def test_structure_accepts_512_pixel_jpg_and_jpeg_icons(tmp_path: Path) -> None:
    for extension in ("jpg", "jpeg"):
        integration = tmp_path / f"good-{extension}-integration"
        shutil.copytree(EXAMPLES / "good-integration", integration)
        (integration / "icon.png").unlink()
        (integration / f"icon.{extension}").write_bytes(_jpeg_with_dimensions(512, 512))

        report = run_validation([integration], only={"structure"})

        assert report.exit_code() == 0
        assert not any("icon" in message.message.lower() for message in report.results[0].messages)


def test_structure_rejects_unsupported_icon_format(tmp_path: Path) -> None:
    integration = tmp_path / "svg-icon-integration"
    shutil.copytree(EXAMPLES / "good-integration", integration)
    (integration / "icon.png").rename(integration / "icon.svg")

    report = run_validation([integration], only={"structure"})

    assert report.results[0].status == "failed"
    assert report.results[0].messages[0].message == (
        "Missing required file: icon.png, icon.jpg, or icon.jpeg (Integration icon)"
    )


def test_structure_rejects_wrong_sized_jpeg_icon(tmp_path: Path) -> None:
    integration = tmp_path / "wrong-sized-icon-integration"
    shutil.copytree(EXAMPLES / "good-integration", integration)
    (integration / "icon.png").unlink()
    (integration / "icon.jpg").write_bytes(_jpeg_with_dimensions(256, 512))

    report = run_validation([integration], only={"structure"})

    assert report.results[0].status == "failed"
    assert any(
        "icon.jpg must be 512x512 pixels (found 256x512)" in message.message
        for message in report.results[0].messages
    )


def test_structure_rejects_invalid_jpeg_icon(tmp_path: Path) -> None:
    integration = tmp_path / "invalid-jpeg-integration"
    shutil.copytree(EXAMPLES / "good-integration", integration)
    (integration / "icon.png").unlink()
    (integration / "icon.jpeg").write_bytes(b"not a jpeg")

    report = run_validation([integration], only={"structure"})

    assert report.results[0].status == "failed"
    assert any(
        "Could not read icon.jpeg: not a valid JPEG file" in message.message
        for message in report.results[0].messages
    )


def test_package_includes_only_supported_icon_formats(tmp_path: Path) -> None:
    integration = tmp_path / "demo"
    integration.mkdir()
    for name in ("icon.png", "icon.jpg", "icon.jpeg", "icon.svg", "icon.webp"):
        (integration / name).touch()
    package = tmp_path / "demo.zip"

    write_package_zip(integration, package, None)

    with zipfile.ZipFile(package) as archive:
        assert set(archive.namelist()) == {"icon.png", "icon.jpg", "icon.jpeg"}


def test_package_writes_root_layout_and_excludes_development_files(tmp_path: Path) -> None:
    integration = tmp_path / "demo"
    integration.mkdir()
    included = {
        "config.json": "{}",
        "requirements.txt": "example==1.0",
        "README.md": "# Demo",
        "demo.py": "VALUE = 1",
        "actions/get_data.py": "VALUE = 2",
        "assets/schema.json": "{}",
        "icon.png": "png",
    }
    for name, content in included.items():
        path = integration / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    for name in (
        "tests/test_demo.py",
        ".env",
        ".env.local",
        ".git/config",
        ".venv/lib/module.py",
        "__pycache__/demo.pyc",
        "dependencies/local.py",
        "dist/generated.py",
        "icon.svg",
        "icon.webp",
        ".coverage",
        "old-package.zip",
    ):
        path = integration / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("excluded", encoding="utf-8")
    dependencies = tmp_path / "staged-dependencies"
    (dependencies / "example").mkdir(parents=True)
    (dependencies / "example" / "__init__.py").write_text("", encoding="utf-8")
    package = integration / "demo.zip"

    write_package_zip(integration, package, dependencies)

    with zipfile.ZipFile(package) as archive:
        assert set(archive.namelist()) == {
            *included,
            "dependencies/example/__init__.py",
        }


def test_package_excludes_root_git_worktree_metadata(tmp_path: Path) -> None:
    integration = tmp_path / "demo"
    integration.mkdir()
    (integration / "demo.py").write_text("VALUE = 1\n", encoding="utf-8")
    (integration / ".git").write_text("gitdir: /Users/alice/project/.git/worktrees/demo\n", encoding="utf-8")
    package = tmp_path / "demo.zip"

    write_package_zip(integration, package, None)

    with zipfile.ZipFile(package) as archive:
        assert archive.namelist() == ["demo.py"]


def test_package_is_reproducible_across_source_metadata_changes(tmp_path: Path) -> None:
    integration = tmp_path / "demo"
    integration.mkdir()
    source = integration / "demo.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    dependencies = tmp_path / "staged-dependencies"
    dependency = dependencies / "example" / "__init__.py"
    dependency.parent.mkdir(parents=True)
    dependency.write_text("VERSION = '1.0'\n", encoding="utf-8")
    bytecode = dependencies / "example" / "__pycache__" / "__init__.pyc"
    bytecode.parent.mkdir()
    bytecode.write_bytes(b"host-specific bytecode")
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"

    write_package_zip(integration, first, dependencies)
    os.chmod(source, 0o755)
    os.chmod(dependency, 0o700)
    os.utime(source, (2_000_000_000, 2_000_000_000))
    os.utime(dependency, (2_000_000_000, 2_000_000_000))
    write_package_zip(integration, second, dependencies)

    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        assert archive.namelist() == ["demo.py", "dependencies/example/__init__.py"]
        for info in archive.infolist():
            assert info.date_time == (1980, 1, 1, 0, 0, 0)
            assert info.external_attr >> 16 == 0o100644


def test_package_preserves_existing_archive_when_write_fails(tmp_path: Path, monkeypatch) -> None:
    integration = tmp_path / "demo"
    integration.mkdir()
    (integration / "demo.py").write_text("VALUE = 1\n", encoding="utf-8")
    package = tmp_path / "demo.zip"
    package.write_bytes(b"existing release archive")

    def fail_write(*args, **kwargs) -> None:
        raise OSError("forced write failure")

    monkeypatch.setattr("hiveup.packaging._write_file", fail_write)

    try:
        write_package_zip(integration, package, None)
    except PackageBuildError as exc:
        assert "forced write failure" in str(exc)
    else:
        raise AssertionError("Expected package write to fail")

    assert package.read_bytes() == b"existing release archive"
    assert list(tmp_path.glob(".demo.zip.*.tmp")) == []


def test_structure_rejects_reserved_entry_point_basenames(tmp_path: Path) -> None:
    for index, entry_point in enumerate(("main.py", "MAIN.PY", "source/main.py")):
        integration = _integration_with_entry_point(tmp_path / f"reserved-{index}", entry_point)

        report = run_validation([integration], only={"structure"})

        assert report.results[0].status == "failed"
        assert any(message.message == RESERVED_ENTRY_POINT_MESSAGE for message in report.results[0].messages)


def test_structure_accepts_non_reserved_entry_point_name(tmp_path: Path) -> None:
    integration = _integration_with_entry_point(tmp_path / "domain-main", "domain_main.py")

    report = run_validation([integration], only={"structure"})

    assert report.exit_code() == 0
    assert not any(message.message == RESERVED_ENTRY_POINT_MESSAGE for message in report.results[0].messages)


def test_structure_rejects_nested_entry_point(tmp_path: Path) -> None:
    integration = _integration_with_entry_point(tmp_path / "nested-entry-point", "source/domain_main.py")

    report = run_validation([integration], only={"structure"})

    assert report.results[0].status == "failed"
    assert any(message.message == ROOT_ENTRY_POINT_MESSAGE for message in report.results[0].messages)


def test_structure_rejects_non_identifier_entry_point_stems(tmp_path: Path) -> None:
    for index, entry_point in enumerate(("my-api.py", "class.py")):
        integration = _integration_with_entry_point(tmp_path / f"invalid-identifier-{index}", entry_point)

        report = run_validation([integration], only={"structure"})

        assert report.results[0].status == "failed"
        assert any(message.message == ENTRY_POINT_IDENTIFIER_MESSAGE for message in report.results[0].messages)
        assert not any("must define" in message.message for message in report.results[0].messages)


def test_structure_requires_named_integration_load_export(tmp_path: Path) -> None:
    integration = _integration_with_entry_point(tmp_path / "wrong-export", "demo.py")
    entry_point = integration / "demo.py"
    entry_point.write_text(
        entry_point.read_text(encoding="utf-8").replace("demo =", "app ="),
        encoding="utf-8",
    )

    report = run_validation([integration], only={"structure"})

    assert report.results[0].status == "failed"
    assert any(
        message.message == "entry point demo.py must define 'demo = Integration.load(...)' at module scope"
        for message in report.results[0].messages
    )


def test_structure_entry_point_export_check_does_not_execute_code(tmp_path: Path) -> None:
    integration = _integration_with_entry_point(tmp_path / "safe-static-check", "demo.py")
    entry_point = integration / "demo.py"
    marker = tmp_path / "executed"
    entry_point.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n"
        "from autohive_integrations_sdk import Integration as RuntimeIntegration\n"
        "demo = RuntimeIntegration.load(Path(__file__).with_name('config.json'))\n",
        encoding="utf-8",
    )

    report = run_validation([integration], only={"structure"})

    assert report.exit_code() == 0
    assert not marker.exists()


def test_package_rejects_reserved_entry_point_when_validation_is_skipped(tmp_path: Path) -> None:
    integration = _integration_with_entry_point(tmp_path / "reserved-package", "main.py")

    result = CliRunner().invoke(app, ["package", str(integration), "--skip-validate"])

    assert result.exit_code == 2
    assert RESERVED_ENTRY_POINT_MESSAGE in result.output


def test_package_rejects_nested_entry_point_when_validation_is_skipped(tmp_path: Path) -> None:
    integration = _integration_with_entry_point(tmp_path / "nested-package", "source/demo.py")

    result = CliRunner().invoke(app, ["package", str(integration), "--skip-validate"])

    assert result.exit_code == 2
    assert ROOT_ENTRY_POINT_MESSAGE in result.output


def test_package_rejects_non_identifier_entry_point_when_validation_is_skipped(tmp_path: Path) -> None:
    integration = _integration_with_entry_point(tmp_path / "invalid-identifier-package", "my-api.py")

    result = CliRunner().invoke(app, ["package", str(integration), "--skip-validate"])

    assert result.exit_code == 2
    assert ENTRY_POINT_IDENTIFIER_MESSAGE in result.output


def test_package_dependencies_target_deployment_runtime(tmp_path: Path, monkeypatch) -> None:
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("example==1.0\n", encoding="utf-8")
    target = tmp_path / "dependencies"
    run = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr("hiveup.packaging.subprocess.run", run)

    install_dependencies(requirements, target)

    run.assert_called_once_with(
        [
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
        ],
        capture_output=True,
        text=True,
    )


def test_package_dependency_error_explains_wheel_contract(tmp_path: Path, monkeypatch) -> None:
    requirements = tmp_path / "requirements.txt"
    target = tmp_path / "dependencies"
    monkeypatch.setattr(
        "hiveup.packaging.subprocess.run",
        Mock(return_value=subprocess.CompletedProcess([], 1, "", "No matching distribution found")),
    )

    try:
        install_dependencies(requirements, target)
    except PackageBuildError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected dependency installation to fail")

    assert f"Python {TARGET_PYTHON_VERSION} on {TARGET_PLATFORM}" in message
    assert "must provide compatible wheels" in message
    assert "No matching distribution found" in message


def test_package_requires_requirements_even_when_validation_is_skipped(tmp_path: Path) -> None:
    integration = _integration_with_entry_point(tmp_path / "missing-requirements", "demo.py")
    (integration / "requirements.txt").unlink()

    result = CliRunner().invoke(app, ["package", str(integration), "--skip-validate"])

    assert result.exit_code == 2
    assert "requirements.txt not found" in result.output


def test_doctor_handles_successful_version_command_without_output(monkeypatch) -> None:
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        Mock(return_value=subprocess.CompletedProcess([], 0, "", "")),
    )

    result = CliRunner().invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "ruff: unknown" in result.output
    assert "bandit: unknown" in result.output
    assert "pip-audit: unknown" in result.output


def test_build_package_replaces_output_without_mutating_integration(tmp_path: Path, monkeypatch) -> None:
    integration = tmp_path / "demo"
    integration.mkdir()
    (integration / "requirements.txt").write_text("example==1.0\n", encoding="utf-8")
    (integration / "demo.py").write_text("VALUE = 1\n", encoding="utf-8")
    owned_dependencies = integration / "dependencies"
    owned_dependencies.mkdir()
    owned_file = owned_dependencies / "keep.txt"
    owned_file.write_text("developer-owned", encoding="utf-8")
    package = tmp_path / "demo.zip"
    package.write_bytes(b"old archive")

    def stage_dependencies(requirements: Path, target: Path) -> None:
        assert requirements == integration / "requirements.txt"
        (target / "pure_python").mkdir(parents=True)
        (target / "pure_python" / "__init__.py").write_text("", encoding="utf-8")
        (target / "native_extension.so").write_bytes(b"native wheel content")

    monkeypatch.setattr("hiveup.packaging.install_dependencies", stage_dependencies)

    build_package(integration, package)

    assert owned_file.read_text(encoding="utf-8") == "developer-owned"
    assert set(integration.iterdir()) == {integration / "requirements.txt", integration / "demo.py", owned_dependencies}
    with zipfile.ZipFile(package) as archive:
        assert set(archive.namelist()) == {
            "demo.py",
            "requirements.txt",
            "dependencies/native_extension.so",
            "dependencies/pure_python/__init__.py",
        }


def _git_integration_without_canonical_tests(tmp_path: Path, *, existing: bool) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "README.md").write_text("# Integrations\n", encoding="utf-8")
    integration = repo / "good-integration"

    if existing:
        shutil.copytree(EXAMPLES / "good-integration", integration)
        (integration / "tests" / "test_good_integration_unit.py").unlink()

    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
    base_ref = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    if not existing:
        shutil.copytree(EXAMPLES / "good-integration", integration)
        (integration / "tests" / "test_good_integration_unit.py").unlink()
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "add integration"], cwd=repo, check=True)

    return integration, base_ref


def _jpeg_with_dimensions(width: int, height: int) -> bytes:
    frame = b"\x08" + struct.pack(">HH", height, width) + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
    return b"\xff\xd8\xff\xc0" + struct.pack(">H", len(frame) + 2) + frame + b"\xff\xd9"


def _integration_with_entry_point(path: Path, entry_point: str) -> Path:
    shutil.copytree(EXAMPLES / "good-integration", path)
    original = path / "good_integration.py"
    replacement = path / entry_point
    replacement.parent.mkdir(parents=True, exist_ok=True)
    original.rename(replacement)
    replacement.write_text(
        replacement.read_text(encoding="utf-8").replace("good_integration", replacement.stem),
        encoding="utf-8",
    )
    config_path = path / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["entry_point"] = entry_point
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return path
