"""Hooks: user shell commands that run at agent events (.mtrini/hooks.json).

    {"PreToolUse":  [{"matcher": "execute_command", "command": "python check.py"}],
     "PostToolUse": [{"matcher": "write_file|edit_file", "command": "npx prettier --write ."}],
     "UserPromptSubmit": [{"command": "..."}], "Stop": [{"command": "..."}]}

Each command gets the event as JSON on stdin. Exit code 2 from PreToolUse blocks
the tool call (stderr is the reason the model sees); exit 2 from UserPromptSubmit
blocks the prompt; stdout from UserPromptSubmit is added to the model's context.

A cloned repository could ship a hooks file, so hooks run only after the user
trusts that exact file: trust is stored outside the project, keyed by its hash.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from ..proc import NO_WINDOW

EVENTS = ("PreToolUse", "PostToolUse", "UserPromptSubmit", "Stop")
TIMEOUT = 60


def _hooks_file(root: Path) -> Path:
    return root / ".mtrini" / "hooks.json"


def _trust_file() -> Path:
    home = Path(os.environ.get("MTRINI_HOME") or Path.home() / ".mtrini")
    return home / "trusted-hooks.json"


def _digest(root: Path) -> str | None:
    try:
        return hashlib.sha256(_hooks_file(root).read_bytes()).hexdigest()
    except OSError:
        return None


def status(root: Path) -> dict[str, Any]:
    digest = _digest(root)
    if digest is None:
        return {"present": False, "trusted": False, "hooks": {}}
    try:
        trusted = json.loads(_trust_file().read_text(encoding="utf-8")).get(str(root.resolve())) == digest
    except (OSError, ValueError):
        trusted = False
    return {"present": True, "trusted": trusted, "hooks": load(root)}


def trust(root: Path) -> dict[str, Any]:
    digest = _digest(root)
    if digest is None:
        return status(root)
    f = _trust_file()
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data[str(root.resolve())] = digest
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return status(root)


def load(root: Path) -> dict[str, list[dict[str, str]]]:
    try:
        data = json.loads(_hooks_file(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {e: [h for h in data.get(e, []) if isinstance(h, dict) and h.get("command")]
            for e in EVENTS if isinstance(data.get(e), list)}


async def _run_one(root: Path, command: str, payload: dict[str, Any]) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_shell(
        command, cwd=str(root), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, **NO_WINDOW)
    try:
        out, err = await asyncio.wait_for(proc.communicate(json.dumps(payload, default=str).encode()), TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        return 1, "", f"hook timed out after {TIMEOUT}s"
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


async def run(root: Path, event: str, payload: dict[str, Any], tool: str | None = None) -> dict[str, Any]:
    """Run trusted hooks for an event. Returns {blocked, reason, context, ran}."""
    result: dict[str, Any] = {"blocked": False, "reason": "", "context": "", "ran": 0}
    st = status(root)
    if not st["trusted"]:
        return result
    for h in st["hooks"].get(event, []):
        matcher = h.get("matcher") or ""
        if tool and matcher and not re.fullmatch(matcher, tool):
            continue
        code, out, err = await _run_one(root, h["command"], {"event": event, "tool": tool, **payload})
        result["ran"] += 1
        if code == 2 and event in ("PreToolUse", "UserPromptSubmit"):
            result["blocked"] = True
            result["reason"] = (err or out).strip()[:2000] or f"blocked by hook: {h['command']}"
            return result
        if event == "UserPromptSubmit" and out.strip():
            result["context"] += out.strip()[:4000] + "\n"
    return result
