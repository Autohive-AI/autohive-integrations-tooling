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
        self.bindings: dict[str, str] = {"dict": "body_type", "list": "body_type", "isinstance": "builtin_isinstance"}
        self.errors: list[str] = []
        self.class_outer: dict[str, str] | None = None
        self.deferred_annotations = False
        self.function_scope = False
        self.later_writes: set[str] = set()

    def _symbol(self, node: ast.AST | None) -> str | None:
        if isinstance(node, ast.Name):
            return self.bindings.get(node.id)
        if isinstance(node, ast.Attribute):
            module = self._symbol(node.value)
            if module == "sdk":
                return "sdk" if node.attr == "integration" else node.attr
            if module == "typing":
                return f"typing.{node.attr}"
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            try:
                return self._symbol(ast.parse(node.value, mode="eval").body)
            except SyntaxError:
                pass
        members = []
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            members = [node.left, node.right]
        elif isinstance(node, ast.Subscript):
            symbol = self._symbol(node.value)
            if symbol == "typing.Optional":
                return self._symbol(node.slice)
            if symbol == "typing.Union":
                members = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
        if members:
            symbols = {
                self._symbol(member)
                for member in members
                if not (isinstance(member, ast.Constant) and member.value is None)
            }
            return symbols.pop() if len(symbols) == 1 else None
        return None

    def _value_kind(self, node: ast.AST | None) -> str | None:
        if isinstance(node, (ast.Name, ast.Attribute)):
            return self._symbol(node)
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

    def _body(self, body: list[ast.AST]):
        outer_later = self.later_writes
        for index, statement in enumerate(body):
            self.later_writes = outer_later.copy()
            if self.class_outer is None:  # Class-local writes do not rebind method closures.
                for following in body[index:]:
                    self.later_writes.update(self._written_names(following))
            self.visit(statement)
        self.later_writes = outer_later

    def visit_Module(self, node: ast.Module):
        self._body(node.body)

    def _branches(self, bodies: list[list[ast.AST]]):
        before = self.bindings.copy()
        outcomes = []
        for body in bodies:
            self.bindings = before.copy()
            self._body(body)
            outcomes.append(self.bindings)
        self._merge(outcomes)

    def _merge(self, outcomes: list[dict[str, str]]):
        # A value is proven after a branch only when every path agrees.
        self.bindings = {
            name: kind for name, kind in outcomes[0].items() if all(other.get(name) == kind for other in outcomes[1:])
        }

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            name = alias.asname or alias.name.split(".")[0]
            self._bind(ast.Name(id=name))
            if alias.name in {"autohive_integrations_sdk", "autohive_integrations_sdk.integration"} or (
                alias.asname is None and alias.name.startswith("autohive_integrations_sdk.")
            ):
                self.bindings[name] = "sdk"
            elif alias.name == "typing":
                self.bindings[name] = "typing"

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.level == 0 and node.module == "__future__" and any(a.name == "annotations" for a in node.names):
            self.deferred_annotations = True
        for alias in node.names:
            if alias.name == "*":
                self.bindings.clear()  # Unknown exports may replace any proven symbol.
                return
            name = alias.asname or alias.name
            self.bindings.pop(name, None)
            if node.level == 0 and node.module in {
                "autohive_integrations_sdk",
                "autohive_integrations_sdk.integration",
            }:
                self.bindings[name] = "sdk" if alias.name == "integration" else alias.name
            elif node.level == 0 and node.module == "typing" and alias.name in {"Optional", "Union"}:
                self.bindings[name] = f"typing.{alias.name}"

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef):
        args = [*node.args.posonlyargs, *node.args.args]
        if node.args.vararg is not None:
            args.append(node.args.vararg)
        args.extend(node.args.kwonlyargs)
        if node.args.kwarg is not None:
            args.append(node.args.kwarg)
        for expression in [*node.decorator_list, *node.args.defaults, *node.args.kw_defaults]:
            if expression is not None:
                self.visit(expression)
        annotation_outer = self.bindings
        if node.type_params:
            self.bindings = self.bindings.copy()
            for parameter in node.type_params:
                self.bindings.pop(parameter.name, None)
        annotations = []
        for arg in args:
            annotations.append(self._symbol(arg.annotation))
            if not self.deferred_annotations and arg.annotation is not None:
                self.visit(arg.annotation)
        if not self.deferred_annotations and node.returns is not None:
            self.visit(node.returns)
        if node.type_params:
            self.bindings = annotation_outer
        self.bindings.pop(node.name, None)
        outer = self.bindings
        class_outer = self.class_outer
        function_scope = self.function_scope
        # Signatures use the class namespace; method bodies do not close over it.
        self.bindings = (class_outer if class_outer is not None else outer).copy()
        later_writes = self.later_writes
        for name in later_writes:
            self.bindings.pop(name, None)
        self.later_writes = set()
        self.class_outer = None
        self.function_scope = True
        for parameter in node.type_params:
            self.bindings.pop(parameter.name, None)
        for arg, annotation in zip(args, annotations):
            kind = None
            if arg not in (node.args.vararg, node.args.kwarg):
                kind = {"ExecutionContext": "context", "FetchResponse": "response"}.get(annotation)
                if arg.arg == "context" and arg.annotation is None:
                    # Preserve the conventional unannotated SDK handler parameter.
                    kind = "context"
            self._bind(ast.Name(id=arg.arg), kind)
        self._body(node.body)
        self.bindings = outer
        self.class_outer = class_outer
        self.function_scope = function_scope
        self.later_writes = later_writes

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node: ast.Lambda):
        for default in [*node.args.defaults, *node.args.kw_defaults]:
            if default is not None:
                self.visit(default)
        outer = self.bindings
        class_outer = self.class_outer
        self.bindings = (class_outer if class_outer is not None else outer).copy()
        later_writes = self.later_writes
        for name in later_writes:
            self.bindings.pop(name, None)
        self.later_writes = set()
        self.class_outer = None
        args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        args.extend(arg for arg in (node.args.vararg, node.args.kwarg) if arg is not None)
        for arg in args:
            self.bindings.pop(arg.arg, None)
        self.visit(node.body)
        self.bindings = outer
        self.class_outer = class_outer
        self.later_writes = later_writes

    def _class_escapes(self, node: ast.ClassDef):
        # Explicitly escaped class bindings are outside the class-local model.
        pending = list(node.body)
        while pending:
            child = pending.pop()
            if isinstance(child, (ast.Nonlocal, ast.Global)):
                yield from child.names
            elif not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                pending.extend(ast.iter_child_nodes(child))

    def visit_ClassDef(self, node: ast.ClassDef):
        for expression in node.decorator_list:
            self.visit(expression)
        defining = self.bindings
        if node.type_params:
            self.bindings = self.bindings.copy()
            for parameter in node.type_params:
                self.bindings.pop(parameter.name, None)
        for expression in [*node.bases, *node.keywords]:
            self.visit(expression)
        if node.type_params:
            self.bindings = defining
        outer = self.bindings
        class_outer = self.class_outer
        function_scope = self.function_scope
        enclosing = class_outer if class_outer is not None else outer
        self.bindings = enclosing.copy()
        self.class_outer = enclosing.copy()
        self.function_scope = False
        for parameter in node.type_params:
            self.bindings.pop(parameter.name, None)
            self.class_outer.pop(parameter.name, None)
        # The old name remains visible in the class body, but not in later methods.
        self.class_outer.pop(node.name, None)
        escaped = set(self._class_escapes(node))
        for name in escaped:
            self.class_outer.pop(name, None)
        self._body(node.body)
        self.bindings = outer
        self.bindings.pop(node.name, None)
        self.class_outer = class_outer
        self.function_scope = function_scope
        for name in escaped:
            self.bindings.pop(name, None)
            if self.class_outer is not None:
                self.class_outer.pop(name, None)

    def visit_Global(self, node: ast.Global):
        for name in node.names:
            self.bindings.pop(name, None)  # Do not confuse a lexical local with a module global.

    def _assign_target(self, target: ast.AST, kind: str | None = None):
        if isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                self._assign_target(element)
        elif isinstance(target, ast.Starred):
            self._assign_target(target.value)
        else:
            self.visit(target)
            self._bind(target, kind)

    def visit_Delete(self, node: ast.Delete):
        for target in node.targets:
            self._assign_target(target)

    def visit_Assign(self, node: ast.Assign):
        kind = self._value_kind(node.value)
        self.visit(node.value)
        for target in node.targets:
            self._assign_target(target, kind)

    def visit_AnnAssign(self, node: ast.AnnAssign):
        if node.value is not None:
            kind = self._value_kind(node.value)
            self.visit(node.value)
            self._assign_target(node.target, kind)
        elif isinstance(node.target, (ast.Attribute, ast.Subscript)):
            # Evaluate the receiver/index, but not the outer get/set operation.
            self.visit(node.target.value)
            if isinstance(node.target, ast.Subscript):
                self.visit(node.target.slice)
        if not self.function_scope and not self.deferred_annotations:
            self.visit(node.annotation)

    def visit_TypeAlias(self, node: ast.TypeAlias):
        self._bind(node.name)  # The value and type parameter bounds are lazy.

    def visit_AugAssign(self, node: ast.AugAssign):
        self.generic_visit(node)
        self._bind(node.target)

    def visit_NamedExpr(self, node: ast.NamedExpr):
        kind = self._value_kind(node.value)
        self.visit(node.value)
        self._bind(node.target, kind)

    def visit_Assert(self, node: ast.Assert):
        self.visit(node.test)
        if node.msg is not None:
            before = self.bindings
            self.bindings = before.copy()
            self.visit(node.msg)
            self.bindings = before  # The message runs only on the raising path.

    def visit_If(self, node: ast.If):
        self.visit(node.test)
        self._branches([node.body, node.orelse])

    def visit_IfExp(self, node: ast.IfExp):
        self.visit(node.test)
        self._branches([[node.body], [node.orelse]])

    def visit_BoolOp(self, node: ast.BoolOp):
        outcomes = []
        for value in node.values:
            self.visit(value)
            outcomes.append(self.bindings.copy())  # Each operand may short-circuit.
        self._merge(outcomes)

    def visit_Compare(self, node: ast.Compare):
        self.visit(node.left)
        outcomes = []
        for comparator in node.comparators:
            self.visit(comparator)
            outcomes.append(self.bindings.copy())
        self._merge(outcomes)  # Later comparators may short-circuit.

    def visit_Dict(self, node: ast.Dict):
        for key, value in zip(node.keys, node.values):
            if key is not None:  # A missing key denotes **mapping unpacking.
                self.visit(key)
            self.visit(value)

    def visit_Match(self, node: ast.Match):
        self.visit(node.subject)
        unmatched = self.bindings.copy()
        outcomes = []
        for case in node.cases:
            self.bindings = unmatched.copy()
            for pattern in ast.walk(case.pattern):
                if isinstance(pattern, (ast.MatchAs, ast.MatchStar)) and pattern.name:
                    self.bindings.pop(pattern.name, None)
                elif isinstance(pattern, ast.MatchMapping) and pattern.rest:
                    self.bindings.pop(pattern.rest, None)
            self.visit(case.pattern)
            if case.guard is not None:
                self.visit(case.guard)
            # A failed guard can retain assignments, but a failed pattern may not.
            unmatched = {name: kind for name, kind in unmatched.items() if self.bindings.get(name) == kind}
            self._body(case.body)
            outcomes.append(self.bindings)
        if not any(
            case.guard is None and isinstance(case.pattern, ast.MatchAs) and case.pattern.pattern is None
            for case in node.cases
        ):
            outcomes.append(unmatched)  # No case is guaranteed to match.
        self._merge(outcomes)

    def visit_For(self, node: ast.For | ast.AsyncFor):
        self.visit(node.iter)
        before = self.bindings.copy()
        self._assign_target(node.target)
        self._body(node.body)
        self.bindings = {name: kind for name, kind in before.items() if self.bindings.get(name) == kind}
        self._branches([node.orelse, []])  # A break bypasses the else suite.

    visit_AsyncFor = visit_For

    def visit_While(self, node: ast.While):
        self.visit(node.test)
        self._branches([node.body, []])
        self._branches([node.orelse, []])

    def visit_With(self, node: ast.With | ast.AsyncWith):
        partial = self.bindings.copy()
        for name in self._written_names(node):
            partial.pop(name, None)
        for item in node.items:
            kind = self._value_kind(item.context_expr)
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self._assign_target(item.optional_vars, kind)
        self._body(node.body)
        self._merge([self.bindings, partial])  # A manager may suppress a partially executed body.

    visit_AsyncWith = visit_With

    def _written_names(self, node: ast.AST):
        """Names a statement can rebind in its enclosing scope."""
        children = ast.iter_child_nodes(node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node.name
            children = [*node.decorator_list, *node.args.defaults, *node.args.kw_defaults]
            if not self.deferred_annotations:
                args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
                args.extend(arg for arg in (node.args.vararg, node.args.kwarg) if arg is not None)
                children.extend([*(arg.annotation for arg in args), node.returns])
        elif isinstance(node, ast.ClassDef):
            yield node.name
            yield from self._class_escapes(node)
            children = [*node.decorator_list, *node.bases, *node.keywords]
        elif isinstance(node, ast.Lambda):
            children = [*node.args.defaults, *node.args.kw_defaults]
        elif isinstance(node, ast.TypeAlias):
            yield node.name.id
            return
        elif isinstance(node, ast.AnnAssign):
            children = []
            if node.value is not None:
                children.extend([node.value, node.target])
            elif isinstance(node.target, (ast.Attribute, ast.Subscript)):
                # An annotation alone does not bind its target.
                children.append(node.target.value)
                if isinstance(node.target, ast.Subscript):
                    children.append(node.target.slice)
            if not self.function_scope and not self.deferred_annotations:
                children.append(node.annotation)
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for target in self._walrus_targets(node):
                yield target.id
            return
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            yield node.id
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == "*":
                    yield from self.bindings
                else:
                    yield alias.asname or alias.name.split(".")[0]
        elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and node.name:
            yield node.name
        elif isinstance(node, ast.MatchMapping) and node.rest:
            yield node.rest
        for child in children:
            if child is not None:
                yield from self._written_names(child)

    def visit_Try(self, node: ast.Try | ast.TryStar):
        handler_entry = self.bindings.copy()
        for statement in node.body:
            for name in self._written_names(statement):
                handler_entry.pop(name, None)
        self._body(node.body)
        self._body(node.orelse)
        outcomes = [self.bindings]
        for handler in node.handlers:
            # A handler may run after any partially executed try-body statement.
            self.bindings = handler_entry.copy()
            self.visit(handler)
            outcomes.append(self.bindings)
            # except types execute in order; except* bodies can also run in sequence.
            for preceding in [handler] if isinstance(node, ast.TryStar) else [handler.type]:
                if preceding is not None:
                    for name in self._written_names(preceding):
                        handler_entry.pop(name, None)
        if node.finalbody:
            for statement in [*node.orelse, *node.handlers]:
                for name in self._written_names(statement):
                    handler_entry.pop(name, None)
            outcomes.append(handler_entry)  # Finally also runs on unhandled, partially executed paths.
        self._merge(outcomes)
        self._body(node.finalbody)

    visit_TryStar = visit_Try

    def visit_ExceptHandler(self, node: ast.ExceptHandler):
        if node.type is not None:
            self.visit(node.type)
        if node.name:
            self.bindings.pop(node.name, None)
        self._body(node.body)
        if node.name:
            self.bindings.pop(node.name, None)

    def _walrus_targets(self, node: ast.AST):
        if isinstance(node, ast.NamedExpr):
            yield node.target
        # Lambda defaults execute here; assignments in their bodies are local.
        children = (
            [*node.args.defaults, *node.args.kw_defaults]
            if isinstance(node, ast.Lambda)
            else ast.iter_child_nodes(node)
        )
        for child in children:
            if child is not None:
                yield from self._walrus_targets(child)

    def visit_ListComp(self, node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp):
        # Only the first iterable uses the defining (possibly class) namespace.
        self.visit(node.generators[0].iter)
        outer = self.bindings
        class_outer = self.class_outer
        self.bindings = (class_outer if class_outer is not None else outer).copy()
        if isinstance(node, ast.GeneratorExp):
            for name in self.later_writes:
                self.bindings.pop(name, None)
        self.class_outer = None
        for index, generator in enumerate(node.generators):
            if index:
                self.visit(generator.iter)
            self._assign_target(generator.target)
            for condition in generator.ifs:
                self.visit(condition)
        if isinstance(node, ast.DictComp):
            self.visit(node.key)
            self.visit(node.value)
        else:
            self.visit(node.elt)
        self.bindings = outer
        self.class_outer = class_outer
        for target in self._walrus_targets(node):
            self._bind(target)  # The comprehension may execute zero times.

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp

    def visit_Subscript(self, node: ast.Subscript):
        if self._value_kind(node.value) == "response":
            self.errors.append(
                f"Line {node.lineno}: raw fetch response subscript — use response.data[...] with SDK 2.x"
            )
        self.generic_visit(node)

    def _is_body_type(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Tuple):
            return bool(node.elts) and all(self._is_body_type(item) for item in node.elts)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return self._is_body_type(node.left) and self._is_body_type(node.right)
        return isinstance(node, ast.Name) and self._symbol(node) == "body_type"

    def visit_Call(self, node: ast.Call):
        callee = self._symbol(node.func)
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and self._value_kind(node.func.value) == "response"
        ):
            self.errors.append(
                f"Line {node.lineno}: raw fetch response .get(...) — use response.data.get(...) with SDK 2.x"
            )
        self.visit(node.func)
        checked_response = False
        for index, argument in enumerate(node.args):
            kind = self._value_kind(argument)
            self.visit(argument)
            if index == 0:
                checked_response = kind == "response"
            elif (
                callee == "builtin_isinstance"
                and len(node.args) == 2
                and checked_response
                and self._is_body_type(argument)
            ):
                self.errors.append(
                    f"Line {node.lineno}: raw fetch response body type check — use isinstance(response.data, ...) with SDK 2.x"
                )
        for keyword in node.keywords:
            kind = self._value_kind(keyword.value)
            self.visit(keyword.value)
            if callee == "ActionResult" and keyword.arg == "data" and kind == "response":
                self.errors.append(
                    f"Line {node.lineno}: ActionResult(data=...) receives a raw fetch response — pass response.data with SDK 2.x"
                )


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
