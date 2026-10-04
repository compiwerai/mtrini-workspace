"""Native desktop window (OpenCode-style): local server + app window, no console.

Falls back to opening the system browser when pywebview/WebView2 is missing.
"""
from __future__ import annotations

import os
import sys
import threading

import uvicorn

from mtrini.main import app

# Windowed (PyInstaller --noconsole) apps have sys.stdout/sys.stderr = None;
# libraries like uvicorn assume they exist. Point them at devnull first.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")  # noqa: PTH123
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")  # noqa: PTH123

TITLE = "Mtrini Workspace"
URL = "http://127.0.0.1:8787"
PORT = 8787


def _resource(*parts: str) -> str | None:
    base = getattr(sys, "_MEIPASS", None)  # PyInstaller bundle
    candidates = []
    if base:
        candidates.append(os.path.join(base, *parts))
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(here, "..", *parts))  # repo checkout
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def _log(msg: str) -> None:
    try:
        with open(os.path.join(os.path.expanduser("~"), "mtrini-desktop.log"), "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def _serve() -> None:
    try:
        _log("server starting")
        uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
    except Exception:
        import traceback

        _log("server crashed:\n" + traceback.format_exc())


def main() -> None:
    _log("desktop starting")
    threading.Thread(target=_serve, daemon=True).start()
    try:
        import webview  # type: ignore

        _log("webview starting")
        webview.create_window(TITLE, URL, width=1400, height=900, min_size=(1100, 700))
        webview.start()
    except Exception:
        import traceback
        import webbrowser

        _log("webview failed:\n" + traceback.format_exc())
        webbrowser.open(URL)
        threading.Event().wait()  # keep serving until killed


if __name__ == "__main__":
    main()
