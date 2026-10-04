"""Gemini + Anthropic providers via official REST endpoints (httpx, no extra SDK)."""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from . import ChatMessage, ModelInfo


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    def _to_gemini(self, messages: list[ChatMessage]) -> tuple[str | None, list[dict]]:
        system = None
        contents = []
        for m in messages:
            if m.role == "system":
                system = (system + "\n" if system else "") + m.content
                continue
            role = "model" if m.role == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": m.content}]})
        return system, contents

    async def chat(self, model: str, messages: list[ChatMessage], tools: list[dict] | None = None, **kw: Any) -> dict[str, Any]:
        from .openai_compat import EFFORT_TO_GEMINI_BUDGET, normalize_effort

        system, contents = self._to_gemini(messages)
        body: dict[str, Any] = {"contents": contents}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        budget = EFFORT_TO_GEMINI_BUDGET.get(normalize_effort(kw.get("effort")))
        if budget:
            body["generationConfig"] = {"thinkingConfig": {"thinkingBudget": budget}}
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                params={"key": self.api_key}, json=body)
            r.raise_for_status()
            data = r.json()
        text = ""
        try:
            text = "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        except Exception:
            text = ""
        return {"content": text, "tool_calls": [], "raw": data}

    async def stream(self, model: str, messages: list[ChatMessage], tools: list[dict] | None = None, **kw: Any) -> AsyncIterator[dict[str, Any]]:
        res = await self.chat(model, messages, tools, **kw)
        yield {"delta": res["content"]}
        yield {"done": True}

    async def list_models(self, **kw: Any) -> list[ModelInfo]:
        return [ModelInfo(id=m, label=m, provider="gemini",
                          capabilities={"text": True, "vision": True, "streaming": True})
                for m in ("gemini-2.0-flash", "gemini-1.5-pro")]

    def supports_tools(self) -> bool:
        return True

    def supports_vision(self) -> bool:
        return True

    def supports_streaming(self) -> bool:
        return True


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    async def chat(self, model: str, messages: list[ChatMessage], tools: list[dict] | None = None, **kw: Any) -> dict[str, Any]:
        from .openai_compat import EFFORT_TO_ANTHROPIC_BUDGET, normalize_effort

        system = "\n".join(m.content for m in messages if m.role == "system")
        msgs = [{"role": ("assistant" if m.role == "assistant" else "user"), "content": m.content}
                for m in messages if m.role in ("user", "assistant")]
        body: dict[str, Any] = {"model": model, "max_tokens": kw.get("max_tokens", 4096), "messages": msgs}
        budget = EFFORT_TO_ANTHROPIC_BUDGET.get(normalize_effort(kw.get("effort")))
        if budget:
            body["thinking"] = {"type": "enabled", "budget_tokens": budget}
            body["max_tokens"] = max(body["max_tokens"], budget + 1024)
        if system:
            body["system"] = system
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post("https://api.anthropic.com/v1/messages", headers={
                "x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                "content-type": "application/json"}, json=body)
            r.raise_for_status()
            data = r.json()
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        return {"content": text, "tool_calls": [], "raw": data}

    async def stream(self, model: str, messages: list[ChatMessage], tools: list[dict] | None = None, **kw: Any) -> AsyncIterator[dict[str, Any]]:
        res = await self.chat(model, messages, tools, **kw)
        yield {"delta": res["content"]}
        yield {"done": True}

    async def list_models(self, **kw: Any) -> list[ModelInfo]:
        return [ModelInfo(id=m, label=m, provider="anthropic",
                          capabilities={"text": True, "tools": True, "streaming": True})
                for m in ("claude-sonnet-4-5", "claude-haiku-4-5")]

    def supports_tools(self) -> bool:
        return True

    def supports_vision(self) -> bool:
        return True

    def supports_streaming(self) -> bool:
        return True
