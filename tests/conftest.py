from pathlib import Path

import pytest


@pytest.fixture
def require_symlink_support(tmp_path: Path) -> None:
    """Skip symlink-specific tests when the host cannot create symlinks."""
    target = tmp_path / "symlink-capability-target"
    target.mkdir()
    link = tmp_path / "symlink-capability-link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink creation is not available: {exc}")
    finally:
        link.unlink(missing_ok=True)
