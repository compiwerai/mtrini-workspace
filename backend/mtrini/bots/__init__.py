"""Mtrini Bots: named assistants with a role, a folder and a memory of their own.

Everything a bot owns is a plain file under `~/.mtrini/bots/<id>/`:

    bot.json            name, role, instructions, model
    files/              the bot's own folder (its workspace: notes, drafts, results)
    files/.mtrini/      its memory (memory.md), sessions, browser profile
    conversation.jsonl  what you and the bot said, as the app shows it
    inbox.json          what the bot sent you: briefings, results, approvals
    routines.json       work it does on a schedule
"""
from __future__ import annotations

import json
import re
import shutil
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..config import user_dir

__version__ = "0.1.0"  # Mtrini Bots is its own app, with its own version

COLORS = ["#5ad1e6", "#f0892b", "#26b97a", "#8a5cf5", "#e5505b", "#e2b93b", "#4f8df7", "#d86ad0"]
_LOCK = threading.RLock()
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
MAX_CONVERSATION = 400
MAX_INBOX = 300

MASCOTS = ["camel", "fennec", "owl", "stork", "cat", "tortoise", "parrot", "beetle", "bee", "gecko"]

TEMPLATES: list[dict[str, Any]] = [
    {"key": "chief", "name": "Atlas", "role": "Chief of staff", "mascot": "camel",
     "instructions": "Keep me on top of my day. Collect what my other bots reported, my notes in your folder, and "
                     "what I told you matters. Be short: what needs me, what is done, what is next.",
     "routines": [{"title": "Morning briefing", "kind": "daily", "time": "08:30",
                   "prompt": "Write my morning briefing: what needs my attention today, what you or the other bots "
                             "finished since yesterday, and my three priorities. Read your notes first. If you have "
                             "nothing new, say so in one line."}]},
    {"key": "research", "name": "Scout", "role": "Researcher", "mascot": "fennec",
     "instructions": "Research topics on the web for me. Give sources as links. Separate what you verified from what "
                     "you could not. Keep a file per topic in your folder so you know what you already told me.",
     "routines": [{"title": "What's new", "kind": "daily", "time": "09:00",
                   "prompt": "Search the web for news on the topics in topics.md in your folder. Report only what is "
                             "new since your last report (keep seen.md up to date), with links. If topics.md is "
                             "missing, ask me which topics to follow."}]},
    {"key": "watch", "name": "Sentinel", "role": "Web watcher", "mascot": "owl",
     "instructions": "Watch web pages for changes that matter to me (availability, new posts, deadlines). "
                     "Keep the last state of each page in your folder and tell me only when something changed.",
     "routines": [{"title": "Check my pages", "kind": "interval", "minutes": 180,
                   "prompt": "Check every page listed in watch.md in your folder. Compare with the last state you "
                             "saved. Report only real changes, with the link. If nothing changed, reply 'No changes.'"}]},
    {"key": "writer", "name": "Quill", "role": "Writer", "mascot": "stork",
     "instructions": "Draft posts, emails and documents in my voice. Save every draft as a file in your folder. "
                     "Never send or publish anything yourself: hand me the draft.",
     "routines": []},
    {"key": "news", "name": "Herald", "role": "News digest", "mascot": "parrot",
     "instructions": "Read the sites I follow so I don't have to. One digest a day, eight items at most, each with a "
                     "one-line reason it matters to me and a link. No filler.",
     "routines": [{"title": "Daily digest", "kind": "daily", "time": "07:30",
                   "prompt": "Open each site listed in sources.md in your folder and pick what is new since your last "
                             "digest (keep seen.md). Write at most eight items, most important first, each with a "
                             "link. If sources.md is missing, ask me which sites to follow."}]},
    {"key": "deals", "name": "Bazaar", "role": "Price watcher", "mascot": "cat",
     "instructions": "Watch prices for things I want to buy. Keep a price history per product in your folder. Tell me "
                     "only when a price drops or reaches my target. Never buy anything.",
     "routines": [{"title": "Check prices", "kind": "interval", "minutes": 360,
                   "prompt": "For each product in wishlist.md (a link and my target price), read the current price and "
                             "add it to prices.md. Report only drops and targets reached, with the link. If nothing "
                             "moved, reply 'No changes.'"}]},
    {"key": "study", "name": "Sage", "role": "Study coach", "mascot": "tortoise",
     "instructions": "Help me learn what is in the notes I put in your folder. Quiz me, track what I get wrong in "
                     "progress.md, and come back to the weak spots. Explain simply and briefly.",
     "routines": [{"title": "Evening quiz", "kind": "daily", "time": "18:00",
                   "prompt": "Write five questions from the notes in your folder, weighted to what progress.md says I "
                             "get wrong. Put the answers at the end. If there are no notes yet, ask me to add some."}]},
    {"key": "jobs", "name": "Compass", "role": "Job scout", "mascot": "gecko",
     "instructions": "Find openings that fit profile.md in your folder. For each, say why it fits and what is missing. "
                     "Draft applications only when I ask, as files. Never apply or send anything yourself.",
     "routines": [{"title": "New openings", "kind": "daily", "time": "10:00",
                   "prompt": "Check the job boards listed in boards.md for roles that fit profile.md. Report only "
                             "openings you have not reported before (keep seen.md), with links. If either file is "
                             "missing, ask me for it."}]},
    {"key": "social", "name": "Echo", "role": "Social drafts", "mascot": "bee",
     "instructions": "Turn my notes and ideas into post drafts in my voice. Save them under drafts/ in your folder. "
                     "Never post, reply or publish anywhere: I do that myself.",
     "routines": [{"title": "Posts for the week", "kind": "weekly", "time": "09:00", "days": [0],
                   "prompt": "Draft five posts for this week from ideas.md in your folder and save them in drafts/ "
                             "with today's date. List their first lines in your report. If ideas.md is missing, ask "
                             "me what I want to talk about."}]},
    {"key": "repo", "name": "Patch", "role": "Repo watcher", "mascot": "beetle",
     "instructions": "Watch the code repositories I care about. Tell me about new issues, pull requests and releases "
                     "that need me, in one line each with a link. Skip noise.",
     "routines": [{"title": "Repo check", "kind": "interval", "minutes": 180,
                   "prompt": "Open each repository listed in repos.md in your folder and report new issues, pull "
                             "requests and releases since your last check (keep seen.md). If nothing is new, reply "
                             "'No changes.'"}]},
    {"key": "blank", "name": "", "role": "", "mascot": "", "instructions": "", "routines": []},
]


class BotError(Exception):
    pass


@dataclass
class Bot:
    id: str
    name: str
    role: str = ""
    instructions: str = ""
    provider: str = "free"
    model: str = ""
    effort: str = "off"
    color: str = COLORS[0]
    mascot: str = ""
    created: float = 0.0
    paused: bool = False
    session: int = 1  # bumped by "New conversation": the model starts fresh, the memory stays

    def public(self) -> dict[str, Any]:
        return asdict(self)


def home() -> Path:
    d = user_dir() / "bots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def bot_dir(bid: str) -> Path:
    if not _ID.match(bid or ""):
        raise BotError("Unknown bot.")
    return home() / bid


def files_dir(bid: str) -> Path:
    d = bot_dir(bid) / "files"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read(p: Path, default: Any) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(p: Path, data: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


# ---- bots ----
def _load(d: Path) -> Bot | None:
    data = _read(d / "bot.json", None)
    if not isinstance(data, dict) or not data.get("name"):
        return None
    known = {k: data[k] for k in Bot.__dataclass_fields__ if k in data}
    known["id"] = d.name
    bot = Bot(**known)
    if bot.mascot not in MASCOTS:  # bots made before mascots get one from their name, always the same
        bot.mascot = default_mascot(bot.name)
    return bot


def _free(options: list[str], taken: list[str], n: int) -> str:
    """The first option nobody has yet, so a crew is easy to tell apart; when all are taken, go round again."""
    return next((o for o in options if o not in taken), options[n % len(options)])


def default_mascot(name: str) -> str:
    return MASCOTS[sum(ord(c) for c in name.lower()) % len(MASCOTS)]


def list_bots() -> list[Bot]:
    with _LOCK:
        bots = [b for b in (_load(d) for d in home().iterdir() if d.is_dir()) if b]
    return sorted(bots, key=lambda b: b.created)


def get(bid: str) -> Bot:
    b = _load(bot_dir(bid))
    if not b:
        raise BotError("Unknown bot.")
    return b


def _slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:24] or "bot"
    if len(base) < 2:
        base += "-bot"
    return base


def save(bot: Bot) -> Bot:
    with _LOCK:
        _write(bot_dir(bot.id) / "bot.json", {k: v for k, v in asdict(bot).items() if k != "id"})
    return bot


def create(name: str, role: str = "", instructions: str = "", provider: str = "free", model: str = "",
           effort: str = "off", color: str = "", mascot: str = "") -> Bot:
    name = " ".join(str(name).split())[:40]
    if not name:
        raise BotError("Give the bot a name.")
    with _LOCK:
        existing = list_bots()
        if any(b.name.lower() == name.lower() for b in existing):
            raise BotError(f"You already have a bot called {name}.")
        bid, n = _slug(name), 1
        while (home() / bid).exists():
            n += 1
            bid = f"{_slug(name)}-{n}"
        bot = Bot(id=bid, name=name, role=" ".join(str(role).split())[:80], instructions=str(instructions).strip()[:4000],
                  provider=provider or "free", model=model or "", effort=effort or "off",
                  color=color if color in COLORS else _free(COLORS, [b.color for b in existing], len(existing)),
                  mascot=mascot if mascot in MASCOTS else default_mascot(name), created=time.time())
        files_dir(bid)
        return save(bot)


def update(bid: str, patch: dict[str, Any]) -> Bot:
    with _LOCK:
        bot = get(bid)
        if patch.get("mascot") is not None and patch["mascot"] not in MASCOTS:
            raise BotError("Unknown mascot.")
        for key in ("role", "instructions", "provider", "model", "effort", "color", "paused", "mascot"):
            if key in patch and patch[key] is not None:
                setattr(bot, key, patch[key])
        if patch.get("name"):
            name = " ".join(str(patch["name"]).split())[:40]
            if any(b.id != bid and b.name.lower() == name.lower() for b in list_bots()):
                raise BotError(f"You already have a bot called {name}.")
            bot.name = name
        bot.role = " ".join(str(bot.role).split())[:80]
        bot.instructions = str(bot.instructions).strip()[:4000]
        bot.paused = bool(bot.paused)
        return save(bot)


def delete(bid: str) -> None:
    """Remove a bot and everything it owns: its folder, memory, conversation and inbox."""
    d = bot_dir(bid)
    with _LOCK:
        if d.exists() and d.parent == home():
            shutil.rmtree(d, ignore_errors=True)


STARTERS = ["chief", "research", "watch", "writer", "news"]


def seed_starters() -> list[Bot]:
    """First run: a small crew is already there, so the app never opens empty.

    Their routines start switched off: a bot should not spend your model allowance before you have told it
    what to follow. This runs once (a marker file remembers), so a starter you delete stays deleted, and a
    bot you already made with the same name is left alone.
    """
    from . import firstrun, routines

    marker = home() / "starters.json"
    if marker.exists():
        return []
    made: list[Bot] = []
    with _LOCK:
        have = {b.name.lower() for b in list_bots()}
        for key in STARTERS:
            t = next(x for x in TEMPLATES if x["key"] == key)
            if t["name"].lower() in have:
                continue
            taken = [b.mascot for b in list_bots()]
            mascot = t["mascot"] if t["mascot"] not in taken else _free(MASCOTS, taken, len(taken))
            bot = create(t["name"], t["role"], t["instructions"], mascot=mascot)
            for r in t["routines"]:
                routines.upsert(bot.id, {**r, "enabled": False})
            made.append(bot)
            if key == firstrun.TEMPLATE:
                firstrun.arm(bot.id)  # the first window runs this one, so a new user sees a result in seconds
        _write(marker, {"seeded": [b.id for b in made], "at": time.time()})
    return made


def new_conversation(bid: str) -> Bot:
    with _LOCK:
        bot = get(bid)
        bot.session += 1
        try:
            (bot_dir(bid) / "conversation.jsonl").unlink()
        except OSError:
            pass
        return save(bot)


def session_id(bot: Bot) -> str:
    return f"bot-{bot.id}-{bot.session}"


# ---- conversation ----
def say(bid: str, role: str, content: str, **extra: Any) -> dict[str, Any]:
    msg = {"id": uuid.uuid4().hex[:10], "role": role, "content": content, "ts": time.time(), **extra}
    p = bot_dir(bid) / "conversation.jsonl"
    with _LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
    return msg


def conversation(bid: str, limit: int = MAX_CONVERSATION) -> list[dict[str, Any]]:
    p = bot_dir(bid) / "conversation.jsonl"
    out: list[dict[str, Any]] = []
    with _LOCK:
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
    for ln in lines[-limit:]:
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


# ---- inbox ----
def _inbox_path(bid: str) -> Path:
    return bot_dir(bid) / "inbox.json"


def post(bid: str, kind: str, title: str, body: str, **extra: Any) -> dict[str, Any]:
    """Put something in the user's inbox. kind: briefing | result | message | approval | error."""
    item = {"id": uuid.uuid4().hex[:10], "bot": bid, "kind": kind, "title": title[:140], "body": body[:20000],
            "ts": time.time(), "read": False, **extra}
    with _LOCK:
        items = _read(_inbox_path(bid), [])
        items.append(item)
        _write(_inbox_path(bid), items[-MAX_INBOX:])
    return item


def inbox(bid: str | None = None) -> list[dict[str, Any]]:
    with _LOCK:
        ids = [bid] if bid else [b.id for b in list_bots()]
        items: list[dict[str, Any]] = []
        for i in ids:
            items += _read(_inbox_path(i), [])
    return sorted(items, key=lambda x: x.get("ts", 0), reverse=True)


def item(bid: str, iid: str) -> dict[str, Any]:
    for it in _read(_inbox_path(bid), []):
        if it.get("id") == iid:
            return it
    raise BotError("That inbox item is gone.")


def update_item(bid: str, iid: str, patch: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        items = _read(_inbox_path(bid), [])
        for it in items:
            if it.get("id") == iid:
                it.update(patch)
                _write(_inbox_path(bid), items)
                return it
    raise BotError("That inbox item is gone.")


def clear_inbox(bid: str | None = None) -> int:
    """Remove everything that is read and not waiting for an answer."""
    removed = 0
    with _LOCK:
        for i in ([bid] if bid else [b.id for b in list_bots()]):
            items = _read(_inbox_path(i), [])
            keep = [it for it in items if not it.get("read") or (it.get("kind") == "approval" and it.get("state") == "pending")]
            removed += len(items) - len(keep)
            _write(_inbox_path(i), keep)
    return removed


def unread() -> int:
    return sum(1 for it in inbox() if not it.get("read"))
