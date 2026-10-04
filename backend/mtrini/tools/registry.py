"""Tool registry: all tools, permission checks, OpenAI schema export."""
from __future__ import annotations

from . import Tool
from .extra import TOOLS as EXTRA
from .filesystem import TOOLS as FS

ALL: list[Tool] = [*FS, *EXTRA]
BY_NAME = {t.name: t for t in ALL}

ORDER = {"read": 0, "write": 1, "execute": 2, "network": 3, "destructive": 4}


def openai_schema() -> list[dict]:
    return [{"type": "function", "function": t.to_openai()} for t in ALL]


def needs_approval(tool: Tool, mode: str) -> bool:
    """mode: auto (allow all) | ask (confirm write+) | readonly."""
    if mode == "auto":
        return False
    if mode == "readonly":
        return tool.permission != "read"
    # ask: write/execute/network/destructive need approval
    return ORDER.get(tool.permission, 9) >= 1
