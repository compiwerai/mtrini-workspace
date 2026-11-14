"""Native desktop window (OpenCode-style): local server + app window, no console.

Falls back to opening the system browser when pywebview/WebView2 is missing.
"""
from __future__ import annotations

import os
import sys
import threading

import uvicorn

# Windowed (PyInstaller --noconsole) apps have sys.stdout/sys.stderr = None;
# libraries like uvicorn assume they exist. Point them at devnull first.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")  # noqa: PTH123
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")  # noqa: PTH123

# Two apps share this launcher. Mtrini Bots (bots_desktop.py) has its own server, port and window; it shares
# the engine and ~/.mtrini with Mtrini Workspace, so a model you set up in one works in the other.
BOTS = os.environ.get("MTRINI_APP") == "bots" or "--bots" in sys.argv[1:]
# "--background" serves with no window: this is what starts at sign-in so bots keep their schedule.
BACKGROUND = BOTS and "--background" in sys.argv[1:]
if BOTS:
    from mtrini.bots.app import app

    TITLE, PORT = "Mtrini Bots", 8789
else:
    from mtrini.main import app

    TITLE, PORT = "Mtrini Workspace", 8787
URL = f"http://127.0.0.1:{PORT}"


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


def _port_free() -> bool:
    """False when another copy of the app is already serving: then this one only opens a window onto it."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", PORT))
            return True
        except OSError:
            return False


def _stay_for_bots(owns_server: bool) -> bool:
    """After the window closes: keep serving when the user asked for it and a bot has work to do."""
    if not owns_server or not BOTS:
        return False
    try:
        from mtrini.bots import background

        return background.should_stay()
    except Exception:
        import traceback

        _log("background check failed:\n" + traceback.format_exc())
        return False


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


def _install_update_on_exit() -> None:
    """Closing the app installs a downloaded update (Windows: silent installer; AppImage: file swap)."""
    if BOTS:
        return
    try:
        from mtrini import updater

        if updater.enabled() and updater.apply(relaunch=False):
            _log("update installed on exit")
    except Exception:
        import traceback

        _log("update on exit failed:\n" + traceback.format_exc())


def main() -> None:
    _log("desktop starting")
    os.environ["MTRINI_DESKTOP"] = "1"
    owns_server = _port_free()
    if BACKGROUND and not owns_server:
        _log("background start skipped: the app is already running")
        return
    if owns_server:
        threading.Thread(target=_serve, daemon=True).start()
    else:
        _log("joining the copy that is already running")
    if not BOTS:  # Mtrini Bots has no self-update yet; the Workspace updater would fetch the wrong installer
        from mtrini import updater

        threading.Thread(target=updater.background_loop, daemon=True).start()
    if BACKGROUND:
        _log("serving in the background for bots")
        threading.Event().wait()
    if sys.platform.startswith("linux"):
        _linux_main()
        if _stay_for_bots(owns_server):
            _log("window closed; staying in the background for bots")
            threading.Event().wait()
        _install_update_on_exit()
        return
    try:
        import webview  # type: ignore

        _log("webview starting")
        if BOTS:
            webview.create_window(TITLE, URL, width=1180, height=820, min_size=(900, 620))
        else:
            webview.create_window(TITLE, URL, width=1400, height=900, min_size=(1100, 700))
        webview.start()
        if _stay_for_bots(owns_server):  # the window was closed, but a bot still has work
            _log("window closed; staying in the background for bots")
            threading.Event().wait()
        _install_update_on_exit()  # the window was closed
    except Exception:
        import traceback
        import webbrowser

        _log("webview failed:\n" + traceback.format_exc())
        webbrowser.open(URL)
        threading.Event().wait()  # keep serving until killed


if __name__ == "__main__":
    main()
