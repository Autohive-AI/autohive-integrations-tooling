#!/usr/bin/env python3
"""Render the validation-results PR comment as Markdown to stdout.

All inputs are read from environment variables so that multi-line tool
output (which can contain backticks, ``EOF`` markers, etc.) is handled
correctly without any YAML or heredoc escaping.

Expected env vars per check (prefix is one of STRUCTURE / CODE / TESTS /
README / VERSION):

    {PREFIX}_OUTCOME   one of "success", "failure", "skipped", ""
    {PREFIX}_WARN      "true" if the check emitted warnings
    {PREFIX}_OUTPUT    full captured stdout/stderr of the check

Plus context vars: HEAD_SHA, SERVER_URL, REPOSITORY, COMMIT_MSG,
UPDATED_AT, DIRS.
"""

from __future__ import annotations

import os
import sys


CHECKS: list[tuple[str, str]] = [
    ("Structure", "STRUCTURE"),
    ("Code", "CODE"),
    ("Tests", "TESTS"),
    ("README", "README"),
    ("Version", "VERSION"),
]


def _status(outcome: str, has_warnings: str) -> tuple[str, str]:
    """Return (icon, table_text) for a check result."""
    if outcome == "failure":
        return "❌", "❌ Failed"
    if has_warnings == "true":
        return "⚠️", "⚠️ Passed with warnings"
    return "✅", "✅ Passed"


def _section(label: str, prefix: str) -> str:
    outcome = os.environ.get(f"{prefix}_OUTCOME", "")
    warn = os.environ.get(f"{prefix}_WARN", "")
    output = os.environ.get(f"{prefix}_OUTPUT", "") or "(no output)"
    icon, _ = _status(outcome, warn)
    return (
        f"<details><summary>{icon} {label} Check output</summary>\n\n"
        f"```\n{output}\n```\n\n"
        f"</details>\n"
    )


def main() -> int:
    head_sha = os.environ.get("HEAD_SHA", "")
    server_url = os.environ.get("SERVER_URL", "")
    repository = os.environ.get("REPOSITORY", "")
    commit_msg = os.environ.get("COMMIT_MSG", "")
    updated_at = os.environ.get("UPDATED_AT", "")
    dirs = os.environ.get("DIRS", "")

    rows = []
    for label, prefix in CHECKS:
        outcome = os.environ.get(f"{prefix}_OUTCOME", "")
        warn = os.environ.get(f"{prefix}_WARN", "")
        _, text = _status(outcome, warn)
        rows.append(f"| {label} | {text} |")

    sections = [_section(label, prefix) for label, prefix in CHECKS]

    md = (
        "## 🔍 Integration Validation Results\n\n"
        f"**Commit:** [`{head_sha}`]({server_url}/{repository}/commit/{head_sha})"
        f" · {commit_msg}\n"
        f"**Updated:** {updated_at}\n\n"
        f"**Changed directories:** `{dirs}`\n\n"
        "| Check | Result |\n"
        "|-------|--------|\n"
        + "\n".join(rows)
        + "\n\n"
        + "\n".join(sections)
    )
    sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
