"""Run one turn through the user's own coding-agent CLI (Claude Code, Codex, Gemini CLI).

The CLI runs in the project folder with the user's own login. Mtrini sends the message on
stdin, reads the CLI's JSON lines, and turns them into the same events as its own agent
loop, so the thread view, tool cards and thread file work unchanged. The CLI's session id
is kept in the Mtrini session, so the next message continues the same conversation.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from ..proc import NO_WINDOW
from ..providers import agent_cli
from . import session as session_mod

TURN_TIMEOUT = 60 * 60  # an agent turn can be long; stop after an hour without finishing
LINE_LIMIT = 8 * 1024 * 1024


def _log(root: Path, thread_id: str | None, role: str, content: str = "", **extra: Any) -> None:
    if not thread_id:
        return
    from .. import threads

    try:
        threads.append_message(root, thread_id, role, content, **extra)
    except (FileNotFoundError, ValueError):
        pass


async def run_external(root: Path, cli_id: str, model: str, user_text: str, permission_mode: str = "ask", *,
                       thread_id: str | None = None, system_extra: str = "", context: str = "",
                       images: list[dict] | None = None) -> AsyncIterator[dict[str, Any]]:
    cli = agent_cli.CLIS[cli_id]
    exe = agent_cli.find(cli_id)
    if not exe:
        yield {"type": "error", "message": f"{cli.label} isn't installed. Install it with `{cli.install}`, then: {cli.login}"}
        return

    s = session_mod.load(root, thread_id)
    ext = s.external if s.external.get("cli") == cli_id else {}
    first = not ext.get("sessionId")
    s.turn += 1
    s.mode = permission_mode

    parts = []
    if first and system_extra:  # project instructions, once, like the built-in agent's system prompt
        parts.append(system_extra)
    if first:
        from .. import memory

        mem = memory.for_prompt(root)
        if mem:
            parts.append("Memory from earlier Mtrini sessions (may be out of date):\n" + mem)
    if context:
        parts.append(context)
    if images:
        parts.append(f"[{len(images)} image(s) were attached in Mtrini; this CLI only receives text.]")
    parts.append(user_text)
    prompt = "\n\n".join(parts)

    cmd = agent_cli.command(cli_id, exe, model, permission_mode, ext.get("sessionId"))
    _log(root, thread_id, "user", user_text, turn=s.turn, images=len(images or []))
    yield {"type": "turn", "turn": s.turn}
    yield {"type": "status", "status": "planning", "message": f"Starting {cli.label}…"}

    env = {**os.environ, "NO_COLOR": "1", "CI": os.environ.get("CI", "")}
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=str(root), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env=env, limit=LINE_LIMIT, **NO_WINDOW)
    except OSError as e:
        yield {"type": "error", "message": f"Could not start {cli.exe}: {e}"}
        return

    assert proc.stdin and proc.stdout and proc.stderr
    proc.stdin.write(prompt.encode("utf-8"))
    await proc.stdin.drain()
    proc.stdin.close()

    parse = agent_cli.PARSERS[cli_id]
    names: dict[str, str] = {}
    started: dict[str, float] = {}
    texts: list[str] = []
    partial = ""
    final, failed, steps, plain = "", "", 0, []
    t0 = time.time()

    async def lines():
        while True:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=max(1, TURN_TIMEOUT - (time.time() - t0)))
            if not line:
                return
            yield line

    try:
        async for raw in lines():
            text = raw.decode("utf-8", "replace").strip()
            if not text:
                continue
            try:
                ev = json.loads(text)
            except ValueError:
                plain.append(text)  # not JSON: keep it in case the CLI is explaining an error
                continue
            if not isinstance(ev, dict):
                continue
            events, sid = parse(ev)
            if sid:
                ext = {"cli": cli_id, "sessionId": sid}
            for out in events:
                t = out["type"]
                if t == "assistant_delta":
                    if out.pop("partial", False):  # Gemini streams small pieces of one message
                        partial += out["delta"]
                    else:
                        if partial:
                            texts.append(partial)
                            partial = ""
                        texts.append(out["delta"])
                    yield out
                    continue
                if partial and t in ("tool_start", "final", "error"):
                    texts.append(partial)
                    partial = ""
                while texts:  # whole assistant messages go into the thread file before the next tool
                    _log(root, thread_id, "assistant", texts.pop(0))
                if t == "tool_start":
                    steps += 1
                    if out.get("id"):
                        names[out["id"]] = out["tool"]
                        started[out["id"]] = time.time()
                    yield out
                elif t == "tool_result":
                    cid = out.get("id")
                    out.setdefault("tool", names.get(cid, "tool"))
                    out["durationMs"] = int((time.time() - started.pop(cid, time.time())) * 1000)
                    _log(root, thread_id, "tool", tool=out["tool"], id=cid, ok=out["ok"], output=out.get("output"),
                         error=out.get("error"), durationMs=out["durationMs"], via=cli_id)
                    yield out
                elif t == "final":
                    final = out.get("content") or ""
                elif t == "error":
                    failed = out["message"]
                else:
                    yield out
            # Log whole assistant messages (not Gemini's partial pieces) as they finish.
            while texts:
                _log(root, thread_id, "assistant", texts.pop(0))
    except asyncio.TimeoutError:
        proc.kill()
        failed = f"{cli.label} took longer than {TURN_TIMEOUT // 60} minutes and was stopped."
    except asyncio.CancelledError:  # the user pressed Stop
        proc.kill()
        raise
    finally:
        if proc.returncode is None:
            try:
                await asyncio.wait_for(proc.wait(), timeout=10)
            except asyncio.TimeoutError:
                proc.kill()

    if partial:
        _log(root, thread_id, "assistant", partial)
    err = (await proc.stderr.read()).decode("utf-8", "replace")[-4000:] if proc.stderr else ""
    s.external = ext
    s.save(root)

    if failed or proc.returncode not in (0, None):
        detail = failed or (err.strip() or "\n".join(plain[-5:]) or f"exit code {proc.returncode}")
        hint = agent_cli.login_hint(cli_id, detail + "\n" + err + "\n" + "\n".join(plain[-5:]))
        msg = hint or (detail if failed else f"{cli.label} failed: {detail[:1500]}")
        _log(root, thread_id, "assistant", f"Error: {msg}")
        yield {"type": "error", "message": msg}
        return
    yield {"type": "done", "content": final, "steps": steps, "via": cli_id}
