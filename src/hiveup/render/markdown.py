"""Markdown rendering for CI validation reports."""

from __future__ import annotations

from collections.abc import Iterable

from hiveup.core.results import CheckResult, ValidationReport

GROUPS = {
    "structure": {"structure"},
    "code": {"syntax", "imports", "json", "lint", "format", "security", "audit", "sync", "fetch"},
    "tests": {"tests"},
    "readme": {"readme"},
    "version": {"version"},
}


def render_markdown(report: ValidationReport, *, commit: str = "", commit_msg: str = "", dirs: str = "") -> str:
    rows = []
    sections = []
    grouped_checks = set().union(*GROUPS.values())
    run_errors = [
        result
        for result in report.results
        if result.check not in grouped_checks and result.status in {"failed", "error"}
    ]
    for label, group in [
        ("Structure", "structure"),
        ("Code", "code"),
        ("Tests", "tests"),
        ("README", "readme"),
        ("Version", "version"),
    ]:
        results = list(_group_results(report, group))
        rows.append(f"| {label} | {_group_status_text([*run_errors, *results])} |")
        sections.append(_section(label, results))

    if run_errors:
        sections.insert(0, _section("Run", run_errors))

    header = "## 🔍 Integration Validation Results\n\n"
    if commit:
        header += f"**Commit:** `{commit}`"
        if commit_msg:
            header += f" · {commit_msg}"
        header += "\n"
    if dirs:
        header += f"**Changed directories:** `{dirs}`\n"
    if commit or dirs:
        header += "\n"

    return header + "| Check | Result |\n" + "|-------|--------|\n" + "\n".join(rows) + "\n\n" + "\n".join(sections)


def _group_results(report: ValidationReport, group: str) -> Iterable[CheckResult]:
    checks = GROUPS[group]
    return (result for result in report.results if result.check in checks)


def _group_status_text(results: list[CheckResult]) -> str:
    if not results or all(result.status == "skipped" for result in results):
        return "⏭️ Skipped"
    if any(result.status in {"failed", "error"} for result in results):
        return "❌ Failed"
    if any(result.status == "warning" for result in results):
        return "⚠️ Passed with warnings"
    return "✅ Passed"


def _section(label: str, results: list[CheckResult]) -> str:
    body = "\n".join(_result_lines(result) for result in results) or "(skipped)"
    icon = _group_status_text(results).split(" ", 1)[0]
    return f"<details><summary>{icon} {label} Check output</summary>\n\n```\n{body}\n```\n\n</details>\n"


def _result_lines(result: CheckResult) -> str:
    lines = [f"[{result.integration}] {result.check}: {result.status}"]
    for message in result.messages:
        location = f"{message.file}: " if message.file else ""
        lines.append(f"  {message.severity}: {location}{message.message}")
    if result.raw_output:
        lines.append(result.raw_output)
    return "\n".join(lines)
