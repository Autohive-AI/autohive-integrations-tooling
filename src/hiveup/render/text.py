"""Shared plain-text tables and diagnostic filtering."""

from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath, PureWindowsPath

from wcwidth import wcswidth

from hiveup.core.results import CheckResult

ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def raw_output_without_messages(result: CheckResult) -> str:
    """Remove ANSI/whitespace-equivalent structured diagnostics, without changing raw data."""
    messages = {ANSI_ESCAPE.sub("", message.message).strip() for message in result.messages}
    output = ANSI_ESCAPE.sub("", result.raw_output)
    if output.strip() in messages:
        return ""
    return "\n".join(line for line in output.splitlines() if line.strip() not in messages).strip()


def normalized_path(value: str, integration: str) -> str:
    """Display a package/integration/workspace-relative source, or its basename if unknown."""
    path = value.replace("\\", "/")
    for marker in ("/site-packages/", f"/{integration}/"):
        if marker in path:
            suffix = path.rsplit(marker, 1)[1]
            return f"{integration}/{suffix}" if marker.endswith(f"/{integration}/") else suffix
    path_type = PureWindowsPath if re.match(r"^[A-Za-z]:/|^//", path) else PurePosixPath
    source = path_type(path)
    if not source.is_absolute():
        return source.as_posix()
    for workspace in (os.environ.get("GITHUB_WORKSPACE"), str(Path.cwd())):
        if workspace:
            try:
                return source.relative_to(path_type(workspace)).as_posix()
            except ValueError:
                pass
    return source.name


def bandit_warnings(result: CheckResult) -> list[str]:
    """Summarize nosec warnings, preserving distinct original sources with the same basename."""
    warnings = []
    seen = set()
    pattern = re.compile(r"^\[tester\]\s+WARNING\s+nosec encountered \((B\d+)\), but no failed test on file (.+)$")
    for line in ANSI_ESCAPE.sub("", result.raw_output).splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue
        warning = f"nosec encountered ({match.group(1)}) in {normalized_path(match.group(2), result.integration)}"
        if match.groups() not in seen:
            warnings.append(warning)
            seen.add(match.groups())
    return warnings


def format_table(
    headers: tuple[str, ...],
    rows: list[tuple[str, ...]],
    *,
    right_align: tuple[int, ...] = (),
    total_row: tuple[str, ...] | None = None,
) -> str:
    """Format a fixed-width table using terminal cells, including emoji and combining marks."""
    values = [headers, *rows, *([total_row] if total_row else [])]
    widths = [max(wcswidth(ANSI_ESCAPE.sub("", row[index])) for row in values) for index in range(len(headers))]

    def line(row: tuple[str, ...]) -> str:
        cells = []
        for index, value in enumerate(row):
            padding = " " * (widths[index] - wcswidth(ANSI_ESCAPE.sub("", value)))
            cells.append(padding + value if index in right_align else value + padding)
        return "  ".join(cells)

    divider = "-" * (sum(widths) + 2 * (len(headers) - 1))
    lines = [line(headers), divider, *map(line, rows)]
    if total_row:
        lines.extend([divider, line(total_row)])
    return "\n".join(lines)
