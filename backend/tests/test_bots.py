"""Mtrini Bots: bots and their files, routines, turns with approvals, the browser's rules, Telegram."""
from __future__ import annotations

import datetime as dt
import json
import sys

import anyio
import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from mtrini import bots
from mtrini import browser as br
from mtrini.agent import engine
from mtrini.bots import background, routines, runner, telegram
from mtrini.tools import registry


class Scripted:
    """A model that makes the given tool calls, one per step, then says `final`."""

    def __init__(self, calls: list[dict], final: str = "All done."):
        self.calls, self.final, self.seen = list(calls), final, []

    async def chat(self, model, messages, tools=None, **kw):
        self.seen.append(messages)
        done = sum(1 for m in messages if m.role == "tool")
        if done < len(self.calls):
            c = self.calls[done]
            return {"content": "", "tool_calls": [{"id": f"c{done}", "name": c["name"], "arguments": json.dumps(c["args"])}]}
        return {"content": self.final, "tool_calls": []}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", None)  # secrets go to the temp user folder, never the real keychain
    runner._STATE.clear()
    runner._TASKS.clear()
    runner._LOCKS.clear()
    runner._GATES.clear()
    runner.LISTENERS.clear()
    yield
    runner.LISTENERS.clear()


def _use(monkeypatch, provider):
    monkeypatch.setattr(engine, "build_provider", lambda *a, **k: provider)


async def _wait_idle(bid: str, want: str = "idle"):
    for _ in range(400):
        if not runner.busy(bid) and runner.state(bid)["status"] == want:
            return
        await anyio.sleep(0.02)
    raise AssertionError(f"bot never became {want}: {runner.state(bid)} {bots.conversation(bid)[-2:]}")


# ---- bots and their files ----
def test_create_list_update_delete():
    a = bots.create("Scout", "Researcher", "Find things.")
    b = bots.create("Atlas")
    assert [x.name for x in bots.list_bots()] == ["Scout", "Atlas"]
    assert a.id == "scout" and a.color != b.color and bots.files_dir(a.id).is_dir()
    assert a.mascot in bots.MASCOTS and bots.get(a.id).mascot == a.mascot  # every bot has a mascot, and keeps it
    assert bots.update(a.id, {"mascot": "owl"}).mascot == "owl"
    with pytest.raises(bots.BotError, match="mascot"):
        bots.update(a.id, {"mascot": "dragon"})
    with pytest.raises(bots.BotError, match="already have a bot called scout"):
        bots.create("scout")
    with pytest.raises(bots.BotError, match="name"):
        bots.create("   ")
    assert bots.update(a.id, {"role": "Web  researcher", "paused": True}).role == "Web researcher"
    assert bots.get(a.id).paused is True
    with pytest.raises(bots.BotError):
        bots.update(a.id, {"name": "Atlas"})
    bots.delete(a.id)
    assert [x.name for x in bots.list_bots()] == ["Atlas"]
    with pytest.raises(bots.BotError):
        bots.get("../../etc")


def test_starter_crew_is_seeded_once_with_routines_off():
    mine = bots.create("scout", "My own researcher")  # a bot you already made is left alone
    made = bots.seed_starters()
    assert [b.name for b in made] == ["Atlas", "Sentinel", "Quill", "Herald"]
    assert bots.get(mine.id).role == "My own researcher"
    crew = bots.list_bots()
    assert len({b.mascot for b in crew}) == 5 and len({b.color for b in crew}) == 5  # easy to tell apart
    rs = [r for b in made for r in routines.load(b.id)]
    assert len(rs) == 3 and not any(r["enabled"] for r in rs)  # nothing runs until you switch it on
    assert routines.due(9e12) == []
    bots.delete(made[0].id)
    assert bots.seed_starters() == [] and "Atlas" not in [b.name for b in bots.list_bots()]  # deleted stays deleted


def test_inbox_and_conversation_are_plain_files():
    bot = bots.create("Scout")
    bots.say(bot.id, "user", "hello")
    it = bots.post(bot.id, "briefing", "Morning", "Nothing urgent.")
    assert bots.unread() == 1 and bots.inbox()[0]["title"] == "Morning"
    bots.update_item(bot.id, it["id"], {"read": True})
    assert bots.unread() == 0 and bots.clear_inbox() == 1 and bots.inbox() == []
    assert [m["content"] for m in bots.conversation(bot.id)] == ["hello"]
    assert bots.new_conversation(bot.id).session == 2 and bots.conversation(bot.id) == []


# ---- routines ----
def test_next_run_for_each_kind():
    mon_10 = dt.datetime(2026, 11, 9, 10, 0).timestamp()  # a Monday
    assert routines.next_run({"kind": "interval", "minutes": 30}, mon_10) == mon_10 + 1800
    assert routines.next_run({"kind": "interval", "minutes": 1}, mon_10) == mon_10 + 300  # never under 5 minutes
    later = dt.datetime.fromtimestamp(routines.next_run({"kind": "daily", "time": "18:15"}, mon_10))
    assert (later.day, later.hour, later.minute) == (9, 18, 15)
    tomorrow = dt.datetime.fromtimestamp(routines.next_run({"kind": "daily", "time": "08:30"}, mon_10))
    assert (tomorrow.day, tomorrow.hour) == (10, 8)
    friday = dt.datetime.fromtimestamp(routines.next_run({"kind": "weekly", "time": "09:00", "days": [4]}, mon_10))
    assert (friday.day, friday.weekday()) == (13, 4)
    assert routines.describe({"kind": "weekly", "time": "09:00", "days": [0, 4]}) == "Mon, Fri at 09:00"
    assert routines.describe({"kind": "interval", "minutes": 180}) == "Every 3 hours"


def test_routines_are_validated_and_due_once():
    bot = bots.create("Scout")
    with pytest.raises(bots.BotError, match="HH:MM"):
        routines.upsert(bot.id, {"title": "x", "prompt": "do it", "kind": "daily", "time": "25:00"})
    with pytest.raises(bots.BotError, match="at least one day"):
        routines.upsert(bot.id, {"title": "x", "prompt": "do it", "kind": "weekly", "time": "09:00", "days": []})
    r = routines.upsert(bot.id, {"title": "News", "prompt": "What's new?", "kind": "interval", "minutes": 60})
    assert r["when"] == "Every hour" and routines.due() == []
    soon = r["nextRun"] + 1
    assert [x[1]["id"] for x in routines.due(soon)] == [r["id"]]
    assert routines.due(soon) == []  # rescheduled: not returned twice
    bots.update(bot.id, {"paused": True})
    assert routines.due(soon + 99999) == []  # a paused bot runs nothing


# ---- turns ----
def test_bot_mode_lets_files_and_browsing_run_and_asks_for_the_rest():
    by = registry.BY_NAME
    free = ["read_file", "write_file", "web_search", "web_fetch", "browser_open", "browser_click", "browser_type", "remember"]
    asks = ["execute_command", "run_python", "delete_file", "browser_act"]
    assert not any(registry.needs_approval(by[n], "bot") for n in free)
    assert all(registry.needs_approval(by[n], "bot") for n in asks)


def test_a_turn_works_in_the_bots_own_folder_with_its_own_persona(monkeypatch):
    model = Scripted([{"name": "write_file", "args": {"path": "notes.md", "content": "seen\n"}}], "Saved your note.")
    _use(monkeypatch, model)
    bot = bots.create("Scout", "Researcher", "Keep notes.", provider="local", model="m")

    async def go():
        runner.start_turn(bot.id, "Note that I like tea")
        await _wait_idle(bot.id)
    anyio.run(go)

    assert (bots.files_dir(bot.id) / "notes.md").read_text() == "seen\n"
    convo = bots.conversation(bot.id)
    assert [m["role"] for m in convo] == ["user", "assistant"] and convo[1]["content"] == "Saved your note."
    assert convo[1]["steps"] == [{"tool": "write_file", "label": "Wrote notes.md", "ok": True}]
    system = model.seen[0][0].content
    assert "You are Scout" in system and "Researcher" in system and "Keep notes." in system
    assert "coding agent" not in system
    assert bots.inbox() == []  # a chat reply stays in the chat


def test_acting_for_the_user_waits_for_approval_and_resumes(monkeypatch, tmp_path):
    marker = tmp_path / "ran.txt"
    cmd = f'{sys.executable} -c "open(r\'{marker}\', \'w\').write(\'x\')"'
    _use(monkeypatch, Scripted([{"name": "execute_command", "args": {"command": cmd}}], "Command finished."))
    bot = bots.create("Atlas", provider="local", model="m")

    async def go():
        runner.start_turn(bot.id, "Run it")
        await _wait_idle(bot.id, "waiting")
        assert not marker.exists()  # nothing ran yet
        it = bots.inbox()[0]
        assert it["kind"] == "approval" and it["state"] == "pending" and "run a command" in it["title"]
        await runner.resolve(bot.id, it["id"], "allow")
        await _wait_idle(bot.id)
        with pytest.raises(bots.BotError, match="already answered"):
            await runner.resolve(bot.id, it["id"], "allow")
    anyio.run(go)

    assert marker.exists()
    assert bots.inbox()[0]["state"] == "approved"
    assert bots.conversation(bot.id)[-1]["content"] == "Command finished."


def test_denying_keeps_the_action_from_running(monkeypatch, tmp_path):
    marker = tmp_path / "ran.txt"
    cmd = f'{sys.executable} -c "open(r\'{marker}\', \'w\').write(\'x\')"'
    _use(monkeypatch, Scripted([{"name": "execute_command", "args": {"command": cmd}}], "OK, I did not run it."))
    bot = bots.create("Atlas", provider="local", model="m")

    async def go():
        runner.start_turn(bot.id, "Run it")
        await _wait_idle(bot.id, "waiting")
        await runner.resolve(bot.id, bots.inbox()[0]["id"], "deny")
        await _wait_idle(bot.id)
    anyio.run(go)

    assert not marker.exists() and bots.inbox()[0]["state"] == "denied"


def test_a_new_message_closes_a_waiting_approval(monkeypatch):
    _use(monkeypatch, Scripted([{"name": "execute_command", "args": {"command": "echo hi"}}], "Fine."))
    bot = bots.create("Atlas", provider="local", model="m")

    async def go():
        runner.start_turn(bot.id, "Run it")
        await _wait_idle(bot.id, "waiting")
        _use(monkeypatch, Scripted([], "Forgotten."))
        runner.start_turn(bot.id, "Never mind")
        await _wait_idle(bot.id)
    anyio.run(go)

    assert [it["state"] for it in bots.inbox() if it["kind"] == "approval"] == ["expired"]
    assert bots.conversation(bot.id)[-1]["content"] == "Forgotten."


def test_a_routine_reports_to_the_inbox_and_stays_quiet_when_nothing_changed(monkeypatch):
    bot = bots.create("Scout", provider="local", model="m")
    r = routines.upsert(bot.id, {"title": "News", "prompt": "What's new?", "kind": "interval", "minutes": 60})

    async def go(final):
        _use(monkeypatch, Scripted([], final))
        assert await runner.tick(r["nextRun"] + 1 + go.n * 4000) == 1
        go.n += 1
        await _wait_idle(bot.id)
    go.n = 0

    anyio.run(go, "Two new releases: A and B.")
    first = bots.inbox()[0]
    assert (first["kind"], first["title"], first["read"]) == ("briefing", "News", False)
    assert routines.load(bot.id)[0]["lastResult"] == "Two new releases: A and B."
    anyio.run(go, "No changes.")
    assert bots.inbox()[0]["read"] is True and bots.unread() == 1  # filed, but it does not nag
    assert bots.conversation(bot.id)[0]["content"] == "Routine: News"


def test_a_message_cut_off_by_a_restart_gets_a_note():
    bot = bots.create("Scout")
    bots.say(bot.id, "user", "hi")
    assert runner.recover() == 1 and runner.recover() == 0  # said once, not on every start
    last = bots.conversation(bot.id)[-1]
    assert last["role"] == "assistant" and "closed before I finished" in last["content"]


def test_a_failed_routine_says_so(monkeypatch):
    class Broken:
        async def chat(self, *a, **k):
            raise RuntimeError("model exploded")

    _use(monkeypatch, Broken())
    bot = bots.create("Scout", provider="local", model="m")
    r = routines.upsert(bot.id, {"title": "News", "prompt": "What's new?", "kind": "interval", "minutes": 60})

    async def go():
        await runner.tick(r["nextRun"] + 1)
        await _wait_idle(bot.id)
    anyio.run(go)

    it = bots.inbox()[0]
    assert it["kind"] == "error" and it["title"] == "News failed"
    assert bots.conversation(bot.id)[-1].get("error") is True


# ---- always on ----
def test_background_stays_only_when_asked_and_there_is_work(monkeypatch):
    applied = []
    monkeypatch.setattr(background, "_apply_autostart", lambda on: applied.append(on))  # never the real registry
    assert background.status() == {"keepRunning": False, "autostart": False, "installed": False, "desktop": False,
                                   "hasWork": False, "staysOn": False}
    background.save(keep_running=True)
    assert not background.should_stay()  # asked, but no bot has anything to do
    bot = bots.create("Scout")
    r = routines.upsert(bot.id, {"title": "News", "prompt": "What is new?", "kind": "daily", "time": "09:00"})
    assert background.should_stay()
    routines.upsert(bot.id, {**r, "enabled": False})
    assert not background.should_stay()  # a routine that is switched off is not work
    routines.upsert(bot.id, {**r, "enabled": True})
    bots.update(bot.id, {"paused": True})
    assert not background.should_stay()
    bots.update(bot.id, {"paused": False})
    background.save(keep_running=False)
    assert not background.should_stay()

    with pytest.raises(bots.BotError, match="installed app"):
        background.save(autostart=True)  # a development copy has nothing to start at sign-in
    assert applied == []
    monkeypatch.setattr(background.sys, "frozen", True, raising=False)
    st = background.save(autostart=True)
    assert applied == [True] and st["autostart"] and st["keepRunning"]  # starting hidden implies staying
    assert background.launch_command().endswith('" --background')
    background.save(autostart=False)
    assert applied == [True, False] and not background.settings()["autostart"]


# ---- the browser's rules ----
def test_risky_clicks_and_search_fields_are_told_apart():
    assert br.looks_risky({"tag": "button", "text": "Send message"})
    assert br.looks_risky({"tag": "button", "text": "Place order"})
    assert br.looks_risky({"tag": "button", "type": "submit", "text": "Go", "form": "contact /send"})
    assert br.looks_risky({"tag": "a", "aria": "Delete account"})
    assert not br.looks_risky({"tag": "a", "text": "Pricing"})
    assert not br.looks_risky({"tag": "button", "type": "submit", "text": "", "form": "search /search"})
    assert br.is_search_field({"tag": "input", "type": "search"})
    assert br.is_search_field({"tag": "input", "type": "text", "name": "q"})
    assert not br.is_search_field({"tag": "textarea", "name": "message"})


class _FakePage(br.Browser):
    def __init__(self, root, el):
        super().__init__(root)
        self.el, self.ran = el, []

    async def ensure(self):
        return None

    async def _describe(self, index):
        return self.el

    async def js(self, expression, timeout=30):
        self.ran.append(expression)
        return True

    async def _settle(self, timeout=20):
        return None

    async def _read(self):
        return {"url": "https://example.com/", "title": "Example", "text": "Hello", "elements": [{"i": 0, **self.el}]}


def test_browser_refuses_passwords_and_unapproved_actions(tmp_path):
    async def go():
        pw = _FakePage(tmp_path, {"tag": "input", "type": "password"})
        with pytest.raises(br.BrowserError, match="Passwords are never typed"):
            await pw.type(0, "hunter2")
        assert pw.ran == []
        send = _FakePage(tmp_path, {"tag": "button", "text": "Send"})
        with pytest.raises(br.BrowserError, match="browser_act"):
            await send.click(0)
        assert send.ran == []
        assert "URL: https://example.com/" in br.render(await send.click(0, approved=True)) and len(send.ran) == 1
        msg = _FakePage(tmp_path, {"tag": "textarea", "name": "message"})
        with pytest.raises(br.BrowserError, match="Pressing Enter"):
            await msg.type(0, "hi", enter=True)
        box = _FakePage(tmp_path, {"tag": "input", "type": "text", "name": "q"})
        assert '[0] input:text "q"' in br.render(await box.type(0, "mtrini", enter=True))
        with pytest.raises(br.BrowserError, match="http and https"):
            await box.open("file:///etc/passwd")
    anyio.run(go)


def test_browser_profile_is_kept_out_of_git(tmp_path):
    d = br.profile_dir(tmp_path)
    assert d == tmp_path / ".mtrini" / "browser"
    assert "browser/" in (tmp_path / ".mtrini" / ".gitignore").read_text()


# ---- Telegram ----
TOKEN = "123456789:AAExampleTokenForTests_abcdefghijklmnop"


@respx.mock
def test_telegram_pairs_one_chat_and_ignores_the_rest(monkeypatch):
    respx.get(f"{telegram.API}/bot{TOKEN}/getMe").mock(return_value=httpx.Response(200, json={"ok": True, "result": {"username": "my_mtrini_bot"}}))
    sent = respx.post(f"{telegram.API}/bot{TOKEN}/sendMessage").mock(return_value=httpx.Response(200, json={"ok": True, "result": {}}))
    monkeypatch.setattr(telegram, "start", lambda: None)
    _use(monkeypatch, Scripted([], "Hello from Scout."))
    bots.create("Atlas", provider="local", model="m")
    scout = bots.create("Scout", provider="local", model="m")
    runner.LISTENERS.append(telegram.on_event)

    async def go():
        with pytest.raises(bots.BotError, match="does not look like"):
            await telegram.connect("nope")
        st = await telegram.connect(TOKEN)
        assert st["connected"] and not st["paired"] and len(st["pairCode"]) == 6
        await telegram.handle({"message": {"chat": {"id": 666}, "text": "000000"}})  # wrong code: silence
        assert not telegram.status()["paired"] and sent.call_count == 0
        await telegram.handle({"message": {"chat": {"id": 42}, "text": "/start " + st["pairCode"]}})
        assert telegram.status()["paired"] and sent.call_count == 1
        await telegram.handle({"message": {"chat": {"id": 666}, "text": "@Scout hi"}})  # a stranger: nothing happens
        assert bots.conversation(scout.id) == []
        await telegram.handle({"message": {"chat": {"id": 42}, "text": "@Scout what's new?"}})
        await _wait_idle(scout.id)
        await anyio.sleep(0.05)  # the reply is forwarded by a listener task
    anyio.run(go)

    convo = bots.conversation(scout.id)
    assert convo[0]["content"] == "what's new?" and convo[0]["source"] == "telegram"
    last = json.loads(sent.calls.last.request.content)
    assert last["chat_id"] == 42 and last["text"] == "Scout: Hello from Scout."
    assert TOKEN not in (bots.home() / "telegram.json").read_text()  # the token is not in the config file
    assert telegram.disconnect() == {**telegram.status(), "connected": False, "paired": False}


@respx.mock
def test_telegram_approval_buttons(monkeypatch, tmp_path):
    respx.get(f"{telegram.API}/bot{TOKEN}/getMe").mock(return_value=httpx.Response(200, json={"ok": True, "result": {"username": "b"}}))
    sent = respx.post(f"{telegram.API}/bot{TOKEN}/sendMessage").mock(return_value=httpx.Response(200, json={"ok": True, "result": {}}))
    respx.post(f"{telegram.API}/bot{TOKEN}/answerCallbackQuery").mock(return_value=httpx.Response(200, json={"ok": True, "result": True}))
    monkeypatch.setattr(telegram, "start", lambda: None)
    marker = tmp_path / "ran.txt"
    cmd = f'{sys.executable} -c "open(r\'{marker}\', \'w\').write(\'x\')"'
    _use(monkeypatch, Scripted([{"name": "execute_command", "args": {"command": cmd}}], "Ran it."))
    bot = bots.create("Atlas", provider="local", model="m")
    runner.LISTENERS.append(telegram.on_event)

    async def go():
        st = await telegram.connect(TOKEN)
        await telegram.handle({"message": {"chat": {"id": 42}, "text": st["pairCode"]}})
        await telegram.handle({"message": {"chat": {"id": 42}, "text": "run the thing"}})
        await _wait_idle(bot.id, "waiting")
        await anyio.sleep(0.05)
        it = bots.inbox()[0]
        asked = json.loads(sent.calls.last.request.content)
        assert asked["reply_markup"]["inline_keyboard"][0][0] == {"text": "Approve", "callback_data": f"allow:{bot.id}:{it['id']}"}
        await telegram.handle({"callback_query": {"id": "q1", "data": f"allow:{bot.id}:{it['id']}", "message": {"chat": {"id": 666}}}})
        assert not marker.exists()  # a button pressed from another chat does nothing
        await telegram.handle({"callback_query": {"id": "q2", "data": f"allow:{bot.id}:{it['id']}", "message": {"chat": {"id": 42}}}})
        await _wait_idle(bot.id)
    anyio.run(go)
    assert marker.exists()


# ---- API ----
def test_api_round_trip(monkeypatch):
    _use(monkeypatch, Scripted([], "Hi, I'm Scout."))
    from mtrini.bots.app import app as bots_app
    from mtrini.main import app as workspace_app

    # Bots is its own app: Mtrini Workspace neither serves nor runs bots, so having both never runs a routine twice.
    assert not [r.path for r in workspace_app.routes if "/bots" in r.path]
    with TestClient(bots_app) as c:
        assert c.get("/api/health").json() == {"ok": True, "app": "mtrini-bots", "version": bots.__version__}
        assert c.get("/api/providers").status_code == 200  # the model picker works without Workspace running
        assert [t["key"] for t in c.get("/api/bots/templates").json()["templates"]][:2] == ["chief", "research"]
        crew = c.get("/api/bots").json()["bots"]  # the starter crew is already there on first run
        assert [b["name"] for b in crew] == ["Atlas", "Scout", "Sentinel", "Quill", "Herald"]
        assert len({b["mascot"] for b in crew}) == 5 and len({b["color"] for b in crew}) == 5
        for b in crew:
            assert c.delete(f"/api/bots/{b['id']}").json() == {"ok": True}
        made = c.post("/api/bots", json={"template": "research", "provider": "local", "model": "m"}).json()
        assert made["name"] == "Scout" and made["routines"] == 1 and made["state"]["status"] == "idle"
        assert made["mascot"] == "fennec"
        tpls = c.get("/api/bots/templates").json()["templates"]
        assert len(tpls) == 11 and all(t["mascot"] in bots.MASCOTS for t in tpls if t["key"] != "blank")
        assert len({t["mascot"] for t in tpls}) == 11  # each ready-made bot has its own
        bid = made["id"]
        assert c.post("/api/bots", json={"template": "research"}).status_code == 400  # same name twice
        assert c.get("/api/bots/nope").status_code == 404
        assert c.post(f"/api/bots/{bid}/message", json={"text": "  "}).status_code == 400
        assert c.post(f"/api/bots/{bid}/message", json={"text": "hello"}).json() == {"ok": True}
        for _ in range(200):
            msgs = c.get(f"/api/bots/{bid}/conversation").json()
            if len(msgs["messages"]) == 2 and not msgs["busy"]:
                break
            anyio.run(anyio.sleep, 0.02)
        assert msgs["messages"][1]["content"] == "Hi, I'm Scout."
        assert c.put(f"/api/bots/{bid}/memory", json={"text": "api_key = sk-abcdefghijklmnopqrstuv"}).status_code == 400
        assert c.put(f"/api/bots/{bid}/memory", json={"text": "- Likes tea\n"}).json() == {"ok": True}
        assert c.get(f"/api/bots/{bid}/memory").json()["text"] == "- Likes tea\n"
        (bots.files_dir(bid) / "topics.md").write_bytes(b"AI agents\n")
        assert [f["path"] for f in c.get(f"/api/bots/{bid}/files").json()["files"]] == ["topics.md"]
        assert c.get(f"/api/bots/{bid}/file", params={"path": "topics.md"}).json()["text"] == "AI agents\n"
        assert c.get(f"/api/bots/{bid}/file", params={"path": "../bot.json"}).status_code == 404
        assert c.get(f"/api/bots/{bid}/file", params={"path": ".mtrini/memory.md"}).status_code == 404
        r = c.post(f"/api/bots/{bid}/routines", json={"title": "Daily", "prompt": "Report.", "kind": "daily", "time": "07:05"}).json()
        assert r["when"] == "Every day at 07:05" and len(c.get(f"/api/bots/{bid}/routines").json()["routines"]) == 2
        assert c.delete(f"/api/bots/{bid}/routines/{r['id']}").json() == {"ok": True}
        assert c.patch(f"/api/bots/{bid}", json={"paused": True}).json()["paused"] is True
        assert c.post(f"/api/bots/{bid}/message", json={"text": "hi"}).status_code == 400  # paused
        assert c.get("/api/bots/telegram").json()["connected"] is False
        assert c.post("/api/bots/background", json={"keepRunning": True}).json()["keepRunning"] is True
        assert c.post("/api/bots/background", json={"autostart": True}).status_code == 400  # not the installed app
        assert c.post("/api/bots/background/quit").status_code == 400  # only the desktop app quits this way
        assert c.delete(f"/api/bots/{bid}").json() == {"ok": True}
        assert c.get("/api/bots").json()["bots"] == []
