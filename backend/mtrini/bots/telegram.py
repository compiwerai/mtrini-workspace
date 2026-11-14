"""Talk to your bots from Telegram.

You create a Telegram bot with @BotFather and paste its token in Mtrini Bots (the token is kept in the
system keychain, never in a file the agent can read). You then send the pairing code shown in the app to
that Telegram bot: only the chat that sent the right code is ever answered.

From Telegram you can:
- write a message: it goes to your default bot, or to another one with "@name message";
- get briefings and results as they land in the inbox;
- answer approvals with the Approve / Deny buttons.
"""
from __future__ import annotations

import asyncio
import re
import secrets
from typing import Any

import httpx

from .. import bots
from ..config import delete_secret, get_secret, set_secret, user_dir
from . import _read, _write, runner

API = "https://api.telegram.org"
SERVICE, ACCOUNT = "mtrini-bots", "telegram"
LIMIT = 3900  # Telegram cuts messages at 4096 characters

_TASK: asyncio.Task | None = None
_STATUS: dict[str, Any] = {"running": False, "error": "", "username": ""}


def _cfg_path():
    return bots.home() / "telegram.json"


def config() -> dict[str, Any]:
    c = _read(_cfg_path(), {})
    return c if isinstance(c, dict) else {}


def _save(c: dict[str, Any]) -> None:
    _write(_cfg_path(), c)


def token() -> str:
    return get_secret(user_dir(), SERVICE, ACCOUNT) or ""


def status() -> dict[str, Any]:
    c = config()
    return {"connected": bool(token()), "paired": bool(c.get("chat")), "pairCode": c.get("code", ""),
            "defaultBot": c.get("defaultBot", ""), "username": _STATUS.get("username", ""),
            "running": bool(_STATUS.get("running")), "error": _STATUS.get("error", "")}


async def _call(method: str, payload: dict[str, Any] | None = None, timeout: float = 35) -> Any:
    tok = token()
    if not tok:
        raise bots.BotError("Telegram is not connected.")
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(f"{API}/bot{tok}/{method}", json=payload or {})
    try:
        data = r.json()
    except ValueError:
        raise bots.BotError(f"Telegram answered with an error ({r.status_code}).") from None
    if not data.get("ok"):
        raise bots.BotError(f"Telegram: {data.get('description', 'request failed')}")
    return data.get("result")


async def connect(tok: str) -> dict[str, Any]:
    """Check the token with Telegram, keep it in the keychain, and make a pairing code."""
    tok = tok.strip()
    if not re.match(r"^\d{5,}:[A-Za-z0-9_-]{20,}$", tok):
        raise bots.BotError("That does not look like a Telegram bot token. Copy it from @BotFather.")
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{API}/bot{tok}/getMe")
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if not data.get("ok"):
        raise bots.BotError("Telegram refused that token. Check it with @BotFather.")
    set_secret(user_dir(), SERVICE, ACCOUNT, tok)
    c = config()
    c.update({"code": f"{secrets.randbelow(900000) + 100000}", "chat": None, "offset": 0})
    _save(c)
    _STATUS.update({"username": data["result"].get("username", ""), "error": ""})
    start()
    return status()


def disconnect() -> dict[str, Any]:
    stop()
    delete_secret(user_dir(), SERVICE, ACCOUNT)
    _save({})
    _STATUS.update({"username": "", "error": "", "running": False})
    return status()


def set_default(bid: str) -> dict[str, Any]:
    bots.get(bid)
    c = config()
    c["defaultBot"] = bid
    _save(c)
    return status()


async def send(text: str, buttons: list[list[dict[str, str]]] | None = None) -> None:
    chat = config().get("chat")
    if not chat or not token():
        return
    chunks = [text[i:i + LIMIT] for i in range(0, len(text), LIMIT)] or [""]
    for n, chunk in enumerate(chunks):
        payload: dict[str, Any] = {"chat_id": chat, "text": chunk, "disable_web_page_preview": True}
        if buttons and n == len(chunks) - 1:
            payload["reply_markup"] = {"inline_keyboard": buttons}
        try:
            await _call("sendMessage", payload)
        except (bots.BotError, httpx.HTTPError):
            return


def _pick_bot(text: str) -> tuple[bots.Bot | None, str]:
    """'@scout what's new' goes to Scout; anything else goes to the default bot."""
    all_bots = [b for b in bots.list_bots() if not b.paused]
    if not all_bots:
        return None, text
    m = re.match(r"^@(\S+)\s+(.*)$", text, re.S)
    if m:
        want = m.group(1).lower()
        for b in all_bots:
            if b.name.lower() == want or b.id == want:
                return b, m.group(2).strip()
    default = config().get("defaultBot")
    for b in all_bots:
        if b.id == default:
            return b, text
    return all_bots[0], text


async def handle(update: dict[str, Any]) -> None:
    """One Telegram update: a pairing attempt, a message for a bot, or an approval button."""
    c = config()
    cb = update.get("callback_query")
    if cb:
        chat = (cb.get("message") or {}).get("chat", {}).get("id")
        if not c.get("chat") or chat != c["chat"]:
            return
        m = re.match(r"^(allow|deny):([a-z0-9-]+):([a-f0-9]+)$", str(cb.get("data", "")))
        try:
            await _call("answerCallbackQuery", {"callback_query_id": cb.get("id")})
        except (bots.BotError, httpx.HTTPError):
            pass
        if m:
            try:
                await runner.resolve(m.group(2), m.group(3), m.group(1))
                await send("Approved. Carrying on." if m.group(1) == "allow" else "Denied.")
            except bots.BotError as e:
                await send(str(e))
        return
    msg = update.get("message") or {}
    chat = (msg.get("chat") or {}).get("id")
    text = str(msg.get("text") or "").strip()
    if not chat or not text:
        return
    if not c.get("chat"):
        code = text.replace("/start", "").strip()
        if c.get("code") and secrets.compare_digest(code, str(c["code"])):
            c.update({"chat": chat, "code": ""})
            _save(c)
            await send("Paired. Write to me and your default bot answers. Use @name to reach another bot.")
        return  # an unknown chat gets no answer at all
    if chat != c["chat"]:
        return
    if text in ("/start", "/help"):
        names = ", ".join("@" + b.name for b in bots.list_bots()) or "none yet"
        await send(f"Your bots: {names}. Write a message, or start it with @name.")
        return
    bot, body = _pick_bot(text)
    if not bot:
        await send("You have no bots yet. Create one in Mtrini Bots.")
        return
    if not body:
        return
    runner.start_turn(bot.id, body, "telegram")


async def on_event(ev: dict[str, Any]) -> None:
    """Forward what matters to Telegram: replies to Telegram messages, inbox items, approvals."""
    if not config().get("chat"):
        return
    t = ev.get("type")
    if t == "message" and ev.get("source") == "telegram" and (ev.get("message") or {}).get("role") == "assistant":
        try:
            name = bots.get(ev["bot"]).name
        except bots.BotError:
            name = "Bot"
        await send(f"{name}: {ev['message'].get('content', '')}")
    elif t == "inbox":
        it = ev.get("item") or {}
        name = ev.get("botName", "Bot")
        if it.get("kind") == "approval" and it.get("state") == "pending":
            await send(f"{it.get('title', '')}\n\n{it.get('body', '')}",
                       [[{"text": "Approve", "callback_data": f"allow:{it['bot']}:{it['id']}"},
                         {"text": "Deny", "callback_data": f"deny:{it['bot']}:{it['id']}"}]])
        elif it.get("kind") in ("briefing", "error") and not it.get("quiet") and it.get("source") != "telegram":
            await send(f"{name} · {it.get('title', '')}\n\n{it.get('body', '')}")


async def _poll() -> None:
    _STATUS.update({"running": True, "error": ""})
    backoff = 2
    try:
        while True:
            c = config()
            try:
                updates = await _call("getUpdates", {"offset": c.get("offset", 0), "timeout": 25,
                                                     "allowed_updates": ["message", "callback_query"]}, timeout=40)
                backoff = 2
                _STATUS["error"] = ""
            except bots.BotError as e:
                _STATUS["error"] = str(e)
                if "not connected" in str(e):
                    return
                await asyncio.sleep(min(backoff, 60))
                backoff *= 2
                continue
            except httpx.HTTPError:
                _STATUS["error"] = "Can't reach Telegram. Check the internet connection."
                await asyncio.sleep(min(backoff, 60))
                backoff *= 2
                continue
            for u in updates or []:
                c = config()
                c["offset"] = int(u.get("update_id", 0)) + 1
                _save(c)
                try:
                    await handle(u)
                except Exception:  # noqa: BLE001  (one bad update must not stop the channel)
                    pass
    finally:
        _STATUS["running"] = False


def start() -> None:
    global _TASK
    if on_event not in runner.LISTENERS:
        runner.LISTENERS.append(on_event)
    if not token():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _TASK is None or _TASK.done():
        _TASK = loop.create_task(_poll())


def stop() -> None:
    global _TASK
    if _TASK is not None:
        _TASK.cancel()
        _TASK = None
    _STATUS["running"] = False
