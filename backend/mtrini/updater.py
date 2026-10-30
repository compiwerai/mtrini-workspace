"""Automatic updates from GitHub releases.

The installed app checks the latest release, downloads the package for this platform in the
background, and checks it against the SHA-256 published with the release. Then:

- Windows: the installer runs silently when the app closes, or now with "Restart to update"
  (it reopens the app afterwards).
- Linux AppImage: the AppImage file is replaced; the next start runs the new version.
- .deb and .tar.gz installs (and running from source) only report that an update exists.

Downloads go through api.github.com, which also works where github.com itself is unreachable.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from . import __version__
from .config import user_dir

REPO = "compiwerai/mtrini-workspace"
API = f"https://api.github.com/repos/{REPO}"
CHECK_EVERY = 6 * 3600
_lock = threading.Lock()
_state: dict[str, Any] = {"status": "idle", "current": __version__}  # idle|checking|uptodate|available|downloading|ready|error


def _settings_file() -> Path:
    return user_dir() / "updates.json"


def enabled() -> bool:
    try:
        return bool(json.loads(_settings_file().read_text(encoding="utf-8")).get("auto", True))
    except (OSError, ValueError):
        return True


def set_enabled(on: bool) -> None:
    _settings_file().write_text(json.dumps({"auto": bool(on)}), encoding="utf-8")


def parse_version(v: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v.split("-")[0])
    return tuple(int(n) for n in nums[:3]) + (0,) * (3 - len(nums[:3]))


def newer(latest: str, current: str = __version__) -> bool:
    return parse_version(latest) > parse_version(current)


def install_kind() -> str:
    """How this copy was installed, which decides how it can update."""
    if not getattr(sys, "frozen", False):
        return "source"
    if sys.platform == "win32":
        return "windows"
    if os.environ.get("APPIMAGE"):
        return "appimage"
    return "linux-manual"  # .deb (needs admin rights) or .tar.gz


def pick_asset(assets: list[dict[str, Any]], kind: str) -> dict[str, Any] | None:
    patterns = {"windows": r"^MtriniWorkspace-Setup-[\d.]+\.exe$", "appimage": r"^MtriniWorkspace-[\d.]+-x86_64\.AppImage$"}
    pat = patterns.get(kind)
    return next((a for a in assets if pat and re.match(pat, a.get("name", ""))), None)


def expected_sha256(assets: list[dict[str, Any]], name: str, get) -> str | None:
    """The checksum published in the release (`<file>.sha256` or a combined `*.sha256` list)."""
    for a in assets:
        if not a.get("name", "").endswith(".sha256"):
            continue
        text = get(a).decode(errors="replace")
        for line in text.splitlines():
            parts = line.replace("*", " ").split()
            if len(parts) >= 2 and parts[-1] == name and re.fullmatch(r"[0-9a-f]{64}", parts[0]):
                return parts[0]
    return None


def _client() -> httpx.Client:
    return httpx.Client(timeout=60, follow_redirects=True,
                        headers={"User-Agent": f"MtriniWorkspace/{__version__}", "Accept": "application/vnd.github+json"})


def _download(c: httpx.Client, asset: dict[str, Any]) -> bytes:
    # The API asset URL (not github.com) redirects to the download host; it works on networks
    # where github.com itself doesn't resolve properly.
    r = c.get(asset["url"], headers={"Accept": "application/octet-stream"})
    r.raise_for_status()
    return r.content


def status() -> dict[str, Any]:
    with _lock:
        return {**_state, "auto": enabled(), "kind": install_kind()}


def _set(**kw: Any) -> None:
    with _lock:
        _state.update(kw)


def check(download: bool = True) -> dict[str, Any]:
    """Look for a newer release; download and verify it when this install can update itself."""
    _set(status="checking", error=None)
    kind = install_kind()
    try:
        with _client() as c:
            rel = c.get(f"{API}/releases/latest")
            rel.raise_for_status()
            data = rel.json()
            latest = data.get("tag_name", "").lstrip("v")
            _set(latest=latest, notes=(data.get("body") or "")[:4000], url=data.get("html_url"), checked=int(time.time()))
            if not latest or not newer(latest):
                _set(status="uptodate")
                return status()
            asset = pick_asset(data.get("assets", []), kind)
            if not download or asset is None:
                _set(status="available")  # report only: this install updates by hand
                return status()
            target = Path(tempfile.gettempdir()) / "mtrini-update" / asset["name"]
            if _state.get("file") == str(target) and target.exists():
                _set(status="ready")
                return status()
            _set(status="downloading")
            blob = _download(c, asset)
            want = expected_sha256(data.get("assets", []), asset["name"], lambda a: _download(c, a))
            got = hashlib.sha256(blob).hexdigest()
            if not want or want != got:
                _set(status="error", error="The download didn't match its published checksum, so it wasn't used.")
                return status()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob)
            _set(status="ready", file=str(target), sha256=got)
    except Exception as e:
        _set(status="error", error=f"Couldn't check for updates: {str(e)[:200]}")
    return status()


def _spawn_detached(args: list[str]) -> None:
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # outlives this app
    subprocess.Popen(args, creationflags=flags, close_fds=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def apply(relaunch: bool) -> bool:
    """Install a downloaded update. Windows: run the installer silently (the caller then exits);
    AppImage: replace the file in place. Returns True when something was applied."""
    st = status()
    if st.get("status") != "ready" or not st.get("file") or not Path(st["file"]).exists():
        return False
    if st["kind"] == "windows":
        args = [st["file"], "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"]
        if relaunch:
            args.append("/RELAUNCH")
        _spawn_detached(args)
        _set(status="installing")
        return True
    if st["kind"] == "appimage":
        current = Path(os.environ["APPIMAGE"])
        new = current.with_name(current.name + ".new")
        new.write_bytes(Path(st["file"]).read_bytes())
        new.chmod(0o755)
        os.replace(new, current)  # the running copy keeps working; the next start is the new version
        _set(status="installed")
        if relaunch:
            _spawn_detached([str(current)])
        return True
    return False


def background_loop(stop: threading.Event | None = None) -> None:
    """Desktop app: check shortly after start, then every few hours, while automatic updates are on."""
    stop = stop or threading.Event()
    if stop.wait(20):
        return
    while not stop.is_set():
        if enabled() and install_kind() != "source":
            check(download=True)
        if stop.wait(CHECK_EVERY):
            return
