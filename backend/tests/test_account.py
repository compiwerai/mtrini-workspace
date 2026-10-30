"""Mtrini account on the desktop: sign-in polling, token storage, devices, sign-out, account deletion."""
import json
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

from mtrini import account


class FakeCloud:
    """Stand-in for Mtrini Cloud: one login that finishes on the second poll."""

    def __init__(self):
        self.polls = 0
        self.token = "session-abc"
        self.devices = [{"id": "dev-1", "name": "Mtrini Workspace on PC", "current": True},
                        {"id": "dev-2", "name": "Phone", "current": False}]
        self.identities = [{"provider": "google", "email": "a@x.test"}]
        self.seen = []

    def handler(self, req: httpx.Request) -> httpx.Response:
        path, auth = req.url.path, req.headers.get("authorization", "")
        self.seen.append((req.method, path, auth))
        me = {"user": {"id": "u1", "name": "Ayham", "email": "a@x.test"}, "identities": self.identities, "devices": self.devices}
        if path == "/health":
            return httpx.Response(200, json={"ok": True, "providers": ["google", "discord", "github"]})
        if path == "/auth/device":
            return httpx.Response(200, json={"login_id": "L1", "poll_secret": "S1", "url": "https://cloud.test/login/L1", "interval": 2})
        if path == "/auth/device/poll":
            assert json.loads(req.content) == {"login_id": "L1", "poll_secret": "S1"}
            self.polls += 1
            if self.polls < 2:
                return httpx.Response(200, json={"status": "pending"})
            return httpx.Response(200, json={"status": "done", "session_token": self.token, "device_id": "dev-1", **me})
        if auth != f"Bearer {self.token}":
            return httpx.Response(401, json={"error": {"code": "signed_out"}})
        if path == "/me" and req.method == "GET":
            return httpx.Response(200, json=me)
        if path == "/me" and req.method == "DELETE":
            return httpx.Response(200, json={"ok": True})
        if path == "/auth/logout":
            return httpx.Response(200, json={"ok": True})
        if path.startswith("/devices/"):
            self.devices = [d for d in self.devices if d["id"] != path.split("/")[2]]
            return httpx.Response(200, json={"ok": True})
        if path.startswith("/me/identities/"):
            if len(self.identities) == 1:
                return httpx.Response(400, json={"error": {"message": "This is your only sign-in. Link another one first."}})
            return httpx.Response(200, json=me)
        return httpx.Response(404)


@pytest.fixture()
def cloud(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "keyring", None)  # fallback file in the temp user folder, never the real keychain
    monkeypatch.setenv("MTRINI_CLOUD_URL", "https://cloud.test")
    monkeypatch.setenv("MTRINI_NO_BROWSER", "1")
    monkeypatch.setenv("MTRINI_WORKSPACE", str(tmp_path))
    fake = FakeCloud()
    monkeypatch.setattr(account, "_client", lambda: httpx.Client(base_url="https://cloud.test", transport=httpx.MockTransport(fake.handler)))
    account._pending.clear()
    from mtrini.main import app

    return fake, TestClient(app)


def test_not_configured_without_cloud(monkeypatch):
    monkeypatch.delenv("MTRINI_CLOUD_URL", raising=False)
    assert account.status() == {"configured": False, "signedIn": False}


def test_sign_in_poll_then_signed_in(cloud):
    fake, c = cloud
    assert c.get("/api/account").json() == {"configured": True, "reachable": True, "signedIn": False,
                                            "providers": ["google", "discord", "github"]}
    start = c.post("/api/account/login", json={"provider": "google"}).json()
    assert start == {"loginId": "L1", "url": "https://cloud.test/login/L1", "interval": 2}
    assert c.post("/api/account/poll/L1").json() == {"status": "pending"}
    done = c.post("/api/account/poll/L1").json()
    assert done["status"] == "done" and "session_token" not in done  # the token never reaches the UI
    me = c.get("/api/account").json()
    assert me["signedIn"] and me["user"]["name"] == "Ayham" and len(me["devices"]) == 2
    assert any(a == "Bearer session-abc" for _, p, a in fake.seen if p == "/me")


def test_devices_unlink_signout_and_delete(cloud):
    fake, c = cloud
    c.post("/api/account/login", json={})
    c.post("/api/account/poll/L1")
    c.post("/api/account/poll/L1")
    after = c.post("/api/account/devices/dev-2/revoke").json()
    assert [d["id"] for d in after["devices"]] == ["dev-1"]
    r = c.delete("/api/account/identities/google")
    assert r.status_code == 400 and "only sign-in" in r.json()["detail"]
    assert c.post("/api/account/logout").json() == {"ok": True}
    assert c.get("/api/account").json()["signedIn"] is False  # token forgotten locally

    c.post("/api/account/login", json={})
    fake.polls = 1
    c.post("/api/account/poll/L1")
    assert c.delete("/api/account").json() == {"ok": True}
    assert c.get("/api/account").json()["signedIn"] is False


def test_revoked_elsewhere_signs_out_here(cloud):
    fake, c = cloud
    c.post("/api/account/login", json={})
    fake.polls = 1
    c.post("/api/account/poll/L1")
    fake.token = "rotated"  # e.g. this device was revoked from the phone
    assert c.get("/api/account").json()["signedIn"] is False
    assert account._token() is None


def test_unknown_login_and_unreachable_cloud(cloud, monkeypatch):
    _, c = cloud
    assert c.post("/api/account/poll/nope").json() == {"status": "unknown"}

    def boom():
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(account, "_client", boom)
    assert c.get("/api/account").json() == {"configured": True, "reachable": False, "signedIn": False, "providers": []}
