"""Routines: work a bot does on a schedule (every N minutes, every day, or on chosen weekdays).

Times are the computer's local time. A routine that was due while the app was closed runs once when
the app starts, then goes back to its schedule.
"""
from __future__ import annotations

import datetime as dt
import re
import time
import uuid
from typing import Any

from . import _LOCK, BotError, _read, _write, bot_dir, list_bots

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
MIN_INTERVAL = 5  # minutes


def _path(bid: str):
    return bot_dir(bid) / "routines.json"


def load(bid: str) -> list[dict[str, Any]]:
    data = _read(_path(bid), [])
    return data if isinstance(data, list) else []


def _hm(value: str) -> tuple[int, int]:
    m = _TIME.match(str(value or "").strip())
    if not m:
        raise BotError("Give the time as HH:MM, for example 08:30.")
    return int(m.group(1)), int(m.group(2))


def next_run(r: dict[str, Any], after: float) -> float:
    """The first time this routine is due strictly after `after`."""
    kind = r.get("kind")
    if kind == "interval":
        return after + max(MIN_INTERVAL, int(r.get("minutes") or 60)) * 60
    h, m = _hm(r.get("time", "09:00"))
    base = dt.datetime.fromtimestamp(after)
    days = sorted(set(int(d) for d in (r.get("days") or []) if 0 <= int(d) <= 6)) if kind == "weekly" else list(range(7))
    if not days:
        days = list(range(7))
    for add in range(0, 8):
        day = (base + dt.timedelta(days=add)).replace(hour=h, minute=m, second=0, microsecond=0)
        if day.weekday() in days and day.timestamp() > after:
            return day.timestamp()
    return after + 86400


def describe(r: dict[str, Any]) -> str:
    kind = r.get("kind")
    if kind == "interval":
        n = max(MIN_INTERVAL, int(r.get("minutes") or 60))
        if n % 60 == 0:
            return "Every hour" if n == 60 else f"Every {n // 60} hours"
        return f"Every {n} minutes"
    t = r.get("time", "09:00")
    if kind == "weekly":
        days = sorted(set(int(d) for d in (r.get("days") or [])))
        if days and len(days) < 7:
            return f"{', '.join(DAYS[d] for d in days)} at {t}"
    return f"Every day at {t}"


def _clean(data: dict[str, Any], old: dict[str, Any] | None = None) -> dict[str, Any]:
    title = " ".join(str(data.get("title", "")).split())[:80]
    prompt = str(data.get("prompt", "")).strip()[:4000]
    if not title:
        raise BotError("Give the routine a name.")
    if len(prompt) < 3:
        raise BotError("Say what the bot should do.")
    kind = data.get("kind") if data.get("kind") in ("interval", "daily", "weekly") else "daily"
    r: dict[str, Any] = {"id": (old or {}).get("id") or uuid.uuid4().hex[:8], "title": title, "prompt": prompt,
                         "kind": kind, "enabled": bool(data.get("enabled", True)),
                         "lastRun": (old or {}).get("lastRun"), "lastResult": (old or {}).get("lastResult", "")}
    if kind == "interval":
        try:
            r["minutes"] = max(MIN_INTERVAL, int(data.get("minutes") or 60))
        except (TypeError, ValueError):
            raise BotError("Give the interval as a number of minutes.") from None
    else:
        h, m = _hm(data.get("time", "09:00"))
        r["time"] = f"{h:02d}:{m:02d}"
        if kind == "weekly":
            try:
                r["days"] = sorted(set(int(d) for d in (data.get("days") or []) if 0 <= int(d) <= 6))
            except (TypeError, ValueError):
                raise BotError("Days must be numbers from 0 (Monday) to 6 (Sunday).") from None
            if not r["days"]:
                raise BotError("Pick at least one day.")
    r["nextRun"] = next_run(r, time.time())
    r["when"] = describe(r)
    return r


def upsert(bid: str, data: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        items = load(bid)
        old = next((x for x in items if x.get("id") == data.get("id")), None)
        r = _clean(data, old)
        if old:
            items[items.index(old)] = r
        else:
            if len(items) >= 20:
                raise BotError("A bot can have 20 routines at most.")
            items.append(r)
        _write(_path(bid), items)
        return r


def remove(bid: str, rid: str) -> bool:
    with _LOCK:
        items = load(bid)
        keep = [x for x in items if x.get("id") != rid]
        _write(_path(bid), keep)
        return len(keep) != len(items)


def get(bid: str, rid: str) -> dict[str, Any]:
    for r in load(bid):
        if r.get("id") == rid:
            return r
    raise BotError("That routine is gone.")


def mark_run(bid: str, rid: str, result: str = "", when: float | None = None) -> None:
    with _LOCK:
        items = load(bid)
        for r in items:
            if r.get("id") == rid:
                now = when or time.time()
                r["lastRun"] = now
                if result:
                    r["lastResult"] = result[:200]
                r["nextRun"] = next_run(r, now)
        _write(_path(bid), items)


def due(now: float | None = None) -> list[tuple[str, dict[str, Any]]]:
    """Routines whose time has come, each rescheduled so it is returned once."""
    now = now or time.time()
    out: list[tuple[str, dict[str, Any]]] = []
    with _LOCK:
        for bot in list_bots():
            if bot.paused:
                continue
            items = load(bot.id)
            changed = False
            for r in items:
                if r.get("enabled") and float(r.get("nextRun") or 0) <= now:
                    r["lastRun"] = now
                    r["nextRun"] = next_run(r, now)
                    changed = True
                    out.append((bot.id, dict(r)))
            if changed:
                _write(_path(bot.id), items)
    return out
