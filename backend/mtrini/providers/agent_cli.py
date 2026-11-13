"""Use the coding-agent subscription you already pay for: Claude Code, Codex or Gemini CLI.

Mtrini does not log in to those services and never sees a token. It runs the official
CLI that you installed and signed in to yourself, in your project folder, and shows its
output in the thread. Each turn goes through the vendor's own program, under the
vendor's own terms; Mtrini only reads what the CLI prints.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import ModelInfo


@dataclass(frozen=True)
class CLI:
    id: str
    label: str
    exe: str  # program name on PATH
    install: str
    login: str
    models: tuple[tuple[str, str], ...]  # (id, label); "default" = whatever the CLI is set to


CLIS: dict[str, CLI] = {c.id: c for c in (
    CLI("claude-code", "Claude Code (your subscription)", "claude",
        "npm install -g @anthropic-ai/claude-code", "Run `claude` in a terminal once and sign in.",
        (("default", "Claude Code default"), ("opus", "Opus"), ("sonnet", "Sonnet"), ("haiku", "Haiku"))),
    CLI("codex-cli", "Codex CLI (your ChatGPT plan)", "codex",
        "npm install -g @openai/codex", "Run `codex login` in a terminal once.",
        (("default", "Codex default"),)),
    CLI("gemini-cli", "Gemini CLI (your Google account)", "gemini",
        "npm install -g @google/gemini-cli", "Run `gemini` in a terminal once and choose Sign in with Google.",
        (("default", "Gemini CLI default"), ("gemini-2.5-pro", "Gemini 2.5 Pro"), ("gemini-2.5-flash", "Gemini 2.5 Flash"))),
)}

_SAFE = re.compile(r"^[\w.:\-\[\]]{1,80}$")


def find(cli_id: str) -> str | None:
    """Full path of the CLI, or None. MTRINI_<NAME>_BIN overrides (used by tests)."""
    c = CLIS[cli_id]
    env = os.environ.get(f"MTRINI_{c.exe.upper()}_BIN")
    return env or _search(c.exe)


def _search(exe: str) -> str | None:
    hit = shutil.which(exe)
    if hit:
        return hit
    home = Path.home()
    for p in (home / ".local" / "bin" / exe, home / ".local" / "bin" / f"{exe}.exe",
              home / ".claude" / "local" / exe, home / ".claude" / "local" / f"{exe}.cmd"):
        if p.exists():
            return str(p)
    return None


def meta() -> list[dict[str, Any]]:
    out = []
    for c in CLIS.values():
        path = find(c.id)
        out.append({"id": c.id, "label": c.label, "needsKey": False, "agentCli": True, "installed": bool(path),
                    "hint": (f"Runs your own {c.exe} program, signed in with your own account. Mtrini never sees "
                             f"your login. {c.login} Usage counts against your plan, under that service's terms."
                             if path else f"Not installed. Install it with `{c.install}`, then: {c.login}"),
                    "defaultModel": "default"})
    return out


class AgentCLIProvider:
    """Only lists models: the turn itself is run by agent/external.py, not the tool loop."""

    def __init__(self, cli_id: str):
        self.name = cli_id
        self.cli = CLIS[cli_id]

    async def list_models(self, **kw: Any) -> list[ModelInfo]:
        return [ModelInfo(id=m, label=l, provider=self.name, capabilities={"tools": True}) for m, l in self.cli.models]

    async def chat(self, *a: Any, **kw: Any) -> dict[str, Any]:
        raise RuntimeError(f"{self.cli.label} runs its own agent; it can't be used as a plain chat model here.")

    async def stream(self, *a: Any, **kw: Any):
        raise RuntimeError(f"{self.cli.label} runs its own agent.")
        yield {}  # pragma: no cover

    def supports_tools(self) -> bool:
        return True

    def supports_vision(self) -> bool:
        return False

    def supports_streaming(self) -> bool:
        return True


# ---- command lines -------------------------------------------------------------------------
# The prompt always goes in on stdin, so no quoting problems with npm .cmd shims on Windows.
# Mtrini's modes map onto each CLI's own permission modes:
#   plan / readonly -> the CLI's read-only or plan mode
#   ask             -> file edits allowed, anything riskier refused by the CLI
#   auto            -> the CLI's own "allow everything" mode (the same as Mtrini's auto)

def command(cli_id: str, exe: str, model: str, mode: str, session_id: str | None) -> list[str]:
    model = model if model and model != "default" and _SAFE.match(model) else ""
    sid = session_id if session_id and _SAFE.match(session_id) else ""
    if cli_id == "claude-code":
        pm = {"plan": "plan", "readonly": "plan", "auto": "bypassPermissions"}.get(mode, "acceptEdits")
        cmd = [exe, "-p", "--output-format", "stream-json", "--verbose", "--permission-mode", pm]
        if model:
            cmd += ["--model", model]
        if sid:
            cmd += ["--resume", sid]
        return cmd
    if cli_id == "codex-cli":
        sandbox = "read-only" if mode in ("plan", "readonly") else "workspace-write"
        cmd = [exe, "exec", "--json", "--skip-git-repo-check", "-s", sandbox]
        if mode == "auto":
            cmd = [exe, "exec", "--json", "--skip-git-repo-check", "--full-auto"]
        if model:
            cmd += ["-m", model]
        return cmd + (["resume", sid, "-"] if sid else ["-"])
    if cli_id == "gemini-cli":
        am = {"plan": "plan", "readonly": "plan", "auto": "yolo"}.get(mode, "auto_edit")
        cmd = [exe, "-o", "stream-json", "--approval-mode", am, "-p", " "]
        if model:
            cmd += ["-m", model]
        return cmd
    raise ValueError(cli_id)


# ---- output parsing -----------------------------------------------------------------------
# Each parser turns one line of the CLI's JSON output into Mtrini events plus, at most, a
# session id to resume next turn. Unknown lines are ignored, so a newer CLI that adds event
# kinds still works.

def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(b.get("text", "")) for b in content if isinstance(b, dict) and b.get("type") == "text")
    return json.dumps(content, ensure_ascii=False, default=str) if content is not None else ""


def parse_claude(ev: dict) -> tuple[list[dict], str | None]:
    t, out = ev.get("type"), []
    if t == "system" and ev.get("subtype") == "init":
        return [{"type": "status", "status": "thinking", "message": f"Claude Code started ({ev.get('model', 'default')})"}], ev.get("session_id")
    if t == "assistant":
        for b in (ev.get("message") or {}).get("content") or []:
            if b.get("type") == "text" and b.get("text"):
                out.append({"type": "assistant_delta", "delta": b["text"]})
            elif b.get("type") == "tool_use":
                out.append({"type": "tool_start", "tool": b.get("name", "tool"), "id": b.get("id"), "args": b.get("input") or {}})
    elif t == "user":
        for b in (ev.get("message") or {}).get("content") or []:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                err = bool(b.get("is_error"))
                txt = _text_of(b.get("content"))[:20000]
                out.append({"type": "tool_result", "id": b.get("tool_use_id"), "ok": not err,
                            "output": None if err else txt, "error": txt if err else None})
    elif t == "result":
        if ev.get("is_error") or (ev.get("subtype") not in (None, "success")):
            out.append({"type": "error", "message": f"Claude Code stopped: {ev.get('result') or ev.get('subtype')}"})
        else:
            out.append({"type": "final", "content": ev.get("result") or "",
                        "usage": {"costUsd": ev.get("total_cost_usd"), "turns": ev.get("num_turns")}})
        return out, ev.get("session_id")
    return out, None


def parse_codex(ev: dict) -> tuple[list[dict], str | None]:
    t, out = ev.get("type"), []
    if t == "thread.started":
        return [{"type": "status", "status": "thinking", "message": "Codex started"}], ev.get("thread_id")
    item = ev.get("item") or {}
    kind = item.get("type")
    if t == "item.started" and kind == "command_execution":
        out.append({"type": "tool_start", "tool": "run_command", "id": item.get("id"), "args": {"command": item.get("command")}})
    elif t == "item.completed":
        if kind == "agent_message" and item.get("text"):
            out.append({"type": "assistant_delta", "delta": item["text"]})
        elif kind == "command_execution":
            ok = item.get("exit_code") in (0, None) and item.get("status") != "failed"
            txt = str(item.get("aggregated_output") or "")[:20000]
            out.append({"type": "tool_result", "tool": "run_command", "id": item.get("id"), "ok": ok,
                        "output": txt if ok else None, "error": None if ok else (txt or f"exit {item.get('exit_code')}")})
        elif kind == "file_change":
            files = [c.get("path") for c in item.get("changes") or [] if isinstance(c, dict)]
            out.append({"type": "tool_start", "tool": "edit_files", "id": item.get("id"), "args": {"files": files}})
            out.append({"type": "tool_result", "tool": "edit_files", "id": item.get("id"),
                        "ok": item.get("status") != "failed", "output": {"files": files}})
        elif kind == "error" and item.get("message"):
            out.append({"type": "status", "status": "thinking", "message": item["message"][:300]})
    elif t == "turn.completed":
        out.append({"type": "final", "content": None, "usage": ev.get("usage")})
    elif t in ("turn.failed", "error"):
        msg = (ev.get("error") or {}).get("message") if isinstance(ev.get("error"), dict) else ev.get("message")
        out.append({"type": "error", "message": f"Codex stopped: {msg or 'failed'}"})
    return out, None


def parse_gemini(ev: dict) -> tuple[list[dict], str | None]:
    t, out = ev.get("type"), []
    if t == "init":
        return [{"type": "status", "status": "thinking", "message": f"Gemini CLI started ({ev.get('model', 'default')})"}], ev.get("session_id")
    if t == "message" and ev.get("role") == "assistant" and ev.get("content"):
        out.append({"type": "assistant_delta", "delta": ev["content"], "partial": bool(ev.get("delta"))})
    elif t == "tool_use":
        out.append({"type": "tool_start", "tool": ev.get("tool_name", "tool"), "id": ev.get("tool_id"), "args": ev.get("parameters") or {}})
    elif t == "tool_result":
        ok = ev.get("status") == "success"
        err = ev.get("error")
        out.append({"type": "tool_result", "id": ev.get("tool_id"), "ok": ok,
                    "output": str(ev.get("output") or "")[:20000] if ok else None,
                    "error": None if ok else (err.get("message") if isinstance(err, dict) else str(err or "failed"))})
    elif t == "error":
        out.append({"type": "status", "status": "thinking", "message": str(ev.get("message", ""))[:300]})
    elif t == "result":
        if ev.get("status") not in (None, "success"):
            err = ev.get("error")
            out.append({"type": "error", "message": f"Gemini CLI stopped: {err.get('message') if isinstance(err, dict) else err or ev.get('status')}"})
        else:
            out.append({"type": "final", "content": None, "usage": ev.get("stats")})
    return out, None


PARSERS = {"claude-code": parse_claude, "codex-cli": parse_codex, "gemini-cli": parse_gemini}


def login_hint(cli_id: str, text: str) -> str | None:
    """Turn a 'not signed in' message into the next step, without echoing anything secret."""
    low = text.lower()
    if any(k in low for k in ("login", "log in", "sign in", "auth method", "unauthorized", "api key", "not authenticated", "401")):
        return f"{CLIS[cli_id].label} is installed but not signed in. {CLIS[cli_id].login}"
    return None
