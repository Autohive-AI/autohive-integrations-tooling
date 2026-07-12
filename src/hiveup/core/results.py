"""Structured validation result models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

Severity = Literal["error", "warning", "info"]
Status = Literal["passed", "warning", "failed", "error", "skipped"]


@dataclass
class CheckMessage:
    severity: Severity
    message: str
    file: str | None = None
    line: int | None = None
    fix_hint: str | None = None


@dataclass
class CheckResult:
    check: str
    integration: str
    status: Status
    messages: list[CheckMessage] = field(default_factory=list)
    duration_s: float = 0.0
    raw_output: str = ""


@dataclass
class ValidationReport:
    results: list[CheckResult]

    def has_failures(self) -> bool:
        return any(result.status in {"failed", "error"} for result in self.results)

    def exit_code(self) -> int:
        if any(result.status == "error" for result in self.results):
            return 2
        if any(result.status == "failed" for result in self.results):
            return 1
        return 0

    def to_dict(self) -> dict:
        return {"results": [asdict(result) for result in self.results], "exit_code": self.exit_code()}

    def by_integration(self) -> dict[str, list[CheckResult]]:
        grouped: dict[str, list[CheckResult]] = {}
        for result in self.results:
            grouped.setdefault(result.integration, []).append(result)
        return grouped
