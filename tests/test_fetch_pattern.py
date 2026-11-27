"""Observable fetch-check behavior shared by local and CI validation."""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hiveup.checks.static import check_fetch  # noqa: E402
from hiveup.cli import app  # noqa: E402


def _integration(tmp_path: Path, source: str, requirement: str = "autohive-integrations-sdk~=2.1.0") -> Path:
    integration = tmp_path / "demo"
    integration.mkdir()
    (integration / "config.json").write_text("{}\n", encoding="utf-8")
    (integration / "requirements.txt").write_text(requirement + "\n", encoding="utf-8")
    (integration / "demo.py").write_text(textwrap.dedent(source), encoding="utf-8")
    return integration


@pytest.mark.parametrize(
    "requirement",
    [
        "autohive-integrations-sdk~=2.1.0",
        "autohive_integrations_sdk~=2.1.0",
        "Autohive.Integrations.SDK~=2.1.0",
        "autohive-integrations-sdk>=2.1.0,~=2.1.0",
        "autohive-integrations-sdk==2.1.0",
    ],
)
def test_fetch_check_detects_raw_body_access_for_supported_sdk_requirements(tmp_path: Path, requirement: str) -> None:
    integration = _integration(
        tmp_path,
        """
        async def execute(context):
            response = await context.fetch('https://example.org')
            return response['items']
        """,
        requirement,
    )

    result = check_fetch(integration)

    assert result.status == "failed"
    assert "response.data" in result.raw_output


@pytest.mark.parametrize(
    "requirement",
    [
        "requests~=2.0",
        "# autohive-integrations-sdk~=2.1.0",
        "autohive-integrations-sdk~=",
        "autohive-integrations-sdk>=2.1.0,<3",
        "autohive-integrations-sdk~=2.1.0; python_version >= '3.13'",
        None,
    ],
)
def test_focused_fetch_check_reports_unverifiable_sdk_requirements(tmp_path: Path, requirement: str | None) -> None:
    integration = _integration(tmp_path, "VALUE = 1", requirement or "")
    if requirement is None:
        (integration / "requirements.txt").unlink()

    result = check_fetch(integration)

    assert result.status == "failed"
    assert "requirements.txt" in result.raw_output or "autohive-integrations-sdk" in result.raw_output


@pytest.mark.parametrize(
    "body",
    [
        "response: FetchResponse = await context.fetch(url)\nreturn response.get('items')",
        "ctx = context\nresponse = await ctx.fetch(url)\nreturn response['items']",
        "response = await context.fetch(url)\nalias = response\nreturn alias.get('items')",
        "response = await context.fetch(url)\nreturn isinstance(response, (dict, list))",
        "response = await context.fetch(url)\nreturn isinstance(response, dict | list)",
        "response = await context.fetch(url)\nreturn ActionResult(data=response)",
        "return ActionResult(data=await context.fetch(url))",
        "return (await context.fetch(url))['items']",
        "response = await context.fetch(url)\n"
        "def response(items=response.get('items')):\n    return items\nreturn response()",
        "response = await context.fetch(url)\n"
        "def parse(*, response=response['items']):\n    return response\nreturn parse()",
        "response = await context.fetch(url)\nparse = lambda response=response.get('items'): response\nreturn parse()",
        "response = await context.fetch(url)\n"
        "@decorate(response.get('items'))\ndef parse():\n    return []\nreturn parse()",
        "response = await context.fetch(url)\n@decorate(response['items'])\nclass Parsed:\n    pass\nreturn Parsed()",
        "response = await context.fetch(url)\nclass Parsed(response.get('base', object)):\n    pass\nreturn Parsed()",
        "response = await context.fetch(url)\n"
        "class Parsed(metaclass=response.get('metaclass', type)):\n    pass\nreturn Parsed()",
        "response = await context.fetch(url)\n"
        "class Parser:\n    response = {}\n    def parse(self):\n        return response.get('items')\n"
        "return Parser().parse()",
        "response = await context.fetch(url)\n"
        "class response:\n    items = response.get('items')\nreturn response.items",
        "response = await context.fetch(url)\ndef parse(items: response.get('type', list)):\n    return items",
        "response = await context.fetch(url)\ndef parse() -> response.get('type', list):\n    return []",
        "response = await context.fetch(url)\n"
        "match response.status:\n    case 200 if response.get('ready'):\n        return response.data",
    ],
)
def test_fetch_check_rejects_unambiguous_raw_response_uses(tmp_path: Path, body: str) -> None:
    source = (
        "from autohive_integrations_sdk import ActionResult, ExecutionContext, FetchResponse\n"
        "async def execute(context: ExecutionContext):\n" + textwrap.indent(body, "    ") + "\n"
    )
    integration = _integration(tmp_path, source)

    assert check_fetch(integration).status == "failed"


def test_fetch_check_recognizes_sdk_type_and_module_aliases(tmp_path: Path) -> None:
    integration = _integration(
        tmp_path,
        """
        import autohive_integrations_sdk as sdk
        from autohive_integrations_sdk import ExecutionContext as Context

        async def execute(client: 'Context'):
            response: sdk.FetchResponse = await client.fetch('https://example.org')
            return sdk.ActionResult(data=response)
        """,
    )

    assert check_fetch(integration).status == "failed"


@pytest.mark.parametrize(
    "annotation",
    [
        "Optional[ExecutionContext]",
        "t.Optional[ExecutionContext]",
        "Maybe[Context]",
        "'Optional[Context]'",
        "ExecutionContext | None",
        "None | Context",
        "Union[ExecutionContext, None]",
        "t.Union[None, Context]",
    ],
)
@pytest.mark.parametrize("body_access", [".get('items')", ".data.get('items')"])
def test_fetch_check_recognizes_nullable_sdk_context_annotations(
    tmp_path: Path, annotation: str, body_access: str
) -> None:
    integration = _integration(
        tmp_path,
        "import typing as t\n"
        "from typing import Optional, Optional as Maybe, Union\n"
        "from autohive_integrations_sdk import ExecutionContext, ExecutionContext as Context\n"
        f"async def execute(client: {annotation} = None):\n"
        "    if client is None:\n        return []\n"
        "    response = await client.fetch('https://example.org')\n"
        f"    return response{body_access}\n",
    )

    assert check_fetch(integration).status == ("passed" if body_access.startswith(".data") else "failed")


@pytest.mark.parametrize(
    "source",
    [
        """
        async def first(context):
            response = await context.fetch(url)
            return response.data
        def second(response):
            return response.get('items')
        """,
        """
        async def execute(context):
            response = await context.fetch(url)
            response = response.data
            return response.get('items')
        """,
        """
        from autohive_integrations_sdk import FetchResponse
        async def execute(context):
            response = await context.fetch(url)
            assert isinstance(response, FetchResponse)
            return response.data, response.status, response.headers
        """,
        """
        from autohive_integrations_sdk import ActionResult
        async def execute(client):
            response = await client.fetch(url)
            return response.get('items')
        """,
        """
        async def execute(context: OtherClient):
            response = await context.fetch(url)
            return response.get('items')
        """,
        """
        async def execute(context):
            response = await context.fetch(url)
            def nested(response):
                return response.get('items')
            return nested(response.data)
        """,
        """
        async def execute(context):
            response = await context.fetch(url)
            parse = lambda response: response.get('items')
            return parse(response.data)
        """,
        """
        async def execute(context):
            response = await context.fetch(url)
            def parse(response=response.data):
                return response.get('items')
            return parse()
        """,
        """
        async def execute(context):
            fetched = await context.fetch(url)
            response = fetched.data
            class Parser:
                response = fetched
                def parse(self):
                    return response.get('items')
            return Parser().parse()
        """,
        """
        async def execute(context):
            fetched = await context.fetch(url)
            response = fetched
            class Parser:
                response = fetched.data
                def parse(self, items=response.get('items')):
                    return items
            return Parser().parse()
        """,
        """
        async def execute(context):
            response = await context.fetch(url)
            class response:
                items = response.data.get('items')
            return response.items
        """,
        """
        from __future__ import annotations
        async def execute(context):
            response = await context.fetch(url)
            def parse(items: response.get('type', list)) -> response.get('type', list):
                return items
            return parse([])
        """,
        """
        async def execute(context):
            response = await context.fetch(url)
            def parse(items: "response.get('type', list)") -> "response.get('type', list)":
                return items
            return parse([])
        """,
        """
        async def execute(context):
            response = await context.fetch(url)
            def parse(items: response.data.get('type', list)) -> response.data.get('type', list):
                return items
            return parse([])
        """,
        """
        async def execute(context):
            response = await context.fetch(url)
            parse = lambda *, response=response.data: response.get('items')
            return parse()
        """,
        """
        from typing import Optional
        async def execute(context: Optional[OtherClient]):
            response = await context.fetch(url)
            return response.get('items')
        """,
        """
        from autohive_integrations_sdk import ExecutionContext
        async def execute(context: ExecutionContext | OtherClient | None):
            response = await context.fetch(url)
            return response.get('items')
        """,
        """
        from autohive_integrations_sdk import ExecutionContext
        from other_client import Optional
        async def execute(context: Optional[ExecutionContext]):
            response = await context.fetch(url)
            return response.get('items')
        """,
        """
        async def execute(context):
            response = await context.fetch(url)
            return [response.get('value') for response in response.data]
        """,
        """
        async def execute(context):
            if enabled:
                response = await context.fetch(url)
                return response.data
            else:
                response = {'items': []}
                return response.get('items')
        """,
        """
        async def execute(context):
            response = {'items': []}
            values = response.get('items')
            response = await context.fetch(url)
            return response.data, values
        """,
        """
        from autohive_integrations_sdk import HTTPError
        async def execute(context):
            try:
                response = await context.fetch(url)
                return response.data
            except HTTPError as response:
                return response.headers.get('Retry-After')
        """,
    ],
)
def test_fetch_check_preserves_valid_and_unrelated_response_uses(tmp_path: Path, source: str) -> None:
    integration = _integration(tmp_path, source)

    assert check_fetch(integration).status == "passed"


@pytest.mark.parametrize("body_access", [".get('items')", ".data.get('items')"])
def test_fetch_check_isolates_match_cases(tmp_path: Path, body_access: str) -> None:
    integration = _integration(
        tmp_path,
        "async def execute(context):\n"
        "    response = await context.fetch(url)\n"
        "    match response.status:\n"
        "        case 200:\n"
        "            response = response.data\n"
        "            return response.get('items')\n"
        "        case 201:\n"
        f"            return response{body_access}\n",
    )

    assert check_fetch(integration).status == ("passed" if body_access.startswith(".data") else "failed")


@pytest.mark.parametrize("pattern", ["{'item': response}", "{'item': _, **response}", "[*response]"])
def test_fetch_check_does_not_confuse_match_captures_with_the_response(tmp_path: Path, pattern: str) -> None:
    integration = _integration(
        tmp_path,
        "async def execute(context):\n"
        "    response = await context.fetch(url)\n"
        "    match response.data:\n"
        f"        case {pattern}:\n"
        "            return isinstance(response, (dict, list))\n",
    )

    assert check_fetch(integration).status == "passed"


@pytest.mark.parametrize("exhaustive", [True, False])
def test_fetch_check_merges_match_cases_without_assuming_a_match(tmp_path: Path, exhaustive: bool) -> None:
    source = (
        "async def execute(context, enabled):\n"
        "    response = {}\n"
        "    match enabled:\n"
        "        case True:\n"
        "            response = await context.fetch(url)\n"
    )
    if exhaustive:
        source += "        case _:\n            response = await context.fetch(url)\n"
    source += "    return response.get('items')\n"
    integration = _integration(tmp_path, source)

    assert check_fetch(integration).status == ("failed" if exhaustive else "passed")


def test_fetch_check_keeps_sdk1_body_semantics(tmp_path: Path) -> None:
    integration = _integration(
        tmp_path,
        "async def execute(context):\n    response = await context.fetch(url)\n    return response.get('items')\n",
        "autohive-integrations-sdk~=1.1.1",
    )

    assert check_fetch(integration).status == "passed"


@pytest.mark.parametrize("directory", ["tests", "dependencies", ".venv", "__pycache__", "helpers/.hidden"])
def test_fetch_check_ignores_excluded_development_files(tmp_path: Path, directory: str) -> None:
    integration = _integration(tmp_path, "VALUE = 1")
    excluded = integration / directory / "old_example.py"
    excluded.parent.mkdir(parents=True)
    excluded.write_text(
        "async def execute(context):\n    response = await context.fetch(url)\n    return response.get('items')\n",
        encoding="utf-8",
    )

    assert check_fetch(integration).status == "passed"


def test_fetch_check_still_checks_deployed_helper_modules(tmp_path: Path) -> None:
    integration = _integration(tmp_path, "VALUE = 1")
    helper = integration / "helpers" / "client.py"
    helper.parent.mkdir()
    helper.write_text(
        "async def execute(context):\n    response = await context.fetch(url)\n    return response.get('items')\n",
        encoding="utf-8",
    )

    assert check_fetch(integration).status == "failed"


@pytest.mark.parametrize("valid", [True, False])
def test_local_and_compatibility_entry_points_agree_outside_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, valid: bool
) -> None:
    integration = _integration(
        tmp_path,
        "async def execute(context):\n    response = await context.fetch(url)\n"
        f"    return response{'.data' if valid else ''}.get('items')\n",
        "autohive_integrations_sdk~=2.1.0",
    )
    monkeypatch.chdir(tmp_path)
    local = CliRunner().invoke(app, ["check", "fetch", str(integration), "--json"])
    validate = CliRunner().invoke(app, ["validate", str(integration), "--only", "fetch", "--json"])
    compatibility = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_fetch_pattern.py"), str(integration)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    expected = 0 if valid else 1
    assert local.exit_code == validate.exit_code == compatibility.returncode == expected
    assert json.loads(local.output)["results"][0]["status"] == ("passed" if valid else "failed")
    assert json.loads(validate.output)["results"][0]["status"] == ("passed" if valid else "failed")
