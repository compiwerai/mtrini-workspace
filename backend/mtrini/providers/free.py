"""Heabsy (bring your own key) and the built-in free models, both through Compiwer relays.

- "free": Qwen3.8 27B, sponsored by Heabsy (relay mtrini-free).
- "compiwer-free": Compiwer Free, Grok 4.7 from 100miliongrok (relay compiwer-free).
- "compiwer-deepseek": Compiwer Free, DeepSeek V4.1 Flash from 100milionseek (relay compiwer-deepseek).

Neither needs a key: requests go to a Compiwer relay, which holds the upstream key(s) and
applies daily limits. The app sends an anonymous install id (a random number made on first
use, stored in ~/.mtrini/install-id) so the relay can count each install's daily usage.
Nothing else about the user or their project is added.
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
FREE_LABEL = "Free · Heabsy"


COMPIWER_RELAY_URL = "https://compiwer-free.roblox-event-bot-worker.workers.dev"
COMPIWER_MODEL = "grok-4.7"
COMPIWER_LABEL = "Compiwer Free"

COMPIWER_DEEPSEEK_RELAY_URL = "https://compiwer-deepseek.roblox-event-bot-worker.workers.dev"
COMPIWER_DEEPSEEK_MODEL = "deepseek-v4.1-flash-free"
COMPIWER_DEEPSEEK_LABEL = "Compiwer Free · DeepSeek"


def free_relay_url() -> str:
    return (os.environ.get("MTRINI_FREE_URL") or FREE_RELAY_URL).rstrip("/")


def compiwer_relay_url() -> str:
    return (os.environ.get("MTRINI_COMPIWER_FREE_URL") or COMPIWER_RELAY_URL).rstrip("/")


def compiwer_deepseek_relay_url() -> str:
    return (os.environ.get("MTRINI_COMPIWER_DEEPSEEK_URL") or COMPIWER_DEEPSEEK_RELAY_URL).rstrip("/")


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
    MODEL, MODEL_LABEL, CONTEXT = FREE_MODEL, "Qwen3.8 27B", 32768
    UPGRADE = f" For more, add your own Heabsy key: {HEABSY_UPGRADE_URL}"

    def __init__(self, **kw: Any):
        super().__init__(base_url=self.relay() + "/v1", api_key="")

    @staticmethod
    def relay() -> str:
        return free_relay_url()

    def _headers(self) -> dict[str, str]:
        return {**super()._headers(), "X-Mtrini-Install": install_id()}

    async def chat(self, model: str, messages: list[ChatMessage], tools: list[dict] | None = None, **kw: Any) -> dict[str, Any]:
        try:
            return await super().chat(self.MODEL, messages, tools, **kw)
        except httpx.HTTPStatusError as e:
            raise FreeModelError(_relay_message(e.response, self.UPGRADE)) from None

    async def stream(self, model: str, messages: list[ChatMessage], tools: list[dict] | None = None, **kw: Any):
        try:
            async for ev in super().stream(self.MODEL, messages, tools, **kw):
                yield ev
        except httpx.HTTPStatusError as e:
            raise FreeModelError(_relay_message(e.response, self.UPGRADE)) from None

    async def list_models(self, **kw: Any) -> list[ModelInfo]:
        return [ModelInfo(id=self.MODEL, label=self.MODEL_LABEL, provider=self.name,
                          contextLength=self.CONTEXT, capabilities={"text": True, "tools": True, "streaming": True})]


class CompiwerFreeProvider(FreeProvider):
    """Compiwer Free: Grok 4.7, free from Compiwer AI through its own relay (upstream: 100miliongrok)."""
    name = "compiwer-free"
    MODEL, MODEL_LABEL, CONTEXT = COMPIWER_MODEL, "Grok 4.7", 500000
    UPGRADE = ""

    @staticmethod
    def relay() -> str:
        return compiwer_relay_url()


class CompiwerDeepSeekProvider(FreeProvider):
    """Compiwer Free: DeepSeek V4.1 Flash, through its own relay (upstream: 100milionseek)."""
    name = "compiwer-deepseek"
    MODEL, MODEL_LABEL, CONTEXT = COMPIWER_DEEPSEEK_MODEL, "DeepSeek V4.1 Flash", 131072
    UPGRADE = ""

    @staticmethod
    def relay() -> str:
        return compiwer_deepseek_relay_url()


def _relay_message(r: httpx.Response, upgrade: str = "") -> str:
    try:
        r.read()
        msg = r.json().get("error", {}).get("message", "")
    except Exception:
        msg = ""
    if r.status_code == 429:
        return msg or ("You've used today's free model allowance. It resets at midnight UTC." + upgrade)
    return f"Free model unavailable ({r.status_code}). {msg}".strip()
