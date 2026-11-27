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
        "response = await context.fetch(url)\nreturn ActionResult(data=response)",
        "return ActionResult(data=await context.fetch(url))",
        "return (await context.fetch(url))['items']",
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
