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


# Linux: an app window in an installed Chromium-family browser (no tabs or address bar). Embedding a
# webview would mean bundling WebKitGTK, which breaks across distributions; every desktop has a browser.
APP_BROWSERS = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge",
                "microsoft-edge-stable", "brave-browser", "vivaldi")


def _wait_for_server(timeout: float = 30.0) -> None:
    import time
    import urllib.request

    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(URL + "/api/health", timeout=2)
            return
        except Exception:
            time.sleep(0.3)


def app_window_command(which=None) -> list[str] | None:
    """Command that opens the UI as its own app window, or None if no suitable browser is installed."""
    import shutil

    which = which or shutil.which
    for name in APP_BROWSERS:
        exe = which(name)
        if exe:
            profile = os.path.join(os.path.expanduser("~"), ".mtrini", "app-window")
            return [exe, f"--app={URL}", f"--user-data-dir={profile}", "--window-size=1400,900",
                    "--no-first-run", "--no-default-browser-check"]
    return None


def _linux_main() -> None:
    import subprocess
    import time
    import webbrowser

    if os.environ.get("MTRINI_HEADLESS"):  # servers and CI smoke tests: no window, just serve
        threading.Event().wait()
    _wait_for_server()
    cmd = app_window_command()
    if cmd:
        _log("app window: " + cmd[0])
        t0 = time.time()
        r = subprocess.run(cmd)  # its own profile, so this returns when the window closes
        if r.returncode == 0 or time.time() - t0 > 5:
            return
        _log(f"app window exited at once (code {r.returncode}); opening the default browser")
    else:
        _log("no app-window browser found; opening the default browser")
    webbrowser.open(URL)
    threading.Event().wait()  # keep serving until killed


def main() -> None:
    _log("desktop starting")
    threading.Thread(target=_serve, daemon=True).start()
    if sys.platform.startswith("linux"):
        _linux_main()
        return
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
