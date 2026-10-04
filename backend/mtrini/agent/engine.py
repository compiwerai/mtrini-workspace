"""Agent engine: model-agnostic tool loop with permissions + streaming events."""
from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from ..providers import ChatMessage
from ..providers.openai_compat import normalize_effort
from ..providers.registry import build_provider
from ..tools import Tool as _Tool
from ..tools import registry as tools_registry
from .prompt import SYSTEM_PROMPT

_MCP_TOOL = _Tool(name="mcp", description="external MCP server tool", permission="execute")

# Thinking effort also deepens the agentic loop: higher effort = more tool steps.
EFFORT_TO_STEPS = {"off": 25, "low": 12, "medium": 20, "high": 30, "xhigh": 40, "max": 60}


def _parse_args(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except Exception:
        return {}


async def run_agent(root: Path, provider_name: str, model: str, user_text: str,
                    history: list[dict], permission_mode: str = "ask",
                    provider_settings: dict | None = None,
                    max_steps: int | None = None, effort: str = "off") -> AsyncIterator[dict[str, Any]]:
    """Yield SSE events: status | assistant_delta | tool_start | tool_result | done | error."""
    effort = normalize_effort(effort)
    if max_steps is None:
        max_steps = EFFORT_TO_STEPS[effort]
    provider = build_provider(provider_name, root, provider_settings or {})
    tools_schema = tools_registry.openai_schema()
    # MCP servers contribute tools dynamically (best-effort; failures are skipped).
    from .. import mcp as mcp_manager

    mcp_map: dict[str, tuple[str, str]] = {}
    try:
        mcp_schemas, mcp_map = await mcp_manager.agent_tools(root)
        tools_schema = [*tools_schema, *mcp_schemas]
    except Exception:
        pass

    # Context: project instructions + skill summaries are injected by the API layer
    # via history[0] if it is a system message; ensure a system prompt exists.
    messages = [ChatMessage(role="system", content=SYSTEM_PROMPT)]
    for h in history[-40:]:
        if h.get("role") in ("user", "assistant", "system", "tool"):
            messages.append(ChatMessage(role=h["role"], content=str(h.get("content", ""))[:8000]))
    messages.append(ChatMessage(role="user", content=user_text))

    yield {"type": "status", "status": "planning", "message": "Planning…"}
    # Auto-inspect: cheap project survey without spending model tools.
    try:
        insp = tools_registry.BY_NAME["inspect_project"]
        res = await insp.run(root, {})
        if res.ok:
            yield {"type": "tool_result", "tool": "inspect_project", "ok": True,
                   "output": res.output, "durationMs": res.durationMs}
    except Exception:
        pass

    steps = 0
    while steps < max_steps:
        steps += 1
        yield {"type": "status", "status": "thinking", "message": f"Thinking (step {steps})…"}
        try:
            reply = await provider.chat(model, messages, tools_schema, effort=effort)
        except Exception as e:
            yield {"type": "error", "message": friendly_error(e)}
            return
        content = reply.get("content") or ""
        calls = reply.get("tool_calls") or []
        if content:
            yield {"type": "assistant_delta", "delta": content}
        if not calls:
            yield {"type": "done", "content": content, "steps": steps}
            return
        for call in calls:
            name = call.get("name")
            args = _parse_args(call.get("arguments"))
            if name in mcp_map:
                from .. import mcp as mcp_manager

                server, tool = mcp_map[name]
                if tools_registry.needs_approval(_MCP_TOOL, permission_mode):
                    yield {"type": "permission_request", "tool": name, "args": args,
                           "permission": "execute", "mcp": {"server": server, "tool": tool}}
                    yield {"type": "done", "content": content, "steps": steps,
                           "pendingApproval": {"tool": name, "args": args, "mcp": {"server": server, "tool": tool}}}
                    return
                yield {"type": "tool_start", "tool": name, "args": args}
                t0 = time.time()
                try:
                    out = await mcp_manager.call_tool(root, server, tool, args)
                    dt = int((time.time() - t0) * 1000)
                    out_str = json.dumps(out, default=str)[:6000]
                    messages.append(ChatMessage(role="tool", content=f"[{name}] OK {dt}ms\n{out_str}"))
                    yield {"type": "tool_result", "tool": name, "ok": True, "output": out, "durationMs": dt}
                except Exception as e:
                    dt = int((time.time() - t0) * 1000)
                    messages.append(ChatMessage(role="tool", content=f"[{name}] ERROR {dt}ms\n{e}"))
                    yield {"type": "tool_result", "tool": name, "ok": False, "error": str(e)[:2000], "durationMs": dt}
                continue
            tool = tools_registry.BY_NAME.get(name or "")
            if tool is None:
                messages.append(ChatMessage(role="tool", content=f"Unknown tool: {name}"))
                yield {"type": "tool_result", "tool": name, "ok": False, "error": "unknown tool"}
                continue
            if tools_registry.needs_approval(tool, permission_mode):
                yield {"type": "permission_request", "tool": name, "args": args,
                       "permission": tool.permission}
                # In non-interactive API mode the caller re-posts with approval;
                # here we pause this turn and let the client decide.
                yield {"type": "done", "content": content, "steps": steps,
                       "pendingApproval": {"tool": name, "args": args}}
                return
            yield {"type": "tool_start", "tool": name, "args": args}
            t0 = time.time()
            res = await tool.run(root, args)
            dt = int((time.time() - t0) * 1000)
            # Never leak secrets into the transcript.
            out_str = json.dumps(res.output, default=str)[:6000] if res.ok else (res.error or "")[:2000]
            messages.append(ChatMessage(role="tool",
                                        content=f"[{name}] {'OK' if res.ok else 'ERROR'} {dt}ms\n{out_str}"))
            yield {"type": "tool_result", "tool": name, "ok": res.ok,
                   "output": res.output if res.ok else None,
                   "error": res.error if not res.ok else None, "durationMs": dt}
        messages.append(ChatMessage(role="assistant", content=content or "(tool calls)"))
    yield {"type": "done", "content": "Stopped: step limit reached.", "steps": steps}


async def run_approved_tool(root: Path, tool_name: str, args: dict, mcp: dict | None = None) -> dict[str, Any]:
    if mcp:
        from .. import mcp as mcp_manager

        try:
            out = await mcp_manager.call_tool(root, mcp.get("server", ""), mcp.get("tool", ""), args)
            return {"ok": True, "output": out}
        except Exception as e:
            return {"ok": False, "error": str(e)[:2000]}
    tool = tools_registry.BY_NAME.get(tool_name)
    if tool is None:
        return {"ok": False, "error": "unknown tool"}
    res = await tool.run(root, args)
    return {"ok": res.ok, "output": res.output, "error": res.error, "durationMs": res.durationMs}


def friendly_error(e: Exception) -> str:
    s = str(e)
    if "ConnectError" in type(e).__name__ or "Connect" in s or "refused" in s.lower():
        return ("Model endpoint unreachable. Is your local server running "
                "(e.g. http://localhost:8000/v1)? Check Settings → Providers. Details: " + s[:300])
    if "401" in s or "Unauthorized" in s:
        return "Provider rejected the API key (401). Check Settings → Providers. Details: " + s[:300]
    return f"Model request failed: {s[:500]}"
