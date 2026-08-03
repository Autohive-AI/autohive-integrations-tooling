"""Markdown rendering for CI validation reports."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable

from hiveup.core.results import CheckResult, ValidationReport

GROUPS = {
    "structure": {"structure"},
    "code": {"syntax", "imports", "json", "lint", "format", "security", "audit", "sync", "fetch"},
    "tests": {"tests"},
    "readme": {"readme"},
    "version": {"version"},
}

CHECK_PRESENTATION = {
    "structure": ("🧱", "Structure"),
    "syntax": ("🐍", "Syntax"),
    "imports": ("📦", "Imports"),
    "json": ("📄", "JSON"),
    "lint": ("🔍", "Lint"),
    "format": ("🎨", "Format"),
    "security": ("🔒", "Security"),
    "audit": ("🛡️", "Dependency audit"),
    "sync": ("🔗", "Config-code sync"),
    "fetch": ("🔄", "Fetch patterns"),
    "tests": ("🧪", "Unit tests"),
    "readme": ("📝", "README"),
    "version": ("🏷️", "Version"),
}

STATUS_PRESENTATION = {
    "passed": ("✅", "Passed"),
    "warning": ("⚠️", "Passed with warnings"),
    "failed": ("❌", "Failed"),
    "error": ("🛑", "Error"),
    "skipped": ("⏭️", "Skipped"),
}

ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


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
    icon = _group_status_text(results).split(" ", 1)[0]
    body = _section_body(results)
    return f"<details><summary><strong>{icon} {label}</strong></summary>\n\n<br>\n\n{body}\n\n</details>\n\n<br>\n"


def _section_body(results: list[CheckResult]) -> str:
    if not results:
        return "_Skipped._"

    grouped: dict[str, list[CheckResult]] = defaultdict(list)
    for result in results:
        grouped[result.integration].append(result)

    sections = []
    show_integration_heading = len(grouped) > 1
    for integration, integration_results in grouped.items():
        lines = []
        if show_integration_heading:
            lines.append(f"#### `{integration}`")
        heading = "#####" if show_integration_heading else "####"
        lines.extend(
            [
                f"{heading} Results",
                "",
                "| Check | Result | Summary |",
                "|:------|:-------|:--------|",
                *[_result_row(result) for result in integration_results],
            ]
        )

        notices = [result for result in integration_results if result.messages]
        if notices:
            lines.append(f"\n{heading} Notices")
            lines.extend(_result_notices(result) for result in notices)

        logs = [result for result in integration_results if _result_log_output(result)]
        if logs:
            lines.append(f"\n{heading} Logs")
            lines.extend(_result_log(result) for result in logs)
        sections.append("\n".join(lines))

    return "\n\n".join(sections)


def _result_row(result: CheckResult) -> str:
    check_icon, check_label = _check_presentation(result.check)
    status_icon, status_label = STATUS_PRESENTATION[result.status]
    summary = _result_summary(result)
    return f"| {check_icon} {check_label} | {status_icon} {status_label} | {summary} |"


def _result_summary(result: CheckResult) -> str:
    details = []
    if result.check == "tests":
        passed = re.search(r"(\d+) passed", result.raw_output)
        coverage = re.search(r"^TOTAL\s+\d+\s+\d+\s+(\d+%)", result.raw_output, re.MULTILINE)
        if passed:
            details.append(f"{passed.group(1)} tests")
        if coverage:
            details.append(f"{coverage.group(1)} coverage")
    elif result.check == "format":
        formatted = re.search(r"(\d+) files? already formatted", result.raw_output)
        if formatted:
            details.append(f"{formatted.group(1)} files formatted")
    elif result.check == "audit" and "No known vulnerabilities found" in result.raw_output:
        details.append("No known vulnerabilities")

    if result.duration_s:
        details.append(f"{result.duration_s:.2f}s")
    return " · ".join(details) or "—"


def _result_log(result: CheckResult) -> str:
    check_icon, check_label = _check_presentation(result.check)
    expanded = " open" if result.status in {"failed", "error"} else ""
    output = ANSI_ESCAPE.sub("", _result_log_output(result))
    fence = "````" if "```" in output else "```"
    return (
        f"<details{expanded}><summary>📋 {check_icon} {check_label} log</summary>\n\n"
        f"{fence}text\n{output}\n{fence}\n\n"
        "</details>"
    )


def _result_log_output(result: CheckResult) -> str:
    if result.status != "warning" or not result.messages:
        return result.raw_output
    message_texts = {message.message.strip() for message in result.messages}
    return "\n".join(line for line in result.raw_output.splitlines() if line.strip() not in message_texts).strip()


def _result_notices(result: CheckResult) -> str:
    check_icon, check_label = _check_presentation(result.check)
    has_errors = any(message.severity == "error" for message in result.messages)
    status_icon = "❌" if has_errors else "⚠️"
    expanded = " open" if has_errors else ""
    count = len(result.messages)
    noun = "notice" if count == 1 else "notices"
    lines = [f"<details{expanded}><summary>{status_icon} {check_icon} {check_label} — {count} {noun}</summary>", ""]
    for message in result.messages:
        severity_icon = "❌" if message.severity == "error" else "⚠️" if message.severity == "warning" else "ℹ️"
        location = _message_location(message.file, message.line)
        message_text = re.sub(r"^(?:⚠️|❌|ℹ️)\s*", "", message.message)
        lines.append(f"- {severity_icon} {location}{message_text}")
        if message.fix_hint:
            lines.append(f"  - **Suggested fix:** `{message.fix_hint}`")
    lines.extend(["", "</details>"])
    return "\n".join(lines)


def _check_presentation(check: str) -> tuple[str, str]:
    return CHECK_PRESENTATION.get(check, ("🔧", check.replace("_", " ").title()))


def _message_location(file: str | None, line: int | None) -> str:
    if not file:
        return ""
    location = file
    if line:
        location += f":{line}"
    return f"`{location}` — "
