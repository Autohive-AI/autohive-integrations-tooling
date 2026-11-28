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
        "response = await context.fetch(url)\nclass Parsed:\n    items: response.get('type', list)",
        "response = await context.fetch(url)\nclass Parsed:\n    items: response.get('type', list) = []",
        "response = await context.fetch(url)\nfor response['item'] in [1]:\n    pass",
        "response = await context.fetch(url)\nresponse[response.get('items')]: int",
        "response = await context.fetch(url)\nresponse.get('items').value: int",
        "from contextlib import nullcontext\nresponse = await context.fetch(url)\n"
        "with nullcontext(1) as response['item']:\n    pass",
        "response = await context.fetch(url)\ntry:\n    raise ValueError()\n"
        "except ValueError:\n    return response.get('items')",
        "response = await context.fetch(url)\ntry:\n    response: dict\n    raise ValueError()\n"
        "except ValueError:\n    return response.get('items')",
        "response = await context.fetch(url)\n"
        "try:\n    raise ValueError()\nexcept response.get('exception', ValueError):\n    pass",
        "fetched = await context.fetch(url)\nresponse = fetched\n"
        "class Parsed:\n    response = fetched.data\n    rows = [response.get('items') for _ in range(2)]",
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


@pytest.mark.parametrize(
    ("imports", "annotation"),
    [
        ("from autohive_integrations_sdk import ExecutionContext as Context", "Context"),
        ("from autohive_integrations_sdk.integration import ExecutionContext as Context", "Context"),
        ("import autohive_integrations_sdk.integration", "autohive_integrations_sdk.ExecutionContext"),
        ("import autohive_integrations_sdk.integration", "autohive_integrations_sdk.integration.ExecutionContext"),
        ("import autohive_integrations_sdk.integration as implementation", "implementation.ExecutionContext"),
        ("from autohive_integrations_sdk import integration as implementation", "implementation.ExecutionContext"),
    ],
)
def test_fetch_check_recognizes_sdk_type_and_module_aliases(tmp_path: Path, imports: str, annotation: str) -> None:
    integration = _integration(
        tmp_path,
        "import autohive_integrations_sdk as sdk\n"
        f"{imports}\n"
        f"async def execute(client: '{annotation}'):\n"
        "    response: sdk.FetchResponse = await client.fetch('https://example.org')\n"
        "    return sdk.ActionResult(data=response)\n",
    )

    assert check_fetch(integration).status == "failed"


@pytest.mark.parametrize(
    ("source", "status"),
    [
        (
            "from autohive_integrations_sdk import ExecutionContext as Client\n"
            "from vendor import *\n"
            "async def execute(client: Client):\n"
            "    response = await client.fetch(url)\n    return response.get('items')\n",
            "passed",
        ),
        (
            "from autohive_integrations_sdk import ActionResult as Result\n"
            "from vendor import *\n"
            "async def execute(context):\n"
            "    response = await context.fetch(url)\n    return Result(data=response)\n",
            "passed",
        ),
        (
            "BodyType = list\nfrom vendor import *\n"
            "async def execute(context):\n"
            "    response = await context.fetch(url)\n    return isinstance(response, BodyType)\n",
            "passed",
        ),
        (
            "from autohive_integrations_sdk import ExecutionContext as Client\n"
            "try:\n    from vendor import *\n    raise ValueError()\nexcept ValueError:\n"
            "    async def execute(client: Client):\n"
            "        response = await client.fetch(url)\n        return response.get('items')\n",
            "passed",
        ),
        (
            "from autohive_integrations_sdk import ExecutionContext as Client\n"
            "from vendor import Client\n"
            "async def execute(client: Client):\n"
            "    response = await client.fetch(url)\n    return response.get('items')\n",
            "passed",
        ),
        (
            "from vendor import *\nfrom autohive_integrations_sdk import ExecutionContext as Client\n"
            "async def execute(client: Client):\n"
            "    response = await client.fetch(url)\n    return response.get('items')\n",
            "failed",
        ),
        (
            "from vendor import *\nfrom autohive_integrations_sdk import ActionResult as Result\n"
            "async def execute(context):\n"
            "    response = await context.fetch(url)\n    return Result(data=response)\n",
            "failed",
        ),
        (
            "from autohive_integrations_sdk import ExecutionContext as Client\n"
            "async def execute(context):\n"
            "    client = Client()\n    response = await client.fetch(url)\n    return response.get('items')\n"
            "from vendor import Client\n",
            "passed",
        ),
        (
            "from autohive_integrations_sdk import ExecutionContext as Client\n"
            "async def execute(context):\n"
            "    client = Client()\n    response = await client.fetch(url)\n    return response.get('items')\n"
            "from vendor import *\n",
            "passed",
        ),
        (
            "from autohive_integrations_sdk import ActionResult as Result\n"
            "async def execute(context):\n"
            "    response = await context.fetch(url)\n    return Result(data=response)\n"
            "from vendor import Result\n",
            "passed",
        ),
        (
            "Check = isinstance\nasync def execute(context):\n"
            "    response = await context.fetch(url)\n    return Check(response, list)\n"
            "from vendor import Check\n",
            "passed",
        ),
    ],
)
def test_fetch_check_invalidates_imported_symbols_in_source_order(tmp_path: Path, source: str, status: str) -> None:
    integration = _integration(tmp_path, source)

    assert check_fetch(integration).status == status


@pytest.mark.parametrize(
    "definition",
    [
        "def parse():\n    return response.get('items')\nreturn parse()",
        "parse = lambda: response.get('items')\nreturn parse()",
        "class Parser:\n    def parse(self):\n        return response.get('items')\nreturn Parser().parse()",
        "parsed = (response.get('items') for _ in [1])\nreturn list(parsed)",
    ],
)
@pytest.mark.parametrize("unwrap", [True, False])
@pytest.mark.parametrize("try_finally", [True, False])
def test_fetch_check_does_not_assume_captured_names_are_early_bound(
    tmp_path: Path, definition: str, unwrap: bool, try_finally: bool
) -> None:
    before_return, call = definition.rsplit("\n", 1)
    source = "async def execute(context):\n    response = await context.fetch(url)\n"
    if try_finally:
        source += "    try:\n" + textwrap.indent(before_return, "        ") + "\n    finally:\n"
        source += "        response = response.data\n" if unwrap else "        pass\n"
    else:
        source += textwrap.indent(before_return, "    ") + "\n"
        if unwrap:
            source += "    response = response.data\n"
    source += "    " + call + "\n"
    integration = _integration(tmp_path, source)

    assert check_fetch(integration).status == ("passed" if unwrap else "failed")


@pytest.mark.parametrize("escaped", [True, False])
def test_fetch_check_invalidates_class_global_escapes(tmp_path: Path, escaped: bool) -> None:
    source = (
        "from autohive_integrations_sdk import ExecutionContext\n"
        "class OtherClient:\n"
        "    async def fetch(self, url):\n"
        "        return {'items': [1]}\n"
        "class Bootstrap:\n"
        + ("    global ExecutionContext\n" if escaped else "")
        + "    ExecutionContext = OtherClient\n"
        "async def execute(context):\n"
        "    client = ExecutionContext()\n"
        "    response = await client.fetch('https://example.org')\n"
        "    return response.get('items')\n"
    )
    integration = _integration(tmp_path, source)

    assert check_fetch(integration).status == ("passed" if escaped else "failed")


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
        """
        async def execute(context):
            fetched = await context.fetch(url)
            response = fetched
            class Parsed:
                rows = [(lambda: response.get('items'))() for response in fetched.data]
            return Parsed.rows
        """,
        """
        async def execute(context):
            fetched = await context.fetch(url)
            response = fetched.data
            class Parsed:
                response = fetched
                rows = [response.get('items') for _ in range(2)]
            return Parsed.rows
        """,
        """
        from __future__ import annotations
        async def execute(context):
            response = await context.fetch(url)
            class Parsed:
                items: response.get('type', list)
            return Parsed
        """,
        """
        async def execute(context):
            response = await context.fetch(url)
            items: response.get('type', list)
            class Parsed:
                response: response.get('type', list) = {'type': list}
                def parse(self):
                    items: response.get('type', list)
                    return []
            return Parsed
        """,
        """
        from autohive_integrations_sdk import FetchResponse
        async def execute(context):
            response = await context.fetch(url)
            list = FetchResponse
            assert isinstance(response, dict | list)
            return response.data
        """,
        """
        import autohive_integrations_sdk as sdk
        async def execute(context):
            response = await context.fetch(url)
            list = sdk.FetchResponse
            assert isinstance(response, (dict, list))
            return response.data
        """,
        """
        async def execute(context):
            response = await context.fetch(url)
            try:
                response = response.data
                raise ValueError()
            except ValueError:
                return response.get('items')
        """,
        """
        async def execute(context):
            fetched = await context.fetch(url)
            response = fetched
            try:
                response = response.data
                raise ValueError()
                response = fetched
            except ValueError:
                return response.get('items')
        """,
        """
        async def execute(context):
            fetched = await context.fetch(url)
            response = fetched.data
            False and (response := fetched)
            return response.get('items')
        """,
        """
        async def execute(context):
            fetched = await context.fetch(url)
            response = fetched.data
            unused = (response := fetched) if False else None
            return response.get('items')
        """,
        """
        async def execute(context):
            response = await context.fetch(url)
            response['items']: response.get('type', list)
            type Parsed = response.get('type', list)
            return response.data
        """,
        """
        from autohive_integrations_sdk import FetchResponse
        def isinstance(value, cls):
            return value.status
        def parse(response: FetchResponse):
            return isinstance(response, list)
        async def execute(context):
            fetched = await context.fetch(url)
            return parse(fetched)
        """,
    ],
)
def test_fetch_check_preserves_valid_and_unrelated_response_uses(tmp_path: Path, source: str) -> None:
    integration = _integration(tmp_path, source)

    assert check_fetch(integration).status == "passed"


@pytest.mark.parametrize(
    ("body", "status"),
    [
        (
            "response = fetched.data\nfor item in response['items']:\n    break\n"
            "else:\n    response = fetched\n    return response.data\nreturn response.get('items')",
            "passed",
        ),
        (
            "response = fetched.data\nwhile response['items']:\n    break\n"
            "else:\n    response = fetched\n    return response.data\nreturn response.get('items')",
            "passed",
        ),
        (
            "try:\n    item: (response := dict) = 1\n    raise ValueError()\n"
            "except ValueError:\n    return response.get('items')",
            "failed",
        ),
        ("return ActionResult(cost_usd=float(len((response := response.data))), data=response)", "passed"),
        (
            "response = fetched.data\n"
            "return ActionResult(cost_usd=float(len((response := fetched).data)), data=response)",
            "failed",
        ),
        ("return ActionResult(data=response, cost_usd=float(len((response := response.data))))", "failed"),
        (
            "def parse(*args: (response := response.data), item: response.get('items')):\n    return item\n"
            "return parse(item=[1])",
            "passed",
        ),
        (
            "response = fetched.data\n"
            "def parse(*args: (response := fetched), item: response.get('items')):\n    return item\n"
            "return parse(item=[1])",
            "failed",
        ),
        (
            "try:\n    raise ExceptionGroup('both', [TypeError(), ValueError()])\n"
            "except* TypeError:\n    response = response.data\n"
            "except* ValueError:\n    result = response.get('items')\nreturn result",
            "passed",
        ),
        (
            "try:\n    raise ValueError()\nexcept (response := response.data).get('exception', TypeError):\n"
            "    return []\nexcept ValueError:\n    return response.get('items')",
            "passed",
        ),
        ("response, response['x'] = response.data, 1\nreturn response.get('items')", "passed"),
        ("response['x'], response = 1, response.data\nreturn response.get('items')", "failed"),
        (
            "class Parsed:\n    nonlocal response\n    response = response.data\nreturn response.get('items')",
            "passed",
        ),
        (
            "try:\n    class Parsed:\n        nonlocal response\n        response = response.data\n"
            "    raise ValueError()\nexcept ValueError:\n    return response.get('items')",
            "passed",
        ),
        (
            "class Parsed:\n    def parse(self):\n        nonlocal response\n        response = response.data\n"
            "return response.get('items')",
            "failed",
        ),
        (
            "response = await context.fetch(url, headers=(context := {}))\nreturn response.get('items')",
            "failed",
        ),
        ("return ActionResult(data=await context.fetch(url, headers=(context := {})))", "failed"),
        (
            "class OtherClient:\n    async def fetch(self, url, **kwargs):\n        return {'items': [1]}\n"
            "client = OtherClient()\nresponse = await client.fetch(url, headers=(client := context).auth)\n"
            "return response.get('items')",
            "passed",
        ),
        (
            "def collect(*responses: FetchResponse):\n    return responses[0].data.get('items')\n"
            "return collect(fetched)",
            "passed",
        ),
        (
            "def collect(**responses: FetchResponse):\n    return responses['main'].data.get('items')\n"
            "return collect(main=fetched)",
            "passed",
        ),
        (
            "response = fetched.data\n"
            "result = {0: ActionResult(data=response), (response := fetched).status: 'metadata'}\nreturn result[0]",
            "passed",
        ),
        (
            "response = fetched.data\n"
            "result = {**{0: ActionResult(data=response)}, (response := fetched).status: 'metadata'}\n"
            "return result[0]",
            "passed",
        ),
        (
            "result = {0: ActionResult(data=response), len((response := response.data)): 'metadata'}\nreturn result[0]",
            "failed",
        ),
        (
            "response = fetched.data\n2 < 1 < (response := fetched).status\nreturn ActionResult(data=response)",
            "passed",
        ),
        (
            "response = fetched.data\n0 < (response := fetched).status < 500\nreturn ActionResult(data=response)",
            "failed",
        ),
        (
            "def parse[FetchResponse](response: FetchResponse):\n    return response.get('items')\n"
            "return parse(fetched.data)",
            "passed",
        ),
        (
            "class Parser[FetchResponse]:\n    def parse(self, response: FetchResponse):\n"
            "        return response.get('items')\nreturn Parser().parse(fetched.data)",
            "passed",
        ),
        (
            "ResponseType = FetchResponse\n"
            "def parse(item: ResponseType, other: (ResponseType := dict)):\n    return item.get('items')\n"
            "return parse(fetched, None)",
            "failed",
        ),
        (
            "ResponseType = dict\n"
            "def parse(item: ResponseType, other: (ResponseType := FetchResponse)):\n    return item.get('items')\n"
            "return parse(fetched.data, None)",
            "passed",
        ),
        (
            "response = fetched.data\ntry:\n    int('invalid')\n    response = fetched\n"
            "finally:\n    return response.get('items')",
            "passed",
        ),
        (
            "response = fetched.data\ntry:\n    int('invalid')\n    response = fetched\n"
            "except TypeError:\n    response = fetched\nfinally:\n    return ActionResult(data=response)",
            "passed",
        ),
        ("try:\n    int('invalid')\nfinally:\n    return response.get('items')", "failed"),
        (
            "from contextlib import suppress\nresponse = fetched.data\nwith suppress(ValueError):\n"
            "    int('invalid')\n    response = fetched\nreturn response.get('items')",
            "passed",
        ),
        (
            "from contextlib import suppress\nwith suppress(ValueError):\n"
            "    int('invalid')\nreturn response.get('items')",
            "failed",
        ),
        (
            "def parse(response: FetchResponse, list):\n    return isinstance(response, list)\n"
            "return parse(fetched, FetchResponse)",
            "passed",
        ),
        (
            "def parse(response: FetchResponse):\n    dict = type(response)\n    return isinstance(response, dict)\n"
            "return parse(fetched)",
            "passed",
        ),
        (
            "def parse(response: FetchResponse, isinstance):\n    return isinstance(response, list)\n"
            "return parse(fetched, lambda value, cls: value.status)",
            "passed",
        ),
        (
            "def parse(response: FetchResponse):\n    isinstance = lambda value, cls: value.status\n"
            "    return isinstance(response, list)\nreturn parse(fetched)",
            "passed",
        ),
        (
            "check = isinstance\nreturn check(await context.fetch(url, headers=(check := None)), list)",
            "failed",
        ),
        (
            "class Parser:\n    response = fetched\n    del response\n    items = response.get('items')\n"
            "return Parser.items",
            "passed",
        ),
        (
            "class Parser:\n    response = fetched\n    items = response.get('items')\nreturn Parser.items",
            "failed",
        ),
        ("del response[response.get('items')]", "failed"),
        ("assert response.status == 200, (response := response.data)\nreturn response.get('items')", "failed"),
        (
            "response = fetched.data\nassert fetched.status == 200, (response := fetched)\n"
            "return response.get('items')",
            "passed",
        ),
        (
            "response = fetched.data\nassert fetched.status == 200, (response := fetched)\n"
            "return ActionResult(data=response)",
            "passed",
        ),
        (
            "response = fetched.data\nassert (response := fetched).status == 200\nreturn response.get('items')",
            "failed",
        ),
        (
            "try:\n    assert False, (response := response.data)\n"
            "except AssertionError:\n    return response.get('items')",
            "passed",
        ),
        (
            "def parse():\n    return ActionResult(data=response)\nresponse = response.data\nreturn parse()",
            "passed",
        ),
        (
            "def parse(item=response.get('items')):\n    return item\nresponse = response.data\nreturn parse()",
            "failed",
        ),
        (
            "def parse(read=lambda: response.get('items'), unused=(response := response.data)):\n"
            "    return read()\nreturn parse()",
            "passed",
        ),
        (
            "parse, response = (lambda: response.get('items')), response.data\nreturn parse()",
            "passed",
        ),
        (
            "parsed = (item for item in response.get('items'))\nresponse = response.data\nreturn list(parsed)",
            "failed",
        ),
    ],
)
def test_fetch_check_respects_evaluation_order(tmp_path: Path, body: str, status: str) -> None:
    source = (
        "from autohive_integrations_sdk import ActionResult, FetchResponse\n"
        "async def execute(context):\n"
        "    fetched = await context.fetch(url)\n"
        "    response = fetched\n" + textwrap.indent(body, "    ") + "\n"
    )
    integration = _integration(tmp_path, source)

    assert check_fetch(integration).status == status


@pytest.mark.parametrize("future_annotations", [True, False])
def test_fetch_check_visits_evaluated_annotation_targets(tmp_path: Path, future_annotations: bool) -> None:
    source = "from __future__ import annotations\n" if future_annotations else ""
    source += (
        "async def execute(context):\n"
        "    response = await context.fetch(url)\n"
        "    response[response.get('items')]: int\n"
    )
    integration = _integration(tmp_path, source)

    assert check_fetch(integration).status == "failed"


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


@pytest.mark.parametrize("unwrap", [True, False])
def test_fetch_check_accounts_for_bindings_written_by_earlier_match_guards(tmp_path: Path, unwrap: bool) -> None:
    guard = "(response := response.data).get('ready')" if unwrap else "(response := response).data.get('ready')"
    integration = _integration(
        tmp_path,
        "async def execute(context):\n"
        "    response = await context.fetch(url)\n"
        "    match response.status:\n"
        f"        case _ if {guard}:\n"
        "            return []\n"
        "        case _:\n"
        "            return response.get('items')\n",
    )

    assert check_fetch(integration).status == ("passed" if unwrap else "failed")


@pytest.mark.parametrize("deferred", [True, False])
def test_fetch_check_tracks_comprehension_walruses_without_entering_lambda_bodies(
    tmp_path: Path, deferred: bool
) -> None:
    expression = "lambda: (response := response.data)" if deferred else "(response := response.data)"
    integration = _integration(
        tmp_path,
        "async def execute(context):\n"
        "    response = await context.fetch(url)\n"
        f"    [{expression} for _ in range(1)]\n"
        "    return response.get('items')\n",
    )

    assert check_fetch(integration).status == ("failed" if deferred else "passed")


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
