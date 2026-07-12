"""Human-readable validation output."""

from __future__ import annotations

from hiveup.core.results import CheckResult, ValidationReport

STATUS_ICON = {
    "passed": "✅",
    "warning": "⚠️",
    "failed": "❌",
    "error": "💥",
    "skipped": "⏭️",
}


def render_report(report: ValidationReport) -> None:
    if not report.results:
        print("No integrations to validate.")
        return

    print("\nValidation summary")
    print("=" * 80)
    _render_table(report.results)

    details = [result for result in report.results if result.messages]
    if details:
        print("\nDetails")
        print("=" * 80)
        for result in details:
            _render_result_details(result)

    print("\nResult")
    print("=" * 80)
    if report.exit_code() == 0:
        if any(result.status == "warning" for result in report.results):
            print("⚠️ Validation passed with warnings")
        else:
            print("✅ Validation passed")
    elif report.exit_code() == 1:
        print("❌ Validation failed")
    else:
        print("💥 Validation could not complete")


def _render_table(results: list[CheckResult]) -> None:
    rows = [
        (
            result.integration,
            result.check,
            f"{STATUS_ICON[result.status]} {result.status}",
            f"{result.duration_s:.2f}s",
        )
        for result in results
    ]
    headers = ("Integration", "Check", "Status", "Time")
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))

    def line(values: tuple[str, ...]) -> str:
        return "  ".join(value.ljust(widths[index]) for index, value in enumerate(values))

    print(line(headers))
    print(line(tuple("-" * width for width in widths)))
    for row in rows:
        print(line(row))


def _render_result_details(result: CheckResult) -> None:
    print(f"\n{STATUS_ICON[result.status]} {result.integration} / {result.check}")
    for message in result.messages:
        prefix = "❌" if message.severity == "error" else "⚠️" if message.severity == "warning" else "ℹ️"
        location = ""
        if message.file:
            location = message.file
            if message.line:
                location += f":{message.line}"
            location += ": "
        print(f"  {prefix} {location}{message.message}")
        if message.fix_hint:
            print(f"     Fix: {message.fix_hint}")
