"""The agent's own browser.

Drives a browser already on the machine (Edge or Chrome) through the Chrome DevTools Protocol, with a
profile of its own under `.mtrini/browser/` so it never touches the user's tabs, cookies or passwords.
It runs hidden by default; `show()` reopens it as a normal window so the user can sign in to a site
themselves, and the sign-in stays in that profile.

Rules built in here, not left to the model:
- it never types into a password field;
- a click that looks like it sends, posts, buys, deletes or confirms is refused unless the caller says
  the user approved it (the `browser_act` tool, which asks first).
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

from .proc import NO_WINDOW

TEXT_LIMIT = 12000
MAX_ELEMENTS = 80
RISKY = re.compile(
    r"\b(send|submit|post|publish|tweet|reply|share|buy|purchase|order|pay|checkout|check out|place order|"
    r"subscribe|sign up|register|delete|remove|confirm|accept|agree|apply|transfer|donate|book|reserve|"
    r"unsubscribe|cancel subscription|save changes|update|upload|invite|follow|like|vote|"
    r"envoyer|publier|acheter|payer|commander|supprimer|confirmer|valider|accepter|s'inscrire)\b", re.I)
SEARCHY = re.compile(r"search|query|recherche|find|keyword", re.I)

_WINDOWS = [
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe",
]
_MAC = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]
_LINUX = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "brave-browser"]


class BrowserError(Exception):
    pass


def find_browser() -> str | None:
    """Path of a Chromium-family browser on this machine, or None."""
    override = os.environ.get("MTRINI_BROWSER")
    if override:
        return override if Path(override).exists() else shutil.which(override)
    if os.name == "nt":
        for p in _WINDOWS:
            full = os.path.expandvars(p)
            if Path(full).exists():
                return full
        return None
    for p in _MAC:
        if Path(p).exists():
            return p
    for name in _LINUX:
        found = shutil.which(name)
        if found:
            return found
    return None


def profile_dir(root: Path) -> Path:
    from .agent.session import keep_private

    d = root / ".mtrini" / "browser"
    if not d.exists():
        d.mkdir(parents=True, exist_ok=True)
        keep_private(root)
    return d


def looks_risky(el: dict[str, Any]) -> bool:
    """True when clicking this element probably does something for real: send, buy, delete, confirm."""
    label = " ".join(str(el.get(k) or "") for k in ("text", "aria", "value", "title")).strip()
    if el.get("type") == "submit" and not SEARCHY.search(" ".join(str(el.get(k) or "") for k in ("form", "name", "aria", "text"))):
        return True
    return bool(RISKY.search(label))


def is_search_field(el: dict[str, Any]) -> bool:
    if el.get("type") == "search" or el.get("role") == "searchbox":
        return True
    if str(el.get("name") or "").lower() in ("q", "s", "query", "search") or str(el.get("id") or "").lower() in ("q", "search"):
        return True
    return bool(SEARCHY.search(" ".join(str(el.get(k) or "") for k in ("name", "id", "aria", "placeholder", "form"))))


# Runs in the page: reads the visible text and numbers the things that can be clicked or typed into.
_READ_JS = r"""
(() => {
  const seen = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    const st = getComputedStyle(el);
    return st.visibility !== 'hidden' && st.display !== 'none' && st.opacity !== '0';
  };
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim().slice(0, 90);
  const nodes = [...document.querySelectorAll('a[href], button, input, textarea, select, [role=button], [role=link], [role=tab], [role=menuitem], [role=searchbox], [contenteditable=true]')];
  const els = [];
  window.__mtrini = [];
  for (const el of nodes) {
    if (els.length >= __MAX__) break;
    if (!seen(el) || el.disabled) continue;
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (tag === 'input' && type === 'hidden') continue;
    const form = el.closest('form');
    const d = {
      i: els.length, tag, type,
      role: el.getAttribute('role') || '',
      text: clean(el.innerText || el.value || ''),
      aria: clean(el.getAttribute('aria-label')), title: clean(el.getAttribute('title')),
      name: el.getAttribute('name') || '', id: el.id || '',
      placeholder: clean(el.getAttribute('placeholder')),
      value: tag === 'input' && type !== 'password' ? clean(el.value) : '',
      href: tag === 'a' ? el.href : '',
      form: form ? clean((form.getAttribute('role') || '') + ' ' + (form.getAttribute('action') || '') + ' ' + (form.id || '') + ' ' + (form.getAttribute('name') || '')) : '',
    };
    window.__mtrini.push(el);
    els.push(d);
  }
  const main = document.querySelector('main, article, [role=main]') || document.body;
  return { url: location.href, title: document.title, text: (main ? main.innerText : '').replace(/\n{3,}/g, '\n\n').slice(0, __LIMIT__), elements: els };
})()
""".replace("__MAX__", str(MAX_ELEMENTS)).replace("__LIMIT__", str(TEXT_LIMIT))

_DESCRIBE_JS = r"""
((i) => {
  const el = (window.__mtrini || [])[i];
  if (!el || !el.isConnected) return null;
  const tag = el.tagName.toLowerCase();
  const form = el.closest('form');
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim().slice(0, 90);
  return { tag, type: (el.getAttribute('type') || '').toLowerCase(), role: el.getAttribute('role') || '',
    text: clean(el.innerText || el.value || ''), aria: clean(el.getAttribute('aria-label')), title: clean(el.getAttribute('title')),
    name: el.getAttribute('name') || '', id: el.id || '', placeholder: clean(el.getAttribute('placeholder')),
    value: tag === 'input' ? '' : clean(el.value),
    form: form ? clean((form.getAttribute('role') || '') + ' ' + (form.getAttribute('action') || '') + ' ' + (form.id || '') + ' ' + (form.getAttribute('name') || '')) : '' };
})
"""

_CLICK_JS = r"""
((i) => { const el = window.__mtrini[i]; el.scrollIntoView({block: 'center'}); el.click(); return true; })
"""

_TYPE_JS = r"""
((i, text, enter) => {
  const el = window.__mtrini[i];
  el.scrollIntoView({block: 'center'});
  el.focus();
  if (el.isContentEditable) { el.textContent = text; }
  else {
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : el.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
    setter.call(el, text);
  }
  el.dispatchEvent(new Event('input', {bubbles: true}));
  el.dispatchEvent(new Event('change', {bubbles: true}));
  if (enter) {
    for (const type of ['keydown', 'keypress', 'keyup'])
      el.dispatchEvent(new KeyboardEvent(type, {key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true}));
    const form = el.closest('form');
    if (form) { if (form.requestSubmit) form.requestSubmit(); else form.submit(); }
  }
  return true;
})
"""


class Browser:
    """One browser process and one tab for a workspace."""

    def __init__(self, root: Path):
        self.root = root
        self.proc: subprocess.Popen | None = None
        self.port = 0
        self.headless = True
        self.ws: Any = None
        self._id = 0
        self._lock = asyncio.Lock()

    # ---- process ----
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    async def start(self, headless: bool = True, url: str = "about:blank") -> None:
        exe = find_browser()
        if not exe:
            raise BrowserError("No Edge or Chrome was found on this computer. Install one, or set MTRINI_BROWSER "
                               "to a Chromium-based browser.")
        prof = profile_dir(self.root)
        port_file = prof / "DevToolsActivePort"
        try:
            port_file.unlink()
        except OSError:
            pass
        args = [exe, "--remote-debugging-port=0", f"--user-data-dir={prof}", "--no-first-run",
                "--no-default-browser-check", "--disable-features=Translate", "--window-size=1200,860"]
        if headless:
            args += ["--headless=new", "--disable-gpu"]
        args.append(url)
        kw = NO_WINDOW if headless else {}
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
        self.headless = headless
        for _ in range(100):  # the browser writes its port once it is listening
            if port_file.exists():
                try:
                    self.port = int(port_file.read_text(encoding="utf-8").splitlines()[0])
                    break
                except (ValueError, IndexError, OSError):
                    pass
            if not self.running():
                raise BrowserError("The browser closed while starting. Is another copy using this profile?")
            await asyncio.sleep(0.1)
        else:
            raise BrowserError("The browser did not start in time.")
        await self._attach()

    async def _attach(self) -> None:
        import websockets

        async with httpx.AsyncClient(timeout=5) as c:
            for _ in range(40):
                try:
                    tabs = (await c.get(f"http://127.0.0.1:{self.port}/json/list")).json()
                except (httpx.HTTPError, ValueError):
                    tabs = []
                pages = [t for t in tabs if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
                if pages:
                    break
                await asyncio.sleep(0.15)
            else:
                raise BrowserError("The browser has no tab to use.")
        self.ws = await websockets.connect(pages[0]["webSocketDebuggerUrl"], max_size=40_000_000, origin=None)
        await self.cdp("Page.enable")

    async def stop(self) -> None:
        if self.ws is not None:
            try:
                await self.ws.close()
            except Exception:
                pass
            self.ws = None
        if self.running():
            assert self.proc is not None
            self.proc.terminate()
            try:
                await asyncio.to_thread(self.proc.wait, 5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    async def ensure(self) -> None:
        if not self.running() or self.ws is None:
            await self.stop()
            await self.start(headless=True)

    # ---- protocol ----
    async def cdp(self, method: str, params: dict | None = None, timeout: float = 30) -> dict:
        if self.ws is None:
            raise BrowserError("The browser is not running.")
        self._id += 1
        mid = self._id
        await self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        end = time.time() + timeout
        while True:
            left = end - time.time()
            if left <= 0:
                raise BrowserError(f"The browser did not answer {method} in time.")
            try:
                msg = json.loads(await asyncio.wait_for(self.ws.recv(), left))
            except asyncio.TimeoutError:
                raise BrowserError(f"The browser did not answer {method} in time.") from None
            if msg.get("id") == mid:
                if "error" in msg:
                    raise BrowserError(str(msg["error"].get("message", "browser error")))
                return msg.get("result", {})

    async def js(self, expression: str, timeout: float = 30) -> Any:
        res = await self.cdp("Runtime.evaluate", {"expression": expression, "returnByValue": True,
                                                  "awaitPromise": True}, timeout)
        if res.get("exceptionDetails"):
            raise BrowserError("The page raised an error: " + str(res["exceptionDetails"].get("text", ""))[:200])
        return res.get("result", {}).get("value")

    async def _settle(self, timeout: float = 20) -> None:
        end = time.time() + timeout
        await asyncio.sleep(0.25)
        while time.time() < end:
            try:
                if await self.js("document.readyState", 5) == "complete":
                    break
            except BrowserError:
                pass  # navigating: the old page is gone, the new one is not ready
            await asyncio.sleep(0.25)
        await asyncio.sleep(0.4)  # let late scripts paint

    # ---- actions ----
    async def open(self, url: str) -> dict:
        if not re.match(r"^https?://", url, re.I):
            if re.match(r"^[a-z][a-z0-9+.-]*:", url, re.I):
                raise BrowserError("Only http and https pages can be opened.")
            url = "https://" + url
        async with self._lock:
            await self.ensure()
            await self.cdp("Page.navigate", {"url": url})
            await self._settle()
            return await self._read()

    async def _read(self) -> dict:
        page = await self.js(_READ_JS)
        if not isinstance(page, dict):
            raise BrowserError("The page could not be read.")
        return page

    async def read(self) -> dict:
        async with self._lock:
            await self.ensure()
            return await self._read()

    async def _describe(self, index: int) -> dict:
        el = await self.js(f"{_DESCRIBE_JS}({int(index)})")
        if not el:
            raise BrowserError(f"There is no element [{index}] on this page any more. Read the page again.")
        return el

    async def click(self, index: int, approved: bool = False) -> dict:
        async with self._lock:
            await self.ensure()
            el = await self._describe(index)
            if not approved and looks_risky(el):
                raise BrowserError(f"[{index}] \"{el.get('text') or el.get('aria')}\" looks like it sends, buys, deletes or "
                                   "confirms something. Use browser_act for that: it asks the user first.")
            await self.js(f"{_CLICK_JS}({int(index)})")
            await self._settle(12)
            return await self._read()

    async def type(self, index: int, text: str, enter: bool = False, approved: bool = False) -> dict:
        async with self._lock:
            await self.ensure()
            el = await self._describe(index)
            if el.get("type") == "password":
                raise BrowserError("Passwords are never typed by the agent. Ask the user to open this browser "
                                   "(Show browser) and sign in themselves; the sign-in is kept.")
            if el.get("tag") not in ("input", "textarea", "select") and el.get("role") not in ("searchbox", "textbox"):
                if not await self.js(f"!!window.__mtrini[{int(index)}].isContentEditable"):
                    raise BrowserError(f"[{index}] is not something you can type into.")
            if enter and not approved and not is_search_field(el):
                raise BrowserError("Pressing Enter here may send a message or a form. Type without enter, then use "
                                   "browser_act on the button: it asks the user first.")
            await self.js(f"{_TYPE_JS}({int(index)}, {json.dumps(text)}, {'true' if enter else 'false'})")
            if enter:
                await self._settle(12)
            return await self._read()

    async def screenshot(self) -> Path:
        async with self._lock:
            await self.ensure()
            res = await self.cdp("Page.captureScreenshot", {"format": "png"})
            d = self.root / ".mtrini" / "browser-shots"
            d.mkdir(parents=True, exist_ok=True)
            p = d / f"shot-{time.strftime('%Y%m%d-%H%M%S')}.png"
            p.write_bytes(base64.b64decode(res.get("data", "")))
            return p

    async def current_url(self) -> str:
        try:
            return str(await self.js("location.href", 5) or "")
        except BrowserError:
            return ""

    async def show(self) -> str:
        """Reopen as a normal window, on the same page, so the user can sign in or look."""
        async with self._lock:
            url = await self.current_url() if self.running() and self.ws is not None else ""
            await self.stop()
            await self.start(headless=False, url=url if url.startswith("http") else "about:blank")
            return url

    async def hide(self) -> None:
        async with self._lock:
            url = await self.current_url() if self.running() and self.ws is not None else ""
            await self.stop()
            await self.start(headless=True, url=url if url.startswith("http") else "about:blank")


_OPEN: dict[str, Browser] = {}


def for_root(root: Path) -> Browser:
    key = str(root.resolve())
    if key not in _OPEN:
        _OPEN[key] = Browser(root)
    return _OPEN[key]


def status(root: Path) -> dict[str, Any]:
    b = _OPEN.get(str(root.resolve()))
    return {"available": find_browser() is not None, "running": bool(b and b.running()),
            "visible": bool(b and b.running() and not b.headless)}


async def close_all() -> None:
    for b in list(_OPEN.values()):
        try:
            await b.stop()
        except Exception:
            pass
    _OPEN.clear()


def render(page: dict[str, Any]) -> str:
    """The page as text for the model: where it is, what it says, what can be clicked."""
    lines = [f"URL: {page.get('url', '')}", f"Title: {page.get('title', '')}", ""]
    els = page.get("elements") or []
    if els:
        lines.append("Things you can use (give the number to browser_click or browser_type):")
        for e in els:
            label = e.get("text") or e.get("aria") or e.get("placeholder") or e.get("title") or e.get("name") or ""
            kind = e.get("tag", "")
            if kind == "input":
                kind = f"input:{e.get('type') or 'text'}"
            extra = f" = \"{e['value']}\"" if e.get("value") else ""
            lines.append(f"[{e['i']}] {kind} \"{label}\"{extra}")
        lines.append("")
    lines.append("Text on the page:")
    lines.append(str(page.get("text") or "(no readable text)"))
    return "\n".join(lines)
