"""Sharing what a bot did: result cards (PNG images) and bot recipes (small JSON links).

Nothing here uploads anything. A card is drawn in the app from what the user kept in the preview and saved
on this computer; a recipe carries a bot's job (name, role, instructions, routines), never its memory,
files, conversation, model or keys. Links open only on the few sites the Share buttons point to.
"""
from __future__ import annotations

import base64
import binascii
import datetime as dt
import json
import re
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import COLORS, MASCOTS, Bot, BotError, create, get, list_bots
from . import routines as _routines

SITE = "https://compiwer.ai/bots"
RECIPE_LINK = SITE + "/r#"  # the recipe rides in the fragment: it never reaches a server
OPEN_HOSTS = {"x.com", "twitter.com", "wa.me", "api.whatsapp.com", "compiwer.ai", "www.compiwer.ai"}
PNG = b"\x89PNG\r\n\x1a\n"
MAX_PNG = 6_000_000
MAX_RECIPE = 40_000
RECIPE_VERSION = 1


# ---- where shared things are saved ----
def shared_dir(kind: str = "cards") -> Path:
    """Cards go to Pictures, recipes to Documents, each in a "Mtrini Bots" folder."""
    base = Path.home() / ("Pictures" if kind == "cards" else "Documents")
    d = (base if base.is_dir() else Path.home()) / "Mtrini Bots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _stamp() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H%M%S")


def _file_name(name: str) -> str:
    return " ".join(re.sub(r"[^A-Za-z0-9 _-]+", "", str(name or "")).split())[:40] or "Bot"


def save_card(data: str, name: str) -> Path:
    """Save a card the app drew. `data` is a PNG as base64 (a data: URL is fine)."""
    raw = str(data or "")
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[-1]
    if len(raw) > MAX_PNG * 4 // 3 + 8:
        raise BotError("That image is too big.")
    try:
        png = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        raise BotError("That is not an image.") from None
    if not png.startswith(PNG):
        raise BotError("That is not a PNG image.")
    p = shared_dir("cards") / f"{_file_name(name)} card {_stamp()}.png"
    p.write_bytes(png)
    return p


def reveal(path: str) -> Path:
    """Show a saved card or recipe in the file manager. Only files in the Mtrini Bots folders."""
    p = Path(path).resolve()
    allowed = {shared_dir("cards").resolve(), shared_dir("recipes").resolve()}
    if p.parent not in allowed or not p.exists():
        raise BotError("That file is not one Mtrini Bots saved.")
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(p)])  # noqa: S603,S607
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(p)])  # noqa: S603,S607
    else:
        subprocess.Popen(["xdg-open", str(p.parent)])  # noqa: S603,S607
    return p


def safe_url(url: str) -> bool:
    try:
        u = urlparse(str(url or ""))
    except ValueError:
        return False
    return u.scheme == "https" and (u.hostname or "").lower() in OPEN_HOSTS


def open_url(url: str) -> None:
    """Open a share link in the system browser (the app window does not open new windows)."""
    if not safe_url(url):
        raise BotError("Mtrini Bots only opens its own share links.")
    webbrowser.open(url)


# ---- recipes ----
def recipe(bid: str) -> dict[str, Any]:
    bot = get(bid)
    keep = ("title", "prompt", "kind", "time", "minutes", "days")
    return {"mtriniBot": RECIPE_VERSION, "name": bot.name, "role": bot.role, "instructions": bot.instructions,
            "mascot": bot.mascot, "color": bot.color,
            "routines": [{k: r[k] for k in keep if k in r} for r in _routines.load(bid)]}


def encode(r: dict[str, Any]) -> str:
    raw = json.dumps(r, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def link(r: dict[str, Any]) -> str:
    return RECIPE_LINK + encode(r)


def parse(text: str) -> dict[str, Any]:
    """A recipe from what the user pasted: a link, the code after its '#', or the JSON itself."""
    t = str(text or "").strip()
    if not t or len(t) > MAX_RECIPE:
        raise BotError("Paste a Mtrini Bots recipe link or file.")
    data: Any = None
    if t.startswith("{"):
        try:
            data = json.loads(t)
        except ValueError:
            data = None
    else:
        code = t.split("#", 1)[1] if "#" in t else t
        code = re.sub(r"\s+", "", code)
        try:
            data = json.loads(base64.urlsafe_b64decode(code + "=" * (-len(code) % 4)).decode("utf-8"))
        except (binascii.Error, ValueError, UnicodeDecodeError):
            data = None
    if not isinstance(data, dict) or data.get("mtriniBot") != RECIPE_VERSION or not str(data.get("name") or "").strip():
        raise BotError("That is not a Mtrini Bots recipe.")
    out: dict[str, Any] = {
        "mtriniBot": RECIPE_VERSION,
        "name": " ".join(str(data["name"]).split())[:40],
        "role": " ".join(str(data.get("role") or "").split())[:80],
        "instructions": str(data.get("instructions") or "").strip()[:4000],
        "mascot": data.get("mascot") if data.get("mascot") in MASCOTS else "",
        "color": data.get("color") if data.get("color") in COLORS else "",
        "routines": [],
    }
    for r in (data.get("routines") or [])[:10] if isinstance(data.get("routines"), list) else []:
        if not isinstance(r, dict):
            continue
        try:  # the same checks as a routine made in the app; a broken one is left out
            clean = _routines._clean({**r, "enabled": False})
        except (BotError, TypeError, ValueError):
            continue
        out["routines"].append({k: clean[k] for k in ("title", "prompt", "kind", "time", "minutes", "days") if k in clean})
    return out


def import_recipe(text: str) -> Bot:
    """Make a bot from a recipe. It runs on the free built-in model, and its routines start switched off."""
    r = parse(text)
    taken = {b.name.lower() for b in list_bots()}
    name, n = r["name"], 1
    while name.lower() in taken:
        n += 1
        name = f"{r['name'][:36]} {n}"
    bot = create(name, r["role"], r["instructions"], color=r["color"], mascot=r["mascot"])
    for routine in r["routines"]:
        try:
            _routines.upsert(bot.id, {**routine, "enabled": False})
        except BotError:
            continue
    return bot


def save_recipe(bid: str) -> Path:
    r = recipe(bid)
    p = shared_dir("recipes") / f"{_file_name(r['name'])}.mtrinibot.json"
    p.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    return p

