"""First launch: one starter bot does a real job straight away, so a new user sees a result in seconds.

Scout (the researcher) runs one quick web search on the free built-in model: no key, no setup. Its answer
becomes the first report in the inbox and the first card the user can share. It happens once per install,
when the app window asks for it (not at sign-in in the background, where nobody would see it).
"""
from __future__ import annotations

import time
from typing import Any

from . import _LOCK, BotError, _read, _write, conversation, get, home

TEMPLATE = "research"
SHOWN = "Show me what you can do"
PROMPT = (
    "This is your first job, and the user is watching, so be quick. Make exactly one web_search for today's most "
    "interesting news in AI and technology, then answer. Do not open pages, write files or remember anything. "
    "Reply in this shape and nothing else:\n"
    "First line: a short headline of what you found, under 60 characters, such as \"Scout found 3 AI stories for you\".\n"
    "Then exactly 3 bullet points, one line each: what happened, in plain words, then the link."
)


def _path():
    return home() / "first_run.json"


def arm(bid: str) -> None:
    """Called when the starter crew is made: the first window that opens will run this bot."""
    with _LOCK:
        _write(_path(), {"bot": bid, "state": "pending"})


def status() -> dict[str, Any]:
    from . import runner

    data = _read(_path(), None)
    if not isinstance(data, dict) or not data.get("bot"):
        return {"state": "none"}
    bid = str(data["bot"])
    try:
        bot = get(bid)
    except BotError:
        return {"state": "none"}
    out: dict[str, Any] = {"bot": bid, "botName": bot.name, "provider": bot.provider}
    state = data.get("state")
    if state in ("pending", "seen"):
        return {**out, "state": state}
    if runner.busy(bid):
        return {**out, "state": "running"}
    after = [m for m in conversation(bid, 20) if m.get("ts", 0) >= float(data.get("started") or 0)]
    reply = next((m for m in reversed(after) if m.get("role") == "assistant"), None)
    if reply is None:  # the turn ended with no reply (the app closed, or it never started): offer to try again
        return {**out, "state": "failed"}
    return {**out, "state": "failed" if reply.get("error") or reply.get("stopped") else "done", "message": reply}


def start() -> dict[str, Any]:
    """Run the first job, once. Calling it again (a second window, a reload) changes nothing."""
    from . import runner

    with _LOCK:
        cur = status()
        if cur["state"] not in ("pending", "failed"):
            return cur
        if get(cur["bot"]).paused:
            return cur
        _write(_path(), {"bot": cur["bot"], "state": "started", "started": time.time()})
    runner.start_turn(cur["bot"], PROMPT, "first-run", shown=SHOWN)
    return {**cur, "state": "running"}


def seen() -> dict[str, Any]:
    with _LOCK:
        data = _read(_path(), None)
        if isinstance(data, dict) and data.get("bot"):
            _write(_path(), {**data, "state": "seen"})
    return status()
