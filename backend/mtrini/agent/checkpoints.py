"""Checkpoints: keep each file's original content before the agent first changes it in a turn,
so the user can rewind the workspace to how it was before any turn.

Only changes made through the file tools are tracked; files changed by shell
commands (execute_command, run_python) are not, and the UI says so.
"""
from __future__ import annotations

import base64
import json
import shutil
from pathlib import Path
from typing import Any

from ..security import resolve_inside
from .session import keep_private

# tool -> argument names holding the paths it changes
FILE_TOOLS = {"write_file": ("path",), "edit_file": ("path",), "delete_file": ("path",),
              "move_file": ("src", "dst")}
_MAX_FILE = 5 * 1024 * 1024


def _dir(root: Path, sid: str, turn: int) -> Path:
    return root / ".mtrini" / "checkpoints" / sid / f"{turn:05d}"


def _manifest(d: Path) -> dict[str, Any]:
    try:
        return json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"files": {}}


def snapshot(root: Path, sid: str, turn: int, tool: str, args: dict[str, Any]) -> None:
    """Record the pre-change state of every path this tool call touches (first time per turn)."""
    keys = FILE_TOOLS.get(tool)
    if not keys:
        return
    d = _dir(root, sid, turn)
    man = _manifest(d)
    for k in keys:
        rel = str(args.get(k) or "").replace("\\", "/").strip("/")
        if not rel or rel in man["files"]:
            continue
        try:
            p = resolve_inside(root, rel)
        except ValueError:
            continue
        if p.is_dir():
            man["files"][rel] = {"kind": "dir"}  # directories are not restored (too large to copy)
        elif p.exists() and p.stat().st_size <= _MAX_FILE:
            man["files"][rel] = {"kind": "file", "data": base64.b64encode(p.read_bytes()).decode()}
        elif p.exists():
            man["files"][rel] = {"kind": "too_large"}
        else:
            man["files"][rel] = {"kind": "absent"}
    if not d.exists():
        d.mkdir(parents=True, exist_ok=True)
        keep_private(root)
    (d / "manifest.json").write_text(json.dumps(man), encoding="utf-8")


def list_turns(root: Path, sid: str) -> list[dict[str, Any]]:
    base = root / ".mtrini" / "checkpoints" / sid
    if not base.exists():
        return []
    out = []
    for d in sorted(base.iterdir()):
        if d.is_dir() and d.name.isdigit():
            out.append({"turn": int(d.name), "files": sorted(_manifest(d)["files"])})
    return out


def rewind(root: Path, sid: str, turn: int) -> dict[str, Any]:
    """Restore every file changed in `turn` and later, newest turn first. Returns what changed."""
    final: dict[str, str] = {}  # older turns overwrite newer ones: the oldest state wins
    for t in sorted((x["turn"] for x in list_turns(root, sid) if x["turn"] >= turn), reverse=True):
        d = _dir(root, sid, t)
        for rel, entry in _manifest(d)["files"].items():
            p = resolve_inside(root, rel)
            kind = entry.get("kind")
            if kind == "file":
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(base64.b64decode(entry["data"]))
                final[rel] = "restored"
            elif kind == "absent":
                if p.is_file():
                    p.unlink()  # the agent created it in a rewound turn
                final[rel] = "removed"
            else:
                final[rel] = "skipped"
        shutil.rmtree(d, ignore_errors=True)
    return {state: sorted(r for r, v in final.items() if v == state)
            for state in ("restored", "removed", "skipped")}
