"""Your own Claude Code / Codex / Gemini CLI as the agent: fake CLIs print each vendor's JSON
lines, and the thread gets the same events and records as the built-in agent loop."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import anyio
import pytest

from mtrini import threads
from mtrini.agent import engine
from mtrini.agent import session as session_mod
from mtrini.providers import agent_cli

CLAUDE_LINES = [
    {"type": "system", "subtype": "init", "session_id": "sess-abc", "model": "claude-sonnet"},
    {"type": "assistant", "message": {"content": [{"type": "text", "text": "Reading the file."},
                                                  {"type": "tool_use", "id": "tu1", "name": "Read", "input": {"file_path": "a.py"}}]}},
    {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "tu1", "content": "print(1)"}]}},
    {"type": "assistant", "message": {"content": [{"type": "text", "text": "It prints 1."}]}},
    {"type": "result", "subtype": "success", "result": "It prints 1.", "session_id": "sess-abc",
     "total_cost_usd": 0.0, "num_turns": 2},
]
CODEX_LINES = [
    {"type": "thread.started", "thread_id": "th-1"},
    {"type": "item.started", "item": {"id": "c1", "type": "command_execution", "command": "ls"}},
    {"type": "item.completed", "item": {"id": "c1", "type": "command_execution", "command": "ls",
                                        "aggregated_output": "a.py\n", "exit_code": 0, "status": "completed"}},
    {"type": "item.completed", "item": {"id": "m1", "type": "agent_message", "text": "One file: a.py"}},
    {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}},
]
GEMINI_LINES = [
    {"type": "init", "session_id": "g-1", "model": "gemini-2.5-pro"},
    {"type": "message", "role": "user", "content": "hi"},
    {"type": "message", "role": "assistant", "content": "Hel", "delta": True},
    {"type": "message", "role": "assistant", "content": "lo", "delta": True},
    {"type": "tool_use", "tool_name": "read_file", "tool_id": "r1", "parameters": {"path": "a.py"}},
    {"type": "tool_result", "tool_id": "r1", "status": "success", "output": "print(1)"},
    {"type": "result", "status": "success", "stats": {"total_tokens": 9}},
]

FAKE = r'''
import json, sys
from pathlib import Path
here = Path(__file__).parent
(here / "argv.json").write_text(json.dumps(sys.argv[1:]))
(here / "stdin.txt").write_text(sys.stdin.read(), encoding="utf-8")
spec = json.loads((here / "lines.json").read_text())
for line in spec["lines"]:
    print(json.dumps(line), flush=True)
sys.stderr.write(spec.get("stderr", ""))
sys.exit(spec.get("code", 0))
'''


def _fake_cli(tmp_path: Path, monkeypatch, exe: str, lines: list, code: int = 0, stderr: str = "") -> Path:
    d = tmp_path / f"fake-{exe}"
    d.mkdir()
    (d / "fake.py").write_text(FAKE, encoding="utf-8")
    (d / "lines.json").write_text(json.dumps({"lines": lines, "code": code, "stderr": stderr}))
    if os.name == "nt":
        launcher = d / f"{exe}.cmd"
        launcher.write_text(f'@"{sys.executable}" "{d / "fake.py"}" %*\r\n')
    else:
        launcher = d / exe
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{d / "fake.py"}" "$@"\n')
        launcher.chmod(0o755)
    monkeypatch.setenv(f"MTRINI_{exe.upper()}_BIN", str(launcher))
    return d


def _run(root: Path, cli: str, text: str, mode: str = "ask", tid: str | None = None, model: str = "default"):
    async def go():
        return [ev async for ev in engine.run_agent(root, cli, model, text, [], mode, thread_id=tid)]
    return anyio.run(go)


def test_claude_code_turn_streams_tools_and_resumes(tmp_path, monkeypatch):
    d = _fake_cli(tmp_path, monkeypatch, "claude", CLAUDE_LINES)
    root = tmp_path / "proj"
    root.mkdir()
    tid = threads.create_thread(root, "t")["id"]

    evs = _run(root, "claude-code", "what does a.py do?", tid=tid, model="sonnet")
    kinds = [e["type"] for e in evs]
    assert kinds[:2] == ["turn", "status"]
    assert [e["delta"] for e in evs if e["type"] == "assistant_delta"] == ["Reading the file.", "It prints 1."]
    start = next(e for e in evs if e["type"] == "tool_start")
    res = next(e for e in evs if e["type"] == "tool_result")
    assert (start["tool"], start["id"], res["id"], res["tool"], res["ok"]) == ("Read", "tu1", "tu1", "Read", True)
    assert evs[-1]["type"] == "done" and evs[-1]["content"] == "It prints 1."

    argv = json.loads((d / "argv.json").read_text())
    assert argv[:2] == ["-p", "--output-format"] and "--resume" not in argv
    assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"
    assert argv[argv.index("--model") + 1] == "sonnet"
    assert (d / "stdin.txt").read_text(encoding="utf-8").endswith("what does a.py do?")

    # The thread file shows the user message, both assistant texts and the tool, in order.
    roles = [(m["role"], m.get("tool")) for m in threads.get_thread(root, tid)["messages"]]
    assert roles == [("user", None), ("assistant", None), ("tool", "Read"), ("assistant", None)]
    assert session_mod.load(root, tid).external == {"cli": "claude-code", "sessionId": "sess-abc"}

    # Next message continues the same Claude Code session; plan mode maps to its plan mode.
    _run(root, "claude-code", "now fix it", mode="plan", tid=tid)
    argv = json.loads((d / "argv.json").read_text())
    assert argv[argv.index("--resume") + 1] == "sess-abc"
    assert argv[argv.index("--permission-mode") + 1] == "plan"


def test_codex_turn(tmp_path, monkeypatch):
    d = _fake_cli(tmp_path, monkeypatch, "codex", CODEX_LINES)
    root = tmp_path / "proj"
    root.mkdir()
    tid = threads.create_thread(root, "t")["id"]
    evs = _run(root, "codex-cli", "list files", mode="readonly", tid=tid)
    res = next(e for e in evs if e["type"] == "tool_result")
    assert res["tool"] == "run_command" and res["ok"] and res["output"] == "a.py\n"
    assert [e["delta"] for e in evs if e["type"] == "assistant_delta"] == ["One file: a.py"]
    assert evs[-1]["type"] == "done"
    argv = json.loads((d / "argv.json").read_text())
    assert argv[:2] == ["exec", "--json"] and argv[argv.index("-s") + 1] == "read-only" and argv[-1] == "-"

    _run(root, "codex-cli", "again", tid=tid)
    argv = json.loads((d / "argv.json").read_text())
    assert argv[-3:] == ["resume", "th-1", "-"]


def test_gemini_partial_text_is_one_message(tmp_path, monkeypatch):
    _fake_cli(tmp_path, monkeypatch, "gemini", GEMINI_LINES)
    root = tmp_path / "proj"
    root.mkdir()
    tid = threads.create_thread(root, "t")["id"]
    evs = _run(root, "gemini-cli", "hi", tid=tid)
    assert "".join(e["delta"] for e in evs if e["type"] == "assistant_delta") == "Hello"
    assert evs[-1]["type"] == "done"
    msgs = threads.get_thread(root, tid)["messages"]
    assert [(m["role"], m["content"]) for m in msgs if m["role"] == "assistant"] == [("assistant", "Hello")]


def test_not_signed_in_gives_the_next_step(tmp_path, monkeypatch):
    _fake_cli(tmp_path, monkeypatch, "gemini", [], code=1,
              stderr="Please set an Auth method in your settings.json or specify GEMINI_API_KEY")
    root = tmp_path / "proj"
    root.mkdir()
    evs = _run(root, "gemini-cli", "hi")
    assert evs[-1]["type"] == "error"
    assert "not signed in" in evs[-1]["message"] and "Sign in with Google" in evs[-1]["message"]


def test_missing_cli_says_how_to_install(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_cli, "find", lambda cli_id: None)
    root = tmp_path / "proj"
    root.mkdir()
    evs = _run(root, "claude-code", "hi")
    assert evs == [{"type": "error", "message": evs[0]["message"]}]
    assert "npm install -g @anthropic-ai/claude-code" in evs[0]["message"]


def test_unsafe_model_and_session_values_never_reach_the_command():
    cmd = agent_cli.command("claude-code", "claude", "x; rm -rf /", "auto", "id && evil")
    assert "--model" not in cmd and "--resume" not in cmd
    assert cmd[cmd.index("--permission-mode") + 1] == "bypassPermissions"


@pytest.mark.parametrize("cli", list(agent_cli.CLIS))
def test_listed_as_providers_without_keys(cli, monkeypatch):
    from mtrini.providers.registry import build_provider, provider_meta

    m = next(p for p in provider_meta() if p["id"] == cli)
    assert m["agentCli"] and not m["needsKey"]
    models = anyio.run(build_provider(cli, Path(".")).list_models)
    assert models[0].id == "default"
