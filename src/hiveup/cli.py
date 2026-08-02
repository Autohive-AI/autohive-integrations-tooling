"""Command-line entry point for hiveup."""

from __future__ import annotations

import json
import keyword
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path
from typing import Annotated

import typer

from hiveup import __version__
from hiveup.checks.static import available_checks
from hiveup.checks.structure import (
    ENTRY_POINT_IDENTIFIER_MESSAGE,
    RESERVED_ENTRY_POINT_MESSAGE,
    ROOT_ENTRY_POINT_MESSAGE,
    has_valid_entry_point_identifier,
    is_reserved_entry_point,
    is_root_python_entry_point,
)
from hiveup.core.discovery import changed_integrations, discover_integrations, explicit_integrations
from hiveup.core.results import CheckMessage, CheckResult, ValidationReport
from hiveup.packaging import PackageBuildError, build_package
from hiveup.render.console import render_report
from hiveup.render.markdown import GROUPS, render_markdown

app = typer.Typer(help="Developer CLI for Autohive integrations.", no_args_is_help=True)

AUTH_TYPES = {"platform", "custom", "none"}
PACKAGE_FILENAME_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"hiveup {__version__}")
        raise typer.Exit()


@app.callback()
def callback(
    version: Annotated[
        bool,
        typer.Option("--version", help="Show the hiveup version and exit.", callback=_version_callback),
    ] = False,
) -> None:
    _ = version


@app.command()
def validate(
    dirs: Annotated[list[Path] | None, typer.Argument(help="Integration directories to validate.")] = None,
    changed: Annotated[bool, typer.Option("--changed", help="Validate integrations changed since --base-ref.")] = False,
    base_ref: Annotated[
        str | None,
        typer.Option("--base-ref", help="Git ref used by --changed and version-aware checks."),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON.")] = False,
    skip: Annotated[str | None, typer.Option("--skip", help="Comma-separated checks to skip.")] = None,
    only: Annotated[str | None, typer.Option("--only", help="Comma-separated checks to run.")] = None,
    fix: Annotated[bool, typer.Option("--fix", help="Apply auto-fixes for supported checks.")] = False,
) -> None:
    """Run static validation checks for one or more integrations."""

    report = run_validation(
        dirs or [],
        changed=changed,
        base_ref=base_ref,
        skip=_csv(skip),
        only=_csv(only),
        fix=fix,
    )
    if json_output:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        render_report(report)
    raise typer.Exit(report.exit_code())


@app.command()
def check(
    name: Annotated[str, typer.Argument(help="Check name to run.")],
    dirs: Annotated[list[Path] | None, typer.Argument(help="Integration directories to check.")] = None,
    base_ref: Annotated[
        str | None,
        typer.Option("--base-ref", help="Git ref for checks that need repository history."),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON.")] = False,
    fix: Annotated[bool, typer.Option("--fix", help="Apply auto-fixes when supported by this check.")] = False,
) -> None:
    """Run a single named validation check."""

    report = run_validation(dirs or [], base_ref=base_ref, only={name}, fix=fix)
    if json_output:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        render_report(report)
    raise typer.Exit(report.exit_code())


@app.command()
def test(
    dirs: Annotated[list[Path] | None, typer.Argument(help="Integration directories to test.")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON.")] = False,
) -> None:
    """Run unit tests for one or more integrations."""

    report = run_validation(dirs or [], only={"tests"})
    if json_output:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        render_report(report)
    raise typer.Exit(report.exit_code())


@app.command()
def ci(
    dirs: Annotated[list[Path] | None, typer.Argument(help="Integration directories to validate.")] = None,
    base_ref: Annotated[
        str | None,
        typer.Option("--base-ref", help="Git ref used to detect changed integrations."),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Emit machine-readable JSON.")] = False,
    github_annotations: Annotated[bool, typer.Option("--github-annotations", help="Emit GitHub annotations.")] = False,
    comment_file: Annotated[Path | None, typer.Option("--comment-file", help="Write PR-comment markdown.")] = None,
    output_file: Annotated[Path | None, typer.Option("--output-file", help="Append GitHub Action outputs.")] = None,
    commit: Annotated[str | None, typer.Option("--commit", help="Commit SHA to identify in CI output.")] = None,
) -> None:
    """Run the CI validation profile."""

    report = run_validation(
        dirs or [],
        changed=not bool(dirs),
        base_ref=base_ref,
    )
    dirs_output = _report_dirs(report)
    written_comment_file = None
    if github_annotations:
        _emit_github_annotations(report)
    if comment_file and report.results:
        comment_file.write_text(
            render_markdown(
                report,
                commit=commit or os.environ.get("GITHUB_SHA", ""),
                commit_msg=_git_commit_subject(commit or "HEAD"),
                dirs=dirs_output,
            ),
            encoding="utf-8",
        )
        written_comment_file = comment_file
    if output_file:
        _write_github_outputs(output_file, report, comment_file=written_comment_file, dirs=dirs_output)
    if json_output:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        render_report(report)
    raise typer.Exit(report.exit_code())


@app.command()
def create(
    name: Annotated[str, typer.Argument(help="Integration name to create.")],
    auth_type: Annotated[str, typer.Option("--auth-type", help="platform, custom, or none.")] = "none",
    auth_provider: Annotated[str | None, typer.Option("--auth-provider", help="Platform auth provider.")] = None,
    auth_scopes: Annotated[str | None, typer.Option("--auth-scopes", help="Comma-separated platform scopes.")] = None,
    force: Annotated[bool, typer.Option("--force", help="Overwrite existing files.")] = False,
) -> None:
    """Scaffold a new integration in a child directory."""

    target = Path(_slugify(name))
    created, replaced = _scaffold(
        target,
        display_name=_display_name(name),
        auth_type=auth_type,
        auth_provider=auth_provider,
        auth_scopes=auth_scopes,
        force=force,
    )
    typer.echo(f"✅ Created {target}")
    typer.echo(f"Files: {created} created, {replaced} replaced")
    typer.echo(f"Next: cd {target} && hiveup validate && hiveup test")


@app.command()
def init(
    name: Annotated[str | None, typer.Option("--name", help="Integration name. Defaults to cwd name.")] = None,
    auth_type: Annotated[str, typer.Option("--auth-type", help="platform, custom, or none.")] = "none",
    auth_provider: Annotated[str | None, typer.Option("--auth-provider", help="Platform auth provider.")] = None,
    auth_scopes: Annotated[str | None, typer.Option("--auth-scopes", help="Comma-separated platform scopes.")] = None,
    force: Annotated[bool, typer.Option("--force", help="Overwrite existing files.")] = False,
) -> None:
    """Scaffold an integration in the current directory."""

    target = Path.cwd()
    created, replaced = _scaffold(
        target,
        display_name=_display_name(name or target.name),
        auth_type=auth_type,
        auth_provider=auth_provider,
        auth_scopes=auth_scopes,
        force=force,
    )
    typer.echo(f"✅ Initialized {target.name}")
    typer.echo(f"Files: {created} created, {replaced} replaced")


@app.command()
def auth(
    directory: Annotated[Path, typer.Argument(help="Integration directory to edit.")] = Path("."),
    auth_type: Annotated[str | None, typer.Option("--auth-type", help="platform, custom, or none.")] = None,
    auth_provider: Annotated[str | None, typer.Option("--auth-provider", help="Platform auth provider.")] = None,
    auth_scopes: Annotated[str | None, typer.Option("--auth-scopes", help="Comma-separated platform scopes.")] = None,
) -> None:
    """Add, update, or remove the auth block in config.json."""

    if auth_type is None:
        typer.echo("--auth-type is required; use platform, custom, or none", err=True)
        raise typer.Exit(2)

    config_path = directory / "config.json"
    if not config_path.is_file():
        typer.echo(f"config.json not found: {config_path}", err=True)
        raise typer.Exit(2)

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        typer.echo(f"Could not read config.json: {exc}", err=True)
        raise typer.Exit(2)
    if not isinstance(config, dict):
        typer.echo("config.json must contain a JSON object", err=True)
        raise typer.Exit(2)

    _apply_auth_config(config, auth_type, provider=auth_provider, scopes=auth_scopes)
    try:
        _atomic_write(config_path, (json.dumps(config, indent=2) + "\n").encode())
    except OSError as exc:
        typer.echo(f"Could not write config.json: {exc}", err=True)
        raise typer.Exit(2)
    typer.echo(f"✅ Updated {config_path}")


@app.command()
def package(
    directory: Annotated[Path, typer.Argument(help="Integration directory to package.")] = Path("."),
    output: Annotated[Path | None, typer.Option("-o", "--output", help="Output zip path.")] = None,
    skip_validate: Annotated[bool, typer.Option("--skip-validate", help="Skip validation before packaging.")] = False,
) -> None:
    """Build a deployable integration zip."""

    directory = directory.resolve()
    if not skip_validate:
        report = run_validation([directory], skip={"audit", "tests", "readme", "version"})
        if report.exit_code() != 0:
            render_report(report)
            raise typer.Exit(report.exit_code())

    config_path = directory / "config.json"
    if not config_path.is_file():
        typer.echo(f"config.json not found: {config_path}", err=True)
        raise typer.Exit(2)
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeError) as exc:
        typer.echo(f"Could not read config.json: {exc}", err=True)
        raise typer.Exit(2)
    if not isinstance(config, dict):
        typer.echo("config.json must contain a JSON object", err=True)
        raise typer.Exit(2)
    if is_reserved_entry_point(config.get("entry_point")):
        typer.echo(RESERVED_ENTRY_POINT_MESSAGE, err=True)
        raise typer.Exit(2)
    if not is_root_python_entry_point(config.get("entry_point")):
        typer.echo(ROOT_ENTRY_POINT_MESSAGE, err=True)
        raise typer.Exit(2)
    if not has_valid_entry_point_identifier(config.get("entry_point")):
        typer.echo(ENTRY_POINT_IDENTIFIER_MESSAGE, err=True)
        raise typer.Exit(2)
    try:
        package_path = output or _default_package_path(config, directory)
        build_package(directory, package_path)
    except PackageBuildError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2)

    typer.echo(f"✅ Wrote {package_path}")


def _default_package_path(config: dict, directory: Path) -> Path:
    name = config.get("name", directory.name)
    version = config.get("version", "0.0.0")
    for label, value in (("name", name), ("version", version)):
        if not isinstance(value, str) or not PACKAGE_FILENAME_COMPONENT.fullmatch(value):
            raise PackageBuildError(
                f"config.{label} must be a filename-safe value containing only letters, numbers, "
                f"'.', '_', or '-': {value!r}"
            )
    return Path.cwd() / f"{name}-{version}.zip"


@app.command()
def doctor(directory: Annotated[Path, typer.Argument(help="Directory to inspect.")] = Path(".")) -> None:
    """Print environment and integration sanity information."""

    checks = [
        ("Python", sys.version.split()[0]),
        ("git", shutil.which("git") or "missing"),
        ("uv", shutil.which("uv") or "missing"),
        ("ruff", _module_version("ruff")),
        ("bandit", _module_version("bandit")),
        ("pip-audit", _module_version("pip_audit")),
    ]
    for label, value in checks:
        typer.echo(f"{label}: {value}")
    typer.echo(f"Looks like integration: {'yes' if (directory / 'config.json').is_file() else 'no'}")


def run_validation(
    dirs: list[Path],
    *,
    changed: bool = False,
    base_ref: str | None = None,
    skip: set[str] | None = None,
    only: set[str] | None = None,
    fix: bool = False,
) -> ValidationReport:
    root = Path.cwd()
    try:
        integrations = _select_integrations(root, dirs, changed=changed, base_ref=base_ref)
    except RuntimeError as exc:
        return ValidationReport(
            [
                CheckResult(
                    check="discovery",
                    integration=str(root),
                    status="error",
                    messages=[CheckMessage("error", str(exc))],
                )
            ]
        )

    checks = available_checks(base_ref=base_ref, fix=fix)
    if only and skip:
        return ValidationReport(
            [
                CheckResult(
                    check="selection",
                    integration=str(root),
                    status="error",
                    messages=[CheckMessage("error", "--only and --skip cannot be used together")],
                )
            ]
        )
    selected_names = _select_checks(checks.keys(), skip=skip or set(), only=only)
    unknown = selected_names - set(checks)
    if unknown:
        return ValidationReport(
            [
                CheckResult(
                    check="selection",
                    integration=str(root),
                    status="error",
                    messages=[CheckMessage("error", f"Unknown check(s): {', '.join(sorted(unknown))}")],
                )
            ]
        )

    results: list[CheckResult] = []
    for integration in integrations:
        for check_name in sorted(selected_names, key=list(checks).index):
            results.append(checks[check_name](integration))
    directories = []
    for integration in integrations:
        try:
            directories.append(integration.resolve().relative_to(root.resolve()).as_posix())
        except ValueError:
            directories.append(integration.resolve().as_posix())
    return ValidationReport(results, directories=directories)


def _select_integrations(root: Path, dirs: list[Path], *, changed: bool, base_ref: str | None) -> list[Path]:
    if dirs:
        return explicit_integrations(dirs)
    if changed:
        if not base_ref:
            raise RuntimeError("--changed requires --base-ref")
        return changed_integrations(root, base_ref)
    return discover_integrations(root)


def _select_checks(names: set[str] | list[str] | dict, *, skip: set[str], only: set[str] | None) -> set[str]:
    available = set(names)
    if only:
        return only
    return available - skip


def _report_dirs(report: ValidationReport) -> str:
    return " ".join(report.directories)


def _emit_github_annotations(report: ValidationReport) -> None:
    for result in report.results:
        for message in result.messages:
            if message.severity not in {"error", "warning"}:
                continue
            command = "error" if message.severity == "error" else "warning"
            props = []
            if message.file:
                props.append(f"file={_escape_annotation_prop(message.file)}")
            if message.line:
                props.append(f"line={message.line}")
            prop_text = ",".join(props)
            print(f"::{command} {prop_text}::{_escape_annotation(message.message)}")


def _write_github_outputs(
    output_file: Path,
    report: ValidationReport,
    *,
    comment_file: Path | None,
    dirs: str,
) -> None:
    values = {"directories": dirs, "comment_path": str(comment_file or "")}
    grouped_checks = set().union(*GROUPS.values())
    run_errors = [
        result
        for result in report.results
        if result.check not in grouped_checks and result.status in {"failed", "error"}
    ]
    for group in GROUPS:
        results = [result for result in report.results if result.check in GROUPS[group]]
        if run_errors or any(result.status in {"failed", "error"} for result in results):
            status = "failure"
        elif not results or all(result.status == "skipped" for result in results):
            status = "skipped"
        else:
            status = "success"
        values[f"{group}_result"] = status
        values[f"{group}_output"] = _group_output([*run_errors, *results])
    with output_file.open("a", encoding="utf-8") as file:
        for key, value in values.items():
            _write_github_output(file, key, value)


def _group_output(results: list[CheckResult]) -> str:
    lines = []
    for result in results:
        lines.append(f"[{result.integration}] {result.check}: {result.status}")
        for message in result.messages:
            lines.append(f"  {message.severity}: {message.message}")
        if result.raw_output:
            lines.append(result.raw_output)
    return "\n".join(lines)


def _write_github_output(file, key: str, value: str) -> None:
    delimiter = f"EOF_{key}"
    while delimiter in value:
        delimiter += "_X"
    file.write(f"{key}<<{delimiter}\n{value}\n{delimiter}\n")


def _escape_annotation(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_annotation_prop(value: str) -> str:
    return _escape_annotation(value).replace(":", "%3A").replace(",", "%2C")


def _git_commit_subject(ref: str = "HEAD") -> str:
    result = subprocess.run(["git", "log", "-1", "--format=%s", ref], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def _csv(value: str | None) -> set[str] | None:
    if not value:
        return None
    return {item.strip() for item in value.split(",") if item.strip()}


def _scaffold(
    target: Path,
    *,
    display_name: str,
    auth_type: str,
    auth_provider: str | None,
    auth_scopes: str | None,
    force: bool,
) -> tuple[int, int]:
    auth_type = auth_type.lower()
    if auth_type not in AUTH_TYPES:
        typer.echo(f"Unsupported auth type: {auth_type}", err=True)
        raise typer.Exit(2)
    if target.is_symlink():
        typer.echo(f"Target cannot be a symlink: {target}", err=True)
        raise typer.Exit(2)
    if target.exists() and not target.is_dir():
        typer.echo(f"Target is not a directory: {target}", err=True)
        raise typer.Exit(2)
    if target.exists() and any(target.iterdir()) and not force:
        typer.echo(f"Directory is not empty: {target} (use --force to overwrite)", err=True)
        raise typer.Exit(2)

    name = _slugify(target.name)
    module = name.replace("-", "_")
    if not module.isidentifier() or keyword.iskeyword(module):
        typer.echo(f"Integration name does not produce a valid Python identifier: {module}", err=True)
        raise typer.Exit(2)
    config = _default_config(
        name,
        module,
        display_name,
        auth_type,
        auth_provider=auth_provider,
        auth_scopes=auth_scopes,
    )
    files = {
        Path("config.json"): (json.dumps(config, indent=2) + "\n").encode(),
        Path("requirements.txt"): b"autohive-integrations-sdk~=2.0.1\n",
        Path("README.md"): _readme_source(display_name, auth_type).encode(),
        Path(".gitignore"): (
            b".coverage\n.env\n.hiveup/\n.pytest_cache/\n.ruff_cache/\n.venv/\n"
            b"__pycache__/\ndependencies/\n*.zip\n"
        ),
        Path("__init__.py"): f"from .{module} import {module}\n\n__all__ = [\"{module}\"]\n".encode(),
        Path(f"{module}.py"): _module_source(module).encode(),
        Path("icon.png"): _png_bytes(),
        Path("tests/__init__.py"): b"",
        Path("tests/conftest.py"): _conftest_source().encode(),
        Path(f"tests/test_{module}_unit.py"): _test_source(module).encode(),
    }
    return _write_scaffold(target, files)


def _default_config(
    name: str,
    module: str,
    display_name: str,
    auth_type: str,
    *,
    auth_provider: str | None,
    auth_scopes: str | None,
) -> dict:
    config = {
        "name": name,
        "display_name": display_name,
        "version": "1.0.0",
        "description": f"{display_name} integration",
        "entry_point": f"{module}.py",
        "actions": {
            "get_data": {
                "display_name": "Get Data",
                "description": "Retrieve sample data.",
                "input_schema": {"type": "object", "properties": {}, "required": []},
                "output_schema": {
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                },
            }
        },
    }
    _apply_auth_config(config, auth_type, provider=auth_provider, scopes=auth_scopes)
    return config


def _apply_auth_config(config: dict, auth_type: str, *, provider: str | None = None, scopes: str | None = None) -> None:
    auth_type = auth_type.lower()
    if auth_type not in AUTH_TYPES:
        typer.echo(f"Unsupported auth type: {auth_type}", err=True)
        raise typer.Exit(2)
    existing = config.get("auth")
    compatible = existing if isinstance(existing, dict) and existing.get("type") == auth_type else {}
    if auth_type == "none":
        config.pop("auth", None)
    elif auth_type == "platform":
        selected_provider = provider or compatible.get("provider")
        if not selected_provider:
            typer.echo("--auth-provider is required for platform authentication", err=True)
            raise typer.Exit(2)
        platform_auth = {
            **compatible,
            "type": "platform",
            "provider": selected_provider,
        }
        if scopes is not None:
            platform_auth["scopes"] = _csv_list(scopes)
        config["auth"] = platform_auth
    else:
        config["auth"] = {
            "type": "custom",
            "title": "API Key Authentication",
            "fields": {
                "type": "object",
                "properties": {"api_key": {"type": "string", "format": "password", "label": "API Key"}},
                "required": ["api_key"],
            },
            **compatible,
        }


def _write_scaffold(target: Path, files: dict[Path, bytes]) -> tuple[int, int]:
    """Replace scaffold-owned files with per-file atomic writes and rollback."""

    for relative in files:
        destination = target / relative
        if destination.is_symlink() or (destination.exists() and destination.is_dir()):
            typer.echo(f"Cannot replace scaffold file: {destination}", err=True)
            raise typer.Exit(2)
        for parent in relative.parents:
            if parent == Path("."):
                continue
            candidate = target / parent
            if candidate.is_symlink():
                typer.echo(f"Cannot use symlinked scaffold directory: {candidate}", err=True)
                raise typer.Exit(2)
            if candidate.exists() and not candidate.is_dir():
                typer.echo(f"Cannot create scaffold directory: {candidate}", err=True)
                raise typer.Exit(2)

    target.mkdir(parents=True, exist_ok=True)
    originals = {
        target / relative: (target / relative).read_bytes() if (target / relative).is_file() else None
        for relative in files
    }
    try:
        for relative, content in files.items():
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(destination, content)
    except OSError as exc:
        for destination, content in originals.items():
            if content is None:
                destination.unlink(missing_ok=True)
            else:
                _atomic_write(destination, content)
        typer.echo(f"Could not write scaffold: {exc}", err=True)
        raise typer.Exit(2)

    created = sum(content is None for content in originals.values())
    return created, len(files) - created


def _atomic_write(path: Path, content: bytes) -> None:
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as temporary:
            temporary.write(content)
            temporary_name = temporary.name
        os.chmod(temporary_name, 0o644)
        os.replace(temporary_name, path)
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def _module_source(module: str) -> str:
    return f'''from pathlib import Path
from typing import Any

from autohive_integrations_sdk import ActionHandler, ActionResult, ExecutionContext, Integration

{module} = Integration.load(Path(__file__).with_name("config.json"))


@{module}.action("get_data")
class GetDataAction(ActionHandler):
    async def execute(self, inputs: dict[str, Any], context: ExecutionContext) -> ActionResult:
        return ActionResult(data={{"message": "hello from {module}"}}, cost_usd=0.0)
'''


def _conftest_source() -> str:
    return """import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def mock_context():
    \"\"\"Return an isolated SDK execution context for unit tests.\"\"\"
    context = MagicMock(name="ExecutionContext")
    context.fetch = AsyncMock(name="fetch")
    context.auth = {}
    return context
"""


def _test_source(module: str) -> str:
    return f'''import pytest

from {module} import {module}

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


async def test_get_data(mock_context):
    result = await {module}.execute_action("get_data", {{}}, mock_context)

    assert result.result.data["message"] == "hello from {module}"
'''


def _readme_source(display_name: str, auth_type: str) -> str:
    auth = {
        "none": "This integration uses a public API and does not require authentication.",
        "platform": (
            "This integration uses platform-managed OAuth. "
            "Configure the provider and required scopes in `config.json`."
        ),
        "custom": (
            "This integration uses custom API-key authentication. "
            "Configure the required fields in `config.json`."
        ),
    }[auth_type]
    return f"""# {display_name}

## Description

{display_name} integration for Autohive.

## Authentication

{auth}

## Actions

### Get Data

Returns sample data from the integration.

## Requirements

- Python 3.13
- `autohive-integrations-sdk~=2.0.1`

## Development

```bash
hiveup validate
hiveup test
hiveup package
```
"""


def _png_bytes() -> bytes:
    width = height = 512
    raw = b"".join(b"\x00" + b"\xff\xff\xff\xff" * width for _ in range(height))
    png = b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    png += _png_chunk(b"IDAT", zlib.compress(raw)) + _png_chunk(b"IEND", b"")
    return png


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", value.lower().strip())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "my-integration"


def _display_name(value: str) -> str:
    return re.sub(r"[-_]+", " ", value).strip().title()


def _csv_list(value: str | None) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()] if value else []


def _module_version(module: str) -> str:
    result = subprocess.run([sys.executable, "-m", module, "--version"], capture_output=True, text=True)
    if result.returncode == 0:
        output = (result.stdout or result.stderr).strip()
        return output.splitlines()[0] if output else "unknown"
    return "missing"


def _load_config(directory: Path) -> dict:
    config_path = directory / "config.json"
    if not config_path.is_file():
        typer.echo(f"config.json not found: {config_path}", err=True)
        raise typer.Exit(2)
    return json.loads(config_path.read_text(encoding="utf-8"))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
