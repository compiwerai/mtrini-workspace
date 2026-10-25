"""Web tools: fetch a page as text, and search through a configured search API.

Search needs one of: a Brave Search API key, a Tavily API key, or a SearXNG
instance URL (Settings -> Web search). Nothing is sent anywhere until one is set.
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
            raise ValueError("Web search is not set up. Add a Brave or Tavily API key, or a SearXNG URL, "
                             "in Settings -> Web search.")
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
