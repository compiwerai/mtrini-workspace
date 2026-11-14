"""Always on: bots keep working after you close the window, and start again when you sign in.

"Always" here means while this computer is on and awake. Nothing runs when it is off: that would need
a server somewhere, and Mtrini Bots runs on your own machine.

Two switches, both off until you turn them on:
- keep running: closing the window leaves the app serving in the background (no window) while a bot has
  a routine switched on or Telegram is connected;
- start at sign-in: the installed app registers `MtriniWorkspace --background` for your user account
  (Windows: the per-user Run key; Linux: an autostart entry). No admin rights, and switching it off removes it.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from .. import bots
from . import _read, _write, routines

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "MtriniBots"


def _path() -> Path:
    return bots.home() / "background.json"


def settings() -> dict[str, bool]:
    s = _read(_path(), {})
    s = s if isinstance(s, dict) else {}
    return {"keepRunning": bool(s.get("keepRunning")), "autostart": bool(s.get("autostart"))}


def installed() -> bool:
    """True in the packaged desktop app, where there is one program to start again."""
    return bool(getattr(sys, "frozen", False))


def in_desktop_app() -> bool:
    return os.environ.get("MTRINI_DESKTOP") == "1"


def launch_command() -> str:
    return f'"{sys.executable}" --background'


def _linux_entry() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "autostart" / "mtrini-bots.desktop"


def _apply_autostart(on: bool) -> None:
    """Add or remove the sign-in entry for this user. Kept small so tests can stand in for it."""
    if sys.platform == "win32":
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if on:
                winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, launch_command())
            else:
                try:
                    winreg.DeleteValue(key, RUN_NAME)
                except FileNotFoundError:
                    pass
    elif sys.platform.startswith("linux"):
        entry = _linux_entry()
        if on:
            entry.parent.mkdir(parents=True, exist_ok=True)
            entry.write_text("[Desktop Entry]\nType=Application\nName=Mtrini Bots\n"
                             f"Exec={launch_command()}\nX-GNOME-Autostart-enabled=true\n", encoding="utf-8")
        else:
            entry.unlink(missing_ok=True)
    else:
        raise bots.BotError("Starting at sign-in is not available on this system yet.")


def save(keep_running: bool | None = None, autostart: bool | None = None) -> dict[str, Any]:
    s = settings()
    if keep_running is not None:
        s["keepRunning"] = bool(keep_running)
    if autostart is not None and bool(autostart) != s["autostart"]:
        if autostart and not installed():
            raise bots.BotError("Starting at sign-in works in the installed app, not in a development copy.")
        if installed():
            try:
                _apply_autostart(bool(autostart))
            except OSError as e:
                raise bots.BotError(f"Could not change the sign-in entry: {e}") from None
        s["autostart"] = bool(autostart)
        if autostart:
            s["keepRunning"] = True  # starting in the background only makes sense if it then stays
    _write(_path(), s)
    return status()


def has_work() -> bool:
    """Is there anything for the background to do: a routine switched on, or Telegram connected?"""
    from . import telegram

    for bot in bots.list_bots():
        if not bot.paused and any(r.get("enabled") for r in routines.load(bot.id)):
            return True
    return bool(telegram.token())


def should_stay() -> bool:
    """Asked when the window closes: keep serving, or quit?"""
    return settings()["keepRunning"] and has_work()


def status() -> dict[str, Any]:
    s = settings()
    return {**s, "installed": installed(), "desktop": in_desktop_app(), "hasWork": has_work(),
            "staysOn": s["keepRunning"] and has_work()}
