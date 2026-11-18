"""Use the coding agent you already have: Claude Code, Codex, Gemini CLI or OpenCode (and its free models).

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
import subprocess
import time
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
    # OpenCode's free models only work through OpenCode itself (its terms), so Mtrini runs your OpenCode.
    # The model list is read from `opencode models`, so it is always what your OpenCode offers today.
    CLI("opencode", "OpenCode (free models)", "opencode",
        "Get OpenCode from https://opencode.ai", "Its free models need no sign-in.",
        (("default", "OpenCode default"),)),
)}

_SAFE = re.compile(r"^[\w.:\-\[\]]{1,80}$")
_SAFE_OC = re.compile(r"^[\w.:\-/#@]{1,120}$")  # OpenCode models look like provider/model#variant


def find(cli_id: str) -> str | None:
    """Full path of the CLI, or None. MTRINI_<NAME>_BIN overrides (used by tests)."""
    c = CLIS[cli_id]
    env = os.environ.get(f"MTRINI_{c.exe.upper()}_BIN")
    return env or _search(c.exe)


def _opencode_cli() -> str | None:
    """OpenCode's command-line program. The desktop app puts a launcher called `opencode` on PATH that opens
    its window, so look for the real CLI it ships (`opencode-cli`) before trusting PATH."""
    home = Path.home()
    local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
    spots = [
        local / "Programs" / "@opencode-aidesktop" / "resources" / "opencode-cli.exe",
        local / "Programs" / "OpenCode" / "resources" / "opencode-cli.exe",
        Path("/Applications/OpenCode.app/Contents/Resources/opencode-cli"),
        Path("/opt/OpenCode/resources/opencode-cli"),
        home / ".opencode" / "bin" / "opencode.exe",
        home / ".opencode" / "bin" / "opencode",
    ]
    hit = shutil.which("opencode-cli")
    if hit:
        return hit
    for p in spots:
        if p.exists():
            return str(p)
    hit = shutil.which("opencode")
    if not hit:
        return None
    here = Path(hit).resolve().parent
    for bundled in (here / "resources" / "opencode-cli.exe", here / "resources" / "opencode-cli"):
        if bundled.exists():  # PATH pointed at the desktop app: use the CLI inside it
            return str(bundled)
    if (here / "resources" / "app.asar").exists():  # a desktop app with no CLI: running it would open a window
        return None
    return hit


def _search(exe: str) -> str | None:
    if exe == "opencode":
        return _opencode_cli()
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
        if c.id == "opencode":
            hint = ("Found OpenCode on this computer: its free models are ready to use, with no key. Mtrini runs your "
                    "OpenCode for each turn, under OpenCode's terms. Free models are offered for a limited time and "
                    "some keep your prompts to improve the model: check each one at opencode.ai."
                    if path else f"Not installed. {c.install}. Its free models then show up here by themselves.")
        else:
            hint = (f"Runs your own {c.exe} program, signed in with your own account. Mtrini never sees "
                    f"your login. {c.login} Usage counts against your plan, under that service's terms."
                    if path else f"Not installed. Install it with `{c.install}`, then: {c.login}")
        out.append({"id": c.id, "label": c.label, "needsKey": False, "agentCli": True, "installed": bool(path),
                    "hint": hint, "defaultModel": "default"})
    return out


_OC_CACHE: dict[str, Any] = {"at": 0.0, "exe": "", "models": []}
OC_TTL = 600  # seconds


def is_free_model(model: str) -> bool:
    """OpenCode's own free models: `opencode/...-free`, plus its stealth free model."""
    name = model.split("/", 1)[1] if model.startswith("opencode/") else ""
    return bool(name) and ("free" in name.split("#")[0].split("-") or name.split("#")[0] == "big-pickle")


def parse_models(text: str) -> list[tuple[str, str]]:
    """`opencode models` prints one provider/model per line. Keep OpenCode's own, free ones first."""
    own = sorted({ln.strip() for ln in text.splitlines() if ln.strip().startswith("opencode/") and _SAFE_OC.match(ln.strip())})
    free = [m for m in own if is_free_model(m)]
    paid = [m for m in own if not is_free_model(m)]
    label = lambda m: m.split("/", 1)[1]  # noqa: E731
    return [(m, f"{label(m)} (free)") for m in free] + [(m, label(m)) for m in paid]


def opencode_models() -> list[tuple[str, str]]:
    """What your OpenCode offers right now, cached for a few minutes. Falls back to OpenCode's default."""
    exe = find("opencode")
    if not exe:
        return list(CLIS["opencode"].models)
    now = time.time()
    if _OC_CACHE["models"] and _OC_CACHE["exe"] == exe and now - _OC_CACHE["at"] < OC_TTL:
        return list(_OC_CACHE["models"])
    from ..proc import NO_WINDOW

    try:
        out = subprocess.run([exe, "models"], capture_output=True, text=True, timeout=45, stdin=subprocess.DEVNULL,
                             encoding="utf-8", errors="replace", **NO_WINDOW).stdout
        models = parse_models(out)
    except (OSError, subprocess.SubprocessError):
        models = []
    if not models:
        return list(CLIS["opencode"].models)
    _OC_CACHE.update({"at": now, "exe": exe, "models": models})
    return list(models)


class AgentCLIProvider:
    """Only lists models: the turn itself is run by agent/external.py, not the tool loop."""

    def __init__(self, cli_id: str):
        self.name = cli_id
        self.cli = CLIS[cli_id]

    async def list_models(self, **kw: Any) -> list[ModelInfo]:
        models = opencode_models() if self.name == "opencode" else list(self.cli.models)
        return [ModelInfo(id=m, label=l, provider=self.name, capabilities={"tools": True}) for m, l in models]

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
    oc_model = model if model and model != "default" and _SAFE_OC.match(model) else ""
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
    if cli_id == "opencode":
        # No --auto unless Mtrini's own mode is auto: otherwise OpenCode follows the permissions in your
        # OpenCode settings. --archived keeps these runs out of your OpenCode session list.
        cmd = [exe, "run", "--format", "json", "--archived"]
        if mode in ("plan", "readonly"):
            cmd += ["--agent", "plan"]
        elif mode == "auto":
            cmd += ["--auto"]
        if oc_model:
            cmd += ["--model", oc_model]
        if sid:
            cmd += ["--session", sid]
        return cmd
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


def _codex_mcp_name(item: dict) -> str:
    """A Codex MCP call, named like Claude Code names them: mcp__<server>__<tool>."""
    return f"mcp__{item.get('server') or 'mcp'}__{item.get('tool') or 'tool'}"


def _codex_mcp_result(item: dict) -> dict:
    err = item.get("error")
    failed = item.get("status") == "failed" or bool(err)
    if failed:
        msg = err.get("message") if isinstance(err, dict) else err
        return {"ok": False, "output": None, "error": str(msg or "failed")[:20000]}
    res = item.get("result") or {}
    text = _text_of(res.get("content")) if isinstance(res, dict) else ""
    if not text and isinstance(res, dict) and res.get("structured_content") is not None:
        text = json.dumps(res["structured_content"], ensure_ascii=False, default=str)
    return {"ok": True, "output": text[:20000], "error": None}


def parse_codex(ev: dict) -> tuple[list[dict], str | None]:
    t, out = ev.get("type"), []
    if t == "thread.started":
        return [{"type": "status", "status": "thinking", "message": "Codex started"}], ev.get("thread_id")
    item = ev.get("item") or {}
    kind = item.get("type")
    if t == "item.started" and kind == "command_execution":
        out.append({"type": "tool_start", "tool": "run_command", "id": item.get("id"), "args": {"command": item.get("command")}})
    elif t == "item.started" and kind == "mcp_tool_call":
        args = item.get("arguments")
        out.append({"type": "tool_start", "tool": _codex_mcp_name(item), "id": item.get("id"),
                    "args": args if isinstance(args, dict) else ({} if args is None else {"arguments": args})})
    elif t == "item.completed" and kind == "mcp_tool_call":
        out.append({"type": "tool_result", "tool": _codex_mcp_name(item), "id": item.get("id"), **_codex_mcp_result(item)})
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


def parse_opencode(ev: dict) -> tuple[list[dict], str | None]:
    t, out = ev.get("type"), []
    part = ev.get("part") or {}
    sid = ev.get("sessionID") or part.get("sessionID")
    if t == "tool_use":
        state = part.get("state") or {}
        cid = part.get("id") or part.get("partID")
        name = part.get("tool", "tool")
        failed = state.get("status") == "error"
        out.append({"type": "tool_start", "tool": name, "id": cid, "args": state.get("input") or {}})
        text = str(state.get("error") if failed else state.get("output") or "")[:20000]
        out.append({"type": "tool_result", "tool": name, "id": cid, "ok": not failed,
                    "output": None if failed else text, "error": text or "failed" if failed else None})
    elif t == "text" and part.get("text"):
        out.append({"type": "assistant_delta", "delta": part["text"]})
    elif t == "step_finish" and part.get("reason") == "stop":
        out.append({"type": "final", "content": None, "usage": {"costUsd": part.get("cost"), "tokens": part.get("tokens")}})
    elif t == "error":
        err = ev.get("error")
        data = err.get("data") if isinstance(err, dict) and isinstance(err.get("data"), dict) else {}
        msg = data.get("message") or (err.get("message") or err.get("name") if isinstance(err, dict) else err) or ev.get("message")
        out.append({"type": "error", "message": f"OpenCode stopped: {str(msg or 'failed')[:600]}"})
    return out, sid


PARSERS = {"claude-code": parse_claude, "codex-cli": parse_codex, "gemini-cli": parse_gemini, "opencode": parse_opencode}


def login_hint(cli_id: str, text: str) -> str | None:
    """Turn a 'not signed in' message into the next step, without echoing anything secret."""
    low = text.lower()
    if any(k in low for k in ("login", "log in", "sign in", "auth method", "unauthorized", "api key", "not authenticated", "401")):
        if cli_id == "opencode":
            return "OpenCode refused this model. Pick one of its free models, or connect the provider inside OpenCode."
        return f"{CLIS[cli_id].label} is installed but not signed in. {CLIS[cli_id].login}"
    return None
