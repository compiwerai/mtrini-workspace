"""File safety + command classification.

Filesystem layer normalizes paths, prevents workspace escape, rejects
unsafe traversal, and follows a conservative symlink policy (resolved
path must stay inside the workspace).
"""
from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

SAFE_COMMANDS = ("git status", "git diff", "git log", "git branch", "git show",
                 "npm test", "npm run", "pytest", "python -m pytest", "python ",
                 "node ", "ls", "dir", "echo", "cat ", "pwd")
RISKY_PATTERNS = ("npm install", "pip install", "git reset", "git checkout",
                  "git clean", "rm ", "del ", "mv ", "move ")
DESTRUCTIVE_PATTERNS = (
    r"\brm\s+-rf\b", r"\bformat\b", r"\bmkfs\b", r"\bdd\b.*of=/dev",
    r"rd\s+/s", r"del\s+/[fs]", r":\(\)\s*\{\s*:\|\:&\s*\}",
)


def resolve_inside(root: Path, rel: str) -> Path:
    """Resolve rel against root, raising ValueError on escape attempt."""
    root = root.resolve()
    # Reject absolute paths outside root and null bytes upfront.
    if "\x00" in rel:
        raise ValueError("Invalid path: null byte")
    candidate = (root / rel).resolve() if not os.path.isabs(rel) else Path(rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise ValueError(f"Path escapes workspace: {rel!r}")
    return candidate


def classify_command(cmd: str) -> str:
    c = cmd.strip()
    for pat in DESTRUCTIVE_PATTERNS:
        if re.search(pat, c, re.IGNORECASE):
            return "destructive"
    low = c.lower()
    for p in RISKY_PATTERNS:
        if low.startswith(p):
            return "risky"
    return "safe"


def shell_for_platform() -> tuple[str, list[str]]:
    if os.name == "nt":
        return ("powershell", ["powershell", "-NoLogo", "-NoProfile", "-Command"])
    shell = os.environ.get("SHELL", "/bin/sh")
    name = os.path.basename(shell)
    return (name, [shell, "-lc"])


def split_command(cmd: str) -> list[str]:
    try:
        return shlex.split(cmd, posix=os.name != "nt")
    except ValueError:
        return [cmd]
