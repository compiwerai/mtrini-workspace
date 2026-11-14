"""Web tools: fetch a page as text, and search the web.

Search works with no setup: the query goes to DuckDuckGo's plain HTML page, and if that gives nothing,
to a results page opened in the agent's own browser. Set a Brave Search key, a Tavily key or a SearXNG
URL (Settings -> Web search) to use that instead; then queries go only there.
"""
from __future__ import annotations

import ipaddress
import re
import socket
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from . import Tool

MAX_CHARS = 20000
UA = "MtriniWorkspace/0.8 (+https://github.com/compiwerai)"
SEARCH_PROVIDERS = ("brave", "tavily", "searxng")


class _Text(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "section", "article"}
    SKIP = {"script", "style", "noscript", "svg", "head", "template"}

    def __init__(self) -> None:
        super().__init__()
        self.out: list[str] = []
        self.skip = 0
        self.title = ""
        self._in_title = False
        self._href: str | None = None

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        if tag == "title":
            self._in_title = True
        if tag in self.BLOCK:
            self.out.append("\n")
        if tag == "a" and not self.skip:
            href = dict(attrs).get("href") or ""
            if href.startswith("http"):
                self._href = href  # appended after the link text

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag == "title":
            self._in_title = False
        if tag == "a" and self._href:
            self.out.append(f" ({self._href})")
            self._href = None

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skip:
            self.out.append(data)

    def text(self) -> str:
        t = "".join(self.out)
        t = re.sub(r"[ \t\r\f\v]+", " ", t)
        return re.sub(r"\n\s*\n+", "\n\n", t).strip()


def _check_url(url: str) -> None:
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("only http(s) URLs can be fetched")
    try:
        for info in socket.getaddrinfo(u.hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_link_local:  # cloud metadata endpoints (169.254.x.x)
                raise ValueError("link-local addresses are blocked")
    except socket.gaierror:
        raise ValueError(f"cannot resolve {u.hostname}")


async def _h_fetch(root: Path, a: dict[str, Any]):
    url = str(a["url"]).strip()
    _check_url(url)
    limit = min(int(a.get("maxChars") or MAX_CHARS), 100_000)
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": UA}) as c:
        r = await c.get(url)
    ctype = r.headers.get("content-type", "")
    if "html" in ctype:
        p = _Text()
        p.feed(r.text)
        body, title = p.text(), p.title.strip()
    elif ctype.startswith("text/") or "json" in ctype or "xml" in ctype:
        body, title = r.text, ""
    else:
        return {"url": str(r.url), "status": r.status_code, "contentType": ctype,
                "text": f"(binary content, {len(r.content)} bytes, not shown)"}
    return {"url": str(r.url), "status": r.status_code, "title": title,
            "text": body[:limit], "truncated": len(body) > limit}


def search_config(root: Path) -> dict[str, Any]:
    from ..config import get_secret, load_config

    cfg = load_config(root).get("webSearch", {})
    cfg = cfg if isinstance(cfg, dict) else {}
    provider = cfg.get("provider", "")
    key = get_secret(root, f"mtrini-search-{provider}", "apiKey") if provider in ("brave", "tavily") else None
    return {"provider": provider, "baseUrl": cfg.get("baseUrl", ""), "key": key or ""}


DDG = "https://html.duckduckgo.com/html/"
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/126.0 Safari/537.36")
_RESULT = re.compile(r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_SNIPPET = re.compile(r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>', re.S)


def _plain(fragment: str) -> str:
    import html

    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", fragment)).split())


def _real_url(href: str) -> str:
    """DuckDuckGo sometimes wraps a result in its own redirect: unwrap it."""
    from urllib.parse import parse_qs, unquote

    if "duckduckgo.com/l/" in href:
        target = parse_qs(urlparse(href if "://" in href else "https:" + href).query).get("uddg", [""])[0]
        return unquote(target)
    return href


def parse_duckduckgo(page: str) -> list[dict[str, Any]]:
    snippets = [_plain(s) for s in _SNIPPET.findall(page)]
    out = []
    for i, (href, title) in enumerate(_RESULT.findall(page)):
        url = _real_url(href.replace("&amp;", "&"))
        if not url.startswith("http") or "duckduckgo.com/y.js" in url:  # an ad or a broken link
            continue
        out.append({"title": _plain(title), "url": url, "snippet": snippets[i] if i < len(snippets) else ""})
    return out


async def _browser_search(root: Path, q: str) -> list[dict[str, Any]]:
    """Search the way a person would: open a results page in the agent's own browser and read the links."""
    from urllib.parse import quote_plus

    from .. import browser as br

    page = await br.for_root(root).open("https://www.bing.com/search?q=" + quote_plus(q))
    out, seen = [], set()
    for e in page.get("elements") or []:
        url, title = str(e.get("href") or ""), str(e.get("text") or "")
        host = urlparse(url).netloc
        if not url.startswith("http") or len(title) < 12 or any(h in host for h in ("bing.com", "microsoft.com", "msn.com")):
            continue
        if url not in seen:
            seen.add(url)
            out.append({"title": title, "url": url, "snippet": ""})
    return out


async def _free_search(root: Path, c: httpx.AsyncClient, q: str) -> tuple[str, list[dict[str, Any]]]:
    """No key set up: DuckDuckGo's plain page first, the agent's own browser if that gives nothing."""
    try:
        r = await c.post(DDG, data={"q": q}, headers={"User-Agent": BROWSER_UA}, follow_redirects=True)
        results = parse_duckduckgo(r.text) if r.status_code == 200 else []
    except httpx.HTTPError:
        results = []
    if results:
        return "duckduckgo", results
    try:
        results = await _browser_search(root, q)
    except Exception:  # noqa: BLE001  (no browser on this machine, or the page did not load)
        results = []
    if results:
        return "browser", results
    raise ValueError("The free web search gave no results right now. Try again in a minute, or add a Brave or "
                     "Tavily API key, or a SearXNG URL, in Settings -> Web search.")


async def _h_search(root: Path, a: dict[str, Any]):
    q = str(a["query"]).strip()
    n = max(1, min(int(a.get("count") or 8), 20))
    cfg = search_config(root)
    p = cfg["provider"]
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": UA}) as c:
        if p == "brave" and cfg["key"]:
            r = await c.get("https://api.search.brave.com/res/v1/web/search", params={"q": q, "count": n},
                            headers={"X-Subscription-Token": cfg["key"], "Accept": "application/json"})
            r.raise_for_status()
            items = r.json().get("web", {}).get("results", [])
            results = [{"title": i.get("title"), "url": i.get("url"), "snippet": i.get("description")} for i in items]
        elif p == "tavily" and cfg["key"]:
            r = await c.post("https://api.tavily.com/search", json={"query": q, "max_results": n},
                             headers={"Authorization": f"Bearer {cfg['key']}"})
            r.raise_for_status()
            results = [{"title": i.get("title"), "url": i.get("url"), "snippet": i.get("content")}
                       for i in r.json().get("results", [])]
        elif p == "searxng" and cfg["baseUrl"]:
            r = await c.get(cfg["baseUrl"].rstrip("/") + "/search", params={"q": q, "format": "json"})
            r.raise_for_status()
            results = [{"title": i.get("title"), "url": i.get("url"), "snippet": i.get("content")}
                       for i in r.json().get("results", [])]
        else:
            p, results = await _free_search(root, c, q)
    return {"query": q, "provider": p, "results": results[:n]}


TOOLS = [
    Tool("web_fetch", "Fetch a web page (http/https) and return its readable text", "network",
         {"type": "object", "properties": {"url": {"type": "string"},
                                           "maxChars": {"type": "integer", "description": "default 20000"}},
          "required": ["url"]}, _h_fetch),
    Tool("web_search", "Search the web; returns titles, URLs and snippets", "network",
         {"type": "object", "properties": {"query": {"type": "string"},
                                           "count": {"type": "integer", "description": "1-20, default 8"}},
          "required": ["query"]}, _h_search),
]
