"""Mtrini account (optional): sign in with Google, Discord or GitHub through Mtrini Cloud.

Signing in opens the provider in your browser; the app polls Mtrini Cloud until the sign-in is
finished and stores the session token in the system keychain. Nothing else changes when you're
signed out: accounts are only needed for the phone app and sync.
"""
from __future__ import annotations

import json
import os
import platform
import socket
import time
from pathlib import Path
from typing import Any

import httpx

from .config import delete_secret, get_secret, set_secret, user_dir

# Set when Mtrini Cloud is deployed; MTRINI_CLOUD_URL overrides it (tests, self-hosting).
CLOUD_URL = "https://mtrini-cloud.roblox-event-bot-worker.workers.dev"
_SERVICE, _ACCOUNT = "mtrini-account", "session"
_pending: dict[str, dict[str, Any]] = {}  # login_id -> {secret, started}


def cloud_url() -> str:
    return (os.environ.get("MTRINI_CLOUD_URL") or CLOUD_URL).rstrip("/")


def _home() -> Path:
    return user_dir().parent  # secret helpers take a root; user-level secrets live beside ~/.mtrini


def _token() -> str | None:
    return get_secret(_home(), _SERVICE, _ACCOUNT)


def _client() -> httpx.Client:
    return httpx.Client(base_url=cloud_url(), timeout=20)


def _call(method: str, path: str, *, auth: bool = True, body: Any = None) -> httpx.Response:
    headers = {"authorization": f"Bearer {_token()}"} if auth and _token() else {}
    with _client() as c:
        return c.request(method, path, json=body, headers=headers)


def _device_name() -> str:
    try:
        host = socket.gethostname()
    except OSError:
        host = ""
    return f"Mtrini Workspace on {host}".strip()[:80] if host else "Mtrini Workspace"


def _forget_local() -> None:
    delete_secret(_home(), _SERVICE, _ACCOUNT)
    try:
        (user_dir() / "account.json").unlink()
    except OSError:
        pass


def status() -> dict[str, Any]:
    if not cloud_url():
        return {"configured": False, "signedIn": False}
    try:
        with _client() as c:
            providers = c.get("/health").json().get("providers", [])
    except Exception:
        return {"configured": True, "reachable": False, "signedIn": bool(_token()), "providers": []}
    out: dict[str, Any] = {"configured": True, "reachable": True, "signedIn": False, "providers": providers}
    if not _token():
        return out
    r = _call("GET", "/me")
    if r.status_code == 401:  # revoked from another device, or expired
        _forget_local()
        return out
    r.raise_for_status()
    return {**out, "signedIn": True, **r.json()}


def start_login(provider: str = "", link: bool = False) -> dict[str, Any]:
    if not cloud_url():
        raise RuntimeError("Mtrini accounts aren't available yet.")
    body = {"device_name": _device_name(), "platform": platform.system().lower(), "provider": provider}
    r = _call("POST", "/auth/device", auth=link, body=body)
    r.raise_for_status()
    data = r.json()
    _pending[data["login_id"]] = {"secret": data["poll_secret"], "started": time.time(), "link": link}
    if not os.environ.get("MTRINI_NO_BROWSER"):
        import webbrowser

        webbrowser.open(data["url"])
    return {"loginId": data["login_id"], "url": data["url"], "interval": data.get("interval", 2)}


def poll_login(login_id: str) -> dict[str, Any]:
    p = _pending.get(login_id)
    if not p:
        return {"status": "unknown"}
    r = _call("POST", "/auth/device/poll", auth=False, body={"login_id": login_id, "poll_secret": p["secret"]})
    if r.status_code == 404:
        _pending.pop(login_id, None)
        return {"status": "unknown"}
    r.raise_for_status()
    data = r.json()
    if data.get("status") == "done":
        set_secret(_home(), _SERVICE, _ACCOUNT, data["session_token"])
        (user_dir() / "account.json").write_text(json.dumps({"deviceId": data["device_id"]}), encoding="utf-8")
    if data.get("status") != "pending":
        _pending.pop(login_id, None)
    data.pop("session_token", None)  # never sent to the UI
    return data


def cancel_login(login_id: str) -> None:
    _pending.pop(login_id, None)


def logout() -> None:
    if _token() and cloud_url():
        try:
            _call("POST", "/auth/logout")
        except Exception:
            pass  # still forget it locally
    _forget_local()


def revoke_device(device_id: str) -> dict[str, Any]:
    r = _call("POST", f"/devices/{device_id}/revoke")
    r.raise_for_status()
    return status()


def unlink(provider: str) -> dict[str, Any]:
    r = _call("DELETE", f"/me/identities/{provider}")
    if r.status_code == 400:
        raise ValueError(r.json().get("error", {}).get("message", "Can't unlink that sign-in."))
    r.raise_for_status()
    return status()


def delete_account() -> None:
    r = _call("DELETE", "/me")
    r.raise_for_status()
    _forget_local()
