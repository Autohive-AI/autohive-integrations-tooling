"""Validate the minimum Autohive Integrations SDK requirement."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version


MINIMUM_SDK_VERSION = (1, 0, 2)
MINIMUM_SDK_VERSION_TEXT = ".".join(str(part) for part in MINIMUM_SDK_VERSION)

_SDK_NAME = canonicalize_name("autohive-integrations-sdk")
# Finds a line that names the SDK, so that a line packaging cannot parse is reported instead of ignored.
_SDK_NAME_AT_START = re.compile(r"^autohive[-_.]+integrations[-_.]+sdk(?![-_.]?[a-z0-9])", re.IGNORECASE)
# The same comment rule as pip: a "#" at the start of a line or after whitespace starts a comment.
_COMMENT = re.compile(r"(^|\s+)#.*$")
_LOWER_BOUND_OPERATORS = ("===", "==", "~=", ">=", ">")
_EXACT_OPERATORS = ("==", "===")

# A later major SDK version can change behavior that an integration depends on, so every SDK
# requirement must include a ~= or == pin. The pin keeps the major version fixed, and other
# specifiers next to it can only narrow the range further.
_PIN_OPERATORS = ("~=", "==", "===")


class SdkRequirementError(ValueError):
    """Raised when requirements.txt does not declare a supported SDK version range."""


@dataclass(frozen=True)
class SdkRequirement:
    operator: str
    version_text: str
    version: tuple[int, int, int]
    # The first exact pin (== or ===) in any SDK requirement, for example "==2.0.1".
    exact_pin: str | None = None


def read_sdk_requirement(requirements_path: Path) -> SdkRequirement:
    """Return the strongest declared SDK lower bound or raise a useful error."""

    try:
        content = requirements_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SdkRequirementError(f"Could not read requirements.txt: {exc}") from exc

    requirements = list(_sdk_requirements(content))
    if not requirements:
        raise SdkRequirementError(
            f"requirements.txt must include autohive-integrations-sdk~={MINIMUM_SDK_VERSION_TEXT} or later"
        )

    resolved: list[SdkRequirement] = []
    exact_pin: str | None = None
    for requirement in requirements:
        if requirement.marker is not None:
            raise SdkRequirementError(
                "autohive-integrations-sdk must not use an environment marker because every deployment "
                f"must guarantee version {MINIMUM_SDK_VERSION_TEXT} or later"
            )

        bounds: list[SdkRequirement] = []
        for specifier in requirement.specifier:
            if specifier.operator not in _LOWER_BOUND_OPERATORS:
                continue
            version = _stable_version(specifier.version)
            if version is None:
                continue
            bounds.append(
                SdkRequirement(
                    operator=specifier.operator,
                    version_text=specifier.version,
                    version=_version_tuple(version),
                )
            )
        if not bounds:
            raise SdkRequirementError(
                "requirements.txt must declare a stable minimum version for "
                f"autohive-integrations-sdk, for example ~={MINIMUM_SDK_VERSION_TEXT}"
            )

        strongest = max(bounds, key=lambda bound: bound.version)
        if strongest.version < MINIMUM_SDK_VERSION:
            raise SdkRequirementError(
                f"autohive-integrations-sdk{strongest.operator}{strongest.version_text} allows an SDK below "
                f"the required minimum {MINIMUM_SDK_VERSION_TEXT}"
            )

        if not any(bound.operator in _PIN_OPERATORS for bound in bounds):
            raise SdkRequirementError(
                f"autohive-integrations-sdk{strongest.operator}{strongest.version_text} can install a later major "
                f"version of the SDK. Pin the SDK with ~={strongest.version_text} so the major version stays fixed"
            )

        exact = next((bound for bound in bounds if bound.operator in _EXACT_OPERATORS), None)
        if exact_pin is None and exact is not None:
            exact_pin = f"{exact.operator}{exact.version_text}"
        resolved.append(strongest)

    return replace(min(resolved, key=lambda bound: bound.version), exact_pin=exact_pin)


def _sdk_requirements(content: str):
    """Yield each SDK requirement in requirements.txt, read the way pip reads the file."""

    for line in _logical_lines(content):
        line = _COMMENT.sub("", line).strip()
        if not line or line.startswith("-"):
            continue

        # pip treats everything from the first token that starts with "-" as options for this
        # requirement, for example --hash or --config-settings. They are not version specifiers.
        requirement_text = _without_requirement_options(line)
        try:
            requirement = Requirement(requirement_text)
        except InvalidRequirement as exc:
            if _SDK_NAME_AT_START.match(requirement_text):
                raise SdkRequirementError(
                    f"Could not parse the autohive-integrations-sdk requirement '{requirement_text}': {exc}"
                ) from exc
            continue

        if canonicalize_name(requirement.name) == _SDK_NAME:
            yield requirement


def _logical_lines(content: str):
    """Join lines that end in a backslash with the next line, as pip does."""

    pending: list[str] = []
    for line in content.splitlines():
        if line.endswith("\\") and not _COMMENT.match(line):
            pending.append(line[:-1])
            continue
        if _COMMENT.match(line):
            # A comment line ends a continued requirement and is removed later.
            line = " " + line
        pending.append(line)
        yield "".join(pending)
        pending = []
    if pending:
        yield "".join(pending)


def _without_requirement_options(line: str) -> str:
    """Return the requirement part of a line, without the options after it (the same split as pip)."""

    requirement_tokens: list[str] = []
    for token in line.split(" "):
        if token.startswith("-"):
            break
        requirement_tokens.append(token)
    return " ".join(requirement_tokens).strip()


def _stable_version(version_text: str) -> Version | None:
    """Return the version when it is a stable release, so a pre-release cannot count as the minimum."""

    try:
        version = Version(version_text)
    except InvalidVersion:
        return None
    if version.is_prerelease or version.is_postrelease or version.is_devrelease or version.local:
        return None
    return version


def _version_tuple(version: Version) -> tuple[int, int, int]:
    parts = list(version.release[:3])
    parts.extend([0] * (3 - len(parts)))
    return tuple(parts)
