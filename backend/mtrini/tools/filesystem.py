"""Filesystem tools with workspace confinement."""
from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from ..security import resolve_inside
from . import Tool

MAX_READ = 200_000


def _h_list(root: Path, a: dict[str, Any]):
    rel = a.get("path", ".")
    p = resolve_inside(root, rel)
    if not p.exists():
        raise FileNotFoundError(f"Not found: {rel}")
    if p.is_file():
        return {"path": rel, "type": "file", "size": p.stat().st_size}
    items = []
    for child in sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
        try:
            items.append({"name": child.name,
                          "type": "dir" if child.is_dir() else "file",
                          "size": child.stat().st_size if child.is_file() else 0})
        except OSError:
            continue
    return {"path": rel, "type": "dir", "entries": items[:500]}


def _h_read(root: Path, a: dict[str, Any]):
    p = resolve_inside(root, a["path"])
    data = p.read_bytes()
    if len(data) > MAX_READ:
        data = data[:MAX_READ]
    try:
        return {"path": a["path"], "content": data.decode("utf-8"), "truncated": len(p.read_bytes()) > MAX_READ}
    except UnicodeDecodeError:
        return {"path": a["path"], "binary": True, "size": len(data)}


def _h_write(root: Path, a: dict[str, Any]):
    p = resolve_inside(root, a["path"])
    p.parent.mkdir(parents=True, exist_ok=True)
    before = p.read_text(encoding="utf-8") if p.exists() else ""
    p.write_text(a["content"], encoding="utf-8")
    diff = list(difflib.unified_diff(before.splitlines(), a["content"].splitlines(), lineterm=""))[:200]
    return {"path": a["path"], "bytes": len(a["content"]), "diff": diff}


def _h_edit(root: Path, a: dict[str, Any]):
    p = resolve_inside(root, a["path"])
    text = p.read_text(encoding="utf-8")
    old, new = a["old"], a["new"]
    if old not in text:
        raise ValueError("oldString not found")
    if a.get("replaceAll"):
        text = text.replace(old, new)
    else:
        if text.count(old) > 1 and not a.get("firstOnly"):
            raise ValueError("oldString matches multiple times; use replaceAll or more context")
        text = text.replace(old, new, 1)
    p.write_text(text, encoding="utf-8")
    return {"path": a["path"], "ok": True}


def _h_delete(root: Path, a: dict[str, Any]):
    p = resolve_inside(root, a["path"])
    if p.is_dir():
        import shutil

        shutil.rmtree(p)
    elif p.exists():
        p.unlink()
    return {"ok": True}


def _h_move(root: Path, a: dict[str, Any]):
    src = resolve_inside(root, a["src"])
    dst = resolve_inside(root, a["dst"])
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    return {"ok": True, "dst": a["dst"]}


def _h_exists(root: Path, a: dict[str, Any]):
    try:
        p = resolve_inside(root, a["path"])
        return {"exists": p.exists()}
    except ValueError:
        return {"exists": False}


TOOLS = [
    Tool("list_directory", "List files in a workspace-relative directory", "read",
         {"type": "object", "properties": {"path": {"type": "string"}}, "required": []}, _h_list),
    Tool("read_file", "Read a workspace file as text", "read",
         {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}, _h_read),
    Tool("write_file", "Create or overwrite a workspace file", "write",
         {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
          "required": ["path", "content"]}, _h_write),
    Tool("edit_file", "Exact string replacement in a file", "write",
         {"type": "object", "properties": {"path": {"type": "string"}, "old": {"type": "string"},
                                           "new": {"type": "string"},
                                           "replaceAll": {"type": "boolean"}}, "required": ["path", "old", "new"]}, _h_edit),
    Tool("delete_file", "Delete a file or directory (destructive)", "destructive",
         {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}, _h_delete),
    Tool("move_file", "Move/rename a file", "write",
         {"type": "object", "properties": {"src": {"type": "string"}, "dst": {"type": "string"}},
          "required": ["src", "dst"]}, _h_move),
    Tool("file_exists", "Check existence of a path", "read",
         {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}, _h_exists),
]
