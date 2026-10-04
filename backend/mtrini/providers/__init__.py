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
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None


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
