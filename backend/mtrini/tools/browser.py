"""Browser tools: the agent's own browser, for pages that need clicking.

`browser_act` is the only one that may press something that sends, buys, deletes or confirms, and its
permission level means the user is asked first in every mode except auto.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import browser as br
from . import Tool


async def _open(root: Path, a: dict[str, Any]):
    return br.render(await br.for_root(root).open(str(a.get("url", ""))))


async def _read(root: Path, a: dict[str, Any]):
    return br.render(await br.for_root(root).read())


async def _click(root: Path, a: dict[str, Any]):
    return br.render(await br.for_root(root).click(int(a.get("element", -1))))


async def _type(root: Path, a: dict[str, Any]):
    return br.render(await br.for_root(root).type(int(a.get("element", -1)), str(a.get("text", "")),
                                                  bool(a.get("enter", False))))


async def _act(root: Path, a: dict[str, Any]):
    b = br.for_root(root)
    if a.get("text") is not None:
        page = await b.type(int(a.get("element", -1)), str(a.get("text", "")), True, approved=True)
    else:
        page = await b.click(int(a.get("element", -1)), approved=True)
    return br.render(page)


async def _shot(root: Path, a: dict[str, Any]):
    p = await br.for_root(root).screenshot()
    return f"Saved a screenshot to {p.relative_to(root).as_posix()}"


_EL = {"type": "integer", "description": "The [number] of the element, from the last page reading"}

TOOLS = [
    Tool("browser_open", "Open a web page in your own browser and read it: its text and a numbered list of the "
         "links, buttons and fields on it. Use it when web_fetch is not enough (pages built with scripts, sites "
         "the user signed in to in this browser).", "network",
         {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}, _open),
    Tool("browser_read", "Read the page your browser is on again, after it changed.", "read",
         {"type": "object", "properties": {}}, _read),
    Tool("browser_click", "Click a link, tab or button that only navigates or reveals something. It refuses "
         "anything that sends, posts, buys, deletes or confirms: use browser_act for those.", "network",
         {"type": "object", "properties": {"element": _EL}, "required": ["element"]}, _click),
    Tool("browser_type", "Type into a field. Never a password: the user signs in themselves. enter=true is only "
         "for search boxes.", "network",
         {"type": "object", "properties": {"element": _EL, "text": {"type": "string"},
                                           "enter": {"type": "boolean"}}, "required": ["element", "text"]}, _type),
    Tool("browser_act", "Press a button that does something for real on the user's behalf: send, post, buy, "
         "delete, confirm, submit a form. The user is asked first. Give text to type it and press Enter instead "
         "of clicking. Say in your message exactly what will happen.", "execute",
         {"type": "object", "properties": {"element": _EL, "text": {"type": "string"},
                                           "what": {"type": "string", "description": "One line: what this does"}},
          "required": ["element", "what"]}, _act),
    Tool("browser_screenshot", "Save a picture of the page your browser is on into the workspace.", "read",
         {"type": "object", "properties": {}}, _shot),
]
