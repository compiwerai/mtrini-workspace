"""Threads (persisted agent conversations) + automations (saved runnable prompts)."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any


def _threads_dir(root: Path) -> Path:
    d = root / ".mtrini" / "threads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _tid_path(root: Path, tid: str) -> Path:
    name = "".join(c for c in tid if c.isalnum() or c in "-_")[:64]
    if not name:
        raise ValueError("bad thread id")
    return _threads_dir(root) / f"{name}.json"


def list_threads(root: Path) -> list[dict[str, Any]]:
    out = []
    for f in sorted(_threads_dir(root).glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            msgs = data.get("messages", [])
            last = msgs[-1].get("content", "")[:120] if msgs else ""
            out.append({"id": data.get("id", f.stem), "title": data.get("title", "Untitled"),
                        "updated": data.get("updated", 0), "messages": len(msgs), "preview": last,
                        "workspace": data.get("workspace", "")})
        except OSError:
            continue
    return out


def create_thread(root: Path, title: str, workspace: str | None = None) -> dict[str, Any]:
    tid = uuid.uuid4().hex[:12]
    now = int(time.time())
    data = {"id": tid, "title": title.strip() or "Untitled", "created": now, "updated": now,
            "workspace": workspace or str(root), "messages": []}
    _tid_path(root, tid).write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def get_thread(root: Path, tid: str) -> dict[str, Any]:
    p = _tid_path(root, tid)
    if not p.exists():
        raise FileNotFoundError("thread not found")
    return json.loads(p.read_text(encoding="utf-8"))


def append_message(root: Path, tid: str, role: str, content: str) -> dict[str, Any]:
    data = get_thread(root, tid)
    data["messages"].append({"role": role, "content": content, "ts": int(time.time())})
    data["updated"] = int(time.time())
    _tid_path(root, tid).write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def delete_thread(root: Path, tid: str) -> bool:
    p = _tid_path(root, tid)
    if p.exists():
        p.unlink()
        return True
    return False


def rename_thread(root: Path, tid: str, title: str, workspace: str | None = None) -> dict[str, Any]:
    data = get_thread(root, tid)
    if title.strip():
        data["title"] = title.strip()
    if workspace:
        data["workspace"] = workspace
    data["updated"] = int(time.time())
    _tid_path(root, tid).write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


# ---- automations: named saved prompts, runnable in one click ----

def _auto_path(root: Path) -> Path:
    return root / ".mtrini" / "automations.json"


def list_automations(root: Path) -> list[dict[str, Any]]:
    p = _auto_path(root)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save_automation(root: Path, name: str, prompt: str) -> dict[str, Any]:
    (root / ".mtrini").mkdir(parents=True, exist_ok=True)
    items = list_automations(root)
    item = {"id": uuid.uuid4().hex[:8], "name": name.strip(), "prompt": prompt,
            "created": int(time.time())}
    items.append(item)
    _auto_path(root).write_text(json.dumps(items, indent=2), encoding="utf-8")
    return item


def delete_automation(root: Path, aid: str) -> bool:
    items = [a for a in list_automations(root) if a.get("id") != aid]
    _auto_path(root).write_text(json.dumps(items, indent=2), encoding="utf-8")
    return True
