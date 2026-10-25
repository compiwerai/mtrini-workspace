"""Gemini (REST via httpx) and Anthropic (official SDK) providers, with tool calling and images."""
from __future__ import annotations

import json
import re
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx

from . import ChatMessage, ModelInfo


def _fn(tool: dict) -> dict:
    """OpenAI-style tool entry -> {name, description, parameters}."""
    return tool["function"] if "function" in tool else tool


def _args(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}


def native(m: ChatMessage, provider: str) -> list | None:
    """Provider-native assistant content, only if it came from this provider."""
    raw = m.raw
    if isinstance(raw, dict) and raw.get("provider") == provider and isinstance(raw.get("content"), list):
        return raw["content"]
    return None


def _merge_same_role(items: list[dict], key: str) -> list[dict]:
    """Both APIs want alternating turns: fold consecutive same-role entries together."""
    out: list[dict] = []
    for it in items:
        if out and out[-1]["role"] == it["role"]:
            out[-1][key] = out[-1][key] + it[key]
        else:
            out.append(it)
    return out


# ---------------------------------------------------------------- Gemini

_GEMINI_SCHEMA_KEYS = {"type", "description", "properties", "required", "items", "enum", "format", "nullable"}


def _gemini_schema(s: Any) -> Any:
    """Gemini accepts an OpenAPI subset: drop keys it rejects (additionalProperties, $schema, ...)."""
    if not isinstance(s, dict):
        return s
    out = {}
    for k, v in s.items():
        if k not in _GEMINI_SCHEMA_KEYS:
            continue
        if k == "properties" and isinstance(v, dict):
            out[k] = {pk: _gemini_schema(pv) for pk, pv in v.items()}
        elif k == "items":
            out[k] = _gemini_schema(v)
        else:
            out[k] = v
    if out.get("type") == "object" and not out.get("properties"):
        out.pop("required", None)
    return out


class GeminiProvider:
    name = "gemini"
    BASE = "https://generativelanguage.googleapis.com/v1beta"
    FALLBACK_MODELS = ("gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-lite")

    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    def _to_gemini(self, messages: list[ChatMessage]) -> tuple[str | None, list[dict]]:
        system = None
        contents: list[dict] = []
        for m in messages:
            if m.role == "system":
                system = (system + "\n\n" if system else "") + m.content
            elif m.role == "assistant":
                parts = list(native(m, "gemini") or [])  # replay native parts: keeps thought signatures
                if not parts:
                    parts = [{"text": m.content}] if m.content else []
                    parts += [{"functionCall": {"name": c["name"], "args": _args(c.get("arguments"))}}
                              for c in m.tool_calls or []]
                if parts:
                    contents.append({"role": "model", "parts": parts})
            elif m.role == "tool":
                contents.append({"role": "user", "parts": [{"functionResponse": {
                    "name": m.name or "tool", "response": {"content": m.content}}}]})
            else:
                parts = [{"text": m.content or " "}]
                parts += [{"inlineData": {"mimeType": im["mime"], "data": im["data"]}} for im in m.images or []]
                contents.append({"role": "user", "parts": parts})
        return system, _merge_same_role(contents, "parts")

    async def chat(self, model: str, messages: list[ChatMessage], tools: list[dict] | None = None, **kw: Any) -> dict[str, Any]:
        from .openai_compat import EFFORT_TO_GEMINI_BUDGET, normalize_effort

        system, contents = self._to_gemini(messages)
        body: dict[str, Any] = {"contents": contents}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            body["tools"] = [{"functionDeclarations": [
                {"name": _fn(t)["name"], "description": _fn(t).get("description", ""),
                 **({"parameters": _gemini_schema(_fn(t)["parameters"])}
                    if _fn(t).get("parameters", {}).get("properties") else {})}
                for t in tools]}]
        budget = EFFORT_TO_GEMINI_BUDGET.get(normalize_effort(kw.get("effort")))
        if budget:
            body["generationConfig"] = {"thinkingConfig": {"thinkingBudget": budget}}
        async with httpx.AsyncClient(timeout=180) as c:
            r = await c.post(f"{self.BASE}/models/{model}:generateContent",
                             headers={"x-goog-api-key": self.api_key}, json=body)
            if r.status_code >= 400:
                raise RuntimeError(f"Gemini {r.status_code}: {r.text[:500]}")
            data = r.json()
        try:
            parts = data["candidates"][0]["content"].get("parts", [])
        except (KeyError, IndexError):
            reason = (data.get("promptFeedback") or {}).get("blockReason") or "no candidates"
            return {"content": f"(Gemini returned no answer: {reason})", "tool_calls": [], "raw": data}
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        calls = [{"id": "call_" + uuid.uuid4().hex[:10], "name": p["functionCall"]["name"],
                  "arguments": json.dumps(p["functionCall"].get("args") or {})}
                 for p in parts if "functionCall" in p]
        return {"content": text, "tool_calls": calls, "raw": data,
                "message_raw": {"provider": "gemini", "content": parts}}

    async def stream(self, model: str, messages: list[ChatMessage], tools: list[dict] | None = None, **kw: Any) -> AsyncIterator[dict[str, Any]]:
        res = await self.chat(model, messages, tools, **kw)
        yield {"delta": res["content"]}
        yield {"done": True}

    async def list_models(self, **kw: Any) -> list[ModelInfo]:
        ids: list[str] = []
        if self.api_key:
            try:
                async with httpx.AsyncClient(timeout=10) as c:
                    r = await c.get(f"{self.BASE}/models", headers={"x-goog-api-key": self.api_key},
                                    params={"pageSize": 200})
                    r.raise_for_status()
                for m in r.json().get("models", []):
                    if "generateContent" in m.get("supportedGenerationMethods", []) and "gemini" in m.get("name", ""):
                        ids.append(m["name"].removeprefix("models/"))
            except Exception:
                ids = []
        return [ModelInfo(id=m, label=m, provider="gemini", contextLength=1_000_000,
                          capabilities={"text": True, "vision": True, "tools": True, "streaming": True})
                for m in (ids or self.FALLBACK_MODELS)]

    def supports_tools(self) -> bool:
        return True

    def supports_vision(self) -> bool:
        return True

    def supports_streaming(self) -> bool:
        return True


# ---------------------------------------------------------------- Anthropic

# Models before Claude 4.6 take a thinking token budget; newer ones take adaptive
# thinking + output_config.effort (budget_tokens returns 400 on them).
_LEGACY_THINKING = re.compile(r"claude-3|claude-(opus|sonnet|haiku)-4-[0-5](\b|-)|claude-(opus|sonnet)-4-\d{8}")
_THINKING_TYPES = {"thinking", "redacted_thinking"}


def strip_thinking(messages: list[ChatMessage]) -> None:
    """Drop thinking blocks from replayed history (needed after history is compacted or edited)."""
    for m in messages:
        blocks = native(m, "anthropic") if m.role == "assistant" else None
        if blocks and any(b.get("type") in _THINKING_TYPES for b in blocks):
            kept = [b for b in blocks if b.get("type") not in _THINKING_TYPES]
            m.raw = {"provider": "anthropic", "content": kept} if kept else None


class AnthropicProvider:
    name = "anthropic"
    MODELS = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1")

    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    def _client(self):
        import anthropic

        return anthropic.AsyncAnthropic(api_key=self.api_key or None, max_retries=2)

    @staticmethod
    def _to_anthropic(messages: list[ChatMessage]) -> tuple[str, list[dict]]:
        system = "\n\n".join(m.content for m in messages if m.role == "system")
        out: list[dict] = []
        for m in messages:
            if m.role == "system":
                continue
            if m.role == "assistant":
                blocks = list(native(m, "anthropic") or [])  # replay unchanged: thinking blocks must not be edited
                if not blocks:
                    blocks = [{"type": "text", "text": m.content}] if m.content.strip() else []
                    blocks += [{"type": "tool_use", "id": c["id"], "name": c["name"], "input": _args(c.get("arguments"))}
                               for c in m.tool_calls or []]
                if blocks:
                    out.append({"role": "assistant", "content": blocks})
            elif m.role == "tool":
                out.append({"role": "user", "content": [{
                    "type": "tool_result", "tool_use_id": m.tool_call_id or "",
                    "content": m.content or "(no output)",
                    **({"is_error": True} if m.content.startswith("ERROR") else {})}]})
            else:
                blocks = [{"type": "image", "source": {"type": "base64", "media_type": im["mime"], "data": im["data"]}}
                          for im in m.images or []]
                blocks.append({"type": "text", "text": m.content or " "})
                out.append({"role": "user", "content": blocks})
        return system, _merge_same_role(out, "content")

    def _params(self, model: str, messages: list[ChatMessage], tools: list[dict] | None, effort: str) -> dict:
        from .openai_compat import EFFORT_TO_ANTHROPIC_BUDGET

        system, msgs = self._to_anthropic(messages)
        params: dict[str, Any] = {"model": model, "max_tokens": 32000, "messages": msgs}
        if system:
            params["system"] = system
        if tools:
            params["tools"] = [{"name": _fn(t)["name"], "description": _fn(t).get("description", ""),
                                "input_schema": _fn(t).get("parameters") or {"type": "object", "properties": {}}}
                               for t in tools]
        if effort != "off":
            if _LEGACY_THINKING.search(model):
                budget = EFFORT_TO_ANTHROPIC_BUDGET[effort]
                params["thinking"] = {"type": "enabled", "budget_tokens": budget}
                params["max_tokens"] = max(16000, budget + 4096)
            else:
                params["thinking"] = {"type": "adaptive"}
                params["output_config"] = {"effort": effort}
                if effort in ("xhigh", "max"):
                    params["max_tokens"] = 64000
        elif _LEGACY_THINKING.search(model):
            params["max_tokens"] = 16000
        return params

    async def chat(self, model: str, messages: list[ChatMessage], tools: list[dict] | None = None, **kw: Any) -> dict[str, Any]:
        import anthropic

        from .openai_compat import normalize_effort

        effort = normalize_effort(kw.get("effort"))
        client = self._client()
        try:
            try:
                msg = await self._send(client, self._params(model, messages, tools, effort))
            except anthropic.BadRequestError as e:
                # History was changed under a thinking block (e.g. after compaction): strip and retry once.
                if "signature" not in str(e) and "thinking" not in str(e):
                    raise
                strip_thinking(messages)
                msg = await self._send(client, self._params(model, messages, tools, effort))
        finally:
            await client.close()

        blocks = [b.model_dump(exclude_none=True) for b in msg.content]
        if msg.stop_reason == "refusal":
            return {"content": "Claude declined this request.", "tool_calls": [], "raw": None,
                    "stop_reason": "refusal"}
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        calls = [{"id": b["id"], "name": b["name"], "arguments": json.dumps(b.get("input") or {})}
                 for b in blocks if b.get("type") == "tool_use"]
        return {"content": text, "tool_calls": calls, "raw": None,
                "message_raw": {"provider": "anthropic", "content": blocks},
                "stop_reason": msg.stop_reason,
                "usage": {"input": msg.usage.input_tokens, "output": msg.usage.output_tokens}}

    @staticmethod
    async def _send(client, params: dict):
        # Stream under the hood: large max_tokens on a plain request can hit HTTP timeouts.
        async with client.messages.stream(**params) as s:
            return await s.get_final_message()

    async def stream(self, model: str, messages: list[ChatMessage], tools: list[dict] | None = None, **kw: Any) -> AsyncIterator[dict[str, Any]]:
        res = await self.chat(model, messages, tools, **kw)
        yield {"delta": res["content"]}
        yield {"done": True}

    async def list_models(self, **kw: Any) -> list[ModelInfo]:
        return [ModelInfo(id=m, label=m, provider="anthropic", contextLength=1_000_000,
                          capabilities={"text": True, "vision": True, "tools": True, "streaming": True})
                for m in self.MODELS]

    def supports_tools(self) -> bool:
        return True

    def supports_vision(self) -> bool:
        return True

    def supports_streaming(self) -> bool:
        return True
