import importlib.util
import json
import sys
import types
from pathlib import Path


_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "discord_case_export.py"
_SPEC = importlib.util.spec_from_file_location("discord_case_export", _SCRIPT)
discord_case_export = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(discord_case_export)


def test_wrapper_forwards_to_case_export(monkeypatch, capsys):
    calls = []

    def fake_discord_core(**kwargs):
        calls.append(kwargs)
        return json.dumps({"case_export": {"count": 0}, "messages": []})

    monkeypatch.setitem(sys.modules, "tools.discord_tool", types.SimpleNamespace(discord_core=fake_discord_core))

    rc = discord_case_export.main([
        "--channel-id", "11",
        "--thread-id", "22",
        "--message-id", "33",
        "--limit", "10",
    ])

    assert rc == 0
    assert calls == [{
        "action": "case_export",
        "channel_id": "11",
        "thread_id": "22",
        "message_id": "33",
        "before": "",
        "after": "",
        "limit": 10,
    }]
    assert json.loads(capsys.readouterr().out)["case_export"]["count"] == 0


def test_wrapper_returns_nonzero_on_tool_error(monkeypatch, capsys):
    def fake_discord_core(**_kwargs):
        return json.dumps({"error": "DISCORD_BOT_TOKEN not configured."})

    monkeypatch.setitem(sys.modules, "tools.discord_tool", types.SimpleNamespace(discord_core=fake_discord_core))

    rc = discord_case_export.main(["--channel-id", "11"])

    assert rc == 1
    assert "DISCORD_BOT_TOKEN" in capsys.readouterr().out
