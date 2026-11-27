#!/usr/bin/env python3
"""
Fetch Pattern Checker

Requires: Python 3.13+

This script validates that integrations use the correct context.fetch()
return-value pattern for their pinned SDK version.

SDK 2.0.0 changed context.fetch() to return a FetchResponse object with
.status, .headers, and .data attributes. Integrations pinned to SDK >=2.0
must access the response body via .data — using the raw return value
directly (e.g., response["key"] or response.get("key")) will fail.

Checks performed:
    1. Validate requirements.txt with the shared SDK requirement parser
    2. Inspect deployment Python sources for recognizable SDK fetch calls
    3. Track simple aliases and assignments within separate scopes
    4. If SDK >= 2.0: reject raw-body subscripts, .get(), dict/list type
       checks, and raw responses passed to SDK ActionResult(data=...)

This is a bounded static check, not a type checker. Unknown clients and
values that differ across branches are not assumed to be SDK responses.

Usage:
    python scripts/check_fetch_pattern.py <dir> [dir ...]

Exit codes:
    0 - All checks passed (possibly with warnings)
    1 - Fetch pattern errors found
    2 - An error occurred (file not found, etc.)

Examples:
    python scripts/check_fetch_pattern.py my-integration
    python scripts/check_fetch_pattern.py integration-a integration-b
"""

import argparse
import ast
import sys
from pathlib import Path

from hiveup.core.deployment import is_excluded_development_path
from hiveup.sdk_requirement import SdkRequirementError, read_sdk_requirement


class _FetchUsage(ast.NodeVisitor):
    """Track proven SDK values in source order, without inferring across calls."""

    def __init__(self):
        self.bindings: dict[str, str] = {}
        self.errors: list[str] = []

    def _symbol(self, node: ast.AST | None) -> str | None:
        if isinstance(node, ast.Name):
            return self.bindings.get(node.id)
        if isinstance(node, ast.Attribute) and self._symbol(node.value) == "sdk":
            return node.attr
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            try:
                return self._symbol(ast.parse(node.value, mode="eval").body)
            except SyntaxError:
                pass
        return None

    def _value_kind(self, node: ast.AST | None) -> str | None:
        if isinstance(node, ast.Name):
            return self.bindings.get(node.id)
        if isinstance(node, ast.Call) and self._symbol(node.func) == "ExecutionContext":
            return "context"
        if isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
            func = node.value.func
            if isinstance(func, ast.Attribute) and func.attr == "fetch" and self._value_kind(func.value) == "context":
                return "response"
        return None

    def _bind(self, target: ast.AST, kind: str | None = None):
        if isinstance(target, ast.Name):
            self.bindings.pop(target.id, None)
            if kind is not None:
                self.bindings[target.id] = kind
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                self._bind(element)
        elif isinstance(target, ast.Starred):
            self._bind(target.value)

    def _body(self, body: list[ast.stmt]):
        for statement in body:
            self.visit(statement)

    def _branches(self, bodies: list[list[ast.stmt]]):
        before = self.bindings.copy()
        outcomes = []
        for body in bodies:
            self.bindings = before.copy()
            self._body(body)
            outcomes.append(self.bindings)
        # A value is proven after a branch only when every path agrees.
        self.bindings = {
            name: kind for name, kind in outcomes[0].items() if all(other.get(name) == kind for other in outcomes[1:])
        }

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self._bind(ast.Name(id=alias.asname or alias.name.split(".")[0]))
            if alias.name == "autohive_integrations_sdk":
                self.bindings[alias.asname or alias.name] = "sdk"

    def visit_ImportFrom(self, node: ast.ImportFrom):
        for alias in node.names:
            name = alias.asname or alias.name
            self.bindings.pop(name, None)
            if node.level == 0 and node.module == "autohive_integrations_sdk":
                self.bindings[name] = alias.name

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef):
        self.bindings.pop(node.name, None)
        outer = self.bindings
        self.bindings = outer.copy()
        args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        args.extend(arg for arg in (node.args.vararg, node.args.kwarg) if arg is not None)
        for arg in args:
            annotation = self._symbol(arg.annotation)
            kind = {"ExecutionContext": "context", "FetchResponse": "response"}.get(annotation)
            if arg.arg == "context" and arg.annotation is None:
                # Preserve the conventional unannotated SDK handler parameter.
                kind = "context"
            self._bind(ast.Name(id=arg.arg), kind)
        self._body(node.body)
        self.bindings = outer

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node: ast.Lambda):
        outer = self.bindings
        self.bindings = outer.copy()
        args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        args.extend(arg for arg in (node.args.vararg, node.args.kwarg) if arg is not None)
        for arg in args:
            self.bindings.pop(arg.arg, None)
        self.visit(node.body)
        self.bindings = outer

    def visit_ClassDef(self, node: ast.ClassDef):
        self.bindings.pop(node.name, None)
        outer = self.bindings
        self.bindings = outer.copy()
        self._body(node.body)
        self.bindings = outer

    def visit_Assign(self, node: ast.Assign):
        self.visit(node.value)
        kind = self._value_kind(node.value)
        for target in node.targets:
            self.visit(target)
            self._bind(target, kind)

    def visit_AnnAssign(self, node: ast.AnnAssign):
        if node.value is not None:
            self.visit(node.value)
            self.visit(node.target)
            self._bind(node.target, self._value_kind(node.value))

    def visit_AugAssign(self, node: ast.AugAssign):
        self.generic_visit(node)
        self._bind(node.target)

    def visit_NamedExpr(self, node: ast.NamedExpr):
        self.visit(node.value)
        self._bind(node.target, self._value_kind(node.value))

    def visit_If(self, node: ast.If):
        self.visit(node.test)
        self._branches([node.body, node.orelse])

    def visit_For(self, node: ast.For | ast.AsyncFor):
        self.visit(node.iter)
        before = self.bindings.copy()
        self._bind(node.target)
        self._body(node.body)
        self.bindings = {name: kind for name, kind in before.items() if self.bindings.get(name) == kind}
        self._body(node.orelse)

    visit_AsyncFor = visit_For

    def visit_While(self, node: ast.While):
        self.visit(node.test)
        self._branches([node.body, []])
        self._body(node.orelse)

    def visit_With(self, node: ast.With | ast.AsyncWith):
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self._bind(item.optional_vars, self._value_kind(item.context_expr))
        self._body(node.body)

    visit_AsyncWith = visit_With

    def visit_Try(self, node: ast.Try | ast.TryStar):
        self._branches([[*node.body, *node.orelse], *[[handler] for handler in node.handlers]])
        self._body(node.finalbody)

    visit_TryStar = visit_Try

    def visit_ExceptHandler(self, node: ast.ExceptHandler):
        if node.name:
            self.bindings.pop(node.name, None)
        self._body(node.body)
        if node.name:
            self.bindings.pop(node.name, None)

    def visit_ListComp(self, node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp):
        outer = self.bindings
        self.bindings = outer.copy()
        for generator in node.generators:
            self.visit(generator.iter)
            self._bind(generator.target)
            for condition in generator.ifs:
                self.visit(condition)
        if isinstance(node, ast.DictComp):
            self.visit(node.key)
            self.visit(node.value)
        else:
            self.visit(node.elt)
        self.bindings = outer

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp

    def visit_Subscript(self, node: ast.Subscript):
        if self._value_kind(node.value) == "response":
            self.errors.append(
                f"Line {node.lineno}: raw fetch response subscript — use response.data[...] with SDK 2.x"
            )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and self._value_kind(node.func.value) == "response"
        ):
            self.errors.append(
                f"Line {node.lineno}: raw fetch response .get(...) — use response.data.get(...) with SDK 2.x"
            )
        if isinstance(node.func, ast.Name) and node.func.id == "isinstance" and len(node.args) == 2:
            types = node.args[1].elts if isinstance(node.args[1], ast.Tuple) else [node.args[1]]
            if (
                types
                and self._value_kind(node.args[0]) == "response"
                and all(isinstance(item, ast.Name) and item.id in {"dict", "list"} for item in types)
            ):
                self.errors.append(
                    f"Line {node.lineno}: raw fetch response body type check — use isinstance(response.data, ...) with SDK 2.x"
                )
        if self._symbol(node.func) == "ActionResult":
            for keyword in node.keywords:
                if keyword.arg == "data" and self._value_kind(keyword.value) == "response":
                    self.errors.append(
                        f"Line {node.lineno}: ActionResult(data=...) receives a raw fetch response — pass response.data with SDK 2.x"
                    )
        self.generic_visit(node)


def check_fetch_pattern(dir_path: str) -> int:
    """Check fetch usage patterns for an integration directory.

    Args:
        dir_path: Path to the integration directory.

    Returns:
        0 if patterns are correct, 1 if issues found, 2 on errors.
    """
    path = Path(dir_path)
    req_path = path / "requirements.txt"

    try:
        requirement = read_sdk_requirement(req_path)
    except SdkRequirementError as exc:
        print(f"❌ {exc}")
        return 1

    if requirement.version[0] < 2:
        # SDK 1.x — old pattern is fine, nothing to check
        return 0

    # SDK >= 2.x — check for old-style direct usage
    all_errors: list[str] = []

    for pyfile in sorted(path.rglob("*.py")):
        if is_excluded_development_path(pyfile.relative_to(path)) or pyfile.is_symlink():
            continue

        try:
            tree = ast.parse(pyfile.read_bytes(), filename=str(pyfile))
        except (SyntaxError, OSError):
            continue

        usage = _FetchUsage()
        usage.visit(tree)
        if usage.errors:
            all_errors.append(f"\n  {pyfile}:")
            for error in usage.errors:
                all_errors.append(f"    {error}")

    if all_errors:
        print(
            "SDK 2.x requires using response.data to access the response body. "
            "context.fetch() now returns a FetchResponse object."
        )
        for line in all_errors:
            print(line)
        return 1

    return 0


def main() -> int:
    """Parse arguments and run fetch pattern check."""
    parser = argparse.ArgumentParser(
        description="Check context.fetch() usage patterns match SDK version.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Exit codes:
  0  Patterns are correct (possibly with warnings)
  1  Pattern issues found
  2  An error occurred

Examples:
  %(prog)s my-integration
  %(prog)s integration-a integration-b
""",
    )
    parser.add_argument(
        "dirs",
        nargs="+",
        metavar="dir",
        help="Integration directories to check",
    )

    args = parser.parse_args()

    exit_code = 0
    for dir_path in args.dirs:
        print(f"\n{'=' * 60}")
        print(f"Fetch pattern: {dir_path}")
        print(f"{'=' * 60}")

        result = check_fetch_pattern(dir_path)
        if result == 0:
            print("✅ Fetch patterns OK")
        if result > exit_code:
            exit_code = result

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
