"""OpenCode as an agent CLI: found on its own, its free models listed, its turns run headless."""
from __future__ import annotations

import sys

import anyio
import pytest

from mtrini.agent import engine
from mtrini.providers import agent_cli
from mtrini.providers.registry import provider_meta

MODELS = """openrouter/google/gemma-4-31b-it:free
opencode/gpt-6-sol
opencode/glm-5.3-flash-free
opencode/big-pickle
local/qwen
opencode/deepseek-v4.1-flash-free
opencode/bad model; rm -rf
"""


def test_free_models_come_first_and_only_opencodes_own_are_listed():
    models = agent_cli.parse_models(MODELS)
    assert models == [("opencode/big-pickle", "big-pickle (free)"),
                      ("opencode/deepseek-v4.1-flash-free", "deepseek-v4.1-flash-free (free)"),
                      ("opencode/glm-5.3-flash-free", "glm-5.3-flash-free (free)"),
                      ("opencode/gpt-6-sol", "gpt-6-sol")]
    assert agent_cli.is_free_model("opencode/big-pickle") and not agent_cli.is_free_model("opencode/gpt-6-sol")
    assert not agent_cli.is_free_model("openrouter/x:free")  # another provider's free tier is not OpenCode's


def test_command_lines_follow_mtrinis_modes():
    cmd = agent_cli.command
    assert cmd("opencode", "oc", "opencode/glm-5.3-flash-free", "ask", None) == \
        ["oc", "run", "--format", "json", "--archived", "--model", "opencode/glm-5.3-flash-free"]
    assert cmd("opencode", "oc", "default", "auto", "ses_abc123") == \
        ["oc", "run", "--format", "json", "--archived", "--auto", "--session", "ses_abc123"]
    assert cmd("opencode", "oc", "opencode/big-pickle", "plan", None)[5:7] == ["--agent", "plan"]
    assert "--model" not in cmd("opencode", "oc", "opencode/x; rm -rf /", "ask", None)  # never an unsafe model name


def test_events_become_mtrini_events():
    p = agent_cli.parse_opencode
    tool = {"type": "tool_use", "sessionID": "ses_1", "part": {"id": "call_1", "tool": "read", "state": {
        "status": "completed", "input": {"path": "note.txt"}, "output": "1: hello"}}}
    events, sid = p(tool)
    assert sid == "ses_1"
    assert events == [{"type": "tool_start", "tool": "read", "id": "call_1", "args": {"path": "note.txt"}},
                      {"type": "tool_result", "tool": "read", "id": "call_1", "ok": True, "output": "1: hello", "error": None}]
    failed, _ = p({"type": "tool_use", "part": {"id": "c2", "tool": "shell", "state": {"status": "error", "error": "denied"}}})
    assert failed[1]["ok"] is False and failed[1]["error"] == "denied" and failed[1]["output"] is None
    assert p({"type": "text", "sessionID": "ses_1", "part": {"text": "Done."}})[0] == [{"type": "assistant_delta", "delta": "Done."}]
    assert p({"type": "step_finish", "part": {"reason": "tool-calls"}})[0] == []
    assert p({"type": "step_finish", "part": {"reason": "stop", "cost": 0}})[0][0]["type"] == "final"
    assert "rate limited" in p({"type": "error", "error": {"name": "APIError", "data": {"message": "rate limited"}}})[0][0]["message"]
    assert p({"type": "something_new"}) == ([], None)  # a newer OpenCode adding event kinds still works


def test_the_desktop_apps_window_launcher_is_never_run(tmp_path, monkeypatch):
    monkeypatch.undo()  # this test needs the real search, not the stand-in from conftest
    monkeypatch.setenv("MTRINI_HOME", str(tmp_path / "_home"))
    app = tmp_path / "Programs" / "@opencode-aidesktop"
    (app / "resources").mkdir(parents=True)
    (app / "resources" / "app.asar").write_text("x")
    launcher = app / ("opencode.exe" if sys.platform == "win32" else "opencode")
    launcher.write_text("gui")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "nowhere"))
    monkeypatch.setattr(agent_cli.Path, "home", lambda: tmp_path / "nobody")
    monkeypatch.setattr(agent_cli.shutil, "which", lambda name: str(launcher) if name == "opencode" else None)
    assert agent_cli._opencode_cli() is None  # a desktop app with no CLI inside: opening it would pop a window
    cli = app / "resources" / ("opencode-cli.exe" if sys.platform == "win32" else "opencode-cli")
    cli.write_text("cli")
    assert agent_cli._opencode_cli() == str(cli)  # the CLI it ships is used instead


def test_opencode_shows_up_by_itself_when_installed(monkeypatch):
    monkeypatch.setattr(agent_cli, "_search", lambda exe: "/bin/opencode-cli" if exe == "opencode" else None)
    meta = {m["id"]: m for m in provider_meta()}
    assert meta["opencode"]["installed"] is True and "free models are ready" in meta["opencode"]["hint"]
    assert meta["claude-code"]["installed"] is False
    monkeypatch.setattr(agent_cli, "_search", lambda exe: None)
    assert {m["id"]: m for m in provider_meta()}["opencode"]["installed"] is False


FAKE = r'''
import json, os, sys
prompt = sys.stdin.read()
args = sys.argv[1:]
sid = args[args.index("--session") + 1] if "--session" in args else "ses_new1"
out = lambda o: print(json.dumps({**o, "sessionID": sid}), flush=True)
out({"type": "step_start", "part": {"type": "step-start"}})
out({"type": "tool_use", "part": {"id": "c1", "tool": "write", "state": {"status": "completed", "input": {"path": "a.txt"}, "output": "Created"}}})
open("a.txt", "w").write("made by " + (args[args.index("--model") + 1] if "--model" in args else "default"))
out({"type": "step_finish", "part": {"reason": "tool-calls"}})
out({"type": "text", "part": {"text": "Wrote a.txt. Session " + sid + ". Auto: " + str("--auto" in args) + ". In its folder: " + str(os.path.samefile(os.environ.get("PWD", "."), os.getcwd()))}})
out({"type": "step_finish", "part": {"reason": "stop", "cost": 0}})
'''


def test_a_turn_runs_through_opencode_and_keeps_its_session(tmp_path, monkeypatch):
    fake = tmp_path / "fake_opencode.py"
    fake.write_text(FAKE, encoding="utf-8")
    monkeypatch.setattr(agent_cli, "command", lambda cli_id, exe, model, mode, sid, _real=agent_cli.command:
                        [sys.executable, str(fake), *_real(cli_id, "x", model, mode, sid)[1:]])
    monkeypatch.setattr(agent_cli, "_search", lambda exe: "x")
    root = tmp_path / "proj"
    root.mkdir()

    async def turn(text):
        return [ev async for ev in engine.run_agent(root, "opencode", "opencode/glm-5.3-flash-free", text, [], "ask", {},
                                                    thread_id="t1")]
    first = anyio.run(turn, "make a file")
    assert [e["type"] for e in first if e["type"] in ("tool_start", "tool_result", "done", "error")] == ["tool_start", "tool_result", "done"]
    # the last message is the answer; PWD names the project folder, which is where OpenCode takes it from
    assert first[-1]["content"] == "Wrote a.txt. Session ses_new1. Auto: False. In its folder: True"
    assert (root / "a.txt").read_text() == "made by opencode/glm-5.3-flash-free"
    second = anyio.run(turn, "again")
    assert "Session ses_new1" in second[-1]["content"]  # the next turn carries on in the same OpenCode session


@pytest.mark.parametrize("mode,flag", [("auto", "--auto"), ("readonly", "plan")])
def test_other_modes(mode, flag):
    assert flag in agent_cli.command("opencode", "oc", "default", mode, None)
