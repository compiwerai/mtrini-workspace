"""Thin wrappers for cloud providers over the OpenAI-compatible core."""
from __future__ import annotations

from typing import Any

from . import ChatMessage, ModelInfo
from .openai_compat import OpenAICompatibleProvider


class _CloudBase(OpenAICompatibleProvider):
    label = "cloud"

    async def list_models(self, **kw: Any) -> list[ModelInfo]:  # curated, no network needed
        return [ModelInfo(id=m, label=m, provider=self.name,
                          capabilities={"text": True, "tools": True, "streaming": True})
                for m in self.curated()]

    def curated(self) -> list[str]:
        return []


class OpenAIProvider(_CloudBase):
    name = "openai"

    def __init__(self, api_key: str = "", **kw: Any):
        super().__init__(base_url="https://api.openai.com/v1", api_key=api_key)

    def reasoning_value(self, effort: str) -> str | None:
        from .openai_compat import EFFORT_TO_OPENAI

        return EFFORT_TO_OPENAI.get(effort)

    def curated(self) -> list[str]:
        return ["gpt-4o", "gpt-4o-mini", "o1-mini"]


class OpenRouterProvider(_CloudBase):
    name = "openrouter"

    def __init__(self, api_key: str = "", **kw: Any):
        super().__init__(base_url="https://openrouter.ai/api/v1", api_key=api_key)

    def curated(self) -> list[str]:
        return ["meta-llama/llama-3.1-70b-instruct", "qwen/qwen-2.5-coder-32b-instruct",
                "google/gemma-2-27b-it", "mistralai/mistral-large"]


class LocalProvider(OpenAICompatibleProvider):
    """Local inference server (llama.cpp llama-server / Ollama / vLLM in OpenAI mode)."""
    name = "local"

    def __init__(self, base_url: str = "http://localhost:8000/v1", api_key: str = "", **kw: Any):
        super().__init__(base_url=base_url, api_key=api_key)


class OllamaProvider(LocalProvider):
    """Ollama (OpenAI-compatible route). Install: https://ollama.com"""
    name = "ollama"

    def __init__(self, base_url: str = "http://localhost:11434/v1", api_key: str = "", **kw: Any):
        super().__init__(base_url=base_url, api_key=api_key)

    async def list_models(self, **kw: Any) -> list[ModelInfo]:
        models = await super().list_models(**kw)
        if models:
            return models
        return [ModelInfo(id=m, label=m, provider="ollama",
                          capabilities={"text": True, "tools": True, "streaming": True})
                for m in ("qwen2.5-coder", "llama3.3", "deepseek-r1", "gemma3")]


class LMStudioProvider(LocalProvider):
    """LM Studio local server (http://localhost:1234/v1)."""
    name = "lmstudio"

    def __init__(self, base_url: str = "http://localhost:1234/v1", api_key: str = "", **kw: Any):
        super().__init__(base_url=base_url, api_key=api_key)


class MistralProvider(_CloudBase):
    name = "mistral"

    def __init__(self, api_key: str = "", **kw: Any):
        super().__init__(base_url="https://api.mistral.ai/v1", api_key=api_key)

    def curated(self) -> list[str]:
        return ["mistral-large-latest", "codestral-latest", "devstral-medium-latest"]


class DeepSeekProvider(_CloudBase):
    name = "deepseek"

    def __init__(self, api_key: str = "", **kw: Any):
        super().__init__(base_url="https://api.deepseek.com/v1", api_key=api_key)

    def curated(self) -> list[str]:
        return ["deepseek-chat", "deepseek-reasoner"]


class GroqProvider(_CloudBase):
    name = "groq"

    def __init__(self, api_key: str = "", **kw: Any):
        super().__init__(base_url="https://api.groq.com/openai/v1", api_key=api_key)

    def curated(self) -> list[str]:
        return ["llama-3.3-70b-versatile", "qwen-qwq-32b", "deepseek-r1-distill-llama-70b"]


class TogetherProvider(_CloudBase):
    name = "together"

    def __init__(self, api_key: str = "", **kw: Any):
        super().__init__(base_url="https://api.together.xyz/v1", api_key=api_key)

    def curated(self) -> list[str]:
        return ["meta-llama/Llama-3.3-70B-Instruct-Turbo", "Qwen/Qwen2.5-Coder-32B-Instruct",
                "deepseek-ai/DeepSeek-R1"]


class FireworksProvider(_CloudBase):
    name = "fireworks"

    def __init__(self, api_key: str = "", **kw: Any):
        super().__init__(base_url="https://api.fireworks.ai/inference/v1", api_key=api_key)

    def curated(self) -> list[str]:
        return ["accounts/fireworks/models/llama-v3p3-70b-instruct",
                "accounts/fireworks/models/qwen2p5-coder-32b-instruct"]


class XAIProvider(_CloudBase):
    name = "xai"

    def __init__(self, api_key: str = "", **kw: Any):
        super().__init__(base_url="https://api.x.ai/v1", api_key=api_key)

    def curated(self) -> list[str]:
        return ["grok-3", "grok-3-mini", "grok-3-fast"]


class CohereProvider(_CloudBase):
    name = "cohere"

    def __init__(self, api_key: str = "", **kw: Any):
        super().__init__(base_url="https://api.cohere.com/compatibility/v1", api_key=api_key)

    def curated(self) -> list[str]:
        return ["command-a-03-2025", "command-r-plus", "command-r7b-12-2024"]


class AzureOpenAIProvider(OpenAICompatibleProvider):
    """Azure OpenAI: base_url is the resource endpoint, model is the DEPLOYMENT name.

    Example: base_url https://my-resource.openai.azure.com, model gpt-4o-deploy
    """
    name = "azure"

    def __init__(self, base_url: str = "", api_key: str = "",
                 api_version: str = "2024-10-21", **kw: Any):
        super().__init__(base_url=base_url, api_key=api_key)
        self.api_version = api_version or "2024-10-21"

    def _url(self, model: str, suffix: str) -> str:
        return (f"{self.base_url.rstrip('/')}/openai/deployments/{model}"
                f"/{suffix}?api-version={self.api_version}")

    def _headers(self) -> dict[str, str]:
        # Azure accepts Bearer or api-key; send both forms harmlessly.
        return {"Content-Type": "application/json", "api-key": self.api_key,
                "Authorization": f"Bearer {self.api_key}"}

    def reasoning_value(self, effort: str) -> str | None:
        from .openai_compat import EFFORT_TO_OPENAI

        return EFFORT_TO_OPENAI.get(effort)

    async def chat(self, model: str, messages: list[ChatMessage], tools: list[dict] | None = None, **kw: Any) -> dict[str, Any]:
        import httpx

        from .openai_compat import normalize_effort

        effort = normalize_effort(kw.get("effort"))
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            r = await c.post(self._url(model, "chat/completions"), headers=self._headers(),
                             json=self._payload(model, messages, tools, False, effort))
            r.raise_for_status()
            data = r.json()
        choice = data["choices"][0]["message"]
        calls = [{"id": tc.get("id"), "name": tc.get("function", {}).get("name"),
                  "arguments": tc.get("function", {}).get("arguments", "{}")}
                 for tc in choice.get("tool_calls") or []]
        return {"content": choice.get("content") or "", "tool_calls": calls, "raw": data}

    async def stream(self, model: str, messages: list[ChatMessage], tools: list[dict] | None = None, **kw: Any):
        import httpx

        from .openai_compat import normalize_effort

        effort = normalize_effort(kw.get("effort"))
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            async with c.stream("POST", self._url(model, "chat/completions"), headers=self._headers(),
                                json=self._payload(model, messages, tools, True, effort)) as r:
                r.raise_for_status()
                async for chunk in r.aiter_text():
                    for line in chunk.splitlines():
                        if line.startswith("data:") and "[DONE]" not in line:
                            try:
                                import json as _j

                                d = _j.loads(line[5:])
                                t = d["choices"][0].get("delta", {}).get("content")
                                if t:
                                    yield {"delta": t}
                            except Exception:
                                continue
        yield {"done": True}

    async def list_models(self, **kw: Any) -> list[ModelInfo]:
        return []  # deployments are customer-defined; user types the deployment name


class CerebrasProvider(_CloudBase):
    name = "cerebras"

    def __init__(self, api_key: str = "", **kw: Any):
        super().__init__(base_url="https://api.cerebras.ai/v1", api_key=api_key)

    def curated(self) -> list[str]:
        return ["llama-3.3-70b", "qwen-3-32b", "gpt-oss-120b"]


class DeepInfraProvider(_CloudBase):
    name = "deepinfra"

    def __init__(self, api_key: str = "", **kw: Any):
        super().__init__(base_url="https://api.deepinfra.com/v1/openai", api_key=api_key)

    def curated(self) -> list[str]:
        return ["meta-llama/Llama-3.3-70B-Instruct", "Qwen/Qwen2.5-Coder-32B-Instruct",
                "deepseek-ai/DeepSeek-R1"]


class NebiusProvider(_CloudBase):
    name = "nebius"

    def __init__(self, api_key: str = "", **kw: Any):
        super().__init__(base_url="https://api.studio.nebius.com/v1/", api_key=api_key)

    def curated(self) -> list[str]:
        return ["meta-llama/Llama-3.3-70B-Instruct", "Qwen/Qwen2.5-32B-Instruct"]


class SambaNovaProvider(_CloudBase):
    name = "sambanova"

    def __init__(self, api_key: str = "", **kw: Any):
        super().__init__(base_url="https://api.sambanova.ai/v1", api_key=api_key)

    def curated(self) -> list[str]:
        return ["Meta-Llama-3.3-70B-Instruct", "DeepSeek-R1-Distill-Llama-70B"]


class NovitaProvider(_CloudBase):
    name = "novita"

    def __init__(self, api_key: str = "", **kw: Any):
        super().__init__(base_url="https://api.novita.ai/openai/v1", api_key=api_key)

    def curated(self) -> list[str]:
        return ["meta-llama/llama-3.3-70b-instruct", "qwen/qwen-2.5-coder-32b-instruct"]


class SiliconFlowProvider(_CloudBase):
    name = "siliconflow"

    def __init__(self, api_key: str = "", **kw: Any):
        super().__init__(base_url="https://api.siliconflow.cn/v1", api_key=api_key)

    def curated(self) -> list[str]:
        return ["Qwen/Qwen2.5-72B-Instruct", "deepseek-ai/DeepSeek-R1",
                "meta-llama/Llama-3.3-70B-Instruct"]


class SDWebUIProvider:
    """Stable Diffusion WebUI (AUTOMATIC1111) local image backend: http://127.0.0.1:7860."""
    name = "sdwebui"

    def __init__(self, base_url: str = "http://127.0.0.1:7860", api_key: str = "", **kw: Any):
        self.base_url = base_url.rstrip("/")
        self.timeout = 600.0

    async def chat(self, model: str, messages: list[ChatMessage], tools: list[dict] | None = None, **kw: Any) -> dict[str, Any]:
        return {"content": "sdwebui is an image backend and does not chat.", "tool_calls": []}

    async def stream(self, model: str, messages: list[ChatMessage], tools: list[dict] | None = None, **kw: Any):
        yield {"delta": "sdwebui is an image backend and does not chat."}
        yield {"done": True}

    async def list_models(self, **kw: Any) -> list[ModelInfo]:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{self.base_url}/sdapi/v1/sd-models")
                r.raise_for_status()
                return [ModelInfo(id=m.get("model_name", "?"), label=m.get("model_name", "?"),
                                  provider="sdwebui", capabilities={"image": True})
                        for m in r.json()]
        except Exception:
            return [ModelInfo(id="sd-checkpoint", label="SD checkpoint (WebUI must run with --api)",
                              provider="sdwebui", capabilities={"image": True})]

    def supports_tools(self) -> bool:
        return False

    def supports_vision(self) -> bool:
        return False

    def supports_streaming(self) -> bool:
        return False
