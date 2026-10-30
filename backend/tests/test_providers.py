"""Connected providers, provider settings kept across projects, thinking support per model."""
import sys

import pytest
from fastapi.testclient import TestClient

from mtrini.providers.registry import supports_reasoning


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", None)  # use the fallback file, never the real keychain
    monkeypatch.setenv("MTRINI_WORKSPACE", str(tmp_path / "projA"))
    (tmp_path / "projA").mkdir()
    from mtrini.main import app

    return TestClient(app)


def _connected(c, **params):
    return {p["id"] for p in c.get("/api/providers", params=params).json()["providers"] if p["configured"]}


def test_only_connected_providers_count(client, tmp_path):
    assert _connected(client) == set()  # nothing set up yet: no local server, no keys
    client.post("/api/providers/configure", json={"provider": "huggingface", "apiKey": "hf_x"})
    assert _connected(client) == {"huggingface"}  # an HF token no longer marks every key provider
    client.post("/api/providers/configure", json={"provider": "openai", "apiKey": "sk-x"})
    client.post("/api/providers/configure", json={"provider": "ollama", "baseUrl": "http://localhost:11434/v1"})
    assert _connected(client) == {"huggingface", "openai", "ollama"}
    client.post("/api/providers/disconnect", json={"provider": "openai"})
    assert _connected(client) == {"huggingface", "ollama"}  # disconnecting one leaves the others


def test_provider_settings_follow_you_across_projects(client, tmp_path):
    client.post("/api/providers/configure", json={"provider": "local", "baseUrl": "http://10.0.0.5:8000/v1"})
    client.post("/api/providers/configure", json={"provider": "mistral", "apiKey": "m-key"})
    other = tmp_path / "projB"
    other.mkdir()
    assert _connected(client, workspace=str(other)) >= {"local", "mistral"}
    from mtrini.config import provider_settings

    assert provider_settings(other, "local")["baseUrl"] == "http://10.0.0.5:8000/v1"
    assert not (tmp_path / "projA" / ".mtrini" / "secrets.json").exists()  # keys never land in a project


def test_image_providers_are_marked(client):
    kinds = {p["id"]: p["kind"] for p in client.get("/api/providers").json()["providers"]}
    assert kinds["sdwebui"] == "image" and kinds["openai"] == "chat"


@pytest.mark.parametrize("provider,model,ok", [
    ("anthropic", "claude-opus-5-5", True), ("anthropic", "claude-3-5-haiku", False),
    ("openai", "gpt-5", True), ("openai", "o4-mini", True), ("openai", "gpt-4o", False),
    ("gemini", "gemini-2.5-pro", True), ("gemini", "gemini-2.0-flash", False),
    ("ollama", "qwen2.5-coder", False), ("free", "qwen38", False), ("heabsy", "qwen38", False),
])
def test_thinking_levels_only_where_supported(provider, model, ok):
    assert supports_reasoning(provider, model) is ok


def test_models_report_reasoning(client):
    models = client.get("/api/models", params={"provider": "anthropic"}).json()["models"]
    assert models and all(m["capabilities"]["reasoning"] for m in models)


def test_free_model_goes_through_the_relay(tmp_path, monkeypatch):
    import anyio
    import httpx

    from mtrini.agent.engine import friendly_error
    from mtrini.providers import ChatMessage, free

    monkeypatch.setenv("MTRINI_FREE_URL", "https://relay.test")
    seen = {}

    def reply(request):
        seen["url"], seen["install"] = str(request.url), request.headers.get("x-mtrini-install")
        seen["model"] = __import__("json").loads(request.content)["model"]
        if seen.get("limit"):
            return httpx.Response(429, json={"error": {"message": "You've used today's free model allowance."}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(reply), **kw))
    p = free.FreeProvider()
    out = anyio.run(p.chat, "anything", [ChatMessage(role="user", content="hi")])
    assert out["content"] == "hi" and seen["url"] == "https://relay.test/v1/chat/completions"
    assert seen["model"] == "qwen38" and seen["install"] == free.install_id() and len(seen["install"]) == 32
    seen["limit"] = True
    with pytest.raises(free.FreeModelError) as e:
        anyio.run(p.chat, "qwen38", [ChatMessage(role="user", content="hi")])
    assert friendly_error(e.value) == "You've used today's free model allowance."


def test_free_model_listed_first_only_when_relay_is_set(client, monkeypatch):
    monkeypatch.delenv("MTRINI_FREE_URL", raising=False)
    assert "free" not in {p["id"] for p in client.get("/api/providers").json()["providers"]}
    monkeypatch.setenv("MTRINI_FREE_URL", "https://relay.test")
    first = client.get("/api/providers").json()["providers"][0]
    assert first["id"] == "free" and first["configured"] is True and first["defaultModel"] == "qwen38"
