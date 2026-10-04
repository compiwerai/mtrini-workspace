"""Hugging Face provider: search, details, file listing via huggingface-hub."""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from . import ChatMessage, ModelInfo


class HuggingFaceProvider:
    name = "huggingface"

    def __init__(self, token: str = ""):
        self.token = token

    def _api(self):
        from huggingface_hub import HfApi

        return HfApi(token=self.token or None)

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        api = self._api()
        out = []
        for m in api.list_models(search=query, limit=limit):
            out.append({"id": m.id, "likes": getattr(m, "likes", 0),
                        "tags": getattr(m, "tags", []),
                        "lastModified": str(getattr(m, "last_modified", ""))})
        return out

    def details(self, repo: str) -> dict[str, Any]:
        api = self._api()
        info = api.model_info(repo)
        siblings = [s.rfilename for s in getattr(info, "siblings", []) or []]
        return {"id": info.id, "tags": getattr(info, "tags", []),
                "pipeline": getattr(info, "pipeline_tag", None),
                "siblings": siblings[:200], "card": getattr(info, "cardData", None)}

    def whoami(self) -> dict[str, Any]:
        api = self._api()
        try:
            u = api.whoami()
            return {"name": u.get("name"), "type": u.get("type")}
        except Exception as e:
            return {"error": str(e)}

    async def chat(self, model: str, messages: list[ChatMessage], tools: list[dict] | None = None, **kw: Any) -> dict[str, Any]:
        # HF Inference Providers endpoint (OpenAI-compatible route).
        import httpx

        sys = "\n".join(m.content for m in messages if m.role == "system")
        prompt = ((sys + "\n\n") if sys else "") + "\n".join(
            f"{m.role}: {m.content}" for m in messages if m.role != "system")
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(f"https://api-inference.huggingface.co/models/{model}",
                             headers=headers, json={"inputs": prompt, "parameters": {"max_new_tokens": 512}})
            r.raise_for_status()
            data = r.json()
        if isinstance(data, list) and data:
            text = data[0].get("generated_text", str(data[0]))
        else:
            text = str(data)
        return {"content": text, "tool_calls": []}

    async def stream(self, model: str, messages: list[ChatMessage], tools: list[dict] | None = None, **kw: Any) -> AsyncIterator[dict[str, Any]]:
        res = await self.chat(model, messages, tools, **kw)
        yield {"delta": res["content"]}
        yield {"done": True}

    async def list_models(self, **kw: Any) -> list[ModelInfo]:
        return []

    def supports_tools(self) -> bool:
        return False

    def supports_vision(self) -> bool:
        return False

    def supports_streaming(self) -> bool:
        return False
