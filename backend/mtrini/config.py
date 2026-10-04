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
    return mtrini_dir(root) / "secrets.json"


def _read_fallback(root: Path) -> dict[str, str]:
    p = _fallback_path(root)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def set_secret(root: Path, service: str, account: str, value: str) -> str:
    """Store a secret. Returns 'keyring' or 'file' depending on backend used."""
    try:
        import keyring  # type: ignore

        keyring.set_password(service, account, value)
        return "keyring"
    except Exception:
        data = _read_fallback(root)
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
    data = _read_fallback(root)
    data.pop(f"{service}/{account}", None)
    _fallback_path(root).write_text(json.dumps(data), encoding="utf-8")


def redact(text: str, secrets: list[str]) -> str:
    out = text
    for s in secrets:
        if s and len(s) >= 4:
            out = out.replace(s, "***")
    return out
