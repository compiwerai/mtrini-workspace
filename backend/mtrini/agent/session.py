"""Agent sessions: the model-side conversation for a thread, kept between requests.

The thread file (threads.py) is what the UI shows; the session is what the model
sees: full tool calls and results, provider-native blocks, todos, and a pending
approval so an approved tool resumes the same loop instead of starting over.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..providers import ChatMessage

PRIVATE_DIRS = ("sessions/", "checkpoints/")


def keep_private(root: Path) -> None:
    """Sessions hold whole conversations and checkpoints hold file copies: keep both out of git."""
    gi = root / ".mtrini" / ".gitignore"
    try:
        have = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
        missing = [d for d in PRIVATE_DIRS if d not in have]
        if missing:
            gi.parent.mkdir(parents=True, exist_ok=True)
            gi.write_text("\n".join([*have, *missing]) + "\n", encoding="utf-8")
    except OSError:
        pass


def _path(root: Path, sid: str) -> Path:
    name = "".join(c for c in sid if c.isalnum() or c in "-_")[:64]
    if not name:
        raise ValueError("bad session id")
    d = root / ".mtrini" / "sessions"
    if not d.exists():
        d.mkdir(parents=True, exist_ok=True)
        keep_private(root)
    return d / f"{name}.json"


@dataclass
class Session:
    id: str
    messages: list[ChatMessage] = field(default_factory=list)
    todos: list[dict[str, Any]] = field(default_factory=list)
    pending: dict[str, Any] | None = None  # {kind: tool|plan, calls, index, ...}
    mode: str = "ask"
    turn: int = 0  # number of user turns so far (checkpoints are keyed by turn)
    turn_index: dict[str, int] = field(default_factory=dict)  # turn -> index of its user message
    persisted: bool = True

    def save(self, root: Path) -> None:
        if not self.persisted:
            return
        data = {"id": self.id, "messages": [m.to_dict() for m in self.messages], "todos": self.todos,
                "pending": self.pending, "mode": self.mode, "turn": self.turn, "turnIndex": self.turn_index}
        _path(root, self.id).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def load(root: Path, sid: str | None) -> Session:
    """Load a session by id; no id gives an in-memory session (old clients, one-off runs)."""
    if not sid:
        return Session(id="mem-" + uuid.uuid4().hex[:8], persisted=False)
    p = _path(root, sid)
    if not p.exists():
        return Session(id=sid)
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Session(id=sid)
    return Session(id=sid, messages=[ChatMessage.from_dict(m) for m in d.get("messages", [])],
                   todos=d.get("todos", []), pending=d.get("pending"), mode=d.get("mode", "ask"),
                   turn=d.get("turn", 0), turn_index=d.get("turnIndex", {}))


def delete(root: Path, sid: str) -> None:
    p = _path(root, sid)
    if p.exists():
        p.unlink()
