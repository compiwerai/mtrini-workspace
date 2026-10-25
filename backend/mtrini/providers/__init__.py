"""Unified provider interface. The agent only speaks this interface."""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ModelInfo:
    id: str
    label: str
    provider: str
    capabilities: dict[str, Any] = field(default_factory=dict)
    contextLength: int = 32768
    status: str = "ready"


@dataclass
class ChatMessage:
    role: str  # system | user | assistant | tool
    content: str
    tool_calls: list[dict[str, Any]] | None = None  # assistant: [{id, name, arguments}]
    tool_call_id: str | None = None  # tool: id of the call this answers
    name: str | None = None  # tool: name of the tool that ran
    images: list[dict[str, str]] | None = None  # user: [{mime, data(base64)}]
    raw: Any = None  # assistant: provider-native content (Anthropic blocks, Gemini parts)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ChatMessage:
        return cls(role=d.get("role", "user"), content=str(d.get("content") or ""),
                   tool_calls=d.get("tool_calls"), tool_call_id=d.get("tool_call_id"),
                   name=d.get("name"), images=d.get("images"), raw=d.get("raw"))


class ModelProvider(Protocol):
    name: str

    async def chat(self, model: str, messages: list[ChatMessage], tools: list[dict] | None = None, **kw: Any) -> dict[str, Any]:
        ...

    async def stream(self, model: str, messages: list[ChatMessage], tools: list[dict] | None = None, **kw: Any) -> AsyncIterator[dict[str, Any]]:
        ...

    async def list_models(self, **kw: Any) -> list[ModelInfo]:
        ...

    def supports_tools(self) -> bool: ...
    def supports_vision(self) -> bool: ...
    def supports_streaming(self) -> bool: ...


OPENAI_TOOL_SCHEMA_HINT = "OpenAI-compatible function tools"
