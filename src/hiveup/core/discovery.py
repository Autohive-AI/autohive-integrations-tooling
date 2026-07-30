"""Integration directory discovery."""

from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath

SKIP_DIRS = {
    ".git",
    ".github",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".vscode",
    "__pycache__",
    "docs",
    "node_modules",
    "scripts",
    "src",
    "template-structure",
    "tests",
    "venv",
}


def is_integration_dir(path: Path) -> bool:
    return path.is_dir() and (path / "config.json").is_file()


def is_candidate_integration_dir(path: Path) -> bool:
    return path.is_dir() and ((path / "config.json").is_file() or any(path.glob("*.py")))


def discover_integrations(root: Path) -> list[Path]:
    root = root.resolve()
    if is_integration_dir(root):
        return [root]

    integrations: list[Path] = []
    for child in sorted(root.iterdir()):
        if child.name in SKIP_DIRS or child.name.startswith("."):
            continue
        if is_candidate_integration_dir(child):
            integrations.append(child)
    return integrations


def explicit_integrations(dirs: list[Path]) -> list[Path]:
    integrations: list[Path] = []
    for path in dirs:
        if not path.exists():
            raise RuntimeError(f"Integration directory does not exist: {path}")
        if not path.is_dir():
            raise RuntimeError(f"Integration path is not a directory: {path}")
        integrations.append(path.resolve())
    return integrations


def changed_integrations(root: Path, base_ref: str) -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(root), "diff", "--name-only", base_ref, "HEAD"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"Could not diff against {base_ref}")

    changed: set[Path] = set()
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        path = PurePosixPath(line)
        if len(path.parts) < 2:
            continue
        top_dir = path.parts[0]
        if top_dir in SKIP_DIRS or top_dir.startswith("."):
            continue
        candidate = root / top_dir
        if candidate.is_dir():
            changed.add(candidate.resolve())
    return sorted(changed)
