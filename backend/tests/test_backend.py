import pytest
from fastapi.testclient import TestClient

from mtrini import security
from mtrini.config import save_config
from mtrini.main import app
from mtrini.providers.registry import build_provider
from mtrini.tools import registry as reg


class _StubProvider:
    """Test-only double (not a product provider): deterministic offline replies."""

    name = "stub"

    async def chat(self, model, messages, tools=None, **kw):
        return {"content": "stub-ok", "tool_calls": []}

    async def stream(self, model, messages, tools=None, **kw):
        yield {"delta": "stub-ok"}
        yield {"done": True}

    async def list_models(self, **kw):
        from mtrini.providers import ModelInfo

        return [ModelInfo(id="stub-1", label="Stub", provider="stub")]

    def supports_tools(self):
        return True

    def supports_vision(self):
        return False

    def supports_streaming(self):
        return True


def _use_stub(monkeypatch):
    monkeypatch.setattr("mtrini.agent.engine.build_provider", lambda *a, **k: _StubProvider())
    monkeypatch.setattr("mtrini.main.build_provider", lambda *a, **k: _StubProvider())


def test_path_traversal_blocked(tmp_path):
    with pytest.raises(ValueError):
        security.resolve_inside(tmp_path, "../../etc/passwd")
    p = security.resolve_inside(tmp_path, "a/b.txt")
    assert str(p).startswith(str(tmp_path.resolve()))


def test_command_classification():
    assert security.classify_command("npm test") == "safe"
    assert security.classify_command("npm install x") == "risky"
    assert security.classify_command("rm -rf /") == "destructive"


def test_filesystem_tools_confined(tmp_path):
    import anyio

    async def _go():
        ok = await reg.BY_NAME["write_file"].run(tmp_path, {"path": "hi.txt", "content": "hello"})
        assert ok.ok
        r = await reg.BY_NAME["read_file"].run(tmp_path, {"path": "hi.txt"})
        assert r.output["content"] == "hello"
        bad = await reg.BY_NAME["read_file"].run(tmp_path, {"path": "../evil.txt"})
        assert not bad.ok
    anyio.run(_go)


def test_provider_factory(tmp_path):
    assert build_provider("local", tmp_path, {"baseUrl": "http://localhost:8000/v1"}).name == "local"
    assert build_provider("openai", tmp_path).name == "openai"
    for pid in ("ollama", "lmstudio", "mistral", "deepseek", "groq", "together",
                "fireworks", "xai", "cohere", "gemini", "anthropic", "openrouter", "huggingface",
                "cerebras", "deepinfra", "nebius", "sambanova", "novita", "siliconflow", "sdwebui"):
        assert build_provider(pid, tmp_path).name == pid
    az = build_provider("azure", tmp_path, {"baseUrl": "https://x.openai.azure.com", "apiVersion": "2024-10-21"})
    assert az.name == "azure" and "deployments" in az._url("dep", "chat/completions")
    with pytest.raises(ValueError):
        build_provider("nope", tmp_path)
    with pytest.raises(ValueError):
        build_provider("mock", tmp_path)


def test_health_and_project(tmp_path, monkeypatch):
    monkeypatch.setenv("MTRINI_WORKSPACE", str(tmp_path))
    c = TestClient(app)
    assert c.get("/api/health").json()["ok"] is True
    assert c.get("/api/providers").status_code == 200
    assert c.get("/api/project").status_code == 200
    assert c.get("/api/runtimes").status_code == 200


def test_tools_execute_api(tmp_path, monkeypatch):
    monkeypatch.setenv("MTRINI_WORKSPACE", str(tmp_path))
    c = TestClient(app)
    r = c.post("/api/tools/execute", json={"tool": "write_file",
                                           "args": {"path": "a.txt", "content": "x"}})
    assert r.json()["ok"] is True


def test_agent_stub_stream(tmp_path, monkeypatch):
    _use_stub(monkeypatch)
    monkeypatch.setenv("MTRINI_WORKSPACE", str(tmp_path))
    c = TestClient(app)
    r = c.post("/api/agent", json={"provider": "local", "model": "stub-1",
                                   "message": "hello", "permissionMode": "auto"})
    assert r.status_code == 200
    assert r.status_code == 200
    assert "assistant_delta" in r.text or "done" in r.text


def test_config_never_stores_secrets(tmp_path):
    save_config(tmp_path, {"activeModel": "x", "apiKey": "SHOULD-NOT-PERSIST"})

    raw = (tmp_path / ".mtrini" / "config.json").read_text()
    assert "SHOULD-NOT-PERSIST" not in raw


def test_permission_gating():
    t = reg.BY_NAME["execute_command"]
    assert reg.needs_approval(t, "ask") is True
    assert reg.needs_approval(t, "auto") is False
    r = reg.BY_NAME["read_file"]
    assert reg.needs_approval(r, "ask") is False


def test_threads_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("MTRINI_WORKSPACE", str(tmp_path))
    c = TestClient(app)
    th = c.post("/api/threads", json={"title": "Hello"}).json()
    assert th["id"]
    c.post(f"/api/threads/{th['id']}/messages", json={"role": "user", "content": "hi"})
    got = c.get(f"/api/threads/{th['id']}").json()
    assert len(got["messages"]) == 1
    lst = c.get("/api/threads").json()["threads"]
    assert any(t["id"] == th["id"] for t in lst)
    assert c.get("/api/threads/nope").status_code == 404


def test_automations_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("MTRINI_WORKSPACE", str(tmp_path))
    c = TestClient(app)
    a = c.post("/api/automations", json={"name": "N", "prompt": "do X"}).json()
    assert a["id"]
    run = c.post(f"/api/automations/{a['id']}/run", json={}).json()
    assert run["thread"]["id"] and run["prompt"] == "do X"
    assert c.delete(f"/api/automations/{a['id']}").json()["ok"] is True


def test_git_commit_and_cached_diff(tmp_path, monkeypatch):
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=False)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, capture_output=True)
    (tmp_path / "f.txt").write_text("v1")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
    monkeypatch.setenv("MTRINI_WORKSPACE", str(tmp_path))
    c = TestClient(app)
    assert c.post("/api/git/commit", json={"message": "init"}).json()["ok"] is True
    assert c.post("/api/git/commit", json={"message": "  "}).status_code == 400
    (tmp_path / "f.txt").write_text("v2")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
    d = c.get("/api/git/diff", params={"cached": "true"}).json()
    assert d["ok"] is True and "v2" in d["output"]["stdout"]


def test_thread_rename_delete(tmp_path, monkeypatch):
    monkeypatch.setenv("MTRINI_WORKSPACE", str(tmp_path))
    c = TestClient(app)
    th = c.post("/api/threads", json={"title": "Old"}).json()
    r = c.patch(f"/api/threads/{th['id']}", json={"title": "New"}).json()
    assert r["title"] == "New"
    r2 = c.patch(f"/api/threads/{th['id']}", json={"title": "", "folder": str(tmp_path / "proj")}).json()
    assert r2["workspace"] == str(tmp_path / "proj")
    assert c.delete(f"/api/threads/{th['id']}").json()["ok"] is True
    assert c.get(f"/api/threads/{th['id']}").status_code == 404


def test_git_stage(tmp_path, monkeypatch):
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=False)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, capture_output=True)
    (tmp_path / "g.txt").write_text("staged-me")
    monkeypatch.setenv("MTRINI_WORKSPACE", str(tmp_path))
    c = TestClient(app)
    assert c.post("/api/git/stage", json={"paths": ["g.txt"]}).json()["ok"] is True
    assert c.post("/api/git/stage", json={"paths": []}).status_code == 400
    d = c.get("/api/git/diff", params={"cached": "true"}).json()
    assert "g.txt" in d["output"]["stdout"]


def test_browse(tmp_path):
    from fastapi.testclient import TestClient as TC

    (tmp_path / "sub").mkdir()
    c = TC(app)
    r = c.get("/api/browse", params={"path": str(tmp_path)}).json()
    assert any(d["name"] == "sub" for d in r["dirs"])
    assert r["parent"]
    assert c.get("/api/browse", params={"path": str(tmp_path / "nope")}).status_code == 400


def test_ui_mount_when_dist_present():
    from mtrini import main as mm

    if mm._DIST is None:
        pytest.skip("no frontend dist in checkout")
    assert any(getattr(r, "name", None) == "ui" for r in mm.app.routes)
    c = TestClient(app)
    r = c.get("/")
    assert r.status_code == 200 and "html" in r.headers["content-type"]


FAKE_MCP_SERVER = (
    "import sys, json\n"
    "def send(o): sys.stdout.write(json.dumps(o) + '\\n'); sys.stdout.flush()\n"
    "tools = [{'name': 'echo', 'description': 'echo back', "
    "'inputSchema': {'type': 'object', 'properties': {'text': {'type': 'string'}}}}]\n"
    "for line in sys.stdin:\n"
    "    try: msg = json.loads(line)\n"
    "    except Exception: continue\n"
    "    m, mid = msg.get('method'), msg.get('id')\n"
    "    if m == 'initialize': send({'jsonrpc': '2.0', 'id': mid, 'result': {'protocolVersion': 'x', 'capabilities': {}}})\n"
    "    elif m == 'notifications/initialized': pass\n"
    "    elif m == 'tools/list': send({'jsonrpc': '2.0', 'id': mid, 'result': {'tools': tools}})\n"
    "    elif m == 'tools/call':\n"
    "        a = (msg.get('params') or {}).get('arguments', {})\n"
    "        send({'jsonrpc': '2.0', 'id': mid, 'result': {'content': [{'type': 'text', 'text': 'echo:' + str(a.get('text', ''))}]}})\n"
)


def test_mcp_stdio_roundtrip(tmp_path, monkeypatch):
    import sys as _sys

    import anyio

    from mtrini import mcp as _mcp

    srv = {"name": "fake", "transport": "stdio", "command": _sys.executable,
           "args": ["-u", "-c", FAKE_MCP_SERVER], "env": {}, "enabled": True}

    async def _go():
        name, entries, err = await _mcp._server_tools(tmp_path, srv)
        assert err == "" and len(entries) == 1 and entries[0]["name"] == "echo"
        session = await _mcp.StdioSession(srv).run()
        try:
            out = await _mcp.StdioSession.call_tool(session, "echo", {"text": "hi"})
        finally:
            await _mcp.StdioSession.close(session)
        assert out["content"][0]["text"] == "echo:hi"
    anyio.run(_go)
    monkeypatch.setenv("MTRINI_WORKSPACE", str(tmp_path))
    c = TestClient(app)
    assert c.post("/api/mcp/servers", json={"name": "bad name!"}).status_code == 400
    assert c.post("/api/mcp/servers", json={"name": "fake", "transport": "stdio",
                                            "command": "x", "args": []}).json()["name"] == "fake"
    assert len(c.get("/api/mcp/servers").json()["servers"]) == 1
    assert c.patch("/api/mcp/servers/fake", json={"enabled": False}).json()["ok"] is True
    assert c.delete("/api/mcp/servers/fake").json()["ok"] is True


def test_mcp_json_import_export(tmp_path, monkeypatch):
    monkeypatch.setenv("MTRINI_WORKSPACE", str(tmp_path))
    c = TestClient(app)
    claude = {"mcpServers": {
        "fs": {"command": "npx", "args": ["-y", "srv"], "env": {"A": "1"}},
        "web": {"url": "http://localhost:9000/mcp"},
        "bad name!": {"command": "x"},
    }}
    r = c.post("/api/mcp/import", json={"config": claude}).json()
    assert set(r["added"]) == {"fs", "web"} and len(r["errors"]) == 1
    assert len(c.get("/api/mcp/servers").json()["servers"]) == 2
    # re-import preserves the disabled flag
    c.patch("/api/mcp/servers/fs", json={"enabled": False})
    c.post("/api/mcp/import", json={"config": claude}).json()
    fs = next(s for s in c.get("/api/mcp/servers").json()["servers"] if s["name"] == "fs")
    assert fs["enabled"] is False and fs["env"] == {"A": "1"}
    exp = c.get("/api/mcp/servers", params={"format": "claude"}).json()
    assert exp["mcpServers"]["fs"]["command"] == "npx"
    assert exp["mcpServers"]["web"] == {"url": "http://localhost:9000/mcp"}
    # array + single shapes
    assert c.post("/api/mcp/import", json={"config": [{"name": "a", "command": "x"}]}).json()["added"] == ["a"]
    assert c.post("/api/mcp/import", json={"config": {"name": "b", "transport": "http", "url": "https://h/mcp"}}).json()["added"] == ["b"]
    assert c.post("/api/mcp/import", json={}).status_code == 400


def test_images_api(tmp_path, monkeypatch):
    import base64

    import anyio
    import httpx
    import respx

    from mtrini import images as _img

    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

    async def _go():
        with respx.mock(base_url="http://localhost:8000") as r1:
            r1.post("/v1/images/generations").mock(
                return_value=httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(png).decode()}]}))
            entry = await _img.generate(tmp_path, "openai", "gpt-image-1", "a red square", "256x256")
        assert entry["bytes"] == len(png) and entry["size"] == "256x256"
        assert len(_img.list_images(tmp_path)) == 1
        assert _img.image_path(tmp_path, entry["id"]).exists()
        assert _img.delete_image(tmp_path, entry["id"]) is True
        assert _img.list_images(tmp_path) == []
        assert _img.support("openai") == "yes" and _img.support("local") == "maybe"
        assert _img.support("anthropic") == "no"
    anyio.run(_go)
    monkeypatch.setenv("MTRINI_WORKSPACE", str(tmp_path))
    c = TestClient(app)
    assert c.get("/api/images").json() == {"images": []}
    assert c.get("/api/images/support").json()["support"]["gemini"] == "yes"


def test_effort_mapping():
    from mtrini.agent.engine import EFFORT_TO_STEPS
    from mtrini.providers.openai_compat import (
        EFFORT_TO_ANTHROPIC_BUDGET,
        EFFORT_TO_GEMINI_BUDGET,
        EFFORT_TO_OPENAI,
        normalize_effort,
    )

    assert normalize_effort("HIGH") == "high"
    assert normalize_effort("bogus") == "off"
    assert EFFORT_TO_OPENAI == {"low": "low", "medium": "medium", "high": "high",
                                  "xhigh": "xhigh", "max": "xhigh"}
    assert EFFORT_TO_STEPS["low"] < EFFORT_TO_STEPS["off"] < EFFORT_TO_STEPS["max"]
    assert EFFORT_TO_ANTHROPIC_BUDGET["max"] == 32000
    assert EFFORT_TO_GEMINI_BUDGET["max"] == 24576


def test_effort_payloads():
    import anyio
    import httpx
    import respx

    from mtrini.providers import ChatMessage
    from mtrini.providers.cloud import OpenAIProvider
    from mtrini.providers.gemini_anthropic import AnthropicProvider, GeminiProvider

    async def _go():
        msgs = [ChatMessage(role="user", content="hi")]
        with respx.mock(base_url="https://api.openai.com") as r1:
            route = r1.post("/v1/chat/completions").mock(
                return_value=httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]}))
            await OpenAIProvider(api_key="x").chat("gpt-5", msgs, effort="high")
            import json as _j

            assert _j.loads(route.calls[0].request.content)["reasoning_effort"] == "high"
        with respx.mock(base_url="https://api.anthropic.com") as r2:
            route = r2.post("/v1/messages").mock(
                return_value=httpx.Response(200, json={"content": [{"type": "text", "text": "hi"}]}))
            await AnthropicProvider(api_key="x").chat("claude-x", msgs, effort="max")
            import json as _j

            body = _j.loads(route.calls[0].request.content)
            assert body["thinking"] == {"type": "enabled", "budget_tokens": 32000}
            assert body["max_tokens"] >= 33024
        with respx.mock(base_url="https://generativelanguage.googleapis.com") as r3:
            route = r3.post(url__regex=r".*generateContent.*").mock(
                return_value=httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "hi"}]}}]}))
            await GeminiProvider(api_key="x").chat("gemini-2.0-flash", msgs, effort="low")
            import json as _j

            body = _j.loads(route.calls[0].request.content)
            assert body["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 1024}
    anyio.run(_go)
