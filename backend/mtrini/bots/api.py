"""HTTP API for Mtrini Bots (mounted under /api/bots)."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .. import bots, memory
from .. import browser as br
from . import background, firstrun, routines, runner, share, telegram

router = APIRouter(prefix="/api/bots")


def _fail(e: Exception) -> HTTPException:
    return HTTPException(400, str(e))


def _view(bot: bots.Bot) -> dict[str, Any]:
    items = bots.inbox(bot.id)
    return {**bot.public(), "state": runner.state(bot.id), "busy": runner.busy(bot.id),
            "folder": str(bots.files_dir(bot.id)), "routines": len(routines.load(bot.id)),
            "unread": sum(1 for it in items if not it.get("read")),
            "waiting": sum(1 for it in items if it.get("kind") == "approval" and it.get("state") == "pending")}


class BotBody(BaseModel):
    name: str = ""
    role: str = ""
    instructions: str = ""
    provider: str = "free"
    model: str = ""
    effort: str = "off"
    color: str = ""
    mascot: str = ""
    template: str = ""


class BotPatch(BaseModel):
    name: str | None = None
    role: str | None = None
    instructions: str | None = None
    provider: str | None = None
    model: str | None = None
    effort: str | None = None
    color: str | None = None
    mascot: str | None = None
    paused: bool | None = None


@router.get("")
def list_bots():
    return {"bots": [_view(b) for b in bots.list_bots()], "unread": bots.unread(),
            "browser": br.find_browser() is not None, "colors": bots.COLORS, "mascots": bots.MASCOTS}


@router.get("/templates")
def templates():
    return {"templates": [{k: t[k] for k in ("key", "name", "role", "instructions", "mascot")}
                          | {"routines": [r["title"] for r in t["routines"]]} for t in bots.TEMPLATES]}


@router.post("")
def create(body: BotBody):
    tpl = next((t for t in bots.TEMPLATES if t["key"] == body.template), None)
    try:
        bot = bots.create(body.name or (tpl or {}).get("name", ""), body.role or (tpl or {}).get("role", ""),
                          body.instructions or (tpl or {}).get("instructions", ""), body.provider, body.model,
                          body.effort, body.color, body.mascot or (tpl or {}).get("mascot", ""))
        for r in (tpl or {}).get("routines", []):
            routines.upsert(bot.id, r)
    except bots.BotError as e:
        raise _fail(e) from None
    runner.publish({"type": "bots"})
    return _view(bot)


# ---- inbox, events and Telegram come before /{bid} so their paths are not read as a bot id ----
@router.get("/inbox")
def inbox():
    names = {b.id: {"name": b.name, "color": b.color, "mascot": b.mascot} for b in bots.list_bots()}
    return {"items": [{**it, "botName": names.get(it.get("bot"), {}).get("name", "Bot"),
                       "botColor": names.get(it.get("bot"), {}).get("color", ""),
                       "botMascot": names.get(it.get("bot"), {}).get("mascot", "")} for it in bots.inbox()],
            "unread": bots.unread()}


class ReadBody(BaseModel):
    read: bool = True


@router.post("/inbox/read-all")
def inbox_read_all():
    for it in bots.inbox():
        if not it.get("read") and not (it.get("kind") == "approval" and it.get("state") == "pending"):
            bots.update_item(it["bot"], it["id"], {"read": True})
    return {"unread": bots.unread()}


@router.post("/inbox/clear")
def inbox_clear():
    return {"removed": bots.clear_inbox(), "unread": bots.unread()}


@router.post("/inbox/{bid}/{iid}/read")
def inbox_read(bid: str, iid: str, body: ReadBody):
    try:
        return bots.update_item(bid, iid, {"read": body.read})
    except bots.BotError as e:
        raise _fail(e) from None


class ResolveBody(BaseModel):
    decision: str


@router.post("/inbox/{bid}/{iid}/resolve")
async def inbox_resolve(bid: str, iid: str, body: ResolveBody):
    try:
        return await runner.resolve(bid, iid, body.decision)
    except bots.BotError as e:
        raise _fail(e) from None


@router.get("/events")
async def events():
    q = runner.subscribe()

    async def gen():
        try:
            yield "data: " + json.dumps({"type": "hello"}) + "\n\n"
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), 15)
                    yield "data: " + json.dumps(ev, default=str) + "\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            runner.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class TelegramBody(BaseModel):
    token: str = ""
    defaultBot: str = ""


@router.get("/telegram")
def telegram_status():
    return telegram.status()


@router.post("/telegram")
async def telegram_connect(body: TelegramBody):
    try:
        if body.token:
            return await telegram.connect(body.token)
        if body.defaultBot:
            return telegram.set_default(body.defaultBot)
    except bots.BotError as e:
        raise _fail(e) from None
    return telegram.status()


@router.delete("/telegram")
def telegram_disconnect():
    return telegram.disconnect()


class BackgroundBody(BaseModel):
    keepRunning: bool | None = None
    autostart: bool | None = None


@router.get("/background")
def background_status():
    return background.status()


@router.post("/background")
def background_save(body: BackgroundBody):
    try:
        return background.save(body.keepRunning, body.autostart)
    except bots.BotError as e:
        raise _fail(e) from None


@router.post("/background/quit")
async def background_quit():
    """Stop every bot and close the app, window or not. Only the desktop app can be quit this way."""
    if not background.in_desktop_app():
        raise HTTPException(400, "Only the desktop app can be quit from here.")
    import os

    runner.stop_scheduler()
    await br.close_all()
    asyncio.get_running_loop().call_later(0.4, os._exit, 0)
    return {"ok": True}


# ---- first run, cards, recipes ----
@router.get("/first-run")
def first_run():
    return firstrun.status()


@router.post("/first-run/start")
async def first_run_start():  # async: the turn is started on the server's event loop
    return firstrun.start()


@router.post("/first-run/seen")
def first_run_seen():
    return firstrun.seen()


class CardBody(BaseModel):
    png: str
    name: str = ""


@router.post("/cards")
def card_save(body: CardBody):
    try:
        p = share.save_card(body.png, body.name)
    except bots.BotError as e:
        raise _fail(e) from None
    return {"path": str(p), "folder": str(p.parent)}


class PathBody(BaseModel):
    path: str


@router.post("/reveal")
def reveal(body: PathBody):
    try:
        share.reveal(body.path)
    except bots.BotError as e:
        raise _fail(e) from None
    return {"ok": True}


class UrlBody(BaseModel):
    url: str


@router.post("/open")
def open_link(body: UrlBody):
    try:
        share.open_url(body.url)
    except bots.BotError as e:
        raise _fail(e) from None
    return {"ok": True}


class RecipeBody(BaseModel):
    text: str


@router.post("/recipes/preview")
def recipe_preview(body: RecipeBody):
    try:
        return {"recipe": share.parse(body.text)}
    except bots.BotError as e:
        raise _fail(e) from None


@router.post("/recipes/import")
def recipe_import(body: RecipeBody):
    try:
        bot = share.import_recipe(body.text)
    except bots.BotError as e:
        raise _fail(e) from None
    runner.publish({"type": "bots"})
    return _view(bot)


# ---- one bot ----
def _bot(bid: str) -> bots.Bot:
    try:
        return bots.get(bid)
    except bots.BotError:
        raise HTTPException(404, "Unknown bot.") from None


@router.get("/{bid}")
def get_bot(bid: str):
    return _view(_bot(bid))


@router.patch("/{bid}")
def patch_bot(bid: str, body: BotPatch):
    _bot(bid)
    try:
        bot = bots.update(bid, body.model_dump(exclude_none=True))
    except bots.BotError as e:
        raise _fail(e) from None
    runner.publish({"type": "bots"})
    return _view(bot)


@router.delete("/{bid}")
async def delete_bot(bid: str):
    _bot(bid)
    await runner.stop(bid)
    try:
        await br.for_root(bots.files_dir(bid)).stop()
    except Exception:  # noqa: BLE001
        pass
    bots.delete(bid)
    runner.publish({"type": "bots"})
    return {"ok": True}


@router.get("/{bid}/conversation")
def conversation(bid: str):
    _bot(bid)
    return {"messages": bots.conversation(bid), "state": runner.state(bid), "busy": runner.busy(bid)}


class MessageBody(BaseModel):
    text: str


@router.post("/{bid}/message")
async def message(bid: str, body: MessageBody):
    bot = _bot(bid)
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Write a message first.")
    if bot.paused:
        raise HTTPException(400, f"{bot.name} is paused. Resume it first.")
    if runner.busy(bid):
        raise HTTPException(409, f"{bot.name} is still working. Wait, or stop it first.")
    runner.start_turn(bid, text[:20000], "chat")
    return {"ok": True}


@router.post("/{bid}/stop")
async def stop(bid: str):
    _bot(bid)
    return {"stopped": await runner.stop(bid)}


@router.post("/{bid}/new-conversation")
async def new_conversation(bid: str):
    _bot(bid)
    await runner.stop(bid)
    bot = bots.new_conversation(bid)
    runner.publish({"type": "bots"})
    return _view(bot)


class MemoryBody(BaseModel):
    text: str


@router.get("/{bid}/memory")
def memory_get(bid: str):
    _bot(bid)
    root = bots.files_dir(bid)
    return {"text": memory.read(root, "project"), "path": str(memory.path(root, "project"))}


@router.put("/{bid}/memory")
def memory_put(bid: str, body: MemoryBody):
    _bot(bid)
    if memory.SECRET.search(body.text):
        raise HTTPException(400, "That looks like it holds a secret (a key, token or password). Remove it first.")
    memory.write(bots.files_dir(bid), "project", body.text[:40000])
    return {"ok": True}


class RoutineBody(BaseModel):
    id: str | None = None
    title: str = ""
    prompt: str = ""
    kind: str = "daily"
    time: str = "09:00"
    minutes: int = 60
    days: list[int] = []
    enabled: bool = True


@router.get("/{bid}/routines")
def routines_list(bid: str):
    _bot(bid)
    return {"routines": routines.load(bid)}


@router.post("/{bid}/routines")
def routines_save(bid: str, body: RoutineBody):
    _bot(bid)
    try:
        return routines.upsert(bid, body.model_dump())
    except bots.BotError as e:
        raise _fail(e) from None


@router.delete("/{bid}/routines/{rid}")
def routines_delete(bid: str, rid: str):
    _bot(bid)
    return {"ok": routines.remove(bid, rid)}


@router.post("/{bid}/routines/{rid}/run")
async def routines_run(bid: str, rid: str):
    bot = _bot(bid)
    try:
        r = routines.get(bid, rid)
    except bots.BotError as e:
        raise _fail(e) from None
    if runner.busy(bid):
        raise HTTPException(409, f"{bot.name} is still working. Wait, or stop it first.")
    runner.start_turn(bid, r["prompt"], "routine", r)
    return {"ok": True}


@router.get("/{bid}/files")
def files(bid: str):
    _bot(bid)
    root = bots.files_dir(bid)
    out = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if rel.parts and rel.parts[0] == ".mtrini" or not p.is_file():
            continue
        st = p.stat()
        out.append({"path": rel.as_posix(), "size": st.st_size, "modified": st.st_mtime})
        if len(out) >= 300:
            break
    return {"files": out, "folder": str(root)}


@router.get("/{bid}/file")
def file(bid: str, path: str):
    _bot(bid)
    root = bots.files_dir(bid).resolve()
    p = (root / path).resolve()
    if root not in p.parents or not p.is_file() or ".mtrini" in p.relative_to(root).parts:
        raise HTTPException(404, "No such file.")
    data = p.read_bytes()[:200_000]
    try:
        return {"path": path, "text": data.decode("utf-8")}
    except UnicodeDecodeError:
        return {"path": path, "text": "", "binary": True}


@router.get("/{bid}/browser")
def browser_status(bid: str):
    _bot(bid)
    return br.status(bots.files_dir(bid))


@router.post("/{bid}/browser/show")
async def browser_show(bid: str):
    _bot(bid)
    try:
        await br.for_root(bots.files_dir(bid)).show()
    except br.BrowserError as e:
        raise _fail(e) from None
    return br.status(bots.files_dir(bid))


@router.post("/{bid}/browser/hide")
async def browser_hide(bid: str):
    _bot(bid)
    b = br.for_root(bots.files_dir(bid))
    try:
        await b.stop()  # the sign-ins are in the profile; the hidden browser starts again when the bot needs it
    except Exception:  # noqa: BLE001
        pass
    return br.status(bots.files_dir(bid))


@router.get("/{bid}/recipe")
def recipe(bid: str):
    _bot(bid)
    r = share.recipe(bid)
    return {"recipe": r, "link": share.link(r)}


@router.post("/{bid}/recipe/save")
def recipe_save(bid: str):
    _bot(bid)
    p = share.save_recipe(bid)
    return {"path": str(p), "folder": str(p.parent)}
