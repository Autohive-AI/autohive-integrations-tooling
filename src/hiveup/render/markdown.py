"""Markdown rendering for CI validation reports."""

from __future__ import annotations

import re
from collections.abc import Iterable

from hiveup.core.results import CheckMessage, CheckResult, ValidationReport

GROUPS = {
    "structure": {"structure"},
    "code": {"syntax", "imports", "json", "lint", "format", "security", "audit", "sync", "fetch"},
    "tests": {"tests"},
    "readme": {"readme"},
    "version": {"version"},
}

CODE_CHECKS = {
    "syntax": ("🐍", "Checking Python syntax", "Syntax"),
    "imports": ("📥", "Checking imports", "Imports"),
    "json": ("📄", "Checking JSON files", "JSON files"),
    "lint": ("🔍", "Linting with ruff", "Lint"),
    "format": ("🎨", "Checking formatting with ruff", "Formatting"),
    "security": ("🔒", "Scanning for security issues with bandit", "Security"),
    "audit": ("🛡️", "Checking dependencies for vulnerabilities with pip-audit", "Dependencies"),
    "sync": ("🔗", "Checking config-code sync", "Config-code sync"),
    "fetch": ("🔄", "Checking fetch patterns", "Fetch patterns"),
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
        sections.append(_section(label, group, results))

    if run_errors:
        sections.insert(0, _section("Run", "run", run_errors))

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


def _section(label: str, group: str, results: list[CheckResult]) -> str:
    icon = _group_status_text(results).split(" ", 1)[0]
    body = _section_output(group, results)
    fence = "````" if "```" in body else "```"
    return f"<details><summary>{icon} {label} Check output</summary>\n\n{fence}text\n{body}\n{fence}\n\n</details>\n"


def _section_output(group: str, results: list[CheckResult]) -> str:
    if not results:
        return "Skipped."
    if group == "structure":
        return _structure_output(results)
    if group == "code":
        return _code_output(results)
    if group == "tests":
        return _tests_output(results)
    if group in {"readme", "version"}:
        return _legacy_output(results)
    return _generic_output(results)


def _structure_output(results: list[CheckResult]) -> str:
    lines = [f"Validating {len(results)} integration(s)..."]
    total_errors = 0
    total_warnings = 0
    for result in results:
        errors = [message for message in result.messages if message.severity == "error"]
        warnings = [message for message in result.messages if message.severity == "warning"]
        total_errors += len(errors)
        total_warnings += len(warnings)
        lines.extend(["", "=" * 60, f"Integration: {result.integration}", "=" * 60])
        if errors:
            lines.extend(["", f"Errors ({len(errors)}):", *[f"  ❌ {_message_text(message)}" for message in errors]])
        if warnings:
            lines.extend(
                ["", f"Warnings ({len(warnings)}):", *[f"  ⚠️ {_message_text(message)}" for message in warnings]]
            )
        if not errors and not warnings:
            lines.extend(["", "✅ Structure valid"])

    lines.extend(
        [
            "",
            "=" * 60,
            "SUMMARY",
            "=" * 60,
            f"Integrations validated: {len(results)}",
            f"Total errors: {total_errors}",
            f"Total warnings: {total_warnings}",
            "",
        ]
    )
    if total_errors:
        lines.append("❌ Validation FAILED - please fix errors before submitting PR")
    elif total_warnings:
        lines.append("⚠️ Validation passed with warnings - please review")
    else:
        lines.append("✅ All validations passed!")
    return "\n".join(lines)


def _code_output(results: list[CheckResult]) -> str:
    integrations: dict[str, list[CheckResult]] = {}
    for result in results:
        integrations.setdefault(result.integration, []).append(result)

    sections = []
    for integration, integration_results in integrations.items():
        lines = ["-" * 40, f"Checking: {integration}", "-" * 40]
        for result in integration_results:
            icon, action, success_label = CODE_CHECKS.get(
                result.check,
                ("🔧", f"Checking {result.check.replace('_', ' ')}", result.check.replace("_", " ").title()),
            )
            lines.extend(["", f"{icon} {action}..."])
            for message in result.messages:
                message_icon = "❌" if message.severity == "error" else "⚠️" if message.severity == "warning" else "ℹ️"
                lines.append(f"   {message_icon} {_message_text(message)}")
                if message.fix_hint:
                    lines.append(f"      Fix: {message.fix_hint}")
            if result.status == "skipped":
                lines.append(f"   ⏭️ {success_label} skipped")
            elif result.status in {"failed", "error"}:
                lines.append(f"   ❌ {success_label} failed")
                output = _raw_output_without_messages(result)
                if output:
                    lines.extend(f"      {line}" for line in output.splitlines())
            else:
                lines.append(f"   ✅ {success_label} OK")

        lines.extend(["", "=" * 40])
        if any(result.status in {"failed", "error"} for result in integration_results):
            lines.append("❌ CODE CHECK FAILED")
        else:
            lines.append("✅ CODE CHECK PASSED")
        lines.append("=" * 40)
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def _tests_output(results: list[CheckResult]) -> str:
    rows = []
    failure_outputs = []
    notices = []
    for result in results:
        passed = _count(r"(\d+) passed", result.raw_output)
        failed = _count(r"(\d+) failed", result.raw_output)
        coverage = _match(r"^TOTAL\s+\d+\s+\d+\s+(\d+%)", result.raw_output, re.MULTILINE) or "n/a"
        total = passed + failed
        tests = f"{passed}/{total}" if total else "n/a"
        status = {
            "passed": "✅ Passed",
            "warning": "⚠️ Warning",
            "failed": "❌ Failed",
            "error": "💥 Error",
            "skipped": "⏭️ Skipped",
        }[result.status]
        rows.append((result.integration, tests, coverage, status))
        notices.extend(f"{_message_line(message)} ({result.integration})" for message in result.messages)
        if result.status in {"failed", "error"} and result.raw_output:
            failure_outputs.extend(
                ["", "=" * 60, f"{result.integration} — failure detail", "=" * 60, result.raw_output]
            )

    headers = ("Integration", "Tests", "Coverage", "Status")
    total_passed = sum(_count(r"(\d+) passed", result.raw_output) for result in results)
    total_failed = sum(_count(r"(\d+) failed", result.raw_output) for result in results)
    total_tests = total_passed + total_failed
    total_status = (
        "✅ All passed" if not any(result.status in {"failed", "error"} for result in results) else "❌ Some failed"
    )
    total_tests_text = f"{total_passed}/{total_tests}" if total_tests else "n/a"
    total_row = ("Total", total_tests_text, "", total_status)
    widths = [len(header) for header in headers]
    for row in [*rows, total_row]:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))

    def table_line(values: tuple[str, ...]) -> str:
        return (
            f"{values[0]:<{widths[0] + 2}}"
            f"{values[1]:>{widths[1] + 2}}"
            f"{values[2]:>{widths[2] + 2}}"
            f"{values[3]:>{widths[3] + 2}}"
        )

    lines = [table_line(headers)]
    divider = "-" * len(lines[0])
    lines.extend([divider, *[table_line(row) for row in rows], divider])
    lines.append(table_line(total_row))
    if notices:
        lines.extend(["", *notices])
    lines.extend(failure_outputs)
    outcome = "✅ Tests passed" if total_status.startswith("✅") else "❌ Tests failed"
    integrations = ", ".join(result.integration for result in results)
    lines.extend(["", f"{outcome}: {integrations}"])
    return "\n".join(lines)


def _legacy_output(results: list[CheckResult]) -> str:
    sections = []
    for result in results:
        if result.raw_output:
            sections.append(ANSI_ESCAPE.sub("", result.raw_output))
        elif result.messages:
            sections.append("\n".join(_message_line(message) for message in result.messages))
        elif result.status == "skipped":
            sections.append("Skipped.")
    return "\n\n".join(sections) or "Passed."


def _generic_output(results: list[CheckResult]) -> str:
    lines = []
    for result in results:
        lines.append(f"[{result.integration}] {result.check}: {result.status}")
        lines.extend(f"  {_message_line(message)}" for message in result.messages)
        output = _raw_output_without_messages(result)
        if output:
            lines.append(output)
    return "\n".join(lines)


def _raw_output_without_messages(result: CheckResult) -> str:
    message_texts = {message.message.strip() for message in result.messages}
    return "\n".join(
        line for line in ANSI_ESCAPE.sub("", result.raw_output).splitlines() if line.strip() not in message_texts
    ).strip()


def _message_line(message: CheckMessage) -> str:
    icon = "❌" if message.severity == "error" else "⚠️" if message.severity == "warning" else "ℹ️"
    return f"{icon} {_message_text(message)}"


def _message_text(message: CheckMessage) -> str:
    text = re.sub(r"^(?:⚠️|❌|ℹ️)\s*", "", message.message)
    if not message.file:
        return text
    location = message.file + (f":{message.line}" if message.line else "")
    return f"{location}: {text}"


def _count(pattern: str, value: str) -> int:
    match = re.search(pattern, value)
    return int(match.group(1)) if match else 0


def _match(pattern: str, value: str, flags: int = 0) -> str | None:
    match = re.search(pattern, value, flags)
    return match.group(1) if match else None
