import sys
import json
import shutil
import struct
import subprocess
import zipfile
from pathlib import Path

from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hiveup.cli import _emit_github_annotations, _write_github_outputs, _write_package_zip, app, run_validation  # noqa: E402
from hiveup.checks.structure import RESERVED_ENTRY_POINT_MESSAGE  # noqa: E402
from hiveup.core.discovery import changed_integrations, discover_integrations  # noqa: E402


EXAMPLES = Path(__file__).resolve().parent / "examples"


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


def test_discovery_includes_candidate_dir_missing_config(tmp_path: Path) -> None:
    candidate = tmp_path / "new-integration"
    candidate.mkdir()
    (candidate / "main.py").write_text("print('hello')\n", encoding="utf-8")

    assert discover_integrations(tmp_path) == [candidate.resolve()]


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
        ("readme", "warning"),
        ("version", "warning"),
    }


def test_github_outputs_include_legacy_action_keys(tmp_path: Path) -> None:
    report = run_validation([EXAMPLES / "good-integration"], only={"structure", "json"})
    output_file = tmp_path / "github-output.txt"

    _write_github_outputs(output_file, report, comment_file=tmp_path / "comment.md", dirs="good-integration")
    output = output_file.read_text(encoding="utf-8")

    assert "directories<<EOF_directories\ngood-integration" in output
    assert "structure_result<<EOF_structure_result\nsuccess" in output
    assert "code_result<<EOF_code_result\nsuccess" in output
    assert "comment_path<<EOF_comment_path" in output


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

    _write_package_zip(integration, package, None)

    with zipfile.ZipFile(package) as archive:
        assert set(archive.namelist()) == {"icon.png", "icon.jpg", "icon.jpeg"}


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


def test_package_rejects_reserved_entry_point_when_validation_is_skipped(tmp_path: Path) -> None:
    integration = _integration_with_entry_point(tmp_path / "reserved-package", "main.py")

    result = CliRunner().invoke(app, ["package", str(integration), "--skip-validate"])

    assert result.exit_code == 2
    assert RESERVED_ENTRY_POINT_MESSAGE in result.output


def _jpeg_with_dimensions(width: int, height: int) -> bytes:
    frame = b"\x08" + struct.pack(">HH", height, width) + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
    return b"\xff\xd8\xff\xc0" + struct.pack(">H", len(frame) + 2) + frame + b"\xff\xd9"


def _integration_with_entry_point(path: Path, entry_point: str) -> Path:
    shutil.copytree(EXAMPLES / "good-integration", path)
    original = path / "good_integration.py"
    replacement = path / entry_point
    replacement.parent.mkdir(parents=True, exist_ok=True)
    original.rename(replacement)
    config_path = path / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["entry_point"] = entry_point
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return path
