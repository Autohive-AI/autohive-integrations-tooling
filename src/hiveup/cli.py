"""Command-line entry point for hiveup."""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path
from typing import Annotated

import typer
from autohive_integrations_sdk import ExecutionContext, Integration

from hiveup import __version__
from hiveup.checks.static import available_checks
from hiveup.core.discovery import changed_integrations, discover_integrations, explicit_integrations
from hiveup.core.results import CheckMessage, CheckResult, ValidationReport
from hiveup.render.console import render_report
from hiveup.render.markdown import GROUPS, render_markdown

app = typer.Typer(help="Developer CLI for Autohive integrations.", no_args_is_help=True)

AUTH_TYPES = {"platform", "custom", "none"}


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
) -> None:
    """Run the CI validation profile."""

    report = run_validation(
        dirs or [],
        changed=not bool(dirs),
        base_ref=base_ref,
    )
    dirs_output = _report_dirs(report)
    if github_annotations:
        _emit_github_annotations(report)
    if comment_file and report.results:
        comment_file.write_text(
            render_markdown(
                report,
                commit=os.environ.get("GITHUB_SHA", ""),
                commit_msg=_git_commit_subject(),
                dirs=dirs_output,
            ),
            encoding="utf-8",
        )
    if output_file:
        _write_github_outputs(output_file, report, comment_file=comment_file, dirs=dirs_output)
    if json_output:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        render_report(report)
    raise typer.Exit(report.exit_code())


@app.command()
def create(
    name: Annotated[str, typer.Argument(help="Integration name to create.")],
    auth_type: Annotated[str, typer.Option("--auth-type", help="platform, custom, or none.")] = "none",
    force: Annotated[bool, typer.Option("--force", help="Overwrite existing files.")] = False,
) -> None:
    """Scaffold a new integration in a child directory."""

    target = Path(_slugify(name))
    _scaffold(target, display_name=_display_name(name), auth_type=auth_type, force=force)
    typer.echo(f"✅ Created {target}")
    typer.echo(f"Next: cd {target} && hiveup validate && hiveup test")


@app.command()
def init(
    name: Annotated[str | None, typer.Option("--name", help="Integration name. Defaults to cwd name.")] = None,
    auth_type: Annotated[str, typer.Option("--auth-type", help="platform, custom, or none.")] = "none",
    force: Annotated[bool, typer.Option("--force", help="Overwrite existing files.")] = False,
) -> None:
    """Scaffold an integration in the current directory."""

    target = Path.cwd()
    _scaffold(target, display_name=_display_name(name or target.name), auth_type=auth_type, force=force)
    typer.echo(f"✅ Initialized {target.name}")


@app.command()
def auth(
    directory: Annotated[Path, typer.Argument(help="Integration directory to edit.")] = Path("."),
    auth_type: Annotated[str, typer.Option("--auth-type", help="platform, custom, or none.")] = "none",
    auth_provider: Annotated[str | None, typer.Option("--auth-provider", help="Platform auth provider.")] = None,
    auth_scopes: Annotated[str | None, typer.Option("--auth-scopes", help="Comma-separated platform scopes.")] = None,
) -> None:
    """Add, update, or remove the auth block in config.json."""

    config_path = directory / "config.json"
    if not config_path.is_file():
        typer.echo(f"config.json not found: {config_path}", err=True)
        raise typer.Exit(2)

    config = json.loads(config_path.read_text(encoding="utf-8"))
    _apply_auth_config(config, auth_type, provider=auth_provider, scopes=auth_scopes)
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
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
    config = json.loads(config_path.read_text(encoding="utf-8"))
    package_path = output or Path.cwd() / f"{config.get('name', directory.name)}-{config.get('version', '0.0.0')}.zip"

    with tempfile.TemporaryDirectory() as tmp:
        deps_dir = Path(tmp) / "dependencies"
        requirements = directory / "requirements.txt"
        if requirements.is_file():
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", str(requirements), "--target", str(deps_dir), "-q"],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                typer.echo(result.stderr or result.stdout, err=True)
                raise typer.Exit(2)

        _write_package_zip(directory, package_path, deps_dir if deps_dir.exists() else None)

    typer.echo(f"✅ Wrote {package_path}")


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


@app.command()
def run(
    action: Annotated[str | None, typer.Argument(help="Action name to execute.")] = None,
    directory: Annotated[Path, typer.Option("--dir", help="Integration directory.")] = Path("."),
    list_items: Annotated[bool, typer.Option("--list", help="List actions and triggers.")] = False,
    inputs_file: Annotated[Path | None, typer.Option("--inputs", help="JSON file containing action inputs.")] = None,
    input_values: Annotated[
        list[str] | None,
        typer.Option("--input", help="Input override as key=value. May be repeated."),
    ] = None,
    auth_file: Annotated[Path | None, typer.Option("--auth", help="JSON auth envelope or credentials file.")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Emit raw JSON result.")] = False,
) -> None:
    """List or execute integration actions locally."""

    config = _load_config(directory)
    if list_items or action is None:
        _print_runnable_items(config, json_output=json_output)
        return

    inputs = _load_inputs(inputs_file, input_values or [])
    auth = _load_auth(auth_file, config)
    result = asyncio.run(_execute_action(directory, config, action, inputs, auth))
    data = _result_to_jsonable(result)
    if json_output:
        print(json.dumps(data, indent=2, default=str))
    else:
        typer.echo(json.dumps(data, indent=2, default=str))


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
    return ValidationReport(results)


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
    dirs = []
    for result in report.results:
        if result.check in {"discovery", "selection"}:
            continue
        if result.integration not in dirs:
            dirs.append(result.integration)
    return " ".join(dirs)


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
    for group in GROUPS:
        results = [result for result in report.results if result.check in GROUPS[group]]
        values[f"{group}_result"] = "failure" if any(r.status in {"failed", "error"} for r in results) else "success"
        values[f"{group}_output"] = _group_output(results)
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


def _git_commit_subject() -> str:
    result = subprocess.run(["git", "log", "-1", "--format=%s"], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def _csv(value: str | None) -> set[str] | None:
    if not value:
        return None
    return {item.strip() for item in value.split(",") if item.strip()}


def _scaffold(target: Path, *, display_name: str, auth_type: str, force: bool) -> None:
    auth_type = auth_type.lower()
    if auth_type not in AUTH_TYPES:
        typer.echo(f"Unsupported auth type: {auth_type}", err=True)
        raise typer.Exit(2)
    if target.exists() and any(target.iterdir()) and not force:
        typer.echo(f"Directory is not empty: {target} (use --force to overwrite)", err=True)
        raise typer.Exit(2)

    target.mkdir(parents=True, exist_ok=True)
    name = _slugify(target.name)
    module = name.replace("-", "_")
    config = _default_config(name, module, display_name, auth_type)
    _write_text(target / "config.json", json.dumps(config, indent=2) + "\n", force=force)
    _write_text(target / "requirements.txt", "autohive-integrations-sdk~=2.0.1\n", force=force)
    _write_text(target / "README.md", f"# {display_name}\n\nAutohive integration scaffold.\n", force=force)
    _write_text(target / ".gitignore", "dependencies/\n.hiveup/\n.env\n", force=force)
    _write_text(target / "__init__.py", f"from .{module} import {module}\n\n__all__ = [\"{module}\"]\n", force=force)
    _write_text(target / f"{module}.py", _module_source(module), force=force)
    _write_png(target / "icon.png", force=force)
    tests = target / "tests"
    tests.mkdir(exist_ok=True)
    _write_text(tests / "__init__.py", "", force=force)
    _write_text(tests / "context.py", _context_source(module), force=force)
    _write_text(tests / f"test_{module}_unit.py", _test_source(module), force=force)


def _default_config(name: str, module: str, display_name: str, auth_type: str) -> dict:
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
                "output_schema": {"type": "object", "properties": {"message": {"type": "string"}}},
            }
        },
    }
    _apply_auth_config(config, auth_type)
    return config


def _apply_auth_config(config: dict, auth_type: str, *, provider: str | None = None, scopes: str | None = None) -> None:
    auth_type = auth_type.lower()
    if auth_type not in AUTH_TYPES:
        typer.echo(f"Unsupported auth type: {auth_type}", err=True)
        raise typer.Exit(2)
    if auth_type == "none":
        config.pop("auth", None)
    elif auth_type == "platform":
        config["auth"] = {"type": "platform", "provider": provider or "github", "scopes": _csv_list(scopes)}
    else:
        config["auth"] = {
            "type": "custom",
            "title": "API Key Authentication",
            "fields": {
                "type": "object",
                "properties": {"api_key": {"type": "string", "format": "password", "label": "API Key"}},
                "required": ["api_key"],
            },
        }


def _write_text(path: Path, content: str, *, force: bool) -> None:
    if path.exists() and not force:
        return
    path.write_text(content, encoding="utf-8")


def _module_source(module: str) -> str:
    return f'''from typing import Any
from pathlib import Path

from autohive_integrations_sdk import ActionHandler, ActionResult, ExecutionContext, Integration

{module} = Integration.load(Path(__file__).with_name("config.json"))


@{module}.action("get_data")
class GetDataAction(ActionHandler):
    async def execute(self, inputs: dict[str, Any], context: ExecutionContext):
        return ActionResult(data={{"message": "hello from {module}"}}, cost_usd=0.0)
'''


def _context_source(module: str) -> str:
    return f"""import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from {module} import {module}  # noqa: E402,F401
"""


def _test_source(module: str) -> str:
    return f'''import pytest
from autohive_integrations_sdk import ExecutionContext

from .context import {module}

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


async def test_get_data():
    async with ExecutionContext(auth={{}}) as context:
        result = await {module}.execute_action("get_data", {{}}, context)

    assert result.result.data["message"] == "hello from {module}"
'''


def _write_png(path: Path, *, force: bool) -> None:
    if path.exists() and not force:
        return
    width = height = 512
    raw = b"".join(b"\x00" + b"\xff\xff\xff\xff" * width for _ in range(height))
    png = b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    png += _png_chunk(b"IDAT", zlib.compress(raw)) + _png_chunk(b"IEND", b"")
    path.write_bytes(png)


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _write_package_zip(directory: Path, package_path: Path, deps_dir: Path | None) -> None:
    excluded = {"tests", "__pycache__", ".pytest_cache", ".ruff_cache", ".venv", "venv", "dependencies"}
    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_dir() or excluded.intersection(path.relative_to(directory).parts):
                continue
            if path.suffix == ".py" or path.name == "config.json" or path.name.startswith("icon."):
                archive.write(path, path.relative_to(directory).as_posix())
        if deps_dir:
            for path in sorted(deps_dir.rglob("*")):
                if path.is_file():
                    archive.write(path, f"dependencies/{path.relative_to(deps_dir).as_posix()}")


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
        return (result.stdout or result.stderr).strip().splitlines()[0]
    return "missing"


def _load_config(directory: Path) -> dict:
    config_path = directory / "config.json"
    if not config_path.is_file():
        typer.echo(f"config.json not found: {config_path}", err=True)
        raise typer.Exit(2)
    return json.loads(config_path.read_text(encoding="utf-8"))


def _print_runnable_items(config: dict, *, json_output: bool) -> None:
    data = {
        "actions": sorted(config.get("actions", {}).keys()),
        "polling_triggers": sorted(config.get("polling_triggers", {}).keys()),
        "supports_connected_account": bool(config.get("supports_connected_account")),
    }
    if json_output:
        print(json.dumps(data, indent=2))
        return
    typer.echo("Actions:")
    for action in data["actions"]:
        typer.echo(f"  - {action}")
    if data["polling_triggers"]:
        typer.echo("Polling triggers:")
        for trigger in data["polling_triggers"]:
            typer.echo(f"  - {trigger}")


def _load_inputs(inputs_file: Path | None, input_values: list[str]) -> dict:
    inputs = {}
    if inputs_file:
        inputs.update(json.loads(inputs_file.read_text(encoding="utf-8")))
    for item in input_values:
        if "=" not in item:
            typer.echo(f"Invalid --input value (expected key=value): {item}", err=True)
            raise typer.Exit(2)
        key, value = item.split("=", 1)
        inputs[key] = _parse_scalar(value)
    return inputs


def _load_auth(auth_file: Path | None, config: dict) -> dict:
    if auth_file:
        auth = json.loads(auth_file.read_text(encoding="utf-8"))
        if "auth_type" in auth and "credentials" in auth:
            return auth
        return {"auth_type": _runtime_auth_type(config), "credentials": auth}
    return {"auth_type": _runtime_auth_type(config), "credentials": {}}


def _runtime_auth_type(config: dict) -> str:
    auth_type = (config.get("auth") or {}).get("type")
    return {"custom": "Custom", "platform": "PlatformOauth2"}.get(auth_type, "None")


async def _execute_action(directory: Path, config: dict, action: str, inputs: dict, auth: dict):
    integration = _load_integration(directory, config)
    async with ExecutionContext(auth=auth) as context:
        return await integration.execute_action(action, inputs, context)


def _load_integration(directory: Path, config: dict) -> Integration:
    entry_point = config.get("entry_point")
    if not entry_point:
        typer.echo("config.json missing entry_point", err=True)
        raise typer.Exit(2)
    module_path = directory / entry_point
    spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
    if spec is None or spec.loader is None:
        typer.echo(f"Could not import entry point: {module_path}", err=True)
        raise typer.Exit(2)

    sys.path.insert(0, str(directory.resolve()))
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        with contextlib.suppress(ValueError):
            sys.path.remove(str(directory.resolve()))

    integrations = [value for value in vars(module).values() if isinstance(value, Integration)]
    if len(integrations) != 1:
        typer.echo(f"Expected exactly one Integration instance, found {len(integrations)}", err=True)
        raise typer.Exit(2)
    return integrations[0]


def _result_to_jsonable(result) -> dict:
    if hasattr(result, "result"):
        inner = result.result
        return {
            "version": getattr(result, "version", None),
            "type": _jsonable(getattr(result, "type", None)),
            "data": _jsonable(getattr(inner, "data", None)),
            "cost_usd": _jsonable(getattr(inner, "cost_usd", None)),
        }
    if hasattr(result, "model_dump"):
        return _jsonable(result.model_dump())
    if hasattr(result, "__dict__"):
        return _jsonable(result.__dict__)
    return {"result": result}


def _jsonable(value):
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _parse_scalar(value: str):
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def main() -> None:
    app()


if __name__ == "__main__":
    main()
