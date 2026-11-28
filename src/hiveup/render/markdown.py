"""Markdown rendering for CI validation reports."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from hiveup.checks.tests import format_test_table, parse_results
from hiveup.core.results import CheckMessage, CheckResult, ValidationReport
from hiveup.render.text import ANSI_ESCAPE, bandit_warnings, normalized_path, raw_output_without_messages

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


@dataclass
class _WarningSummary:
    category: str
    message: str
    source: str
    occurrences: int = 0
    tests: list[str] = field(default_factory=list)


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
    fence = "`" * max(3, 1 + max(map(len, re.findall(r"`+", body)), default=0))
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
                output = raw_output_without_messages(result)
                if output:
                    lines.extend(f"      {line}" for line in output.splitlines())
            else:
                lines.append(f"   ✅ {success_label} OK")
                warnings = bandit_warnings(result) if result.check == "security" else []
                if warnings:
                    lines.append("   Warnings:")
                    lines.extend(f"     ⚠️ {warning}" for warning in warnings)
                if result.status == "warning" and not result.messages:
                    output = raw_output_without_messages(result)
                    if output:
                        lines.extend(f"      {line}" for line in output.splitlines())

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
    warning_sections = []
    for result in results:
        raw_output = ANSI_ESCAPE.sub("", result.raw_output)
        passed, failed, coverage = parse_results(raw_output)
        total = passed + failed
        tests = f"{passed}/{total}" if total else "n/a"
        status = {
            "passed": "✅ Passed",
            "warning": "⚠️ Warning",
            "failed": "❌ Failed",
            "error": "💥 Error",
            "skipped": "⏭️ Skipped",
        }[result.status]
        rows.append((result.integration, tests, coverage, status, result.status))
        notices.extend(f"{_message_line(message)} ({result.integration})" for message in result.messages)
        warnings = [] if result.status in {"failed", "error"} else _pytest_warnings(raw_output, result.integration)
        if warnings:
            warning_sections.append(_pytest_warning_output(result.integration, warnings))
        if result.status in {"failed", "error"} and raw_output:
            failure_outputs.extend(["", "=" * 60, f"{result.integration} — failure detail", "=" * 60, raw_output])

    lines = [format_test_table(rows)]
    if notices:
        lines.extend(["", *notices])
    if warning_sections:
        lines.extend(["", "Warnings:", *warning_sections])
    lines.extend(failure_outputs)
    failures = [result for result in results if result.status in {"failed", "error"}]
    outcome = "❌ Tests failed" if failures else "✅ Tests passed"
    outcome_results = failures or results
    integrations = ", ".join(result.integration for result in outcome_results)
    lines.extend(["", f"{outcome}: {integrations}"])
    return "\n".join(lines)


def _legacy_output(results: list[CheckResult]) -> str:
    sections = []
    multiple = len({result.integration for result in results}) > 1
    for result in results:
        if result.raw_output:
            body = ANSI_ESCAPE.sub("", result.raw_output)
        elif result.messages:
            body = "\n".join(_message_line(message) for message in result.messages)
        else:
            body = f"{result.status.title()}."
        sections.append(f"Integration: {result.integration}\n{body}" if multiple else body)
    return "\n\n".join(sections) or "Passed."


def _generic_output(results: list[CheckResult]) -> str:
    lines = []
    for result in results:
        lines.append(f"[{result.integration}] {result.check}: {result.status}")
        lines.extend(f"  {_message_line(message)}" for message in result.messages)
        output = raw_output_without_messages(result)
        if output:
            lines.append(output)
    return "\n".join(lines)


def _pytest_warnings(output: str, integration: str) -> list[_WarningSummary]:
    lines = ANSI_ESCAPE.sub("", output).splitlines()
    source_pattern = re.compile(r"^\s+(.+?):(\d+): ([A-Za-z_][\w.]*Warning): (.+)$")
    grouped: dict[tuple[str, str, str], _WarningSummary] = {}
    affected_tests: list[str] = []
    in_summary = False
    for line in lines:
        if re.match(r"^=+ warnings summary(?: \(final\))? =+$", line):
            in_summary = True
            affected_tests = []
            continue
        if not in_summary:
            continue
        if line.startswith("-- Docs:") or re.match(r"^=+ .+ =+$", line):
            in_summary = False
            affected_tests = []
            continue
        if not line.strip():
            affected_tests = []
            continue
        source_match = source_pattern.match(line)
        if source_match:
            source = f"{normalized_path(source_match.group(1), integration)}:{source_match.group(2)}"
            category = source_match.group(3)
            message = source_match.group(4).strip()
            key = (category, message, f"{source_match.group(1)}:{source_match.group(2)}")
            warning = grouped.setdefault(key, _WarningSummary(category, message, source))
            warning.occurrences += max(len(affected_tests), 1)
            for test in affected_tests:
                if test not in warning.tests:
                    warning.tests.append(test)
        elif line and not line[0].isspace():
            affected_tests.append(line.strip())
    return list(grouped.values())


def _pytest_warning_output(integration: str, warnings: list[_WarningSummary]) -> str:
    lines = [f"  {integration}:"]
    for warning in warnings:
        noun = "occurrence" if warning.occurrences == 1 else "occurrences"
        lines.extend(
            [
                f"    ⚠️ {warning.category} — {warning.occurrences} {noun}",
                f"       {warning.message}",
                f"       Source: {warning.source}",
            ]
        )
        if warning.tests and len(warning.tests) <= 2:
            lines.append("       Affected tests:")
            lines.extend(f"         - {test}" for test in warning.tests)
        elif warning.tests:
            lines.append(f"       Affected tests: {len(warning.tests)}")
    return "\n".join(lines)


def _message_line(message: CheckMessage) -> str:
    icon = "❌" if message.severity == "error" else "⚠️" if message.severity == "warning" else "ℹ️"
    return f"{icon} {_message_text(message)}"


def _message_text(message: CheckMessage) -> str:
    text = re.sub(r"^(?:⚠️|❌|ℹ️)\s*", "", ANSI_ESCAPE.sub("", message.message).strip())
    if not message.file:
        return text
    location = message.file + (f":{message.line}" if message.line else "")
    return f"{location}: {text}"
