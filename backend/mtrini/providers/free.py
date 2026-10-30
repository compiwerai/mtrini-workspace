"""Heabsy (bring your own key) and the built-in free model (sponsored by Heabsy, through our relay).

The free model needs no key: requests go to the Compiwer relay, which holds the sponsored
Heabsy key and applies daily limits. The app sends an anonymous install id (a random number
made on first use, stored in ~/.mtrini/install-id) so the relay can count each install's
daily usage. Nothing else about the user or their project is added.
"""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Any

import httpx

from . import ChatMessage, ModelInfo
from .cloud import _CloudBase
from .openai_compat import OpenAICompatibleProvider

HEABSY_URL = "https://api.heabsy.com/v1"
HEABSY_UPGRADE_URL = "https://platform.heabsy.com/r/mtrini"  # Heabsy partner referral link
# Set when the relay is deployed; MTRINI_FREE_URL overrides it (tests, self-hosting).
FREE_RELAY_URL = "https://mtrini-free.roblox-event-bot-worker.workers.dev"
FREE_MODEL = "qwen38"
FREE_LABEL = "Free, powered by Heabsy"


def free_relay_url() -> str:
    return (os.environ.get("MTRINI_FREE_URL") or FREE_RELAY_URL).rstrip("/")


def install_id() -> str:
    """Anonymous id for this install, only used by the relay to apply per-install daily limits."""
    home = Path(os.environ.get("MTRINI_HOME") or Path.home() / ".mtrini")
    f = home / "install-id"
    try:
        v = f.read_text(encoding="utf-8").strip()
        if re.fullmatch(r"[0-9a-f]{32}", v):
            return v
    except OSError:
        pass
    v = uuid.uuid4().hex
    try:
        home.mkdir(parents=True, exist_ok=True)
        f.write_text(v, encoding="utf-8")
    except OSError:
        pass
    return v


class FreeModelError(RuntimeError):
    """A message from the relay meant for the user as-is (daily limit reached, paused, busy)."""


class HeabsyProvider(_CloudBase):
    """Heabsy: open-weight models on EU hardware, OpenAI-compatible."""
    name = "heabsy"

    def __init__(self, api_key: str = "", **kw: Any):
        super().__init__(base_url=HEABSY_URL, api_key=api_key)

    async def list_models(self, **kw: Any) -> list[ModelInfo]:
        models = await OpenAICompatibleProvider.list_models(self, **kw) if self.api_key else []
        for m in models:
            m.provider = self.name
        return models or await super().list_models(**kw)

    def curated(self) -> list[str]:
        return [FREE_MODEL]


class FreeProvider(OpenAICompatibleProvider):
    """The built-in free model: Qwen3.8 27B on Heabsy, through the Compiwer relay."""
    name = "free"

    def __init__(self, **kw: Any):
        super().__init__(base_url=free_relay_url() + "/v1", api_key="")

    def _headers(self) -> dict[str, str]:
        return {**super()._headers(), "X-Mtrini-Install": install_id()}

    async def chat(self, model: str, messages: list[ChatMessage], tools: list[dict] | None = None, **kw: Any) -> dict[str, Any]:
        try:
            return await super().chat(FREE_MODEL, messages, tools, **kw)
        except httpx.HTTPStatusError as e:
            raise FreeModelError(_relay_message(e.response)) from None

    async def stream(self, model: str, messages: list[ChatMessage], tools: list[dict] | None = None, **kw: Any):
        try:
            async for ev in super().stream(FREE_MODEL, messages, tools, **kw):
                yield ev
        except httpx.HTTPStatusError as e:
            raise FreeModelError(_relay_message(e.response)) from None

    async def list_models(self, **kw: Any) -> list[ModelInfo]:
        return [ModelInfo(id=FREE_MODEL, label=f"Qwen3.8 27B ({FREE_LABEL})", provider=self.name,
                          contextLength=32768, capabilities={"text": True, "tools": True, "streaming": True})]


def _relay_message(r: httpx.Response) -> str:
    try:
        r.read()
        msg = r.json().get("error", {}).get("message", "")
    except Exception:
        msg = ""
    if r.status_code == 429:
        return msg or (f"You've used today's free model allowance. It resets at midnight UTC. "
                       f"For more, add your own Heabsy key: {HEABSY_UPGRADE_URL}")
    return f"Free model unavailable ({r.status_code}). {msg}".strip()
