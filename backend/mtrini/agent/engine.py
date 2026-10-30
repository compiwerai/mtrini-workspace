"""Agent engine: model-agnostic tool loop with permissions, sessions and streaming events.

Events: status | turn | assistant_delta | tool_start | tool_result | permission_request | plan |
todos | mode | compacted | subagent | hooks_untrusted | done | error.

A turn that stops for an approval (a tool or a plan) saves its place in the
session; the client answers with `resume` and the same loop carries on.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..providers import ChatMessage
from ..providers.openai_compat import normalize_effort
from ..providers.registry import build_provider
from ..tools import Tool as _Tool
from ..tools import registry as tools_registry
from . import checkpoints, compact, hooks, permissions
from . import session as session_mod
from .prompt import SYSTEM_PROMPT

_MCP_TOOL = _Tool(name="mcp", description="external MCP server tool", permission="execute")

# Thinking effort also deepens the agentic loop: higher effort = more tool steps.
EFFORT_TO_STEPS = {"off": 25, "low": 12, "medium": 20, "high": 30, "xhigh": 40, "max": 60}
RESULT_CHARS = 16000
SUBAGENT_STEPS = 20

# Tools the engine handles itself (not in the tool registry, so /api/tools/execute can't reach them).
BUILTIN = [
    _Tool("todo_write", "Create or update your task list for this request. Send the whole list each time. "
          "Use it for work with 3+ steps; keep exactly one item in_progress.", "read",
          {"type": "object", "properties": {"todos": {"type": "array", "items": {
              "type": "object", "properties": {
                  "content": {"type": "string"},
                  "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}},
              "required": ["content", "status"]}}}, "required": ["todos"]}),
    _Tool("exit_plan_mode", "In plan mode: present your finished plan to the user for approval. "
          "Only call this after researching with read-only tools.", "read",
          {"type": "object", "properties": {"plan": {"type": "string", "description": "The plan, in Markdown"}},
           "required": ["plan"]}),
    _Tool("task", "Start a subagent for a self-contained research or search task; it works in its own "
          "context and returns a report. It can read and search, and only changes files in auto mode. "
          "Optionally name one of the project's agents (.mtrini/agents/<name>.md).", "read",
          {"type": "object", "properties": {
              "description": {"type": "string", "description": "3-6 word summary"},
              "prompt": {"type": "string", "description": "Full instructions; the subagent sees nothing else"},
              "agent": {"type": "string"}}, "required": ["description", "prompt"]}),
]
BUILTIN_NAMES = {t.name for t in BUILTIN}

PLAN_NOTE = ("[Plan mode is on: research with read-only tools only, do not change anything. "
             "When your plan is ready, call exit_plan_mode with it.]")


def _parse_args(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        v = json.loads(raw or "{}")
        return v if isinstance(v, dict) else {}
    except (TypeError, ValueError):
        return {}


def _result_text(ok: bool, output: Any, error: str | None) -> str:
    if not ok:
        return "ERROR: " + (error or "failed")[:4000]
    s = output if isinstance(output, str) else json.dumps(output, default=str, ensure_ascii=False)
    return s if len(s) <= RESULT_CHARS else s[:RESULT_CHARS] + f"\n…(truncated, {len(s)} chars total)"


def _ui_output(output: Any) -> Any:
    """Trim tool output for the event stream and thread file."""
    s = json.dumps(output, default=str, ensure_ascii=False)
    return output if len(s) <= 20000 else s[:20000] + "…"


@dataclass
class _Run:
    root: Path
    provider: Any
    provider_name: str
    provider_settings: dict
    model: str
    effort: str
    s: session_mod.Session
    tools_schema: list[dict]
    mcp_map: dict[str, tuple[str, str]]
    thread_id: str | None
    max_steps: int
    depth: int = 0
    steps: int = 0
    paused: bool = False
    final: str = ""
    turn_texts: list[str] = field(default_factory=list)

    @property
    def interactive(self) -> bool:
        return self.depth == 0


def _log(run: _Run, role: str, content: str = "", **extra: Any) -> None:
    """Mirror the turn into the thread file the UI shows (top-level runs only)."""
    if not run.thread_id or run.depth:
        return
    from .. import threads

    try:
        threads.append_message(run.root, run.thread_id, role, content, **extra)
    except (FileNotFoundError, ValueError):
        pass


def _load_agent_def(root: Path, name: str) -> str:
    safe = "".join(c for c in name if c.isalnum() or c in "-_")
    p = root / ".mtrini" / "agents" / f"{safe}.md"
    try:
        text = p.read_text(encoding="utf-8")[:8000]
    except OSError:
        return ""
    return re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)  # drop front matter


async def run_agent(root: Path, provider_name: str, model: str, user_text: str,
                    history: list[dict], permission_mode: str = "ask",
                    provider_settings: dict | None = None,
                    max_steps: int | None = None, effort: str = "off", *,
                    thread_id: str | None = None, resume: dict | None = None,
                    images: list[dict] | None = None, system_extra: str = "", context: str = "",
                    depth: int = 0) -> AsyncIterator[dict[str, Any]]:
    effort = normalize_effort(effort)
    if max_steps is None:
        max_steps = EFFORT_TO_STEPS[effort]
    provider = build_provider(provider_name, root, provider_settings or {})
    tools_schema = tools_registry.openai_schema()
    if depth == 0:
        tools_schema += [{"type": "function", "function": t.to_openai()} for t in BUILTIN]
    # MCP servers contribute tools dynamically (best-effort; failures are skipped).
    from .. import mcp as mcp_manager

    mcp_map: dict[str, tuple[str, str]] = {}
    try:
        mcp_schemas, mcp_map = await mcp_manager.agent_tools(root)
        tools_schema = [*tools_schema, *mcp_schemas]
    except Exception:
        pass

    s = session_mod.load(root, thread_id if depth == 0 else None)
    run = _Run(root, provider, provider_name, provider_settings or {}, model, effort, s, tools_schema,
               mcp_map, thread_id, max_steps, depth)

    if resume:
        if s.pending and s.pending.get("kind") != "plan" and permission_mode in ("ask", "auto", "readonly"):
            s.mode = permission_mode  # the mode picked in the composer when the user answered
        async for ev in _resume(run, resume):
            yield ev
        if not run.paused:
            async for ev in _loop(run):
                yield ev
        return

    if s.pending:  # a new message arrived instead of an answer to the approval card
        _close_pending(run, "Not run: the user sent a new message instead of answering.")

    first_turn = not s.messages
    if first_turn:
        sys_text = SYSTEM_PROMPT + (f"\n\n{system_extra}" if system_extra else "")
        legacy = [h for h in history if h.get("role") == "system"]
        if legacy and not system_extra:  # older clients send instructions as a system message
            sys_text += "\n\n" + "\n\n".join(str(h.get("content", "")) for h in legacy)
        s.messages = [ChatMessage(role="system", content=sys_text)]
        for h in history[-40:]:  # older clients send the transcript instead of a thread id
            if h.get("role") in ("user", "assistant") and h.get("content"):
                s.messages.append(ChatMessage(role=h["role"], content=str(h["content"])[:8000]))
    s.mode = permission_mode
    s.turn += 1

    if depth == 0:
        st = hooks.status(root)
        if st["present"] and not st["trusted"]:
            yield {"type": "hooks_untrusted"}
        hk = await hooks.run(root, "UserPromptSubmit", {"prompt": user_text})
        if hk["blocked"]:
            s.turn -= 1
            yield {"type": "error", "message": f"Blocked by a UserPromptSubmit hook: {hk['reason']}"}
            return
        if hk["context"]:
            context = (context + "\n\n" if context else "") + "Hook context:\n" + hk["context"]

    yield {"type": "status", "status": "planning", "message": "Planning…"}
    if first_turn and depth == 0:
        # Cheap project survey on the first turn: shown in the timeline and given to the model.
        try:
            res = await tools_registry.BY_NAME["inspect_project"].run(root, {})
            if res.ok:
                yield {"type": "tool_result", "tool": "inspect_project", "ok": True,
                       "output": res.output, "durationMs": res.durationMs}
                survey = json.dumps(res.output, default=str)[:3000]
                context = (context + "\n\n" if context else "") + f"Project survey (inspect_project):\n{survey}"
        except Exception:
            pass

    parts = [p for p in (context, PLAN_NOTE if s.mode == "plan" else "", user_text) if p]
    s.turn_index[str(s.turn)] = len(s.messages)
    s.messages.append(ChatMessage(role="user", content="\n\n".join(parts), images=images or None))
    _log(run, "user", user_text, turn=s.turn, images=len(images or []))
    s.save(root)
    if depth == 0:
        yield {"type": "turn", "turn": s.turn}
    async for ev in _loop(run):
        yield ev


async def _loop(run: _Run) -> AsyncIterator[dict[str, Any]]:
    s = run.s
    window = compact.context_window(run.provider_name, run.provider_settings)
    while run.steps < run.max_steps:
        run.steps += 1
        if compact.needs_compaction(s.messages, window):
            yield {"type": "status", "status": "compacting", "message": "Summarizing earlier conversation…"}
            try:
                s.messages, info = await compact.compact(run.provider, run.model, s.messages)
                _shift_turns(s, info)
                if info.get("compacted"):
                    yield {"type": "compacted", **info}
            except Exception as e:
                yield {"type": "status", "status": "thinking", "message": f"Compaction failed: {friendly_error(e)}"}
        yield {"type": "status", "status": "thinking", "message": f"Thinking (step {run.steps})…"}
        try:
            reply = await run.provider.chat(run.model, s.messages, run.tools_schema, effort=run.effort)
        except Exception as e:
            s.save(run.root)
            yield {"type": "error", "message": friendly_error(e)}
            return
        content = reply.get("content") or ""
        calls = []
        for c in reply.get("tool_calls") or []:
            calls.append({"id": c.get("id") or "call_" + uuid.uuid4().hex[:12], "name": c.get("name") or "",
                          "arguments": c.get("arguments") if isinstance(c.get("arguments"), str)
                          else json.dumps(c.get("arguments") or {})})
        s.messages.append(ChatMessage(role="assistant", content=content, tool_calls=calls or None,
                                      raw=reply.get("message_raw")))
        if content:
            run.final = content
            yield {"type": "assistant_delta", "delta": content}
            _log(run, "assistant", content)
        if not calls:
            if run.depth == 0:
                await hooks.run(run.root, "Stop", {"content": content})
            s.save(run.root)
            yield {"type": "done", "content": content, "steps": run.steps}
            return
        async for ev in _exec_calls(run, calls, 0):
            yield ev
        if run.paused:
            return
        s.save(run.root)
    s.save(run.root)
    yield {"type": "done", "content": "Stopped: step limit reached.", "steps": run.steps}


def _shift_turns(s: session_mod.Session, info: dict) -> None:
    """After compaction, move turn start indexes; summarized turns can no longer be rewound."""
    if not info.get("compacted"):
        return
    cut, base = info["cut"], info["keptFrom"]
    s.turn_index = {t: i - cut + base for t, i in s.turn_index.items() if i >= cut}


def _add_result(run: _Run, call: dict, text: str) -> None:
    run.s.messages.append(ChatMessage(role="tool", content=text, tool_call_id=call["id"], name=call["name"]))


def _close_pending(run: _Run, reason: str) -> None:
    """Answer every call left in a pending batch so the history stays valid."""
    p = run.s.pending or {}
    for call in (p.get("calls") or [])[p.get("index", 0):]:
        _add_result(run, call, "ERROR: " + reason)
    run.s.pending = None


async def _gate(run: _Run, name: str, tool: _Tool, args: dict) -> tuple[str, str]:
    """Decide what happens to a tool call: ('run'|'ask'|'block', reason)."""
    mode = run.s.mode
    if mode == "plan" and tool.permission != "read":
        return "block", "Plan mode is on: only read-only tools may run. Present your plan with exit_plan_mode."
    hk = await hooks.run(run.root, "PreToolUse", {"args": args}, tool=name)
    if hk["blocked"]:
        return "block", f"Blocked by a PreToolUse hook: {hk['reason']}"
    if not tools_registry.needs_approval(tool, mode):
        return "run", ""
    if permissions.is_allowed(run.root, name if name not in run.mcp_map else f"mcp:{name}", args):
        return "run", ""
    if not run.interactive:
        return "block", (f"{name} needs the user's approval, which subagents cannot ask for. "
                         "Report what should be done instead.")
    return "ask", ""


async def _execute(run: _Run, call: dict, args: dict) -> AsyncIterator[dict[str, Any]]:
    name, cid = call["name"], call["id"]
    yield {"type": "tool_start", "tool": name, "args": args, "id": cid}
    t0 = time.time()
    if name in run.mcp_map:
        from .. import mcp as mcp_manager

        server, tool = run.mcp_map[name]
        try:
            out = await mcp_manager.call_tool(run.root, server, tool, args)
            ok, output, error = True, out, None
        except Exception as e:
            ok, output, error = False, None, str(e)[:2000]
    else:
        tool_obj = tools_registry.BY_NAME[name]
        if name in checkpoints.FILE_TOOLS and run.s.persisted:
            try:
                checkpoints.snapshot(run.root, run.s.id, run.s.turn, name, args)
            except Exception:
                pass  # a failed snapshot must never block the edit itself
        res = await tool_obj.run(run.root, args)
        ok, output, error = res.ok, res.output, res.error
    dt = int((time.time() - t0) * 1000)
    await hooks.run(run.root, "PostToolUse", {"args": args, "ok": ok, "output": output, "error": error}, tool=name)
    _add_result(run, call, _result_text(ok, output, error))
    ui = _ui_output(output) if ok else None
    _log(run, "tool", tool=name, id=cid, args=args, ok=ok, output=ui, error=error, durationMs=dt)
    yield {"type": "tool_result", "tool": name, "id": cid, "ok": ok, "output": ui,
           "error": error, "durationMs": dt}


async def _exec_calls(run: _Run, calls: list[dict], start: int) -> AsyncIterator[dict[str, Any]]:
    s = run.s
    for i in range(start, len(calls)):
        call = calls[i]
        name = call["name"]
        args = _parse_args(call.get("arguments"))

        if name == "todo_write" and run.depth == 0:
            todos = [{"content": str(t.get("content", ""))[:300], "status": t.get("status", "pending")}
                     for t in args.get("todos") or [] if isinstance(t, dict)]
            s.todos = todos
            _add_result(run, call, "Task list updated.")
            yield {"type": "todos", "todos": todos}
            continue

        if name == "exit_plan_mode" and run.depth == 0:
            if s.mode != "plan":
                _add_result(run, call, "Plan mode is not on; carry on with the task.")
                continue
            plan = str(args.get("plan", ""))
            s.pending = {"kind": "plan", "calls": calls, "index": i, "plan": plan}
            s.save(run.root)
            _log(run, "plan", plan)
            run.paused = True
            yield {"type": "plan", "plan": plan, "threadId": run.thread_id}
            yield {"type": "done", "content": "", "steps": run.steps, "pendingPlan": {"plan": plan}}
            return

        if name == "task" and run.depth == 0:
            async for ev in _subagent(run, call, args):
                yield ev
            continue

        tool = _MCP_TOOL if name in run.mcp_map else tools_registry.BY_NAME.get(name)
        if tool is None:
            _add_result(run, call, f"ERROR: unknown tool {name!r}")
            yield {"type": "tool_result", "tool": name, "id": call["id"], "ok": False, "error": "unknown tool"}
            continue
        verdict, reason = await _gate(run, name, tool, args)
        if verdict == "block":
            _add_result(run, call, "ERROR: " + reason)
            yield {"type": "tool_result", "tool": name, "id": call["id"], "ok": False, "error": reason}
            continue
        if verdict == "ask":
            s.pending = {"kind": "tool", "calls": calls, "index": i}
            s.save(run.root)
            run.paused = True
            # No standing rule for destructive tools: each delete is confirmed on its own.
            rule = None if tool.permission == "destructive" else                 permissions.rule_for(name if name not in run.mcp_map else f"mcp:{name}", args)
            req = {"tool": name, "args": args, "permission": tool.permission, "id": call["id"],
                   "threadId": run.thread_id, "rule": rule}
            if name in run.mcp_map:
                server, mtool = run.mcp_map[name]
                req["mcp"] = {"server": server, "tool": mtool}
            yield {"type": "permission_request", **req}
            yield {"type": "done", "content": "", "steps": run.steps, "pendingApproval": req}
            return
        async for ev in _execute(run, call, args):
            yield ev


async def _resume(run: _Run, resume: dict) -> AsyncIterator[dict[str, Any]]:
    """Continue a paused turn. resume = {decision: allow|always|deny|approve|reject, mode?, feedback?}."""
    s = run.s
    p = s.pending
    if not p:
        run.paused = True
        yield {"type": "error", "message": "Nothing is waiting for approval in this thread."}
        return
    s.pending = None
    calls, i = p["calls"], p["index"]
    call = calls[i]
    decision = resume.get("decision", "deny")
    feedback = str(resume.get("feedback") or "").strip()

    if p["kind"] == "plan":
        if decision == "approve":
            s.mode = resume.get("mode") if resume.get("mode") in ("ask", "auto") else "ask"
            yield {"type": "mode", "mode": s.mode}
            _add_result(run, call, f"The user approved the plan. Permission mode is now '{s.mode}'. Carry it out"
                                   + (f". Their note: {feedback}" if feedback else "."))
        else:
            _add_result(run, call, "The user did not approve the plan yet. Stay in plan mode, revise it"
                                   + (f" based on their feedback: {feedback}" if feedback else "")
                                   + ", and call exit_plan_mode again.")
        async for ev in _exec_calls(run, calls, i + 1):
            yield ev
        return

    args = _parse_args(call.get("arguments"))
    tool = tools_registry.BY_NAME.get(call["name"])
    if decision == "always" and tool is not None and tool.permission == "destructive":
        decision = "allow"
    if decision in ("allow", "always"):
        if decision == "always":
            rule = permissions.add_rule(run.root, call["name"] if call["name"] not in run.mcp_map
                                        else f"mcp:{call['name']}", args)
            yield {"type": "status", "status": "thinking", "message": f"Always allowed: {rule}"}
        async for ev in _execute(run, call, args):
            yield ev
        async for ev in _exec_calls(run, calls, i + 1):
            yield ev
        return

    # Denied: answer this and the remaining calls, then hand the turn back to the user.
    s.pending = {"calls": calls, "index": i}
    _close_pending(run, "The user denied this tool call." + (f" They said: {feedback}" if feedback else ""))
    _log(run, "tool", tool=call["name"], id=call["id"], args=args, ok=False, error="Denied by you")
    yield {"type": "tool_result", "tool": call["name"], "id": call["id"], "ok": False, "error": "Denied"}
    if feedback:
        return  # keep going: the model sees the user's note in the tool result
    run.paused = True
    s.save(run.root)
    yield {"type": "done", "content": "", "steps": run.steps, "denied": True}


async def _subagent(run: _Run, call: dict, args: dict) -> AsyncIterator[dict[str, Any]]:
    desc = str(args.get("description") or "subtask")[:80]
    agent_name = str(args.get("agent") or "")
    system_extra = _load_agent_def(run.root, agent_name) if agent_name else ""
    mode = "auto" if run.s.mode == "auto" else "readonly"
    yield {"type": "subagent", "id": call["id"], "status": "start", "description": desc, "agent": agent_name}
    final, error = "", ""
    async for ev in run_agent(run.root, run.provider_name, run.model, str(args.get("prompt", "")), [], mode,
                              run.provider_settings, SUBAGENT_STEPS, run.effort,
                              system_extra=system_extra, depth=run.depth + 1):
        t = ev.get("type")
        if t in ("tool_start", "tool_result"):
            yield {**ev, "parent": call["id"]}
        elif t == "done":
            final = ev.get("content") or final
        elif t == "assistant_delta":
            final = ev.get("delta") or final
        elif t == "error":
            error = ev.get("message", "failed")
    report = final or (f"Subagent failed: {error}" if error else "(no report)")
    _add_result(run, call, report if not error or final else "ERROR: " + report)
    _log(run, "tool", tool="task", id=call["id"], args=args, ok=not (error and not final),
         output={"report": report[:20000]})
    yield {"type": "subagent", "id": call["id"], "status": "done", "description": desc, "result": report[:20000]}


async def compact_session(root: Path, thread_id: str, provider_name: str, model: str,
                          provider_settings: dict | None = None) -> dict[str, Any]:
    """/compact: summarize a thread's earlier turns now."""
    s = session_mod.load(root, thread_id)
    if len(s.messages) < 3:
        return {"compacted": False, "reason": "nothing to compact yet"}
    provider = build_provider(provider_name, root, provider_settings or {})
    s.messages, info = await compact.compact(provider, model, s.messages, keep_turns=1)
    _shift_turns(s, info)
    s.save(root)
    return info


async def run_approved_tool(root: Path, tool_name: str, args: dict, mcp: dict | None = None) -> dict[str, Any]:
    """Legacy one-shot approval (clients without thread ids)."""
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
    from ..providers.free import FreeModelError

    s = str(e)
    if isinstance(e, FreeModelError):
        return s
    name = type(e).__name__
    if "ConnectError" in name or "APIConnectionError" in name or "Connect" in s or "refused" in s.lower():
        return ("Model endpoint unreachable. Is your local server running "
                "(e.g. http://localhost:8000/v1)? Check Settings → Providers. Details: " + s[:300])
    if "401" in s or "Unauthorized" in s or "AuthenticationError" in name:
        return "Provider rejected the API key (401). Check Settings → Providers. Details: " + s[:300]
    if "429" in s or "RateLimit" in name:
        return "Rate limited by the provider (429). Wait a moment and try again. Details: " + s[:300]
    return f"Model request failed: {s[:500]}"
