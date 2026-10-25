"""Always-allow rules (.mtrini/permissions.json), set from the approval card.

A rule is a tool name ("write_file"), or for shell commands a command prefix
("execute_command:npm test"). Commands the classifier marks destructive are
never auto-allowed by a rule, and a prefix only matches at a word boundary.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..security import classify_command

_CHAIN = ("&&", "||", ";", "|", "`", "$(", ">", "<", "\n", "&")


def _path(root: Path) -> Path:
    return root / ".mtrini" / "permissions.json"


def load_rules(root: Path) -> list[str]:
    try:
        data = json.loads(_path(root).read_text(encoding="utf-8"))
        return [r for r in data.get("allow", []) if isinstance(r, str)]
    except (OSError, ValueError, AttributeError):
        return []


def save_rules(root: Path, rules: list[str]) -> None:
    _path(root).parent.mkdir(parents=True, exist_ok=True)
    _path(root).write_text(json.dumps({"allow": sorted(set(rules))}, indent=2), encoding="utf-8")


def command_prefix(cmd: str) -> str:
    """'npm test -- --watch' -> 'npm test'; 'ls -la' -> 'ls'."""
    words = cmd.strip().split()
    if not words:
        return ""
    if len(words) > 1 and not words[1].startswith(("-", "/", ".", "\\")) and ":" not in words[1]:
        return f"{words[0]} {words[1]}"
    return words[0]


def rule_for(tool: str, args: dict[str, Any]) -> str:
    if tool == "execute_command":
        prefix = command_prefix(str(args.get("command", "")))
        return f"{tool}:{prefix}" if prefix else tool
    return tool


def is_allowed(root: Path, tool: str, args: dict[str, Any]) -> bool:
    rules = load_rules(root)
    if tool == "execute_command":
        cmd = str(args.get("command", "")).strip()
        if classify_command(cmd) == "destructive":
            return False
        # A prefix rule covers one command, never a chain or redirect hidden behind it.
        if any(op in cmd for op in _CHAIN):
            return tool in rules

        for r in rules:
            if r == tool:
                return True
            if r.startswith(tool + ":"):
                prefix = r.split(":", 1)[1]
                if cmd == prefix or cmd.startswith(prefix + " "):
                    return True
        return False
    return tool in rules


def add_rule(root: Path, tool: str, args: dict[str, Any]) -> str:
    rule = rule_for(tool, args)
    save_rules(root, [*load_rules(root), rule])
    return rule
