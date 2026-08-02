"""Shared deployment-source filesystem rules."""

from pathlib import Path


TOP_LEVEL_DEVELOPMENT_DIRECTORIES = {
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
ALWAYS_EXCLUDED_DIRECTORIES = {"__pycache__"}
ASSET_DIRECTORIES = {"assets", "fonts"}
SUPPORTED_ICON_SUFFIXES = {".jpeg", ".jpg", ".png"}


def is_excluded_development_path(relative: Path) -> bool:
    """Return whether a relative path belongs to excluded development content."""
    if not relative.parts:
        return False
    return (
        relative.parts[0] in TOP_LEVEL_DEVELOPMENT_DIRECTORIES
        or bool(ALWAYS_EXCLUDED_DIRECTORIES.intersection(relative.parts))
        or any(part.startswith(".") for part in relative.parts)
    )


def is_deployment_source(relative: Path) -> bool:
    """Return whether a relative regular file belongs in a deployment archive."""
    if is_excluded_development_path(relative):
        return False
    if relative.name == "requirements.txt" or relative.suffix.casefold() in {".pyc", ".zip"}:
        return False
    if relative.suffix.casefold() == ".py":
        return True
    if len(relative.parts) == 1:
        return relative.name == "config.json" or (
            relative.stem.casefold() == "icon"
            and relative.suffix.casefold() in SUPPORTED_ICON_SUFFIXES
        )
    return relative.parts[0].casefold() in ASSET_DIRECTORIES


def symlink_component(path: Path, root: Path) -> Path | None:
    """Return the first symlink at or above path within root."""
    relative = path.relative_to(root)
    candidate = root
    for part in relative.parts:
        candidate /= part
        if candidate.is_symlink():
            return candidate
    return None
