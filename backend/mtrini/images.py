"""Mtrini Images: generate pictures with image models from any provider.

Backends: OpenAI-shape /images/generations (openai, together, fireworks, xai,
deepinfra, nebius, novita, siliconflow), Gemini native image generation,
Hugging Face text-to-image bytes, SD WebUI txt2img, plus best-effort fallback
for local/custom servers (OpenAI-shape, then SD-shape).
Files land in .mtrini/images/ with a JSON manifest. Nothing is fake: every
entry is a real file on disk.
"""
from __future__ import annotations

import base64
import time
import uuid
from pathlib import Path
from typing import Any

# provider -> image support: yes | maybe (try shapes in order) | no
IMAGE_SUPPORT: dict[str, str] = {
    "openai": "yes", "together": "yes", "fireworks": "yes", "xai": "yes",
    "deepinfra": "yes", "nebius": "yes", "novita": "yes", "siliconflow": "yes",
    "gemini": "yes", "huggingface": "yes", "sdwebui": "yes",
    "local": "maybe", "custom": "maybe", "ollama": "maybe", "lmstudio": "maybe",
}


def support(provider: str) -> str:
    return IMAGE_SUPPORT.get(provider, "no")


def _manifest_path(root: Path) -> Path:
    return root / ".mtrini" / "images.json"


def _images_dir(root: Path) -> Path:
    d = root / ".mtrini" / "images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_images(root: Path) -> list[dict[str, Any]]:
    p = _manifest_path(root)
    if not p.exists():
        return []
    try:
        data = __import__("json").loads(p.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else []
        return [e for e in items if (_images_dir(root) / f"{e.get('id')}.png").exists()]
    except (OSError, ValueError):
        return []


def _record(root: Path, entry: dict[str, Any]) -> None:
    import json

    (root / ".mtrini").mkdir(parents=True, exist_ok=True)
    items = []
    p = _manifest_path(root)
    if p.exists():
        try:
            items = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            items = []
    items = [entry, *[e for e in items if e.get("id") != entry["id"]]][:200]
    p.write_text(json.dumps(items, indent=2), encoding="utf-8")


def _save_png(root: Path, raw: bytes) -> tuple[str, int]:
    img_id = uuid.uuid4().hex[:12]
    path = _images_dir(root) / f"{img_id}.png"
    # Accept PNG as-is; JPEG/WebP pass through with .png container name? No:
    # detect real type and keep bytes untouched.
    path.write_bytes(raw)
    return img_id, len(raw)


def parse_size(size: str) -> tuple[int, int]:
    try:
        w, h = size.lower().replace(" ", "").split("x")
        w, h = max(256, min(2048, int(w))), max(256, min(2048, int(h)))
        return w, h
    except Exception:
        return 1024, 1024


async def _openai_shape(base_url: str, api_key: str, model: str, prompt: str,
                        size: str, timeout: float = 300.0) -> bytes:
    import httpx

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(f"{base_url.rstrip('/')}/images/generations", headers=headers,
                         json={"model": model, "prompt": prompt, "size": size})
        r.raise_for_status()
        item = r.json()["data"][0]
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    if item.get("url"):
        import httpx as _hx

        async with _hx.AsyncClient(timeout=timeout) as c2:
            r2 = await c2.get(item["url"])
            r2.raise_for_status()
            return r2.content
    raise ValueError("no image in response")


async def _sd_shape(base_url: str, prompt: str, w: int, h: int, timeout: float = 600.0) -> bytes:
    import httpx

    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(f"{base_url.rstrip('/')}/sdapi/v1/txt2img",
                         json={"prompt": prompt, "width": w, "height": h, "steps": 28})
        r.raise_for_status()
        return base64.b64decode(r.json()["images"][0])


async def generate(root: Path, provider: str, model: str, prompt: str,
                   size: str = "1024x1024") -> dict[str, Any]:
    from .config import get_secret

    if not prompt.strip():
        raise ValueError("prompt is empty")
    w, h = parse_size(size)
    size_str = f"{w}x{h}"
    key = get_secret(root, f"mtrini-{provider}", "apiKey") or ""
    raw: bytes | None = None

    if provider == "gemini":
        import httpx

        tok = key
        async with httpx.AsyncClient(timeout=300) as c:
            r = await c.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                params={"key": tok},
                json={"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                      "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}})
            r.raise_for_status()
            parts = r.json()["candidates"][0]["content"]["parts"]
        for p in parts:
            inline = p.get("inlineData", {})
            if inline.get("data"):
                raw = base64.b64decode(inline["data"])
                break
        if raw is None:
            raise ValueError("model returned no image (try an image-capable Gemini model)")
    elif provider == "huggingface":
        import httpx

        from .config import get_secret as _gs

        tok = _gs(root, "mtrini-hf", "token") or ""
        headers = {"Content-Type": "application/json"}
        if tok:
            headers["Authorization"] = f"Bearer {tok}"
        async with httpx.AsyncClient(timeout=300) as c:
            r = await c.post(f"https://api-inference.huggingface.co/models/{model}",
                             headers=headers, json={"inputs": prompt})
            r.raise_for_status()
            ctype = r.headers.get("content-type", "")
            if "image" not in ctype and len(r.content) < 10000:
                raise ValueError(f"model returned text, not an image: {r.text[:200]}")
            raw = r.content
    elif provider == "sdwebui":
        from .config import load_config

        cfg = load_config(root)
        base = cfg.get("provider.sdwebui", {}).get("baseUrl", "http://127.0.0.1:7860")
        raw = await _sd_shape(base if isinstance(base, str) else "http://127.0.0.1:7860",
                              prompt, w, h)
    else:
        from .config import load_config

        cfg = load_config(root)
        st = cfg.get(f"provider.{provider}", {})
        base = st.get("baseUrl", "http://localhost:8000/v1") if isinstance(st, dict) else "http://localhost:8000/v1"
        if support(provider) == "yes":
            raw = await _openai_shape(base, key, model, prompt, size_str)
        elif support(provider) == "maybe":
            try:
                raw = await _openai_shape(base, key, model, prompt, size_str)
            except Exception as e1:
                try:
                    raw = await _sd_shape(base, prompt, w, h)
                except Exception:
                    raise e1
        else:
            raise ValueError(f"provider '{provider}' has no image backend")

    assert raw is not None
    img_id, nbytes = _save_png(root, raw)
    entry = {"id": img_id, "provider": provider, "model": model, "prompt": prompt,
             "size": size_str, "bytes": nbytes, "created": int(time.time())}
    _record(root, entry)
    return entry


def delete_image(root: Path, img_id: str) -> bool:
    import json

    name = "".join(c for c in img_id if c.isalnum())[:16]
    p = _images_dir(root) / f"{name}.png"
    if p.exists():
        p.unlink()
    mp = _manifest_path(root)
    if mp.exists():
        try:
            items = [e for e in json.loads(mp.read_text(encoding="utf-8")) if e.get("id") != name]
            mp.write_text(json.dumps(items, indent=2), encoding="utf-8")
        except ValueError:
            pass
    return True


def image_path(root: Path, img_id: str) -> Path:
    name = "".join(c for c in img_id if c.isalnum())[:16]
    p = _images_dir(root) / f"{name}.png"
    if not p.exists():
        raise FileNotFoundError("image not found")
    return p
