"""OpenAI-compatible chat provider (local servers, vLLM, llama-server, custom)."""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from . import ChatMessage, ModelInfo

# Thinking effort: UI levels -> provider-native reasoning controls.
# Providers without a native control ignore effort (never inject unknown fields).
EFFORT_TO_OPENAI = {"low": "low", "medium": "medium", "high": "high", "xhigh": "xhigh", "max": "xhigh"}
EFFORT_TO_ANTHROPIC_BUDGET = {"low": 4000, "medium": 8000, "high": 16000, "xhigh": 24000, "max": 32000}
EFFORT_TO_GEMINI_BUDGET = {"low": 1024, "medium": 4096, "high": 8192, "xhigh": 16384, "max": 24576}


def normalize_effort(effort: str | None) -> str:
    e = (effort or "off").lower()
    return e if e in ("off", "low", "medium", "high", "xhigh", "max") else "off"


class OpenAICompatibleProvider:
    name = "openai-compatible"

    def __init__(self, base_url: str = "http://localhost:8000/v1", api_key: str = "", timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def reasoning_value(self, effort: str) -> str | None:
        return None  # only providers with a native control override this

    def _payload(self, model: str, messages: list[ChatMessage], tools: list[dict] | None, stream: bool, effort: str = "off") -> dict:
        msgs = []
        for m in messages:
            d: dict[str, Any] = {"role": m.role, "content": m.content}
            if m.tool_calls:
                d["tool_calls"] = [{"id": t.get("id"), "type": "function",
                                    "function": {"name": t.get("name"), "arguments": t.get("arguments", "{}")}}
                                   for t in m.tool_calls]
            if m.tool_call_id:
                d["tool_call_id"] = m.tool_call_id
            msgs.append(d)
        p: dict[str, Any] = {"model": model, "messages": msgs, "stream": stream}
        if tools:
            p["tools"] = [{"type": "function", "function": t["function"] if "function" in t else t} for t in tools]
        rv = self.reasoning_value(normalize_effort(effort))
        if rv:
            p["reasoning_effort"] = rv
        return p

    async def chat(self, model: str, messages: list[ChatMessage], tools: list[dict] | None = None, **kw: Any) -> dict[str, Any]:
        effort = normalize_effort(kw.get("effort"))
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.post(f"{self.base_url}/chat/completions", headers=self._headers(),
                             json=self._payload(model, messages, tools, False, effort))
            r.raise_for_status()
            data = r.json()
        choice = data["choices"][0]["message"]
        calls = []
        for tc in choice.get("tool_calls") or []:
            fn = tc.get("function", {})
            calls.append({"id": tc.get("id"), "name": fn.get("name"), "arguments": fn.get("arguments", "{}")})
        return {"content": choice.get("content") or "", "tool_calls": calls, "raw": data}

    async def stream(self, model: str, messages: list[ChatMessage], tools: list[dict] | None = None, **kw: Any) -> AsyncIterator[dict[str, Any]]:
        import json as _json

        effort = normalize_effort(kw.get("effort"))
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            async with c.stream("POST", f"{self.base_url}/chat/completions", headers=self._headers(),
                                json=self._payload(model, messages, tools, True, effort)) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        data = _json.loads(payload)
                        delta = data["choices"][0].get("delta", {})
                        if delta.get("content"):
                            yield {"delta": delta["content"]}
                    except Exception:
                        continue
        yield {"done": True}

    async def list_models(self, **kw: Any) -> list[ModelInfo]:
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{self.base_url}/models", headers=self._headers())
                r.raise_for_status()
                data = r.json().get("data", [])
            return [ModelInfo(id=m.get("id", "?"), label=m.get("id", "?"), provider="local",
                              capabilities={"text": True, "tools": True, "streaming": True}) for m in data]
        except Exception:
            return []

    def supports_tools(self) -> bool:
        return True

    def supports_vision(self) -> bool:
        return False

    def supports_streaming(self) -> bool:
        return True
