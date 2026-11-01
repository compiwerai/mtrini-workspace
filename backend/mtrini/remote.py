"""Remote access: lets a paired phone use this PC through Mtrini Cloud's bridge.

Off by default. When on (and signed in), the app keeps one outbound WebSocket to the bridge; nothing listens
on this PC. A phone must be paired once: it sends its public key, both screens show the same 6-digit code,
and you approve it here. After that, every phone message is end-to-end encrypted (remote_crypto) and goes
through `policy()` before it reaches the local API, so a phone can only do what the allow-list permits, only
in projects you shared, and never switches the agent to Auto mode unless you allowed that for the phone.
A phone you give Full access can do everything the app can, in any project, except change remote access itself.

State lives in ~/.mtrini/remote.json:
{enabled, pc_key, projects, paired: {phoneId: {name, pub, paired_at, allow_auto, full}}, tasks_done: [taskId, ...]}.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

from . import account
from . import remote_crypto as rc
from .config import user_dir

PAIR_TTL = 5 * 60  # seconds a pairing request waits for your answer
MAX_BODY = 512 * 1024  # bytes of a non-streamed response sent to the phone
_lock = threading.RLock()
_runtime: dict[str, Any] = {"connected": False, "error": "", "phones_online": [], "pending": {}}
_loop: asyncio.AbstractEventLoop | None = None
_ws = None
_openers: dict[str, rc.Opener] = {}


# ---------------------------------------------------------------- state

def _path() -> Path:
    return user_dir() / "remote.json"


def load() -> dict[str, Any]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data.setdefault("enabled", False)
    data.setdefault("projects", [])
    data.setdefault("paired", {})
    if not data.get("pc_key"):
        data["pc_key"] = rc.private_to_str(rc.new_private_key())
        _save(data)
    return data


def _save(data: dict[str, Any]) -> None:
    p = _path()
    p.write_text(json.dumps(data, indent=1), encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def _device_id() -> str:
    try:
        return json.loads((user_dir() / "account.json").read_text(encoding="utf-8")).get("deviceId", "")
    except (OSError, ValueError):
        return ""


def pc_public() -> str:
    return rc.public_str(rc.private_from_str(load()["pc_key"]))


def status() -> dict[str, Any]:
    data = load()
    now = time.time()
    with _lock:
        pending = [{"id": k, "name": v["name"], "code": v["code"]} for k, v in _runtime["pending"].items() if now - v["at"] < PAIR_TTL]
        return {
            "enabled": data["enabled"],
            "signedIn": bool(account._token()),
            "connected": _runtime["connected"],
            "error": _runtime["error"],
            "phonesOnline": _runtime["phones_online"],
            "paired": [{"id": k, "name": v.get("name", ""), "pairedAt": v.get("paired_at", 0), "allowAuto": bool(v.get("allow_auto")),
                        "full": bool(v.get("full"))} for k, v in data["paired"].items()],
            "pending": pending,
            "projects": data["projects"],
        }


def set_enabled(on: bool) -> dict[str, Any]:
    data = load()
    data["enabled"] = bool(on)
    _save(data)
    restart()
    return status()


def share_project(path: str, share: bool) -> dict[str, Any]:
    data = load()
    norm = str(Path(path).resolve())
    data["projects"] = [p for p in data["projects"] if p != norm] + ([norm] if share else [])
    _save(data)
    return status()


def shared(phone: dict[str, Any] | None = None) -> dict[str, Any]:
    """What a phone may open: the projects you shared, or with Full access every project this PC has used."""
    from . import threads

    paths = list(load()["projects"])
    if phone and phone.get("full"):
        paths += [p for p in threads.known_workspaces() if p not in paths]
    return {"projects": [{"path": p, "name": Path(p).name or p} for p in paths]}


def set_allow_auto(phone_id: str, allow: bool) -> dict[str, Any]:
    data = load()
    if phone_id in data["paired"]:
        data["paired"][phone_id]["allow_auto"] = bool(allow)
        _save(data)
    return status()


def set_full(phone_id: str, on: bool) -> dict[str, Any]:
    data = load()
    if phone_id in data["paired"]:
        data["paired"][phone_id]["full"] = bool(on)
        _save(data)
    return status()


def forget(phone_id: str) -> dict[str, Any]:
    data = load()
    data["paired"].pop(phone_id, None)
    _save(data)
    _openers.pop(phone_id, None)
    return status()


# ---------------------------------------------------------------- policy

_ALLOW = [
    ("GET", r"/api/(health|about|project|providers|models|skills|skills/[\w-]+|threads|threads/[\w-]+|git/status|git/diff|remote/shared"
            r"|agent/session/[\w-]+|permissions|images|images/[\w-]+/file|mcp/servers|automations)"),
    ("POST", r"/api/(agent|chat|threads|threads/[\w-]+/messages|agent/rewind|agent/compact)"),
    ("PATCH", r"/api/threads/[\w-]+"),
]
# These take a workspace and must name a shared project; the rest are not tied to a folder.
_NO_WORKSPACE = re.compile(r"/api/(health|about|providers|models|images|images/[\w-]+/file|remote/shared)$")


# Even with Full access a phone can't change remote access or sign the PC out: only someone at the PC can.
_PC_ONLY = re.compile(r"/api/(remote|account)(/.*)?$")


def policy(method: str, url: str, body: Any, phone: dict[str, Any], projects: list[str]) -> tuple[bool, str, Any]:
    """(allowed, reason, body) for a phone request. May rewrite the body (Auto mode -> Ask)."""
    parts = urlsplit(url)
    path = parts.path.rstrip("/") or "/"
    if phone.get("full"):
        if path == "/api/remote/shared":
            return True, "", body
        if _PC_ONLY.match(path) or not path.startswith("/api/"):
            return False, "Only someone at the PC can change this.", body
        return True, "", body
    if not any(method == m and re.fullmatch(rx, path) for m, rx in _ALLOW):
        return False, "Not allowed from a phone.", body
    if not _NO_WORKSPACE.match(path):
        ws = (parse_qs(parts.query).get("workspace") or [None])[0]
        if isinstance(body, dict) and body.get("workspace"):
            ws = body["workspace"]
        if not ws or str(Path(ws).resolve()) not in projects:
            return False, "This project isn't shared with your phone. Share it on the PC first.", body
    if isinstance(body, dict):
        body = dict(body)
        if body.get("approve") and not body.get("threadId"):
            return False, "Not allowed from a phone.", body
        if not phone.get("allow_auto"):
            if body.get("permissionMode") == "auto":
                body["permissionMode"] = "ask"
            if isinstance(body.get("resume"), dict) and body["resume"].get("mode") == "auto":
                body["resume"] = {**body["resume"], "mode": "ask"}
    return True, "", body


# ---------------------------------------------------------------- queued tasks

def open_task(task: dict[str, Any]) -> dict[str, Any]:
    """Check a task queued in the cloud: sealed by a phone paired with this PC, not run before, and allowed by
    that phone's access. Returns what to run: {thread_id, workspace, prompt, mode, provider, model}."""
    data = load()
    phone = data["paired"].get(task.get("from_device", ""))
    if not phone:
        raise PermissionError("Sent from a phone that isn't paired with this PC.")
    try:
        box = json.loads(task.get("prompt") or "")
        key = rc.shared_key(rc.private_from_str(data["pc_key"]), phone["pub"], pc_public(), phone["pub"])
        body = rc.open_sealed(key, task["from_device"], _device_id(), box)
    except Exception:
        raise PermissionError("This task isn't sealed by your phone, so it won't run.") from None
    if body.get("kind") != "task" or not body.get("task"):
        raise PermissionError("This task doesn't match what your phone sent.")
    if body["task"] in data.get("tasks_done", []):  # the id inside the seal, so a resent copy is refused too
        raise PermissionError("This task already ran.")
    ws = str(Path(body.get("workspace") or "").resolve())
    if body.get("thread_id") != task.get("thread_id") or ws != str(Path(task.get("workspace") or "").resolve()):
        raise PermissionError("This task doesn't match what your phone sent.")
    mode = body.get("mode") if body.get("mode") in ("ask", "auto", "readonly", "plan") else "ask"
    ok, reason, checked = policy("POST", "/api/agent", {"workspace": ws, "permissionMode": mode}, phone, data["projects"])
    if not ok:
        raise PermissionError(reason)
    data["tasks_done"] = (data.get("tasks_done", []) + [body["task"]])[-1000:]
    _save(data)
    return {"thread_id": body["thread_id"], "workspace": ws, "prompt": str(body.get("prompt") or ""),
            "mode": checked["permissionMode"], "provider": str(body.get("provider") or ""), "model": str(body.get("model") or "")}


# ---------------------------------------------------------------- bridge client

def _local_base() -> str:
    return os.environ.get("MTRINI_LOCAL_URL", "http://127.0.0.1:8787").rstrip("/")


def _local_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=_local_base(), timeout=httpx.Timeout(30, read=None))


async def _send(obj: dict) -> None:
    if _ws is not None:
        await _ws.send(json.dumps(obj))


async def _to_phone(phone_id: str, payload: dict) -> None:
    data = load()
    phone = data["paired"].get(phone_id)
    if not phone:
        return
    key = rc.shared_key(rc.private_from_str(data["pc_key"]), phone["pub"], pc_public(), phone["pub"])
    await _send({"t": "to", "to": phone_id, "data": rc.seal(key, _device_id(), phone_id, payload)})


def _opener(phone_id: str, phone: dict) -> rc.Opener:
    op = _openers.get(phone_id)
    if op is None:
        data = load()
        key = rc.shared_key(rc.private_from_str(data["pc_key"]), phone["pub"], pc_public(), phone["pub"])
        op = _openers[phone_id] = rc.Opener(key, phone_id, _device_id())
    return op


async def _handle_request(phone_id: str, phone: dict, req: dict) -> None:
    rid = req.get("rid")
    method = str(req.get("method", "GET")).upper()
    url = str(req.get("url", ""))
    ok, reason, body = policy(method, url, req.get("body"), phone, load()["projects"])
    if not ok:
        return await _to_phone(phone_id, {"kind": "res", "rid": rid, "status": 403, "body": json.dumps({"detail": reason})})
    if urlsplit(url).path.rstrip("/") == "/api/remote/shared":  # answered here: this module owns the sharing list
        return await _to_phone(phone_id, {"kind": "res", "rid": rid, "status": 200, "type": "application/json",
                                          "body": json.dumps(shared(phone))})
    async with _local_client() as c:
        kwargs = {"json": body} if body is not None else {}
        async with c.stream(method, url, **kwargs) as r:
            ctype = r.headers.get("content-type", "")
            if "text/event-stream" in ctype:
                await _to_phone(phone_id, {"kind": "head", "rid": rid, "status": r.status_code, "type": ctype})
                buf, last = "", time.monotonic()
                async for chunk in r.aiter_text():
                    buf += chunk
                    if len(buf) > 32_000 or time.monotonic() - last > 0.1:
                        await _to_phone(phone_id, {"kind": "chunk", "rid": rid, "data": buf})
                        buf, last = "", time.monotonic()
                if buf:
                    await _to_phone(phone_id, {"kind": "chunk", "rid": rid, "data": buf})
                return await _to_phone(phone_id, {"kind": "end", "rid": rid})
            raw = await r.aread()
            if len(raw) > MAX_BODY:
                return await _to_phone(phone_id, {"kind": "res", "rid": rid, "status": 413, "body": json.dumps({"detail": "Too large to send to the phone."})})
            text = raw.decode("utf-8", "replace") if "json" in ctype or ctype.startswith("text/") else ""
            b64 = "" if text or not raw else rc.b64u(raw)
            await _to_phone(phone_id, {"kind": "res", "rid": rid, "status": r.status_code, "type": ctype, "body": text, "b64": b64})


async def _on_message(msg: dict) -> None:
    t = msg.get("t")
    if t == "presence":
        with _lock:
            _runtime["phones_online"] = msg.get("phones", [])
        return
    if t != "from" or msg.get("role") != "phone":
        return
    phone_id, data = msg.get("from", ""), msg.get("data")
    paired = load()["paired"]
    if isinstance(data, dict) and data.get("kind") == "pair-req":
        pub = str(data.get("pub", ""))
        if not re.fullmatch(r"[\w-]{80,100}", pub):
            return
        with _lock:
            _runtime["pending"][phone_id] = {"name": str(data.get("name", "Phone"))[:80], "pub": pub,
                                              "code": rc.pairing_code(pc_public(), pub), "at": time.time()}
        return
    phone = paired.get(phone_id)
    if not phone:
        return await _send({"t": "to", "to": phone_id, "data": {"kind": "unpaired"}})
    try:
        req = _opener(phone_id, phone).open(data)
    except Exception:
        return  # undecryptable, stale or replayed: drop it
    if req.get("kind") == "req":
        asyncio.create_task(_handle_request(phone_id, phone, req))


def approve_pairing(phone_id: str) -> dict[str, Any]:
    with _lock:
        p = _runtime["pending"].pop(phone_id, None)
    if not p or time.time() - p["at"] > PAIR_TTL:
        raise ValueError("That pairing request has expired. Start again on the phone.")
    data = load()
    data["paired"][phone_id] = {"name": p["name"], "pub": p["pub"], "paired_at": int(time.time()), "allow_auto": False}
    _save(data)
    _openers.pop(phone_id, None)
    if _loop:
        asyncio.run_coroutine_threadsafe(_to_phone(phone_id, {"kind": "pair-ok"}), _loop)
    return status()


def deny_pairing(phone_id: str) -> dict[str, Any]:
    with _lock:
        _runtime["pending"].pop(phone_id, None)
    if _loop:
        asyncio.run_coroutine_threadsafe(_send({"t": "to", "to": phone_id, "data": {"kind": "pair-no"}}), _loop)
    return status()


async def _run(stop: asyncio.Event) -> None:
    global _ws
    import websockets

    delay = 2
    while not stop.is_set():
        data, token = load(), account._token()
        if not data["enabled"] or not token or not account.cloud_url():
            with _lock:
                _runtime.update(connected=False, error="" if data["enabled"] and token else "")
            return
        url = account.cloud_url().replace("https://", "wss://").replace("http://", "ws://") + "/bridge"
        try:
            async with websockets.connect(url, additional_headers={"authorization": f"Bearer {token}"},
                                          max_size=2 * 1024 * 1024, ping_interval=25) as ws:
                _ws = ws
                await ws.send(json.dumps({"t": "hello", "role": "pc", "name": socket.gethostname()[:80], "pub": pc_public()}))
                with _lock:
                    _runtime.update(connected=True, error="")
                delay = 2
                async for raw in ws:
                    if stop.is_set():
                        break
                    try:
                        await _on_message(json.loads(raw))
                    except Exception as e:  # never let one bad message drop the connection
                        with _lock:
                            _runtime["error"] = f"{type(e).__name__}: {e}"
        except Exception as e:
            with _lock:
                _runtime.update(connected=False, error=f"Can't reach Mtrini Cloud ({type(e).__name__}). Retrying…")
        finally:
            _ws = None
            with _lock:
                _runtime["connected"] = False
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass
        delay = min(delay * 2, 60)


_thread: threading.Thread | None = None
_stop: asyncio.Event | None = None


def start() -> None:
    """Start (or keep) the bridge connection if remote access is on. Safe to call repeatedly."""
    global _thread, _loop, _stop
    if _thread and _thread.is_alive():
        return
    if not load()["enabled"]:
        return

    def main() -> None:
        global _loop, _stop
        _loop = asyncio.new_event_loop()
        _stop = asyncio.Event()
        try:
            _loop.run_until_complete(_run(_stop))
        finally:
            _loop.close()
            _loop = None

    _thread = threading.Thread(target=main, name="mtrini-remote", daemon=True)
    _thread.start()


def stop() -> None:
    global _thread
    if _loop and _stop:
        _loop.call_soon_threadsafe(_stop.set)
        if _ws is not None:
            asyncio.run_coroutine_threadsafe(_ws.close(), _loop)
    if _thread:
        _thread.join(timeout=5)
    _thread = None
    with _lock:
        _runtime.update(connected=False, phones_online=[], pending={})


def restart() -> None:
    stop()
    start()
