"""Remote access: the phone policy, pairing, and encrypted requests through a fake bridge."""
import asyncio
import json

import httpx
import pytest

from mtrini import remote
from mtrini import remote_crypto as rc

PHONE = "ph1"
PC = "pc1"


@pytest.fixture()
def home(tmp_path, monkeypatch):
    from mtrini.config import user_dir

    (user_dir() / "account.json").write_text(json.dumps({"deviceId": PC}))
    (user_dir() / "remote.json").unlink(missing_ok=True)
    remote._runtime.update(pending={}, phones_online=[], connected=False, error="")
    remote._openers.clear()
    return tmp_path


class FakeBridge:
    def __init__(self):
        self.sent = []

    async def send(self, text):
        self.sent.append(json.loads(text))


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------- policy

def test_policy_allow_list_and_shared_projects(tmp_path):
    proj = str(tmp_path.resolve())
    def ok(m, u, b=None, phone=None):
        return remote.policy(m, u, b, phone or {}, [proj])

    assert ok("GET", "/api/models")[0]
    assert ok("GET", f"/api/threads?workspace={proj}")[0]
    assert ok("POST", "/api/agent", {"workspace": proj, "message": "hi"})[0]
    assert not ok("GET", "/api/threads?workspace=C:/somewhere/else")[0]  # not shared
    assert not ok("GET", "/api/threads")[0]  # no project named
    for m, u in [("POST", "/api/providers/configure"), ("GET", "/api/account"), ("POST", "/api/tools/execute"),
                 ("POST", "/api/terminal/exec"), ("POST", "/api/git/commit"), ("POST", "/api/permissions"),
                 ("DELETE", "/api/threads/abc"), ("POST", "/api/remote/settings"), ("POST", "/api/update/restart"),
                 ("POST", "/api/hooks/trust")]:
        assert not ok(m, f"{u}?workspace={proj}", {"workspace": proj})[0], (m, u)


def test_policy_downgrades_auto_mode_unless_allowed(tmp_path):
    proj = str(tmp_path.resolve())
    _, _, body = remote.policy("POST", "/api/agent", {"workspace": proj, "permissionMode": "auto",
                                                     "resume": {"decision": "approve", "mode": "auto"}}, {}, [proj])
    assert body["permissionMode"] == "ask" and body["resume"]["mode"] == "ask"
    _, _, body = remote.policy("POST", "/api/agent", {"workspace": proj, "permissionMode": "auto"}, {"allow_auto": True}, [proj])
    assert body["permissionMode"] == "auto"
    assert not remote.policy("POST", "/api/agent", {"workspace": proj, "approve": {"tool": "bash"}}, {}, [proj])[0]


# ---------------------------------------------------------------- pairing and requests

def phone_side(pc_pub):
    key = rc.new_private_key()
    pub = rc.public_str(key)
    shared = rc.shared_key(key, pc_pub, pc_pub, pub)
    return pub, shared


def test_pairing_needs_approval_and_then_requests_flow(home, monkeypatch, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    remote.share_project(str(proj), True)
    bridge = FakeBridge()
    monkeypatch.setattr(remote, "_ws", bridge)
    pc_pub = remote.pc_public()
    phone_pub, shared = phone_side(pc_pub)

    # 1. pairing request: shows a code, nothing is paired yet, and requests are refused
    run(remote._on_message({"t": "from", "from": PHONE, "role": "phone", "data": {"kind": "pair-req", "pub": phone_pub, "name": "Pixel"}}))
    st = remote.status()
    assert st["pending"][0]["code"] == rc.pairing_code(pc_pub, phone_pub) and st["paired"] == []
    box = rc.seal(shared, PHONE, PC, {"kind": "req", "rid": 1, "method": "GET", "url": "/api/models"})
    run(remote._on_message({"t": "from", "from": PHONE, "role": "phone", "data": box}))
    assert bridge.sent[-1] == {"t": "to", "to": PHONE, "data": {"kind": "unpaired"}}

    # 2. approve on the PC: paired, and the phone gets an encrypted pair-ok it can open
    monkeypatch.setattr(remote, "_loop", None)  # send directly below instead of via the loop
    remote.approve_pairing(PHONE)
    run(remote._to_phone(PHONE, {"kind": "pair-ok"}))
    got = rc.Opener(shared, PC, PHONE).open(bridge.sent[-1]["data"])
    assert got["kind"] == "pair-ok" and remote.status()["paired"][0]["name"] == "Pixel"

    # 3. an allowed request runs against the local API; a forbidden one gets 403 without touching it
    calls = []

    def local(req: httpx.Request):
        calls.append(req.url.path)
        if req.url.path == "/api/agent":
            assert json.loads(req.content)["permissionMode"] == "ask"  # downgraded from auto
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=b'data: {"type":"done"}\n\n')
        return httpx.Response(200, json={"models": ["qwen38"]})
    monkeypatch.setattr(remote, "_local_client", lambda: httpx.AsyncClient(base_url="http://local", transport=httpx.MockTransport(local)))
    opener = rc.Opener(shared, PC, PHONE)

    async def ask(payload):
        bridge.sent.clear()
        await remote._on_message({"t": "from", "from": PHONE, "role": "phone", "data": rc.seal(shared, PHONE, PC, payload)})
        await asyncio.sleep(0.05)  # let the request task finish
        return [opener.open(m["data"]) for m in bridge.sent]

    out = run(ask({"kind": "req", "rid": 2, "method": "GET", "url": "/api/models"}))
    assert out[0]["status"] == 200 and json.loads(out[0]["body"]) == {"models": ["qwen38"]}
    out = run(ask({"kind": "req", "rid": 3, "method": "POST", "url": "/api/providers/configure", "body": {}}))
    assert out[0]["status"] == 403 and "/api/providers/configure" not in calls
    out = run(ask({"kind": "req", "rid": 4, "method": "POST", "url": "/api/agent",
                   "body": {"workspace": str(proj), "permissionMode": "auto", "message": "fix it"}}))
    assert [m["kind"] for m in out] == ["head", "chunk", "end"] and "done" in out[1]["data"]


def test_replayed_request_is_dropped(home, monkeypatch, tmp_path):
    bridge = FakeBridge()
    monkeypatch.setattr(remote, "_ws", bridge)
    pc_pub = remote.pc_public()
    phone_pub, shared = phone_side(pc_pub)
    data = remote.load()
    data["paired"][PHONE] = {"name": "Pixel", "pub": phone_pub, "paired_at": 0}
    remote._save(data)
    hits = []
    monkeypatch.setattr(remote, "_local_client", lambda: httpx.AsyncClient(
        base_url="http://local", transport=httpx.MockTransport(lambda r: hits.append(1) or httpx.Response(200, json={}))))
    box = rc.seal(shared, PHONE, PC, {"kind": "req", "rid": 1, "method": "GET", "url": "/api/models"})

    async def twice():
        for _ in range(2):
            await remote._on_message({"t": "from", "from": PHONE, "role": "phone", "data": box})
        await asyncio.sleep(0.05)
    run(twice())
    assert len(hits) == 1


def test_expired_pairing_and_api(home, monkeypatch):
    from fastapi.testclient import TestClient

    from mtrini.main import app

    c = TestClient(app)
    assert c.get("/api/remote").json()["enabled"] is False
    assert c.post("/api/remote/pair/nobody/approve").status_code == 410
    monkeypatch.setattr(remote, "restart", lambda: None)
    assert c.post("/api/remote/settings", json={"enabled": True}).json()["enabled"] is True
