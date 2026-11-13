"""Tool registry: all tools, permission checks, OpenAI schema export."""
from __future__ import annotations

from . import Tool
from .extra import TOOLS as EXTRA
from .filesystem import TOOLS as FS
from .web import TOOLS as WEB


def _h_remember(root, args):
    from .. import memory

    return memory.add(root, str(args.get("fact", "")), str(args.get("scope") or "project"))


MEMORY = [Tool("remember", "Save a short, lasting fact to memory so future sessions know it: build or test "
               "commands, project conventions, decisions, or the user's preferences. scope 'project' (default) "
               "for this project, 'user' for preferences that apply everywhere. Never save secrets.", "read",
               {"type": "object", "properties": {"fact": {"type": "string"},
                                                 "scope": {"type": "string", "enum": ["project", "user"]}},
                "required": ["fact"]}, _h_remember)]

ALL: list[Tool] = [*FS, *EXTRA, *WEB, *MEMORY]
BY_NAME = {t.name: t for t in ALL}

ORDER = {"read": 0, "write": 1, "execute": 2, "network": 3, "destructive": 4}


def openai_schema() -> list[dict]:
    return [{"type": "function", "function": t.to_openai()} for t in ALL]


def needs_approval(tool: Tool, mode: str) -> bool:
    """mode: auto (allow all) | ask (confirm write+) | readonly | plan (read-only until a plan is approved)."""
    if mode == "auto":
        return False
    if mode in ("readonly", "plan"):
        return tool.permission != "read"
    # ask: write/execute/network/destructive need approval
    return ORDER.get(tool.permission, 9) >= 1
