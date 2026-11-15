"""Runs a bot's turns on the server, so a bot keeps working when no window is watching.

A turn starts from a chat message, a routine or Telegram. The same engine as Mtrini Workspace runs it, in
the bot's own folder, in "bot" permission mode: reading, its own files and browsing are allowed; running
commands and anything that acts for the user (browser_act) stop the turn and put an approval in the inbox.
Answering the approval resumes the same turn.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import time
from collections.abc import Awaitable, Callable
from typing import Any

from .. import bots
from ..config import provider_settings
from . import routines

ONE_AT_A_TIME = {"free", "compiwer-free"}  # the free models answer one request at a time per install
RETRIES, RETRY_WAIT, MAX_WAIT = 3, 20, 15 * 60
QUIET = ("no changes", "nothing new", "nothing to report", "no news", "rien de nouveau")
TICK = 20  # seconds between scheduler checks

_STATE: dict[str, dict[str, Any]] = {}
_LOCKS: dict[str, asyncio.Lock] = {}
_TASKS: dict[str, asyncio.Task] = {}
_GATES: dict[tuple[str, int], asyncio.Semaphore] = {}
_SUBS: set[asyncio.Queue] = set()
LISTENERS: list[Callable[[dict[str, Any]], Awaitable[None]]] = []  # channels (Telegram) hear every event
_SCHEDULER: asyncio.Task | None = None

PERSONA = """You are {name}, a personal assistant bot in Mtrini Bots (by Compiwer AI).{role}
{instructions}
How you work:
1. You have a folder of your own (the workspace root). Keep notes, drafts, lists and results there as plain
   files, and read them before you answer: they are how you know what you did before.
2. You have a memory. When the user tells you a lasting fact or preference, save it with remember.
3. Look things up with web_search and web_fetch. For pages that need clicking, use your own browser
   (browser_open, browser_read, browser_click, browser_type). You never type passwords: if a site needs a
   sign-in, tell the user to press "Show browser" in the app and sign in there once.
4. Anything that sends, posts, buys, deletes or changes something outside your folder needs the user's
   approval. Use browser_act for those and say in one line what it will do. Never move money, trade, or
   enter card numbers or ID numbers.
5. Lead with the result. Be brief and concrete. Give links for facts from the web.
6. Say plainly when something failed or when you could not check it. Never invent a result.
7. When a routine runs, your reply goes to the user's inbox: write a short report they can read in a
   minute. If nothing changed, reply with one line such as "No changes."
8. Never reveal secrets, tokens or API keys.
"""


def persona(bot: bots.Bot) -> str:
    role = f" Your role: {bot.role}." if bot.role else ""
    instr = f"\nWhat the user asked of you:\n{bot.instructions}\n" if bot.instructions else ""
    return PERSONA.format(name=bot.name, role=role, instructions=instr)


def _now_note(source: str, routine: dict | None) -> str:
    now = dt.datetime.now()
    where = {"chat": "the user, in the app", "telegram": "the user, on Telegram"}.get(source, source)
    if routine:
        where = f"your routine \"{routine.get('title', '')}\" (nobody is watching: report to the inbox)"
    return f"Now: {now.strftime('%A %d %B %Y, %H:%M')} (local time). This message is from {where}."


# ---- live state and events ----
def state(bid: str) -> dict[str, Any]:
    return _STATE.get(bid) or {"status": "idle", "label": "", "since": 0}


def _set(bid: str, status: str, label: str = "") -> None:
    _STATE[bid] = {"status": status, "label": label[:140], "since": time.time()}
    publish({"type": "state", "bot": bid, **_STATE[bid]})


def publish(ev: dict[str, Any]) -> None:
    for q in list(_SUBS):
        try:
            q.put_nowait(ev)
        except asyncio.QueueFull:
            pass
    for fn in LISTENERS:
        try:
            asyncio.get_running_loop().create_task(fn(ev))
        except RuntimeError:
            pass  # no loop: a test called this outside one


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=500)
    _SUBS.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _SUBS.discard(q)


def _gate(provider: str) -> asyncio.Semaphore:
    """Bots take turns: one at a time on the free model, two at a time otherwise."""
    key = (provider if provider in ONE_AT_A_TIME else "*", id(asyncio.get_running_loop()))
    if key not in _GATES:
        _GATES[key] = asyncio.Semaphore(1 if provider in ONE_AT_A_TIME else 2)
    return _GATES[key]


def _lock(bid: str) -> asyncio.Lock:
    key = f"{bid}:{id(asyncio.get_running_loop())}"
    if key not in _LOCKS:
        _LOCKS[key] = asyncio.Lock()
    return _LOCKS[key]


# ---- what a step looks like to a person ----
def step_label(tool: str, args: dict[str, Any]) -> str:
    a = args or {}
    short = lambda v, n=70: str(v or "").replace("\n", " ")[:n]  # noqa: E731
    table = {
        "web_search": lambda: f"Searched the web: {short(a.get('query'))}",
        "web_fetch": lambda: f"Read {short(a.get('url'))}",
        "browser_open": lambda: f"Opened {short(a.get('url'))}",
        "browser_read": lambda: "Read the page again",
        "browser_click": lambda: f"Clicked element {a.get('element')}",
        "browser_type": lambda: f"Typed \"{short(a.get('text'), 40)}\"",
        "browser_act": lambda: f"Acted in the browser: {short(a.get('what'))}",
        "browser_screenshot": lambda: "Took a screenshot",
        "read_file": lambda: f"Read {short(a.get('path'))}",
        "write_file": lambda: f"Wrote {short(a.get('path'))}",
        "edit_file": lambda: f"Edited {short(a.get('path'))}",
        "delete_file": lambda: f"Deleted {short(a.get('path'))}",
        "list_directory": lambda: "Looked in its folder",
        "execute_command": lambda: f"Ran: {short(a.get('command'))}",
        "run_python": lambda: "Ran Python code",
        "remember": lambda: f"Remembered: {short(a.get('fact'))}",
    }
    return table.get(tool, lambda: tool.replace("_", " ").capitalize())()


def approval_title(bot: bots.Bot, tool: str, args: dict[str, Any]) -> str:
    a = args or {}
    if tool == "browser_act":
        return f"{bot.name} wants to: {str(a.get('what') or 'act in the browser')[:110]}"
    if tool == "execute_command":
        return f"{bot.name} wants to run a command"
    if tool == "delete_file":
        return f"{bot.name} wants to delete {str(a.get('path', 'a file'))[:80]}"
    return f"{bot.name} wants to use {tool.replace('_', ' ')}"


def approval_body(tool: str, args: dict[str, Any]) -> str:
    a = args or {}
    if tool == "browser_act":
        typed = f"\nIt will type: {a.get('text')}" if a.get("text") is not None else ""
        return f"In its browser, on element [{a.get('element')}].{typed}"
    if tool == "execute_command":
        return f"Command:\n{a.get('command', '')}"
    return "\n".join(f"{k}: {str(v)[:400]}" for k, v in a.items())


def _rate_limited(msg: str) -> bool:
    from ..swarm import _rate_limited as check

    return check(msg)


# ---- turns ----
async def _drive(bot: bots.Bot, text: str, source: str, routine: dict | None, resume: dict | None) -> None:
    """Run the engine for one turn (or the rest of one, after an approval) and record what came of it."""
    from ..agent.engine import friendly_error, run_agent
    from ..providers import agent_cli

    root = bots.files_dir(bot.id)
    settings = provider_settings(root, bot.provider)
    is_cli = bot.provider in agent_cli.CLIS
    steps: list[dict[str, Any]] = []
    final, error, pending = "", "", None
    message, tries, waited = text, 0, 0.0
    while True:
        final, error, pending = "", "", None
        before = len(steps)
        try:
            async for ev in run_agent(
                    root, bot.provider, bot.model, message, [], "ask" if is_cli else "bot", settings,
                    effort=bot.effort, thread_id=bots.session_id(bot), resume=resume,
                    system_base="" if is_cli else persona(bot), system_extra=persona(bot) if is_cli else "",
                    context="" if resume else _now_note(source, routine)):
                t = ev.get("type")
                if t == "tool_start":
                    step = {"tool": ev.get("tool", ""), "label": step_label(ev.get("tool", ""), ev.get("args") or {}), "ok": None}
                    steps.append(step)
                    _set(bot.id, "working", step["label"])
                    publish({"type": "step", "bot": bot.id, "step": step})
                elif t == "tool_result":
                    if steps and steps[-1]["ok"] is None:
                        steps[-1]["ok"] = bool(ev.get("ok"))
                elif t == "assistant_delta":
                    publish({"type": "live", "bot": bot.id, "text": str(ev.get("delta", ""))[-2000:]})
                elif t == "status" and ev.get("message"):
                    _set(bot.id, "working", str(ev["message"]))
                elif t == "error":
                    error = str(ev.get("message", "Something went wrong."))[:1500]
                elif t == "done":
                    final = str(ev.get("content") or "")
                    pending = ev.get("pendingApproval") or (ev.get("pendingPlan") and {"tool": "plan", "args": {}})
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001  (a provider or tool blew up: report it, keep the app alive)
            error = friendly_error(e)
        if error and _rate_limited(error):
            # A small API plan allows few requests a minute. Keep going while the bot gets a step done
            # between limits; give up after RETRIES in a row with none, or MAX_WAIT of waiting in total.
            tries = 1 if len(steps) > before else tries + 1
            if tries <= RETRIES and waited < MAX_WAIT:
                wait = min(RETRY_WAIT * tries, 60)
                waited += wait
                _set(bot.id, "working", f"The model is busy; trying again in {wait}s")
                await asyncio.sleep(wait)
                _set(bot.id, "working", "Trying again")
                message, resume = "Continue where you stopped.", None
                continue
        break

    shown = [s for s in steps if s.get("label")][-40:]
    if pending:
        tool, args = str(pending.get("tool", "")), pending.get("args") or {}
        it = bots.post(bot.id, "approval", approval_title(bot, tool, args), approval_body(tool, args), state="pending",
                       request={"tool": tool, "args": args}, source=source, routine=(routine or {}).get("id"))
        msg = bots.say(bot.id, "assistant", "I need your approval before I go on.", steps=shown, approval=it["id"])
        publish({"type": "message", "bot": bot.id, "message": msg})
        publish({"type": "inbox", "item": it, "botName": bot.name})
        _set(bot.id, "waiting", it["title"])
        return
    if error:
        if _rate_limited(error):  # say it in plain words; the provider's own text is a wall of URLs
            error = ("The model's provider keeps limiting requests, so I stopped part way. "
                     + ("What I did so far is in the steps above. " if shown else "")
                     + "Say \"continue\" and I'll carry on, or pick another model in Settings.")
        msg = bots.say(bot.id, "assistant", error, steps=shown, error=True)
        publish({"type": "message", "bot": bot.id, "message": msg, "source": source})
        if routine:
            routines.mark_run(bot.id, routine["id"], "Failed: " + error)
            it = bots.post(bot.id, "error", f"{routine.get('title', 'Routine')} failed", error, routine=routine.get("id"))
            publish({"type": "inbox", "item": it, "botName": bot.name})
        _set(bot.id, "idle")
        return
    final = final.strip() or "Done."
    msg = bots.say(bot.id, "assistant", final, steps=shown, routine=(routine or {}).get("title"))
    publish({"type": "message", "bot": bot.id, "message": msg, "source": source})
    if routine:
        quiet = len(final) < 90 and final.lower().rstrip(".! ").startswith(QUIET)
        routines.mark_run(bot.id, routine["id"], final.splitlines()[0] if final else "")
        it = bots.post(bot.id, "briefing", str(routine.get("title", "Routine")), final, routine=routine.get("id"),
                       read=quiet, quiet=quiet)
        publish({"type": "inbox", "item": it, "botName": bot.name})
    _set(bot.id, "idle")


async def run_turn(bid: str, text: str, source: str = "chat", routine: dict | None = None) -> None:
    bot = bots.get(bid)
    async with _lock(bid):
        _expire_approvals(bid)
        shown = f"Routine: {routine.get('title', '')}" if routine else text
        msg = bots.say(bid, "user", shown, source=source, routine=bool(routine))
        publish({"type": "message", "bot": bid, "message": msg, "source": source})
        _set(bid, "queued", "Waiting for its turn")
        try:
            async with _gate(bot.provider):
                _set(bid, "working", "Thinking")
                await _drive(bot, text, source, routine, None)
        except asyncio.CancelledError:
            m = bots.say(bid, "assistant", "Stopped.", stopped=True)
            publish({"type": "message", "bot": bid, "message": m})
            _set(bid, "idle")
            raise
        finally:
            if state(bid)["status"] in ("working", "queued"):
                _set(bid, "idle")


def _expire_approvals(bid: str) -> None:
    """A new message closes whatever was waiting: the engine drops the paused step, so the card must go too."""
    for it in bots.inbox(bid):
        if it.get("kind") == "approval" and it.get("state") == "pending":
            bots.update_item(bid, it["id"], {"state": "expired", "read": True})


async def resolve(bid: str, iid: str, decision: str) -> dict[str, Any]:
    """Answer an approval: allow | always | deny. The paused turn carries on."""
    if decision not in ("allow", "always", "deny"):
        raise bots.BotError("Answer with allow, always or deny.")
    bot = bots.get(bid)
    it = bots.item(bid, iid)
    if it.get("kind") != "approval" or it.get("state") != "pending":
        raise bots.BotError("This was already answered.")
    it = bots.update_item(bid, iid, {"state": "approved" if decision != "deny" else "denied", "read": True,
                                     "answered": time.time()})
    publish({"type": "inbox", "item": it, "botName": bot.name})
    routine = None
    if it.get("routine"):
        try:
            routine = routines.get(bid, it["routine"])
        except bots.BotError:
            routine = None

    async def go() -> None:
        async with _lock(bid):
            try:
                async with _gate(bot.provider):
                    _set(bid, "working", "Carrying on")
                    await _drive(bot, "", str(it.get("source") or "chat"), routine, {"decision": decision})
            finally:
                if state(bid)["status"] in ("working", "queued"):
                    _set(bid, "idle")

    _spawn(bid, go())
    return it


def _spawn(bid: str, coro: Awaitable[None]) -> asyncio.Task:
    task = asyncio.get_running_loop().create_task(coro)  # type: ignore[arg-type]
    _TASKS[bid] = task

    def done(t: asyncio.Task) -> None:
        if _TASKS.get(bid) is t:
            _TASKS.pop(bid, None)
        if not t.cancelled() and t.exception():
            _set(bid, "idle")

    task.add_done_callback(done)
    return task


def start_turn(bid: str, text: str, source: str = "chat", routine: dict | None = None) -> asyncio.Task:
    return _spawn(bid, run_turn(bid, text, source, routine))


def busy(bid: str) -> bool:
    t = _TASKS.get(bid)
    return bool(t and not t.done())


async def stop(bid: str) -> bool:
    t = _TASKS.get(bid)
    if not t or t.done():
        return False
    t.cancel()
    try:
        await t
    except (asyncio.CancelledError, Exception):  # noqa: BLE001
        pass
    return True


# ---- scheduler ----
async def tick(now: float | None = None) -> int:
    """Start every routine that is due. Returns how many were started."""
    started = 0
    for bid, r in routines.due(now):
        if busy(bid):  # the bot is in the middle of something: this run waits for the lock, in order
            asyncio.get_running_loop().create_task(run_turn(bid, r["prompt"], "routine", r))
        else:
            start_turn(bid, r["prompt"], "routine", r)
        started += 1
    return started


async def _loop() -> None:
    while True:
        try:
            await tick()
        except Exception:  # noqa: BLE001  (never let one bad routine stop the clock)
            pass
        await asyncio.sleep(TICK)


def recover() -> int:
    """After a restart: a message the app closed on gets an honest note instead of silence."""
    fixed = 0
    for bot in bots.list_bots():
        convo = bots.conversation(bot.id, 1)
        if convo and convo[-1].get("role") == "user" and not busy(bot.id):
            what = "that routine" if convo[-1].get("routine") else "that"
            bots.say(bot.id, "assistant", f"The app closed before I finished {what}. Send it again and I'll pick it up.", stopped=True)
            fixed += 1
    return fixed


def start_scheduler() -> None:
    global _SCHEDULER
    if _SCHEDULER is None or _SCHEDULER.done():
        _SCHEDULER = asyncio.get_running_loop().create_task(_loop())


def stop_scheduler() -> None:
    global _SCHEDULER
    if _SCHEDULER is not None:
        _SCHEDULER.cancel()
        _SCHEDULER = None
