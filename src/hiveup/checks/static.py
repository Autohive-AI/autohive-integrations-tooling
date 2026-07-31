"""Static validation checks for integrations."""

from __future__ import annotations

import contextlib
import ast
import io
import importlib.resources
import json
import py_compile
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from hiveup.checks.config_sync import check_config_sync, is_new_integration, verify_base_ref
from hiveup.checks.fetch_pattern import check_fetch_pattern
from hiveup.checks.readme import check_readme
from hiveup.checks.structure import IntegrationValidator
from hiveup.checks.tests import find_unit_test_files, run_integration_tests
from hiveup.checks.version import check_version_bump
from hiveup.core.deployment import symlink_component
from hiveup.core.environment import EnvironmentBuildError, module_available, prepare_environment
from hiveup.core.results import CheckMessage, CheckResult

CheckFn = Callable[[Path], CheckResult]
BANDIT_EXCLUDE_DIRS = [".venv", "venv", "__pycache__", "site-packages", "dependencies"]
RUFF_CONFIG = Path(str(importlib.resources.files("hiveup").joinpath("data/ruff.toml")))


def available_checks(*, base_ref: str | None = None, fix: bool = False) -> dict[str, CheckFn]:
    return {
        "structure": lambda path: check_structure(path, base_ref=base_ref),
        "syntax": check_syntax,
        "imports": check_imports_all,
        "json": check_json,
        "lint": lambda path: check_lint(path, fix=fix),
        "format": lambda path: check_format(path, fix=fix),
        "security": check_security,
        "audit": check_audit,
        "sync": lambda path: check_sync(path, base_ref=base_ref),
        "fetch": check_fetch,
        "tests": check_tests,
        "readme": lambda path: check_readme_update(path, base_ref=base_ref),
        "version": lambda path: check_version(path, base_ref=base_ref),
    }


def check_structure(path: Path, *, base_ref: str | None = None) -> CheckResult:
    start = time.perf_counter()
    repo_root = _git_repo_root(path) if base_ref else None
    if base_ref and (repo_root is None or not verify_base_ref(base_ref, repo_root)):
        return _result(
            "structure",
            path,
            "error",
            [CheckMessage("error", f"base-ref '{base_ref}' not resolvable — check fetch-depth or ref name")],
            start,
        )
    allow_legacy_missing_unit_tests = not base_ref or not is_new_integration(path, base_ref, repo_root)
    validator = IntegrationValidator(
        path,
        allow_legacy_missing_unit_tests=allow_legacy_missing_unit_tests,
    )
    try:
        validator.validate()
    except Exception as exc:  # pragma: no cover - defensive boundary for legacy validator
        return _result("structure", path, "error", [CheckMessage("error", str(exc))], start)

    messages = [CheckMessage("error", error.message) for error in validator.errors]
    messages.extend(CheckMessage("warning", warning.message) for warning in validator.warnings)
    return _result("structure", path, _status_from_messages(messages), messages, start)


def check_syntax(path: Path) -> CheckResult:
    start = time.perf_counter()
    messages: list[CheckMessage] = []
    for pyfile in _python_files(path):
        try:
            py_compile.compile(str(pyfile), doraise=True)
        except py_compile.PyCompileError as exc:
            messages.append(
                CheckMessage(
                    "error",
                    exc.msg,
                    file=_relative(pyfile),
                    fix_hint="Run: python -m py_compile <file.py>",
                )
            )
    return _result("syntax", path, _status_from_messages(messages), messages, start)


def check_imports_all(path: Path) -> CheckResult:
    start = time.perf_counter()
    messages: list[CheckMessage] = []
    processing_error = False

    try:
        environment = prepare_environment(path, include_test_tools=True)
    except EnvironmentBuildError as exc:
        message = CheckMessage(
            "error",
            f"Could not prepare isolated environment: {exc}",
            file=_relative(path / "requirements.txt"),
            fix_hint="Fix requirements.txt or verify package index access.",
        )
        return _result("imports", path, "error", [message], start)

    availability: dict[str, bool] = {}

    def dependency_available(module_name: str) -> bool:
        if module_name not in availability:
            availability[module_name] = module_available(environment, module_name)
        return availability[module_name]

    for pyfile in _python_files(path):
        try:
            messages.extend(_check_file_imports(pyfile, path, dependency_available=dependency_available))
        except (EnvironmentBuildError, OSError, SyntaxError) as exc:
            processing_error = True
            messages.append(CheckMessage("error", str(exc), file=_relative(pyfile)))

    status = "error" if processing_error else _status_from_messages(messages)
    return _result("imports", path, status, messages, start)


def check_json(path: Path) -> CheckResult:
    start = time.perf_counter()
    messages: list[CheckMessage] = []
    for jsonfile in sorted(path.rglob("*.json")):
        if _is_ignored(jsonfile):
            continue
        try:
            with jsonfile.open(encoding="utf-8") as file:
                json.load(file)
        except (json.JSONDecodeError, OSError) as exc:
            messages.append(
                CheckMessage(
                    "error",
                    str(exc),
                    file=_relative(jsonfile),
                    fix_hint="Check for missing commas, quotes, or brackets.",
                )
            )
    return _result("json", path, _status_from_messages(messages), messages, start)


def check_sync(path: Path, *, base_ref: str | None = None) -> CheckResult:
    repo_root = _git_repo_root(path) if base_ref else None
    return _legacy_check("sync", path, lambda: check_config_sync(str(path), base_ref=base_ref), cwd=repo_root)


def check_fetch(path: Path) -> CheckResult:
    return _legacy_check("fetch", path, lambda: check_fetch_pattern(str(path)))


def check_lint(path: Path, *, fix: bool = False) -> CheckResult:
    command = [sys.executable, "-m", "ruff", "check", "--config", str(RUFF_CONFIG)]
    if fix:
        command.append("--fix")
    command.append(str(path))
    return _subprocess_check(
        "lint",
        path,
        command,
        fix_hint="Run: hiveup validate --fix" if not fix else None,
    )


def check_format(path: Path, *, fix: bool = False) -> CheckResult:
    command = [sys.executable, "-m", "ruff", "format", "--config", str(RUFF_CONFIG)]
    if not fix:
        command.append("--check")
    command.append(str(path))
    return _subprocess_check(
        "format",
        path,
        command,
        fix_hint="Run: hiveup validate --fix" if not fix else None,
    )


def check_security(path: Path) -> CheckResult:
    excludes = ",".join(str(path / directory) for directory in BANDIT_EXCLUDE_DIRS)
    return _subprocess_check(
        "security",
        path,
        [sys.executable, "-m", "bandit", "-r", str(path), "-x", excludes, "-s", "B101", "-q"],
        fix_hint="Review flagged code for security risks.",
    )


def check_audit(path: Path) -> CheckResult:
    requirements = path / "requirements.txt"
    if not requirements.is_file():
        return CheckResult(check="audit", integration=path.name, status="skipped")
    return _subprocess_check(
        "audit",
        path,
        [sys.executable, "-m", "pip_audit", "-r", str(requirements)],
        fix_hint="Update affected packages in requirements.txt.",
    )


def check_tests(path: Path) -> CheckResult:
    start = time.perf_counter()
    test_files = find_unit_test_files(path)
    if not test_files:
        return _result(
            "tests",
            path,
            "warning",
            [CheckMessage("warning", "No unit tests found (expected tests/test_*_unit.py)")],
            start,
        )

    try:
        exit_code, output = run_integration_tests(path, test_files)
    except EnvironmentBuildError as exc:
        environment_error = str(exc)
        return _result(
            "tests",
            path,
            "error",
            [
                CheckMessage(
                    "error",
                    environment_error or "Could not prepare isolated environment",
                    fix_hint="Fix requirements.txt or verify package index access.",
                )
            ],
            start,
            raw_output=environment_error,
        )

    if exit_code == 0:
        return _result("tests", path, "passed", [], start, raw_output=output)

    return _result(
        "tests",
        path,
        "failed",
        [CheckMessage("error", "Unit tests failed", fix_hint="Run: hiveup test <dir>")],
        start,
        raw_output=output,
    )


def check_readme_update(path: Path, *, base_ref: str | None = None) -> CheckResult:
    if not base_ref:
        return CheckResult(
            check="readme",
            integration=path.name,
            status="skipped",
            messages=[CheckMessage("info", "README check requires --base-ref")],
        )
    repo_root = _git_repo_root(path)
    dir_name = _git_relative_or_name(path, repo_root=repo_root)
    return _legacy_check("readme", path, lambda: check_readme(base_ref, [dir_name]), cwd=repo_root)


def check_version(path: Path, *, base_ref: str | None = None) -> CheckResult:
    if not base_ref:
        return CheckResult(
            check="version",
            integration=path.name,
            status="skipped",
            messages=[CheckMessage("info", "Version check requires --base-ref")],
        )
    repo_root = _git_repo_root(path)
    dir_name = _git_relative_or_name(path, repo_root=repo_root)
    return _legacy_check("version", path, lambda: check_version_bump(base_ref, [dir_name]), cwd=repo_root)


def _legacy_check(check: str, path: Path, run: Callable[[], int], *, cwd: Path | None = None) -> CheckResult:
    start = time.perf_counter()
    stdout = io.StringIO()
    stderr = io.StringIO()
    cwd_context = contextlib.chdir(cwd) if cwd else contextlib.nullcontext()
    try:
        with cwd_context, contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = run()
    except Exception as exc:  # Defensive boundary around migrated script checks.
        output = (stdout.getvalue() + stderr.getvalue()).strip()
        return _result(
            check,
            path,
            "error",
            [CheckMessage("error", str(exc) or type(exc).__name__)],
            start,
            raw_output=output,
        )

    output = (stdout.getvalue() + stderr.getvalue()).strip()
    messages: list[CheckMessage] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        if "❌" in line:
            messages.append(CheckMessage("error", line))
        elif "⚠️" in line:
            messages.append(CheckMessage("warning", line))

    if code != 0 and not any(message.severity == "error" for message in messages):
        messages.append(CheckMessage("error", f"Legacy {check} check exited with status {code}"))

    if code == 0:
        status = "warning" if messages else "passed"
    elif code == 1:
        status = "failed"
    else:
        status = "error"
    return _result(check, path, status, messages, start, raw_output=output)


def _subprocess_check(
    check: str,
    path: Path,
    command: list[str],
    *,
    fix_hint: str | None = None,
) -> CheckResult:
    start = time.perf_counter()
    result = subprocess.run(command, capture_output=True, text=True)
    output = (result.stdout + result.stderr).strip()
    if result.returncode == 0:
        return _result(check, path, "passed", [], start, raw_output=output)

    message = output or f"{check} check failed"
    status = "failed" if result.returncode == 1 else "error"
    return _result(
        check,
        path,
        status,
        [CheckMessage("error", message, fix_hint=fix_hint)],
        start,
        raw_output=output,
    )


def _check_file_imports(
    pyfile: Path,
    integration_path: Path,
    *,
    dependency_available: Callable[[str], bool],
) -> list[CheckMessage]:
    source = pyfile.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(pyfile))
    messages: list[CheckMessage] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module = alias.name
                if not _is_import_available(
                    module,
                    integration_path,
                    source_dir=pyfile.parent,
                    dependency_available=dependency_available,
                ):
                    messages.append(_missing_import_message(module, pyfile, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                module = node.module or ""
                names = [alias.name for alias in node.names]
                if not _is_relative_import_available(pyfile, node.level, module, names):
                    label = "." * node.level + module
                    messages.append(_missing_import_message(label, pyfile, node.lineno))
            elif node.module and not _is_import_available(
                node.module,
                integration_path,
                source_dir=pyfile.parent,
                dependency_available=dependency_available,
            ):
                messages.append(_missing_import_message(node.module, pyfile, node.lineno))

    return messages


def _missing_import_message(module: str, pyfile: Path, line: int) -> CheckMessage:
    return CheckMessage(
        "error",
        f"Missing module: {module}",
        file=_relative(pyfile),
        line=line,
        fix_hint="Install missing packages in requirements.txt or fix the import path.",
    )


def _is_import_available(
    module_name: str,
    integration_path: Path,
    *,
    source_dir: Path,
    dependency_available: Callable[[str], bool],
) -> bool:
    if _local_module_exists(module_name, integration_path, source_dir=source_dir):
        return True
    return dependency_available(module_name)


def _local_module_exists(module_name: str, integration_path: Path, *, source_dir: Path) -> bool:
    parts = module_name.split(".")
    roots = [source_dir, integration_path]
    if parts[0] == integration_path.name:
        roots.append(integration_path.parent)
    for root in roots:
        candidate = root.joinpath(*parts)
        if _module_path_exists(candidate, integration_root=integration_path):
            return True
    return False


def _module_path_exists(path: Path, *, integration_root: Path | None = None) -> bool:
    if (
        integration_root is not None
        and path.is_relative_to(integration_root)
        and symlink_component(path, integration_root) is not None
    ):
        return False
    module_file = path.with_suffix(".py")
    package_init = path / "__init__.py"
    return (module_file.is_file() and not module_file.is_symlink()) or (
        path.is_dir() and not path.is_symlink() and package_init.is_file() and not package_init.is_symlink()
    )


def _is_relative_import_available(pyfile: Path, level: int, module: str, names: list[str]) -> bool:
    base = pyfile.parent
    for _ in range(level - 1):
        base = base.parent

    if module:
        target = base.joinpath(*module.split("."))
        return _module_path_exists(target)

    return all(_module_path_exists(base / name) for name in names if name != "*")


def _python_files(path: Path) -> list[Path]:
    return [
        pyfile for pyfile in sorted(path.rglob("*.py")) if not pyfile.is_symlink() and not _is_ignored(pyfile)
    ]


def _is_ignored(path: Path) -> bool:
    ignored_parts = {"__pycache__", ".venv", "venv", "dependencies", ".hiveup"}
    return bool(ignored_parts.intersection(path.parts))


def _status_from_messages(messages: list[CheckMessage]) -> str:
    if any(message.severity == "error" for message in messages):
        return "failed"
    if any(message.severity == "warning" for message in messages):
        return "warning"
    return "passed"


def _result(
    check: str,
    path: Path,
    status: str,
    messages: list[CheckMessage],
    start: float,
    *,
    raw_output: str = "",
) -> CheckResult:
    return CheckResult(
        check=check,
        integration=path.name,
        status=status,  # type: ignore[arg-type]
        messages=messages,
        duration_s=time.perf_counter() - start,
        raw_output=raw_output,
    )


def _relative(path: Path) -> str:
    with contextlib.suppress(ValueError):
        return path.resolve().relative_to(Path.cwd()).as_posix()
    return path.as_posix()


def _git_repo_root(path: Path) -> Path | None:
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).resolve()


def _git_relative_or_name(path: Path, *, repo_root: Path | None = None) -> str:
    if repo_root:
        with contextlib.suppress(ValueError):
            return path.resolve().relative_to(repo_root).as_posix()
    with contextlib.suppress(ValueError):
        return path.resolve().relative_to(Path.cwd()).as_posix()
    return path.name
