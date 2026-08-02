import json
import subprocess
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hiveup.checks.config_sync import check_config_sync, extract_actions_from_code  # noqa: E402


def _write_entry_point(tmp_path: Path, source: str) -> Path:
    entry_point = tmp_path / "main.py"
    entry_point.write_text(source, encoding="utf-8")
    return entry_point


def test_extract_actions_from_code_keeps_direct_inputs_get(tmp_path: Path) -> None:
    entry_point = _write_entry_point(
        tmp_path,
        """
app = None

@app.action("get_data")
class GetData:
    def execute(self, inputs):
        return inputs.get("foo")
""",
    )

    actions = extract_actions_from_code(entry_point)

    assert actions == {"get_data": {"direct": set(), "get": {"foo"}}}


def test_extract_actions_from_code_includes_called_helper_input_accesses_only(tmp_path: Path) -> None:
    entry_point = _write_entry_point(
        tmp_path,
        """
app = None

def _helper(action_inputs):
    return {
        "required": action_inputs["required_key"],
        "optional": action_inputs.get("optional_key"),
    }

@app.action("calls_helper")
class CallsHelper:
    def execute(self, inputs):
        return _helper(inputs)

@app.action("does_not_call_helper")
class DoesNotCallHelper:
    def execute(self, inputs):
        return inputs.get("local_key")
""",
    )

    actions = extract_actions_from_code(entry_point)

    assert actions == {
        "calls_helper": {"direct": {"required_key"}, "get": {"optional_key"}},
        "does_not_call_helper": {"direct": set(), "get": {"local_key"}},
    }


def test_extract_actions_from_code_includes_helper_keyword_input_accesses(tmp_path: Path) -> None:
    entry_point = _write_entry_point(
        tmp_path,
        """
app = None

def _helper(action_inputs):
    return action_inputs.get("optional_key")

@app.action("calls_helper")
class CallsHelper:
    def execute(self, inputs):
        return _helper(action_inputs=inputs)
""",
    )

    actions = extract_actions_from_code(entry_point)

    assert actions == {"calls_helper": {"direct": set(), "get": {"optional_key"}}}


def test_check_config_sync_still_fails_new_integration_unused_schema_param(
    tmp_path: Path,
    capsys,
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=tmp_path, check=True)
    base_ref = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    integration = tmp_path / "new-integration"
    integration.mkdir()
    (integration / "config.json").write_text(
        json.dumps(
            {
                "entry_point": "main.py",
                "actions": {
                    "get_data": {
                        "input_schema": {
                            "type": "object",
                            "properties": {"unused_param": {"type": "string"}},
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (integration / "main.py").write_text(
        """
app = None

@app.action("get_data")
class GetData:
    def execute(self, inputs):
        return {}
""",
        encoding="utf-8",
    )

    assert check_config_sync(str(integration), base_ref=base_ref) == 1
    output = capsys.readouterr().out
    assert "New integrations must keep config.json input_schema in sync with code" in output
    assert "unused_param" in output
