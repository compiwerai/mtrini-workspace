"""Mtrini Bots: shareable cards, recipes as links, and the first run on the free model."""
from __future__ import annotations

import base64
import json
import sys

import anyio
import pytest
from fastapi.testclient import TestClient

from mtrini import bots
from mtrini.agent import engine
from mtrini.bots import firstrun, routines, runner, share

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


class Scripted:
    def __init__(self, final: str):
        self.final, self.seen = final, []

    async def chat(self, model, messages, tools=None, **kw):
        self.seen.append(messages)
        return {"content": self.final, "tool_calls": []}


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "keyring", None)
    for d in (runner._STATE, runner._TASKS, runner._LOCKS, runner._GATES):
        d.clear()
    runner.LISTENERS.clear()
    # never write into the real Pictures or Documents, never open a real browser or file manager
    monkeypatch.setattr(share, "shared_dir", lambda kind="cards": (tmp_path / "shared" / kind).mkdir(parents=True, exist_ok=True)
                        or tmp_path / "shared" / kind)
    opened: list[str] = []
    monkeypatch.setattr(share.webbrowser, "open", lambda url: opened.append(url))
    monkeypatch.setattr(share.subprocess, "Popen", lambda *a, **k: opened.append(str(a[0])))
    yield opened


async def _wait_idle(bid: str):
    for _ in range(400):
        if not runner.busy(bid) and runner.state(bid)["status"] == "idle":
            return
        await anyio.sleep(0.02)
    raise AssertionError(runner.state(bid))


# ---- cards ----
def test_a_card_is_saved_as_a_png_and_nothing_else(tmp_path):
    p = share.save_card("data:image/png;base64," + base64.b64encode(PNG).decode(), "Scout / ../x")
    assert p.read_bytes() == PNG and p.parent == tmp_path / "shared" / "cards"
    assert p.name.startswith("Scout x card ") and p.suffix == ".png"
    for bad in ("not base64 !!", base64.b64encode(b"<svg/>").decode(), ""):
        with pytest.raises(bots.BotError):
            share.save_card(bad, "Scout")


def test_reveal_only_shows_files_mtrini_bots_saved(tmp_path, _clean):
    p = share.save_card(base64.b64encode(PNG).decode(), "Scout")
    share.reveal(str(p))
    assert _clean  # the file manager was asked
    with pytest.raises(bots.BotError):
        share.reveal(str(tmp_path / "elsewhere.png"))


def test_only_share_links_open(_clean):
    share.open_url("https://x.com/intent/post?text=hi&url=https%3A%2F%2Fcompiwer.ai%2Fbots")
    share.open_url("https://wa.me/?text=hi")
    assert _clean == ["https://x.com/intent/post?text=hi&url=https%3A%2F%2Fcompiwer.ai%2Fbots", "https://wa.me/?text=hi"]
    for bad in ("http://x.com/", "https://evil.example/x.com", "file:///C:/Windows", "https://x.com.evil.io/", "javascript:alert(1)"):
        with pytest.raises(bots.BotError):
            share.open_url(bad)


# ---- recipes ----
def test_a_recipe_carries_the_job_and_nothing_personal():
    b = bots.create("Compass", "Job scout", "Find openings that fit profile.md.", provider="openai", model="gpt-x", mascot="gecko")
    routines.upsert(b.id, {"title": "New openings", "kind": "daily", "time": "10:00", "prompt": "Check boards.md", "enabled": True})
    bots.say(b.id, "user", "my email is me@example.com")
    (bots.files_dir(b.id) / "profile.md").write_text("Private CV", encoding="utf-8")
    r = share.recipe(b.id)
    assert r == {"mtriniBot": 1, "name": "Compass", "role": "Job scout", "instructions": "Find openings that fit profile.md.",
                 "mascot": "gecko", "color": b.color,
                 "routines": [{"title": "New openings", "prompt": "Check boards.md", "kind": "daily", "time": "10:00"}]}
    text = json.dumps(r)
    assert "example.com" not in text and "Private CV" not in text and "gpt-x" not in text and "openai" not in text
    link = share.link(r)
    assert link.startswith("https://compiwer.ai/bots/r#") and "?" not in link
    for pasted in (link, link.split("#", 1)[1], json.dumps(r), f"  {link}\n"):
        assert share.parse(pasted) == r


def test_importing_a_recipe_makes_a_bot_on_the_free_model_with_routines_off():
    r = {"mtriniBot": 1, "name": "Compass", "role": "Job scout", "instructions": "x" * 9000, "mascot": "dragon", "color": "red",
         "provider": "openai", "apiKey": "sk-123",
         "routines": [{"title": "New openings", "kind": "daily", "time": "10:00", "prompt": "Check boards.md", "enabled": True},
                      {"title": "Broken", "kind": "daily", "time": "99:99", "prompt": "x"}, "nonsense"]}
    bots.create("Compass")
    b = share.import_recipe(share.link(r))
    assert b.name == "Compass 2" and b.provider == "free" and b.model == ""  # never the sharer's model or key
    assert len(b.instructions) == 4000 and b.mascot in bots.MASCOTS and b.color in bots.COLORS
    rs = routines.load(b.id)
    assert [x["title"] for x in rs] == ["New openings"] and rs[0]["enabled"] is False
    assert "apiKey" not in json.dumps(bots.get(b.id).public())
    for bad in ("", "https://compiwer.ai/bots/r#bm9wZQ", "{\"name\": \"x\"}", "hello world", "{" * 50_000):
        with pytest.raises(bots.BotError):
            share.parse(bad)


# ---- first run ----
def test_the_first_run_is_armed_for_scout_and_runs_once(monkeypatch):
    provider = Scripted("Scout found 3 AI stories for you\n- One https://a.example\n- Two https://b.example\n- Three https://c.example")
    monkeypatch.setattr(engine, "build_provider", lambda *a, **k: provider)
    made = bots.seed_starters()
    scout = next(b for b in made if b.name == "Scout")
    assert scout.provider == "free"  # the built-in model: no key
    assert firstrun.status()["state"] == "pending" and firstrun.status()["bot"] == scout.id

    async def go():
        assert firstrun.start()["state"] == "running"
        assert firstrun.start()["state"] in ("running", "done")  # a second window starts nothing new
        await _wait_idle(scout.id)
    anyio.run(go)

    st = firstrun.status()
    assert st["state"] == "done" and st["message"]["content"].startswith("Scout found 3 AI stories for you")
    convo = bots.conversation(scout.id)
    assert [m["role"] for m in convo] == ["user", "assistant"] and convo[0]["content"] == firstrun.SHOWN
    assert "first time" in provider.seen[0][0].content or any("first time" in m.content for m in provider.seen[0])
    report = [i for i in bots.inbox(scout.id) if i["kind"] == "result"]
    assert [i["title"] for i in report] == ["Scout found 3 AI stories for you"]
    assert all(not r["enabled"] for b in made for r in routines.load(b.id))  # routines still start switched off
    assert firstrun.seen()["state"] == "seen" and firstrun.start()["state"] == "seen"
    assert bots.seed_starters() == [] and firstrun.status()["state"] == "seen"


def test_no_first_run_without_a_fresh_crew():
    assert firstrun.status() == {"state": "none"}
    assert firstrun.start() == {"state": "none"}


def test_a_failed_first_run_can_be_tried_again(monkeypatch):
    class Down:
        async def chat(self, *a, **k):
            raise RuntimeError("You've used today's free model allowance.")
    monkeypatch.setattr(engine, "build_provider", lambda *a, **k: Down())
    scout = next(b for b in bots.seed_starters() if b.name == "Scout")

    async def go():
        firstrun.start()
        await _wait_idle(scout.id)
    anyio.run(go)
    assert firstrun.status()["state"] == "failed"
    assert not [i for i in bots.inbox(scout.id) if i["kind"] == "result"]
    monkeypatch.setattr(engine, "build_provider", lambda *a, **k: Scripted("Scout found 2 things"))

    async def again():
        assert firstrun.start()["state"] == "running"
        await _wait_idle(scout.id)
    anyio.run(again)
    assert firstrun.status()["state"] == "done"


# ---- API ----
def test_share_api(monkeypatch, _clean):
    monkeypatch.setattr(engine, "build_provider", lambda *a, **k: Scripted("Scout found 1 thing"))
    from mtrini.bots.app import app as bots_app

    with TestClient(bots_app) as c:
        assert c.get("/api/bots/first-run").json()["state"] == "pending"
        bid = c.get("/api/bots/first-run").json()["bot"]
        assert c.post("/api/bots/first-run/start").json()["state"] == "running"
        for _ in range(200):
            if c.get("/api/bots/first-run").json()["state"] == "done":
                break
            anyio.run(anyio.sleep, 0.02)
        assert c.get("/api/bots/first-run").json()["message"]["content"] == "Scout found 1 thing"
        saved = c.post("/api/bots/cards", json={"png": base64.b64encode(PNG).decode(), "name": "Scout"}).json()
        assert saved["path"].endswith(".png")
        assert c.post("/api/bots/reveal", json={"path": saved["path"]}).json() == {"ok": True}
        assert c.post("/api/bots/cards", json={"png": "nope", "name": "x"}).status_code == 400
        assert c.post("/api/bots/open", json={"url": "https://evil.example"}).status_code == 400
        assert c.post("/api/bots/open", json={"url": "https://wa.me/?text=hi"}).json() == {"ok": True}
        got = c.get(f"/api/bots/{bid}/recipe").json()
        assert got["recipe"]["name"] == "Scout" and got["link"].startswith(share.RECIPE_LINK)
        assert c.post("/api/bots/recipes/preview", json={"text": got["link"]}).json()["recipe"] == got["recipe"]
        assert c.post("/api/bots/recipes/preview", json={"text": "hi"}).status_code == 400
        made = c.post("/api/bots/recipes/import", json={"text": got["link"]}).json()
        assert made["name"] == "Scout 2" and made["routines"] == 1
        assert c.post(f"/api/bots/{bid}/recipe/save").json()["path"].endswith("Scout.mtrinibot.json")
        assert c.post("/api/bots/first-run/seen").json()["state"] == "seen"
