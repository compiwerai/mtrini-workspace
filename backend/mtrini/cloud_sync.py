"""Cloud sync: saves this PC's sessions to Mtrini Cloud so they open on your phone (or any signed-in device)
even when the PC is off, and runs work the phone queued while the PC was away.

On while signed in, unless turned off in Settings → Account. Every few seconds it uploads sessions that
changed (cloud/src/sync.js keeps them per account, readable by Mtrini Cloud) and removes ones deleted here.
Big tool outputs and attached images are trimmed in the cloud copy; the copy on this PC is never changed by
the upload. Queued tasks run only when sealed by a phone paired with this PC (remote.open_task).

State lives in ~/.mtrini/sync.json: {enabled, threads: {id: {ws, mtime, rev}}}.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from . import account, remote, threads
from .config import user_dir

INTERVAL = 8  # seconds between sync passes
MAX_FIELD = 20_000  # characters of one text field in the cloud copy
MAX_THREAD = 1_400_000  # characters of one session in the cloud copy (the cloud takes 1.5 MB)
_lock = threading.RLock()
_runtime: dict[str, Any] = {"running": False, "last": 0, "error": "", "uploaded": 0, "task": None}
_thread: threading.Thread | None = None
_stop = threading.Event()
_wake = threading.Event()


# ---------------------------------------------------------------- state

def _path() -> Path:
    return user_dir() / "sync.json"


def load() -> dict[str, Any]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data.setdefault("enabled", True)
    data.setdefault("threads", {})
    return data


def _save(data: dict[str, Any]) -> None:
    _path().write_text(json.dumps(data, indent=1), encoding="utf-8")


def status() -> dict[str, Any]:
    data = load()
    with _lock:
        return {"enabled": data["enabled"], "signedIn": bool(account._token()), "running": _runtime["running"],
                "lastSync": _runtime["last"], "error": _runtime["error"], "sessions": len(data["threads"]),
                "task": _runtime["task"]}


def set_enabled(on: bool) -> dict[str, Any]:
    data = load()
    data["enabled"] = bool(on)
    _save(data)
    restart()
    return status()


# ---------------------------------------------------------------- the cloud copy

def _trim(value: Any, limit: int) -> Any:
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + f"\n… (trimmed in the cloud copy, {len(value)} characters)"
    if isinstance(value, list):
        return [_trim(v, limit) for v in value]
    if isinstance(value, dict):
        return {k: _trim(v, limit) for k, v in value.items()}
    return value


def cloud_copy(thread: dict[str, Any]) -> dict[str, Any] | None:
    """The session as uploaded: images left out, long fields trimmed, older ones harder if it's still too big."""
    msgs = []
    for m in thread.get("messages", []):
        m = dict(m)
        if m.get("images"):
            m["images"], m["imagesOmitted"] = [], len(m["images"])
        msgs.append(m)
    out = {**thread, "messages": [_trim(m, MAX_FIELD) for m in msgs]}
    if len(json.dumps(out)) <= MAX_THREAD:
        return out
    keep = 20  # the latest messages stay as they are; older ones shrink
    out["messages"] = [_trim(m, 1000) for m in out["messages"][:-keep]] + out["messages"][-keep:]
    if len(json.dumps(out)) <= MAX_THREAD:
        return out
    out["messages"] = [_trim(m, 500) for m in out["messages"]]
    return out if len(json.dumps(out)) <= MAX_THREAD else None


def _key(m: dict[str, Any]) -> tuple:
    return (m.get("role"), m.get("ts"), m.get("id"), str(m.get("content", ""))[:200])


def merge(local: dict[str, Any], cloud: dict[str, Any]) -> dict[str, Any]:
    """Local messages win (they're complete); messages only the cloud has are added in time order."""
    have = {_key(m) for m in local.get("messages", [])}
    extra = [m for m in cloud.get("messages", []) if _key(m) not in have]
    if not extra:
        return local
    msgs = sorted([*local.get("messages", []), *extra], key=lambda m: m.get("ts") or 0)
    return {**local, "messages": msgs, "updated": max(local.get("updated", 0), cloud.get("updated", 0))}


# ---------------------------------------------------------------- one pass

def _client() -> httpx.Client:
    return httpx.Client(base_url=account.cloud_url(), timeout=30,
                        headers={"authorization": f"Bearer {account._token()}"})


def _upload(c: httpx.Client, state: dict[str, Any], ws: str, f: Path) -> None:
    tid = f.stem
    try:
        mtime = f.stat().st_mtime
        local = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    known = state["threads"].get(tid)
    if known and known.get("mtime") == mtime and known.get("ws") == ws:
        return
    for _ in range(3):
        copy = cloud_copy(local)
        if copy is None:
            state["threads"][tid] = {"ws": ws, "mtime": mtime, "rev": known.get("rev") if known else None, "skipped": "too big"}
            return
        body: dict[str, Any] = {"thread": copy, "workspace": ws, "from_pc": True}
        if known and known.get("rev") is not None:
            body["base_rev"] = known["rev"]
        r = c.put(f"/sync/threads/{tid}", json=body)
        if r.status_code == 409:  # changed elsewhere: fold those messages in here, then try again
            cur = r.json()
            merged = merge(local, cur.get("thread") or {})
            if merged is not local:
                threads.save_thread(Path(ws), merged)
                local, mtime = merged, f.stat().st_mtime
            known = {"ws": ws, "rev": cur.get("rev")}
            continue
        r.raise_for_status()
        state["threads"][tid] = {"ws": ws, "mtime": mtime, "rev": r.json().get("rev")}
        with _lock:
            _runtime["uploaded"] += 1
        return


def _remove_deleted(c: httpx.Client, state: dict[str, Any]) -> None:
    for tid, info in list(state["threads"].items()):
        ws = Path(info.get("ws", ""))
        if ws.is_dir() and not (ws / ".mtrini" / "threads" / f"{tid}.json").exists():
            r = c.delete(f"/sync/threads/{tid}")
            if r.status_code < 500:
                state["threads"].pop(tid, None)


def _run_task(c: httpx.Client, task: dict[str, Any]) -> None:
    try:
        job = remote.open_task(task)
    except PermissionError as e:
        c.post(f"/sync/tasks/{task['id']}", json={"status": "failed", "error": str(e)})
        return
    c.post(f"/sync/tasks/{task['id']}", json={"status": "running"})
    with _lock:
        _runtime["task"] = {"id": task["id"], "workspace": job["workspace"], "prompt": job["prompt"][:120]}
    root = Path(job["workspace"])
    error, waiting = "", False
    try:
        if not root.is_dir():
            raise RuntimeError("That project folder isn't on this PC.")
        threads.ensure_thread(root, job["thread_id"], job["prompt"])
        body = {"message": job["prompt"], "threadId": job["thread_id"], "workspace": str(root),
                "permissionMode": job["mode"], "provider": job["provider"] or "free", "model": job["model"]}
        with httpx.Client(base_url=remote._local_base(), timeout=httpx.Timeout(30, read=None)) as local:
            with local.stream("POST", "/api/agent", json=body) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if line.startswith("data: "):
                        ev = json.loads(line[6:])
                        if ev.get("type") == "error":
                            error = str(ev.get("message", ""))[:400]
                        elif ev.get("type") in ("permission_request", "plan"):
                            waiting = True  # paused for your OK: answer it from the phone or the PC
                        if _stop.is_set():
                            break
    except Exception as e:  # the agent couldn't run: tell the phone why
        error = str(e)[:400] or type(e).__name__
    finally:
        with _lock:
            _runtime["task"] = None
    c.post(f"/sync/tasks/{task['id']}", json={"status": "failed" if error else "waiting" if waiting else "done", "error": error})


def sync_once() -> None:
    state = load()
    if not state["enabled"] or not account._token():
        return
    with _client() as c:
        for ws in threads.known_workspaces():
            for f in threads.thread_files(Path(ws)):
                if _stop.is_set():
                    break
                _upload(c, state, ws, f)
        _remove_deleted(c, state)
        _save({**load(), "threads": state["threads"]})
        if remote.load()["enabled"]:
            r = c.get("/sync/tasks", params={"pc": "me"})
            if r.status_code == 200:
                for task in r.json().get("tasks", []):
                    if _stop.is_set():
                        break
                    _run_task(c, task)
                    _upload_all_changed(c)


def _upload_all_changed(c: httpx.Client) -> None:
    state = load()
    for ws in threads.known_workspaces():
        for f in threads.thread_files(Path(ws)):
            _upload(c, state, ws, f)
    _save({**load(), "threads": state["threads"]})


# ---------------------------------------------------------------- background thread

def _loop() -> None:
    with _lock:
        _runtime["running"] = True
    while not _stop.is_set():
        try:
            sync_once()
            with _lock:
                _runtime.update(last=int(time.time()), error="")
        except httpx.HTTPStatusError as e:
            with _lock:
                _runtime["error"] = "Sign in again." if e.response.status_code == 401 else f"Mtrini Cloud answered {e.response.status_code}."
        except (httpx.HTTPError, OSError) as e:
            with _lock:
                _runtime["error"] = f"Can't reach Mtrini Cloud ({type(e).__name__})."
        _wake.wait(INTERVAL)
        _wake.clear()
    with _lock:
        _runtime["running"] = False


def start() -> None:
    """Start syncing if signed in and sync is on. Safe to call repeatedly."""
    global _thread
    if _thread and _thread.is_alive():
        return
    if not load()["enabled"] or not account._token():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="mtrini-sync", daemon=True)
    _thread.start()


def stop() -> None:
    global _thread
    _stop.set()
    _wake.set()
    if _thread:
        _thread.join(timeout=10)
    _thread = None


def restart() -> None:
    stop()
    start()


def nudge() -> None:
    """Sync soon (after a session changes)."""
    _wake.set()
