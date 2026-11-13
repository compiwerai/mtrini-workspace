"""Agent memory: short facts the agent keeps between sessions.

Two plain Markdown files you can read and edit:
- project memory, `.mtrini/memory.md` in the project (build commands, conventions, decisions);
- your memory, `~/.mtrini/memory.md` (preferences that apply to every project).

The agent adds lines with the `remember` tool, and both files go into its instructions at the
start of every session. Lines that look like secrets are refused.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from .config import user_dir

LIMIT = 6000  # characters of each file given to the model
HEADER = {"project": "# Project memory\n\nFacts Mtrini keeps about this project. Edit freely.\n\n",
          "user": "# Your memory\n\nPreferences Mtrini keeps for every project. Edit freely.\n\n"}
SECRET = re.compile(r"(sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|hf_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|"
                    r"-----BEGIN [A-Z ]*PRIVATE KEY|(password|passwd|secret|api[_-]?key|token)\s*[:=]\s*\S{6,})", re.I)


def path(root: Path, scope: str) -> Path:
    if scope == "user":
        return user_dir() / "memory.md"
    return root / ".mtrini" / "memory.md"


def read(root: Path, scope: str) -> str:
    try:
        return path(root, scope).read_text(encoding="utf-8")
    except OSError:
        return ""


def write(root: Path, scope: str, text: str) -> None:
    p = path(root, scope)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def add(root: Path, fact: str, scope: str = "project") -> str:
    fact = " ".join(str(fact).split())[:500]
    if scope not in ("project", "user"):
        scope = "project"
    if len(fact) < 3:
        raise ValueError("Nothing to remember.")
    if SECRET.search(fact):
        raise ValueError("That looks like a secret (a key, token or password). Secrets are never saved to memory.")
    cur = read(root, scope)
    if fact.lower() in cur.lower():
        return f"Already in {scope} memory."
    if not cur.strip():
        cur = HEADER[scope]
    write(root, scope, cur.rstrip("\n") + f"\n- {fact} <!-- {time.strftime('%Y-%m-%d')} -->\n")
    return f"Saved to {scope} memory ({path(root, scope).name})."


def for_prompt(root: Path) -> str:
    """Both memories, comments stripped, for the system prompt. Empty when there's nothing."""
    parts = []
    for scope, title in (("user", "Your memory (the user's preferences)"), ("project", "Project memory")):
        body = re.sub(r"<!--.*?-->", "", read(root, scope)).strip()
        body = "\n".join(ln for ln in body.splitlines() if not ln.startswith("# ") and "Edit freely." not in ln).strip()
        if body:
            parts.append(f"{title}:\n{body[-LIMIT:]}")
    return "\n\n".join(parts)
