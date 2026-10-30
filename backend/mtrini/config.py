"""Central configuration: workspace root, settings file, secrets.

Secrets (API keys, HF tokens) are NEVER stored in config.json.
They live in the OS keychain via `keyring` when available, otherwise in
.mtrini/secrets.json with 0600 permissions (documented fallback, gitignored).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "activeModel": "mock:mock-coder",
    "activeProvider": "mock",
    "theme": "dark",
    "router": {"fast": "", "coding": "", "reasoning": "", "vision": "", "general": ""},
    "permissions": {"defaultMode": "ask", "allowList": [], "denyList": []},
    "terminal": {"shell": "", "fontSize": 13},
    "context": {"maxTokens": 32000, "historyLimit": 40},
}


def workspace_root(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("MTRINI_WORKSPACE")
    if env:
        return Path(env).expanduser().resolve()
    return Path.cwd().resolve()


def mtrini_dir(root: Path) -> Path:
    d = root / ".mtrini"
    d.mkdir(parents=True, exist_ok=True)
    return d


def user_dir() -> Path:
    """Per-user folder (~/.mtrini): settings that belong to you, not to one project."""
    d = Path(os.environ.get("MTRINI_HOME") or Path.home() / ".mtrini")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _user_providers() -> dict[str, dict[str, Any]]:
    try:
        data = json.loads((user_dir() / "providers.json").read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def saved_providers() -> set[str]:
    """Providers you connected in Settings (kept for every project)."""
    return set(_user_providers())


def provider_settings(root: Path, provider: str) -> dict[str, Any]:
    """Saved settings for a provider: your user-level settings win over older per-project ones."""
    legacy = load_config(root).get(f"provider.{provider}", {})
    return {**(legacy if isinstance(legacy, dict) else {}), **_user_providers().get(provider, {})}


def save_provider_settings(provider: str, patch: dict[str, Any]) -> None:
    data = _user_providers()
    data[provider] = {**data.get(provider, {}),
                      **{k: v for k, v in patch.items() if "key" not in k.lower() and "token" not in k.lower()}}
    (user_dir() / "providers.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


CUSTOM_PREFIX = "custom-"


def custom_providers() -> list[dict[str, Any]]:
    """Your own OpenAI-compatible providers (any number), e.g. OrcaRouter, Kojo or a friend's server."""
    return [{"id": pid, "label": s.get("label") or pid, "baseUrl": s.get("baseUrl", "")}
            for pid, s in _user_providers().items() if pid.startswith(CUSTOM_PREFIX) and s.get("custom")]


def forget_provider(provider: str) -> None:
    data = _user_providers()
    if data.pop(provider, None) is not None:
        (user_dir() / "providers.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_config(root: Path) -> dict[str, Any]:
    cfg_path = mtrini_dir(root) / "config.json"
    cfg = dict(DEFAULT_CONFIG)
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update(data)
        except Exception:
            pass
    return cfg


def save_config(root: Path, cfg: dict[str, Any]) -> None:
    # Strip anything that looks like a secret before persisting.
    scrubbed = {k: v for k, v in cfg.items() if "key" not in k.lower() and "token" not in k.lower()}
    path = mtrini_dir(root) / "config.json"
    path.write_text(json.dumps(scrubbed, indent=2), encoding="utf-8")


# ---- secrets ----

def _fallback_path(root: Path) -> Path:
    # Per-user, not per-project: keys survive switching projects and never sit in a repo.
    return user_dir() / "secrets.json"


def _read_json(p: Path) -> dict[str, str]:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _read_fallback(root: Path) -> dict[str, str]:
    legacy = _read_json(root / ".mtrini" / "secrets.json")  # older versions kept it in the project
    return {**legacy, **_read_json(_fallback_path(root))}


def set_secret(root: Path, service: str, account: str, value: str) -> str:
    """Store a secret. Returns 'keyring' or 'file' depending on backend used."""
    try:
        import keyring  # type: ignore

        keyring.set_password(service, account, value)
        return "keyring"
    except Exception:
        data = _read_json(_fallback_path(root))
        data[f"{service}/{account}"] = value
        p = _fallback_path(root)
        p.write_text(json.dumps(data), encoding="utf-8")
        try:
            os.chmod(p, 0o600)
        except Exception:
            pass
        return "file"


def get_secret(root: Path, service: str, account: str) -> str | None:
    try:
        import keyring  # type: ignore

        v = keyring.get_password(service, account)
        if v:
            return v
    except Exception:
        pass
    return _read_fallback(root).get(f"{service}/{account}")


def delete_secret(root: Path, service: str, account: str) -> None:
    try:
        import keyring  # type: ignore

        try:
            keyring.delete_password(service, account)
        except Exception:
            pass
    except Exception:
        pass
    for p in (_fallback_path(root), root / ".mtrini" / "secrets.json"):
        data = _read_json(p)
        if data.pop(f"{service}/{account}", None) is not None:
            p.write_text(json.dumps(data), encoding="utf-8")


def redact(text: str, secrets: list[str]) -> str:
    out = text
    for s in secrets:
        if s and len(s) >= 4:
            out = out.replace(s, "***")
    return out
