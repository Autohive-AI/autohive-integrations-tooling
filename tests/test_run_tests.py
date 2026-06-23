import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from run_tests import find_live_integration_test_files, print_live_integration_test_notice  # noqa: E402


def test_find_live_integration_test_files(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    live_test = tests_dir / "test_example_integration.py"
    live_test.write_text("pytestmark = pytest.mark.integration\n", encoding="utf-8")
    (tests_dir / "test_example_unit.py").write_text("", encoding="utf-8")
    (tests_dir / "test_example.py").write_text("", encoding="utf-8")

    assert find_live_integration_test_files(tmp_path) == [live_test]


def test_print_live_integration_test_notice_lists_files(tmp_path: Path, capsys) -> None:
    integration = tmp_path / "example"
    tests_dir = integration / "tests"
    tests_dir.mkdir(parents=True)
    live_test = tests_dir / "test_example_integration.py"
    live_test.write_text("pytestmark = pytest.mark.integration\n", encoding="utf-8")

    print_live_integration_test_notice([integration])

    output = capsys.readouterr().out
    assert "Live integration tests detected" in output
    assert str(live_test) in output
    assert "Live integration tests: not run in CI" in output


def test_print_live_notice_quiet_without_live_tests(tmp_path: Path, capsys) -> None:
    integration = tmp_path / "example"
    tests_dir = integration / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_example_unit.py").write_text("", encoding="utf-8")
    (tests_dir / "test_legacy_integration.py").write_text("", encoding="utf-8")

    print_live_integration_test_notice([integration])

    assert capsys.readouterr().out == ""
