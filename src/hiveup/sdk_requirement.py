"""Validate the minimum Autohive Integrations SDK requirement."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


MINIMUM_SDK_VERSION = (1, 0, 2)
MINIMUM_SDK_VERSION_TEXT = ".".join(str(part) for part in MINIMUM_SDK_VERSION)
_SDK_REQUIREMENT = re.compile(
    r"^[ \t]*autohive[-_.]+integrations[-_.]+sdk(?:\[[^\]]+\])?[ \t]*"
    r"(?P<specifiers>[^;#\r\n]*)(?P<marker>;[^#\r\n]*)?(?:#[^\r\n]*)?\r?$",
    re.IGNORECASE | re.MULTILINE,
)
_LOWER_BOUND = re.compile(r"(?P<operator>===|==|~=|>=|>)\s*(?P<version>\d+(?:\.\d+){1,2})(?P<suffix>[^,\s;#]*)")


class SdkRequirementError(ValueError):
    """Raised when requirements.txt does not guarantee the supported SDK floor."""


@dataclass(frozen=True)
class SdkRequirement:
    operator: str
    version_text: str
    version: tuple[int, int, int]


def read_sdk_requirement(requirements_path: Path) -> SdkRequirement:
    """Return the strongest declared SDK lower bound or raise a useful error."""

    try:
        content = requirements_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SdkRequirementError(f"Could not read requirements.txt: {exc}") from exc

    requirements = list(_SDK_REQUIREMENT.finditer(content))
    if not requirements:
        raise SdkRequirementError(
            f"requirements.txt must include autohive-integrations-sdk>={MINIMUM_SDK_VERSION_TEXT}"
        )

    resolved: list[SdkRequirement] = []
    for requirement in requirements:
        if requirement.group("marker"):
            raise SdkRequirementError(
                "autohive-integrations-sdk must not use an environment marker because every deployment "
                f"must guarantee version {MINIMUM_SDK_VERSION_TEXT} or later"
            )

        bounds: list[SdkRequirement] = []
        for match in _LOWER_BOUND.finditer(requirement.group("specifiers")):
            if match.group("suffix"):
                continue
            version_text = match.group("version")
            bounds.append(
                SdkRequirement(
                    operator=match.group("operator"),
                    version_text=version_text,
                    version=_version_tuple(version_text),
                )
            )
        if not bounds:
            raise SdkRequirementError(
                "requirements.txt must declare a stable minimum version for "
                f"autohive-integrations-sdk, for example >={MINIMUM_SDK_VERSION_TEXT}"
            )

        strongest = max(bounds, key=lambda bound: bound.version)
        if strongest.version < MINIMUM_SDK_VERSION:
            raise SdkRequirementError(
                f"autohive-integrations-sdk{strongest.operator}{strongest.version_text} allows an SDK below "
                f"the required minimum {MINIMUM_SDK_VERSION_TEXT}"
            )
        resolved.append(strongest)

    return min(resolved, key=lambda bound: bound.version)


def _version_tuple(version: str) -> tuple[int, int, int]:
    parts = [int(part) for part in version.split(".")]
    parts.extend([0] * (3 - len(parts)))
    return tuple(parts[:3])
