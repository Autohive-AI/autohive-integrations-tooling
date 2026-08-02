import subprocess
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hiveup.checks import static  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_static_adapters_use_canonical_check_modules() -> None:
    assert static.IntegrationValidator.__module__ == "hiveup.checks.structure"
    assert static.check_config_sync.__module__ == "hiveup.checks.config_sync"
    assert static.check_fetch_pattern.__module__ == "hiveup.checks.fetch_pattern"
    assert static.find_unit_test_files.__module__ == "hiveup.checks.tests"
    assert static.check_readme.__module__ == "hiveup.checks.readme"
    assert static.check_version_bump.__module__ == "hiveup.checks.version"
    assert not (REPO_ROOT / "src/hiveup/_legacy").exists()


@pytest.mark.parametrize(
    "script_name",
    [
        "check_code.py",
        "validate_integration.py",
        "check_config_sync.py",
        "check_fetch_pattern.py",
        "check_readme.py",
        "check_version_bump.py",
    ],
)
def test_compatibility_script_help_works_outside_repo(tmp_path: Path, script_name: str) -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / script_name), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()


def test_run_tests_compatibility_script_works_outside_repo(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts/run_tests.py")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    assert "No integration directories found" in result.stdout
