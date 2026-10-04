"""MCP dev tools: use external MCP servers (stdio + streamable HTTP) as agent tools,
and inspect them manually. No extra dependencies: minimal JSON-RPC 2.0 client."""
from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
PROTOCOL = "2024-11-05"


def _cfg_path(root: Path) -> Path:
    return root / ".mtrini" / "mcp.json"


def load_servers(root: Path) -> list[dict[str, Any]]:
    p = _cfg_path(root)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save_servers(root: Path, servers: list[dict[str, Any]]) -> None:
    (root / ".mtrini").mkdir(parents=True, exist_ok=True)
    _cfg_path(root).write_text(json.dumps(servers, indent=2), encoding="utf-8")


def to_claude_shape(servers: list[dict[str, Any]]) -> dict[str, Any]:
    """Export to the Claude Desktop JSON shape: {"mcpServers": {name: {...}}}."""
    out: dict[str, Any] = {}
    for s in servers:
        if s.get("transport") == "http":
            out[s["name"]] = {"url": s.get("url", "")}
        else:
            entry: dict[str, Any] = {"command": s.get("command", ""),
                                     "args": s.get("args", [])}
            if s.get("env"):
                entry["env"] = s["env"]
            out[s["name"]] = entry
    return {"mcpServers": out}


def from_json_shape(data: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """Import from Claude shape, our array shape, or a single server object.
    Returns (valid_servers, error_messages)."""
    candidates: list[Any] = []
    if isinstance(data, dict) and isinstance(data.get("mcpServers"), dict):
        for name, cfg in data["mcpServers"].items():
            if not isinstance(cfg, dict):
                continue
            entry = dict(cfg)
            entry.setdefault("name", name)
            if "url" in cfg and "transport" not in cfg:
                entry["transport"] = "http"
            candidates.append(entry)
    elif isinstance(data, list):
        candidates = data
    elif isinstance(data, dict):
        candidates = [data]
    else:
        return [], ["config must be an object or array"]
    valid, errors = [], []
    for c in candidates:
        try:
            if not isinstance(c, dict):
                raise ValueError("entry must be an object")
            valid.append(validate_server(c))
        except ValueError as e:
            label = c.get("name", "?") if isinstance(c, dict) else "?"
            errors.append(f"{label}: {e}")
    return valid, errors


def import_config(root: Path, data: Any) -> dict[str, Any]:
    valid, errors = from_json_shape(data)
    servers = load_servers(root)
    by_name = {s.get("name"): s for s in servers}
    for srv in valid:
        srv["enabled"] = by_name.get(srv["name"], {}).get("enabled", True)
        by_name[srv["name"]] = srv
    save_servers(root, list(by_name.values()))
    return {"added": [s["name"] for s in valid], "errors": errors,
            "servers": list(by_name.values())}


def validate_server(body: dict[str, Any]) -> dict[str, Any]:
    name = str(body.get("name", "")).strip().lower()
    if not NAME_RE.match(name):
        raise ValueError("name must be [a-z0-9_-], max 40 chars")
    transport = body.get("transport", "stdio")
    if transport == "stdio":
        if not str(body.get("command", "")).strip():
            raise ValueError("stdio servers need a command")
        srv: dict[str, Any] = {"name": name, "transport": "stdio",
                               "command": str(body["command"]).strip(),
                               "args": [str(a) for a in body.get("args", [])],
                               "env": {str(k): str(v) for k, v in (body.get("env") or {}).items()},
                               "enabled": bool(body.get("enabled", True))}
    elif transport == "http":
        url = str(body.get("url", "")).strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            raise ValueError("http servers need an http(s) url")
        srv = {"name": name, "transport": "http", "url": url,
               "enabled": bool(body.get("enabled", True))}
    else:
        raise ValueError("transport must be stdio or http")
    return srv


class _RPCError(Exception):
    pass


class StdioSession:
    """One-shot JSON-RPC over stdio (newline-delimited, per MCP spec)."""

    def __init__(self, srv: dict[str, Any]):
        self.srv = srv
        self._id = 0

    async def run(self, timeout: float = 30.0) -> dict[str, Any]:
        import os as _os

        env = dict(_os.environ)
        env.update(self.srv.get("env", {}))
        proc = await asyncio.create_subprocess_exec(
            self.srv["command"], *(self.srv.get("args", [])),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, env=env)
        assert proc.stdin and proc.stdout
        tools: dict[str, Any] = {}

        async def call(method: str, params: dict | None = None, notif: bool = False) -> Any:
            self._id += 1
            msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
            if not notif:
                msg["id"] = self._id
            if params is not None:
                msg["params"] = params
            proc.stdin.write((json.dumps(msg) + "\n").encode())
            await proc.stdin.drain()
            if notif:
                return None
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout)
            if not line:
                raise _RPCError("server closed stdout")
            try:
                res = json.loads(line.decode())
            except ValueError:
                raise _RPCError(f"bad JSON: {line[:120]!r}")
            if "error" in res:
                raise _RPCError(str(res["error"])[:300])
            return res.get("result")

        try:
            await call("initialize", {"protocolVersion": PROTOCOL,
                                      "capabilities": {},
                                      "clientInfo": {"name": "mtrini", "version": "0.6.0"}})
            await call("notifications/initialized", None, notif=True)
            listed = await call("tools/list")
            for t in (listed or {}).get("tools", []):
                tools[t["name"]] = {"description": t.get("description", ""),
                                    "schema": t.get("inputSchema", {"type": "object"})}
            return {"tools": tools, "_call": call, "_proc": proc}
        except Exception:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            raise

    @staticmethod
    async def close(session: dict[str, Any]) -> None:
        proc = session.get("_proc")
        if proc is None:
            return
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    @staticmethod
    async def call_tool(session: dict[str, Any], tool: str, args: dict, timeout: float = 120.0) -> Any:
        call = session["_call"]
        res = await asyncio.wait_for(call("tools/call", {"name": tool, "arguments": args}), timeout=timeout)
        return res


_sessions: dict[str, str] = {}  # server url -> Mcp-Session-Id (streamable HTTP)


async def http_rpc(url: str, method: str, params: dict | None = None,
                   token: str = "", timeout: float = 30.0) -> Any:
    """Streamable HTTP transport: POST JSON-RPC, accept SSE or plain JSON."""
    import httpx

    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if url in _sessions:
        headers["Mcp-Session-Id"] = _sessions[url]
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        body["params"] = params
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(url, headers=headers, json=body)
        if r.status_code == 404 and "/mcp" not in url:
            # retry with conventional /mcp suffix once
            r = await c.post(url.rstrip("/") + "/mcp", headers=headers, json=body)
        r.raise_for_status()
        sid = r.headers.get("Mcp-Session-Id") or r.headers.get("mcp-session-id")
        if sid:
            _sessions[url] = sid
        ctype = r.headers.get("content-type", "")
        if "text/event-stream" in ctype:
            for line in r.text.splitlines():
                if line.startswith("data:"):
                    try:
                        data = json.loads(line[5:])
                    except ValueError:
                        continue
                    if "error" in data:
                        raise _RPCError(str(data["error"])[:300])
                    if "result" in data:
                        return data["result"]
            raise _RPCError("no result in event stream")
        data = r.json()
        if "error" in data:
            raise _RPCError(str(data["error"])[:300])
        return data.get("result")


async def _server_tools(root: Path, srv: dict[str, Any]) -> tuple[str, list[dict[str, Any]], str]:
    """Returns (name, tool entries, error). Never raises."""
    t0 = time.time()
    try:
        if srv["transport"] == "stdio":
            session = await StdioSession(srv).run(timeout=20.0)
            try:
                entries = [{"name": n, "description": t.get("description", ""),
                            "schema": t.get("schema", {"type": "object"})}
                           for n, t in session["tools"].items()]
                return srv["name"], entries, ""
            finally:
                await StdioSession.close(session)
        else:
            await http_rpc(srv["url"], "initialize",
                           {"protocolVersion": PROTOCOL, "capabilities": {},
                            "clientInfo": {"name": "mtrini", "version": "0.6.0"}})
            listed = await http_rpc(srv["url"], "tools/list") or {}
            entries = [{"name": t["name"], "description": t.get("description", ""),
                        "schema": t.get("inputSchema", {"type": "object"})}
                       for t in listed.get("tools", [])]
            return srv["name"], entries, ""
    except Exception as e:
        return srv["name"], [], f"{type(e).__name__}: {str(e)[:200]} (after {time.time()-t0:.0f}s)"


def agent_name(server: str, tool: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_-]", "_", f"mcp__{server}__{tool}")
    return clean[:64]


async def agent_tools(root: Path) -> tuple[list[dict], dict[str, tuple[str, str]]]:
    """Collect enabled MCP servers' tools as OpenAI schemas + name map. Best-effort."""
    servers = [s for s in load_servers(root) if s.get("enabled", True)]
    if not servers:
        return [], {}
    results = await asyncio.gather(*[_server_tools(root, s) for s in servers])
    schemas, mapping = [], {}
    for name, entries, _err in results:
        for e in entries:
            aname = agent_name(name, e["name"])
            mapping[aname] = (name, e["name"])
            schemas.append({"type": "function", "function": {
                "name": aname,
                "description": f"[mcp:{name}] {e['description']}"[:500],
                "parameters": e["schema"] if isinstance(e["schema"], dict) else {"type": "object"}}})
    return schemas, mapping


async def call_tool(root: Path, server: str, tool: str, args: dict[str, Any]) -> Any:
    srv = next((s for s in load_servers(root) if s.get("name") == server), None)
    if srv is None:
        raise ValueError("unknown MCP server")
    if not srv.get("enabled", True):
        raise ValueError("server disabled")
    if srv["transport"] == "stdio":
        session = await StdioSession(srv).run(timeout=20.0)
        try:
            res = await StdioSession.call_tool(session, tool, args or {})
        finally:
            await StdioSession.close(session)
    else:
        res = await http_rpc(srv["url"], "tools/call", {"name": tool, "arguments": args or {}},
                             timeout=120.0)
    # Normalize MCP content blocks to text.
    if isinstance(res, dict) and isinstance(res.get("content"), list):
        parts = []
        for b in res["content"]:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
            else:
                parts.append(json.dumps(b)[:2000])
        return {"content": parts, "isError": res.get("isError", False)}
    return res
