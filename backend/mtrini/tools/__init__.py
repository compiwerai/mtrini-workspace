"""Unified tool interface: name, description, schema, permission, execute."""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ToolResult:
    ok: bool
    output: Any
    error: str | None = None
    durationMs: int = 0


@dataclass
class Tool:
    name: str
    description: str
    permission: str  # read | write | execute | network | destructive
    schema: dict[str, Any] = field(default_factory=dict)
    handler: Callable[[Path, dict[str, Any]], Any] | None = None

    def to_openai(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description,
                "parameters": self.schema}

    async def run(self, root: Path, args: dict[str, Any]) -> ToolResult:
        t0 = time.time()
        try:
            assert self.handler is not None
            out = self.handler(root, args)
            if hasattr(out, "__await__"):
                out = await out  # type: ignore
            return ToolResult(ok=True, output=out, durationMs=int((time.time() - t0) * 1000))
        except Exception as e:
            return ToolResult(ok=False, output=None, error=str(e),
                              durationMs=int((time.time() - t0) * 1000))
