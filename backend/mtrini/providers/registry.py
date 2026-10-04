"""Provider registry + factory. Agent code never imports a concrete provider."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import cloud as _cloud
from . import gemini_anthropic as _ga
from . import huggingface as _hf
from . import openai_compat as _compat


def build_provider(name: str, root: Path, settings: dict[str, Any] | None = None):
    from ..config import get_secret

    s = settings or {}
    if name == "local":
        return _cloud.LocalProvider(base_url=s.get("baseUrl", "http://localhost:8000/v1"),
                                    api_key=get_secret(root, "mtrini-local", "apiKey") or "")
    if name == "ollama":
        return _cloud.OllamaProvider(base_url=s.get("baseUrl", "http://localhost:11434/v1"),
                                     api_key=get_secret(root, "mtrini-ollama", "apiKey") or "")
    if name == "lmstudio":
        return _cloud.LMStudioProvider(base_url=s.get("baseUrl", "http://localhost:1234/v1"),
                                       api_key=get_secret(root, "mtrini-lmstudio", "apiKey") or "")
    if name == "custom":
        return _compat.OpenAICompatibleProvider(base_url=s.get("baseUrl", "http://localhost:8000/v1"),
                                                api_key=get_secret(root, "mtrini-custom", "apiKey") or "")
    if name == "openai":
        return _cloud.OpenAIProvider(api_key=get_secret(root, "mtrini-openai", "apiKey") or "")
    if name == "openrouter":
        return _cloud.OpenRouterProvider(api_key=get_secret(root, "mtrini-openrouter", "apiKey") or "")
    if name == "mistral":
        return _cloud.MistralProvider(api_key=get_secret(root, "mtrini-mistral", "apiKey") or "")
    if name == "deepseek":
        return _cloud.DeepSeekProvider(api_key=get_secret(root, "mtrini-deepseek", "apiKey") or "")
    if name == "groq":
        return _cloud.GroqProvider(api_key=get_secret(root, "mtrini-groq", "apiKey") or "")
    if name == "together":
        return _cloud.TogetherProvider(api_key=get_secret(root, "mtrini-together", "apiKey") or "")
    if name == "fireworks":
        return _cloud.FireworksProvider(api_key=get_secret(root, "mtrini-fireworks", "apiKey") or "")
    if name == "xai":
        return _cloud.XAIProvider(api_key=get_secret(root, "mtrini-xai", "apiKey") or "")
    if name == "cohere":
        return _cloud.CohereProvider(api_key=get_secret(root, "mtrini-cohere", "apiKey") or "")
    if name == "cerebras":
        return _cloud.CerebrasProvider(api_key=get_secret(root, "mtrini-cerebras", "apiKey") or "")
    if name == "deepinfra":
        return _cloud.DeepInfraProvider(api_key=get_secret(root, "mtrini-deepinfra", "apiKey") or "")
    if name == "nebius":
        return _cloud.NebiusProvider(api_key=get_secret(root, "mtrini-nebius", "apiKey") or "")
    if name == "sambanova":
        return _cloud.SambaNovaProvider(api_key=get_secret(root, "mtrini-sambanova", "apiKey") or "")
    if name == "novita":
        return _cloud.NovitaProvider(api_key=get_secret(root, "mtrini-novita", "apiKey") or "")
    if name == "siliconflow":
        return _cloud.SiliconFlowProvider(api_key=get_secret(root, "mtrini-siliconflow", "apiKey") or "")
    if name == "sdwebui":
        return _cloud.SDWebUIProvider(base_url=s.get("baseUrl", "http://127.0.0.1:7860"))
    if name == "azure":
        st = s if isinstance(s, dict) else {}
        return _cloud.AzureOpenAIProvider(
            base_url=st.get("baseUrl", ""),
            api_key=get_secret(root, "mtrini-azure", "apiKey") or "",
            api_version=st.get("apiVersion", "2024-10-21"))
    if name == "gemini":
        return _ga.GeminiProvider(api_key=get_secret(root, "mtrini-gemini", "apiKey") or "")
    if name == "anthropic":
        return _ga.AnthropicProvider(api_key=get_secret(root, "mtrini-anthropic", "apiKey") or "")
    if name == "huggingface":
        return _hf.HuggingFaceProvider(token=get_secret(root, "mtrini-hf", "token") or "")
    raise ValueError(f"Unknown provider: {name}")


PROVIDER_META = [
    {"id": "local", "label": "Local OpenAI-compatible server", "needsKey": False,
     "fields": ["baseUrl", "model"]},
    {"id": "ollama", "label": "Ollama (local)", "needsKey": False,
     "fields": ["baseUrl", "model"], "defaultBaseUrl": "http://localhost:11434/v1"},
    {"id": "lmstudio", "label": "LM Studio (local)", "needsKey": False,
     "fields": ["baseUrl", "model"], "defaultBaseUrl": "http://localhost:1234/v1"},
    {"id": "custom", "label": "Custom OpenAI-compatible API", "needsKey": True,
     "fields": ["baseUrl", "model"]},
    {"id": "openai", "label": "OpenAI", "needsKey": True},
    {"id": "gemini", "label": "Google Gemini", "needsKey": True},
    {"id": "anthropic", "label": "Anthropic", "needsKey": True},
    {"id": "openrouter", "label": "OpenRouter", "needsKey": True},
    {"id": "mistral", "label": "Mistral AI", "needsKey": True},
    {"id": "deepseek", "label": "DeepSeek", "needsKey": True},
    {"id": "groq", "label": "Groq", "needsKey": True},
    {"id": "together", "label": "Together AI", "needsKey": True},
    {"id": "fireworks", "label": "Fireworks AI", "needsKey": True},
    {"id": "xai", "label": "xAI (Grok)", "needsKey": True},
    {"id": "cohere", "label": "Cohere", "needsKey": True},
    {"id": "cerebras", "label": "Cerebras", "needsKey": True},
    {"id": "deepinfra", "label": "DeepInfra", "needsKey": True},
    {"id": "nebius", "label": "Nebius", "needsKey": True},
    {"id": "sambanova", "label": "SambaNova", "needsKey": True},
    {"id": "novita", "label": "Novita", "needsKey": True},
    {"id": "siliconflow", "label": "SiliconFlow", "needsKey": True},
    {"id": "sdwebui", "label": "Stable Diffusion WebUI (local images)", "needsKey": False,
     "fields": ["baseUrl", "model"], "defaultBaseUrl": "http://127.0.0.1:7860"},
    {"id": "azure", "label": "Azure OpenAI", "needsKey": True,
     "fields": ["baseUrl", "model", "apiVersion"],
     "hint": "Base URL = resource endpoint, Model = deployment name"},
    {"id": "huggingface", "label": "Hugging Face", "needsKey": True, "token": True},
]
