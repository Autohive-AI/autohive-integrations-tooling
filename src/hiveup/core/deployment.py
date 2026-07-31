"""Shared deployment-source filesystem rules."""

from pathlib import Path


EXCLUDED_DEVELOPMENT_DIRECTORIES = {
    ".git",
    ".github",
    ".hiveup",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dependencies",
    "dist",
    "env",
    "node_modules",
    "test",
    "tests",
    "venv",
}


def is_excluded_development_path(relative: Path) -> bool:
    """Return whether a relative path belongs to excluded development content."""
    return bool(EXCLUDED_DEVELOPMENT_DIRECTORIES.intersection(relative.parts)) or any(
        part.startswith(".") for part in relative.parts
    )


def symlink_component(path: Path, root: Path) -> Path | None:
    """Return the first symlink at or above path within root."""
    relative = path.relative_to(root)
    candidate = root
    for part in relative.parts:
        candidate /= part
        if candidate.is_symlink():
            return candidate
    return None
