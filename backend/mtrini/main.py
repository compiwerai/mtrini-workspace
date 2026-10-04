"""Mtrini Workspace API: health, providers, models, projects, chat/agent, tools, git, HF."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import __version__
from . import models as models_mod
from . import project as project_mod
from .agent import engine as agent_engine
from .config import delete_secret, get_secret, load_config, save_config, set_secret, workspace_root
from .providers import ChatMessage
from .providers.registry import PROVIDER_META, build_provider
from .tools import registry as tools_registry

app = FastAPI(title="Mtrini Workspace", version=__version__)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"], allow_credentials=True)


def _frontend_dist() -> Path | None:
    """Locate the built UI: PyInstaller bundle (_MEIPASS) or repo checkout.

    In an onedir bundle, datas may sit beside _MEIPASS instead of inside it,
    so check the exe directory too — never depend on the working directory.
    """
    import sys

    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "frontend" / "dist")
        candidates.append(Path(meipass).parent / "frontend" / "dist")
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "frontend" / "dist")
    here = Path(__file__).resolve()
    candidates += [here.parent.parent.parent / "frontend" / "dist",  # repo: backend/../frontend/dist
                   Path.cwd() / "frontend" / "dist"]
    for c in candidates:
        if (c / "index.html").exists():
            return c
    return None


_DIST = _frontend_dist()
if getattr(sys, "frozen", False):  # frozen desktop app: record UI resolution for diagnostics
    try:
        with open(os.path.join(os.path.expanduser("~"), "mtrini-desktop.log"), "a", encoding="utf-8") as _f:
            _f.write(f"_DIST={_DIST} _MEIPASS={getattr(sys, '_MEIPASS', None)} "
                     f"exe={Path(sys.executable).resolve().parent}\n")
    except Exception:
        pass
# NOTE: the UI is mounted at the END of this file, after all /api routes,
# so the catch-all static mount never shadows the API.


def root(explicit: str | None = None) -> Path:
    return workspace_root(explicit)


# ---- health / meta ----

@app.get("/api/health")
def health():
    return {"ok": True, "version": __version__, "product": "Mtrini Workspace",
            "vendor": "Compiwer AI"}


@app.get("/api/about")
def about():
    return {"product": "Mtrini Workspace", "vendor": "Compiwer AI",
            "tagline": "Your AI. Your code. Your workspace.",
            "vendorTagline": "Building AI For Everyone.",
            "version": __version__, "license": "Apache-2.0"}


@app.get("/api/runtimes")
def runtimes():
    return models_mod.detect_runtimes()


# ---- providers ----

@app.get("/api/providers")
def providers(workspace: str | None = None):
    r = root(workspace)
    out = []
    for m in PROVIDER_META:
        has_key = False
        if m.get("needsKey"):
            key = get_secret(r, f"mtrini-{m['id']}", "apiKey") or get_secret(r, "mtrini-hf", "token")
            has_key = bool(key)
        out.append({**m, "configured": (not m.get("needsKey")) or has_key})
    # local endpoint liveness
    return {"providers": out}


class ProviderConfig(BaseModel):
    provider: str
    apiKey: str | None = None
    baseUrl: str | None = None
    model: str | None = None
    apiVersion: str | None = None
    workspace: str | None = None


@app.post("/api/providers/configure")
def configure_provider(cfg: ProviderConfig):
    r = root(cfg.workspace)
    if cfg.apiKey:
        svc = "mtrini-hf" if cfg.provider == "huggingface" else f"mtrini-{cfg.provider}"
        acct = "token" if cfg.provider == "huggingface" else "apiKey"
        where = set_secret(r, svc, acct, cfg.apiKey)
    else:
        where = "unchanged"
    cur = load_config(r)
    key = f"provider.{cfg.provider}"
    prev = cur.get(key, {})
    merged = dict(prev) if isinstance(prev, dict) else {}
    if cfg.baseUrl is not None:
        merged["baseUrl"] = cfg.baseUrl
    if cfg.model is not None:
        merged["model"] = cfg.model
    if cfg.apiVersion is not None:
        merged["apiVersion"] = cfg.apiVersion
    if merged:
        cur[key] = merged
    save_config(r, cur)
    return {"ok": True, "stored": where}


@app.post("/api/providers/disconnect")
def disconnect_provider(body: dict):
    r = root(body.get("workspace"))
    pid = body.get("provider", "")
    delete_secret(r, f"mtrini-{pid}", "apiKey")
    delete_secret(r, "mtrini-hf", "token")
    return {"ok": True}


@app.get("/api/models")
def api_models(provider: str = "local", workspace: str | None = None):
    r = root(workspace)
    cfg = load_config(r)
    settings = cfg.get(f"provider.{provider}", {})
    p = build_provider(provider, r, settings if isinstance(settings, dict) else {})
    import anyio

    async def _go():
        return await p.list_models()

    try:
        models = anyio.run(_go)
        return {"models": [{"id": m.id, "label": m.label, "provider": m.provider,
                            "capabilities": m.capabilities, "contextLength": m.contextLength}
                           for m in models]}
    except Exception as e:
        raise HTTPException(502, f"Provider error: {e}")


# ---- local model registry ----

@app.get("/api/registry")
def registry(workspace: str | None = None):
    return {"models": models_mod.list_models(root(workspace))}


@app.post("/api/registry")
def registry_add(body: dict):
    r = root(body.get("workspace"))
    models_mod.upsert(r, body)
    return {"ok": True}


@app.get("/api/local/endpoint")
async def endpoint_status(baseUrl: str, workspace: str | None = None):
    return await models_mod.check_endpoint(baseUrl)


# ---- Hugging Face ----

@app.get("/api/hf/whoami")
def hf_whoami(workspace: str | None = None):
    from .providers.huggingface import HuggingFaceProvider

    tok = get_secret(root(workspace), "mtrini-hf", "token") or ""
    return HuggingFaceProvider(token=tok).whoami()


@app.get("/api/hf/search")
def hf_search(q: str, limit: int = 20, workspace: str | None = None):
    from .providers.huggingface import HuggingFaceProvider

    tok = get_secret(root(workspace), "mtrini-hf", "token") or ""
    try:
        return {"results": HuggingFaceProvider(token=tok).search(q, limit)}
    except Exception as e:
        raise HTTPException(502, str(e)[:500])


@app.get("/api/hf/details")
def hf_details(repo: str, workspace: str | None = None):
    from .providers.huggingface import HuggingFaceProvider

    tok = get_secret(root(workspace), "mtrini-hf", "token") or ""
    try:
        return HuggingFaceProvider(token=tok).details(repo)
    except Exception as e:
        raise HTTPException(502, str(e)[:500])


class DownloadFileBody(BaseModel):
    repo: str
    filename: str
    workspace: str | None = None


@app.post("/api/hf/download-file")
def hf_download_file(body: DownloadFileBody):
    """Download ONE file (e.g. a single .gguf) — size is reported before/after."""
    from huggingface_hub import hf_hub_download

    r = root(body.workspace)
    tok = get_secret(r, "mtrini-hf", "token")
    try:
        path = hf_hub_download(repo_id=body.repo, filename=body.filename, token=tok,
                               local_dir=str(r / ".mtrini" / "models" / body.repo.replace("/", "__")))
        size = Path(path).stat().st_size
        models_mod.upsert(r, {"id": f"{body.repo}:{body.filename}", "provider": "huggingface",
                              "format": "gguf" if body.filename.endswith(".gguf") else "file",
                              "status": "ready", "path": path})
        return {"ok": True, "path": path, "bytes": size, "mb": round(size / 1e6, 1)}
    except Exception as e:
        raise HTTPException(502, str(e)[:800])


@app.post("/api/hf/download")
def hf_download(body: dict):
    r = root(body.get("workspace"))
    tok = get_secret(r, "mtrini-hf", "token")
    try:
        res = models_mod.download_snapshot(r, body["repo"], tok)
        models_mod.upsert(r, {"id": body["repo"], "provider": "huggingface",
                              "format": "snapshot", "status": "ready", "path": res["path"]})
        return {"ok": True, **res}
    except Exception as e:
        raise HTTPException(502, str(e)[:800])


# ---- projects / files ----

@app.get("/api/project")
def project(workspace: str | None = None):
    r = root(workspace)
    cfg = load_config(r)
    return {"root": str(r), "config": cfg,
            "instructions": project_mod.load_instructions(r),
            "skills": project_mod.list_skills(r), "agents": project_mod.list_agents(r)}


@app.get("/api/skills/{name}")
def skill(name: str, workspace: str | None = None):
    try:
        return {"name": name, "content": project_mod.read_skill(root(workspace), name)}
    except FileNotFoundError:
        raise HTTPException(404, "Skill not found")


class ExecBody(BaseModel):
    tool: str
    args: dict[str, Any] = {}
    workspace: str | None = None


@app.post("/api/tools/execute")
async def tools_execute(body: ExecBody):
    r = root(body.workspace)
    tool = tools_registry.BY_NAME.get(body.tool)
    if tool is None:
        raise HTTPException(404, "Unknown tool")
    res = await tool.run(r, body.args)
    return {"ok": res.ok, "output": res.output, "error": res.error, "durationMs": res.durationMs}


@app.get("/api/git/status")
def git_status(workspace: str | None = None):
    import anyio

    async def _go():
        return await tools_registry.BY_NAME["git_status"].run(root(workspace), {})
    res = anyio.run(_go)
    return {"ok": res.ok, "output": res.output, "error": res.error}


@app.get("/api/git/diff")
def git_diff(path: str = ".", cached: bool = False, workspace: str | None = None):
    import subprocess as _sp

    args = ["git", "diff", "--cached" if cached else "--", path] if cached else ["git", "diff", "--", path]
    try:
        p = _sp.run(args, cwd=str(root(workspace)), capture_output=True, text=True, timeout=30)
        return {"ok": p.returncode == 0, "output": {"stdout": p.stdout[-20000:], "stderr": p.stderr[-5000:]}}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


class CommitBody(BaseModel):
    message: str
    workspace: str | None = None


@app.post("/api/git/commit")
def git_commit(body: CommitBody):
    import subprocess as _sp

    if not body.message.strip():
        raise HTTPException(400, "Commit message is empty")
    try:
        p = _sp.run(["git", "commit", "-m", body.message.strip()], cwd=str(root(body.workspace)),
                    capture_output=True, text=True, timeout=60)
    except Exception as e:
        raise HTTPException(500, str(e)[:300])
    if p.returncode != 0:
        raise HTTPException(422, (p.stdout + p.stderr)[-800:])
    return {"ok": True, "output": p.stdout[-2000:]}


@app.post("/api/project/open")
def open_project_folder(body: dict):
    """Reveal the workspace in the OS file manager (real, non-blocking)."""
    import subprocess as _sp
    import sys as _sys

    r = root(body.get("workspace"))
    try:
        if _sys.platform == "win32":
            os.startfile(str(r))  # type: ignore[attr-defined]
        elif _sys.platform == "darwin":
            _sp.Popen(["open", str(r)])
        else:
            _sp.Popen(["xdg-open", str(r)])
    except Exception as e:
        raise HTTPException(500, str(e)[:300])
    return {"ok": True, "root": str(r)}


# ---- threads ----

@app.get("/api/threads")
def api_threads(workspace: str | None = None):
    from . import threads as _t

    return {"threads": _t.list_threads(root(workspace))}


class ThreadBody(BaseModel):
    title: str = "Untitled"
    workspace: str | None = None


@app.post("/api/threads")
def api_create_thread(body: ThreadBody):
    from . import threads as _t

    return _t.create_thread(root(body.workspace), body.title, body.workspace)


@app.get("/api/threads/{tid}")
def api_get_thread(tid: str, workspace: str | None = None):
    from . import threads as _t

    try:
        return _t.get_thread(root(workspace), tid)
    except FileNotFoundError:
        raise HTTPException(404, "thread not found")


class ThreadMsgBody(BaseModel):
    role: str
    content: str
    workspace: str | None = None


@app.post("/api/threads/{tid}/messages")
def api_append_thread_msg(tid: str, body: ThreadMsgBody):
    from . import threads as _t

    try:
        return _t.append_message(root(body.workspace), tid, body.role, body.content)
    except FileNotFoundError:
        raise HTTPException(404, "thread not found")


# ---- automations ----

@app.get("/api/automations")
def api_auto_list(workspace: str | None = None):
    from . import threads as _t

    return {"automations": _t.list_automations(root(workspace))}


class AutoBody(BaseModel):
    name: str
    prompt: str
    workspace: str | None = None


@app.post("/api/automations")
def api_auto_save(body: AutoBody):
    from . import threads as _t

    if not body.name.strip() or not body.prompt.strip():
        raise HTTPException(400, "name and prompt required")
    return _t.save_automation(root(body.workspace), body.name, body.prompt)


@app.delete("/api/automations/{aid}")
def api_auto_delete(aid: str, workspace: str | None = None):
    from . import threads as _t

    return {"ok": _t.delete_automation(root(workspace), aid)}


class AutoRunBody(BaseModel):
    workspace: str | None = None


@app.post("/api/automations/{aid}/run")
def api_auto_run(aid: str, body: AutoRunBody):
    """Run an automation: creates a thread seeded with its prompt. The client
    then drives the agent SSE loop against that thread."""
    from . import threads as _t

    auto = next((a for a in _t.list_automations(root(body.workspace)) if a.get("id") == aid), None)
    if auto is None:
        raise HTTPException(404, "automation not found")
    r = root(body.workspace)
    th = _t.create_thread(r, auto["name"])
    _t.append_message(r, th["id"], "user", auto["prompt"])
    return {"thread": th, "prompt": auto["prompt"]}



# ---- chat + agent (SSE) ----

class ChatBody(BaseModel):
    provider: str = "local"
    model: str = ""
    messages: list[dict[str, Any]] = []
    workspace: str | None = None
    effort: str = "off"


@app.post("/api/chat")
async def chat(body: ChatBody):
    r = root(body.workspace)
    cfg = load_config(r)
    settings = cfg.get(f"provider.{body.provider}", {})
    try:
        p = build_provider(body.provider, r, settings if isinstance(settings, dict) else {})
    except ValueError as e:
        raise HTTPException(400, str(e))
    msgs = [ChatMessage(role=m.get("role", "user"), content=str(m.get("content", "")))
            for m in body.messages]

    async def gen():
        try:
            async for ev in p.stream(body.model, msgs, effort=body.effort):
                yield f"data: {json.dumps(ev)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': agent_engine.friendly_error(e)})}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")


class AgentBody(BaseModel):
    provider: str = "local"
    model: str = ""
    message: str = ""
    history: list[dict[str, Any]] = []
    permissionMode: str = "ask"
    workspace: str | None = None
    effort: str = "off"
    approve: dict[str, Any] | None = None  # {tool, args} — execute an approved tool immediately


@app.post("/api/agent")
async def agent(body: AgentBody):
    r = root(body.workspace)
    if body.approve:
        res = await agent_engine.run_approved_tool(r, body.approve.get("tool", ""), body.approve.get("args", {}),
                                                   body.approve.get("mcp"))
        return res
    cfg = load_config(r)
    settings = cfg.get(f"provider.{body.provider}", {})
    # Inject project instructions + skill list as a leading system message.
    history = list(body.history)
    instr = project_mod.load_instructions(r)
    if instr and not any(h.get("role") == "system" for h in history):
        history.insert(0, {"role": "system",
                           "content": f"Project instructions (.mtrini/instructions.md):\n{instr}"})

    async def gen():
        async for ev in agent_engine.run_agent(
                r, body.provider, body.model, body.message, history,
                body.permissionMode, settings if isinstance(settings, dict) else {},
                effort=body.effort):
            yield f"data: {json.dumps(ev, default=str)}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")


# ---- terminal:dumb exec over REST (PTY streams via WebSocket in future) ----

class TermBody(BaseModel):
    command: str
    cwd: str | None = None
    timeout: float = 120
    workspace: str | None = None


@app.post("/api/terminal/exec")
async def terminal_exec(body: TermBody):
    r = root(body.workspace)
    res = await tools_registry.BY_NAME["execute_command"].run(
        r, {"command": body.command, "cwd": body.cwd or str(r), "timeout": body.timeout})
    return {"ok": res.ok, "output": res.output, "error": res.error}


class StageBody(BaseModel):
    paths: list[str] = []
    workspace: str | None = None


@app.post("/api/git/stage")
def git_stage(body: StageBody):
    import subprocess as _sp

    if not body.paths:
        raise HTTPException(400, "no paths given")
    try:
        p = _sp.run(["git", "add", "--", *body.paths], cwd=str(root(body.workspace)),
                    capture_output=True, text=True, timeout=60)
    except Exception as e:
        raise HTTPException(500, str(e)[:300])
    if p.returncode != 0:
        raise HTTPException(422, (p.stdout + p.stderr)[-800:])
    return {"ok": True}


@app.get("/api/browse")
def browse(path: str | None = None):
    """Server-side folder picker: list directories under path (default: home)."""
    base = Path(path).expanduser() if path else Path.home()
    try:
        base = base.resolve()
    except OSError:
        raise HTTPException(400, "unreadable path")
    if not base.is_dir():
        raise HTTPException(400, "not a directory")
    try:
        dirs = sorted([d for d in base.iterdir() if d.is_dir() and not d.name.startswith(".")],
                      key=lambda d: d.name.lower())[:300]
    except OSError as e:
        raise HTTPException(400, str(e)[:200])
    return {"path": str(base), "parent": str(base.parent),
            "dirs": [{"name": d.name, "path": str(d)} for d in dirs]}


@app.delete("/api/threads/{tid}")
def api_delete_thread(tid: str, workspace: str | None = None):
    from . import threads as _t

    if not _t.delete_thread(root(workspace), tid):
        raise HTTPException(404, "thread not found")
    return {"ok": True}


class ThreadTitleBody(BaseModel):
    title: str = ""
    folder: str | None = None
    workspace: str | None = None


@app.patch("/api/threads/{tid}")
def api_rename_thread(tid: str, body: ThreadTitleBody):
    from . import threads as _t

    try:
        return _t.rename_thread(root(body.workspace), tid, body.title, body.folder)
    except FileNotFoundError:
        raise HTTPException(404, "thread not found")


# ---- MCP dev tools ----

@app.get("/api/mcp/servers")
def api_mcp_list(workspace: str | None = None, format: str = "mtrini"):
    from . import mcp as _mcp

    servers = _mcp.load_servers(root(workspace))
    if format == "claude":
        return _mcp.to_claude_shape(servers)
    return {"servers": servers}


@app.post("/api/mcp/import")
def api_mcp_import(body: dict):
    from . import mcp as _mcp

    r = root(body.get("workspace"))
    if "config" not in body:
        raise HTTPException(400, "provide {config: {...}} — Claude shape, array, or single server")
    return _mcp.import_config(r, body["config"])


@app.post("/api/mcp/servers")
def api_mcp_add(body: dict):
    from . import mcp as _mcp

    r = root(body.get("workspace"))
    try:
        srv = _mcp.validate_server(body)
    except ValueError as e:
        raise HTTPException(400, str(e))
    servers = [s for s in _mcp.load_servers(r) if s.get("name") != srv["name"]]
    servers.append(srv)
    _mcp.save_servers(r, servers)
    return srv


@app.patch("/api/mcp/servers/{name}")
def api_mcp_toggle(name: str, body: dict):
    from . import mcp as _mcp

    r = root(body.get("workspace"))
    servers = _mcp.load_servers(r)
    found = False
    for s in servers:
        if s.get("name") == name:
            s["enabled"] = bool(body.get("enabled", True))
            found = True
    if not found:
        raise HTTPException(404, "server not found")
    _mcp.save_servers(r, servers)
    return {"ok": True}


@app.delete("/api/mcp/servers/{name}")
def api_mcp_delete(name: str, workspace: str | None = None):
    from . import mcp as _mcp

    r = root(workspace)
    servers = [s for s in _mcp.load_servers(r) if s.get("name") != name]
    _mcp.save_servers(r, servers)
    return {"ok": True}


@app.get("/api/mcp/servers/{name}/tools")
async def api_mcp_tools(name: str, workspace: str | None = None):
    from . import mcp as _mcp

    r = root(workspace)
    srv = next((s for s in _mcp.load_servers(r) if s.get("name") == name), None)
    if srv is None:
        raise HTTPException(404, "server not found")
    _name, entries, error = await _mcp._server_tools(r, srv)
    return {"tools": entries, "error": error or None}


class MCPCallBody(BaseModel):
    server: str
    tool: str
    args: dict[str, Any] = {}
    workspace: str | None = None


@app.post("/api/mcp/call")
async def api_mcp_call(body: MCPCallBody):
    from . import mcp as _mcp

    try:
        return {"ok": True, "output": await _mcp.call_tool(root(body.workspace), body.server, body.tool, body.args)}
    except Exception as e:
        raise HTTPException(502, str(e)[:800])


# ---- Mtrini Images ----

@app.get("/api/images/support")
def api_images_support():
    from . import images as _img

    return {"support": _img.IMAGE_SUPPORT}


class ImageGenBody(BaseModel):
    provider: str
    model: str
    prompt: str
    size: str = "1024x1024"
    workspace: str | None = None


@app.post("/api/images/generate")
async def api_images_generate(body: ImageGenBody):
    from . import images as _img

    try:
        return await _img.generate(root(body.workspace), body.provider, body.model, body.prompt, body.size)
    except Exception as e:
        raise HTTPException(502, str(e)[:800])


@app.get("/api/images")
def api_images_list(workspace: str | None = None):
    from . import images as _img

    return {"images": _img.list_images(root(workspace))}


@app.delete("/api/images/{img_id}")
def api_images_delete(img_id: str, workspace: str | None = None):
    from . import images as _img

    return {"ok": _img.delete_image(root(workspace), img_id)}


@app.get("/api/images/{img_id}/file")
def api_images_file(img_id: str, workspace: str | None = None):
    from fastapi.responses import FileResponse

    from . import images as _img

    try:
        return FileResponse(str(_img.image_path(root(workspace), img_id)), media_type="image/png")
    except FileNotFoundError:
        raise HTTPException(404, "image not found")


# ---- desktop UI: mounted LAST so the catch-all never shadows /api ----
if _DIST is not None:  # serve the built frontend from the same origin (desktop exe)
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="ui")
