"""Model registry (SQLite), runtime detection, downloader (HF hub)."""
from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any


def _db(root: Path) -> Path:
    d = root / ".mtrini"
    d.mkdir(parents=True, exist_ok=True)
    return d / "models.db"


def init_db(root: Path) -> sqlite3.Connection:
    con = sqlite3.connect(_db(root))
    con.execute("""CREATE TABLE IF NOT EXISTS models(
      id TEXT PRIMARY KEY, provider TEXT, format TEXT, params TEXT,
      quant TEXT, context INTEGER, path TEXT, status TEXT, updated INTEGER)""")
    return con


def upsert(root: Path, m: dict[str, Any]) -> None:
    con = init_db(root)
    con.execute("""INSERT INTO models(id,provider,format,params,quant,context,path,status,updated)
      VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
      provider=excluded.provider, format=excluded.format, params=excluded.params,
      quant=excluded.quant, context=excluded.context, path=excluded.path,
      status=excluded.status, updated=excluded.updated""",
                (m.get("id"), m.get("provider", ""), m.get("format", ""), m.get("params", ""),
                 m.get("quant", ""), m.get("context", 0), m.get("path", ""),
                 m.get("status", "ready"), int(time.time())))
    con.commit()
    con.close()


def list_models(root: Path) -> list[dict[str, Any]]:
    con = init_db(root)
    rows = con.execute("SELECT id,provider,format,params,quant,context,path,status FROM models").fetchall()
    con.close()
    return [{"id": r[0], "provider": r[1], "format": r[2], "params": r[3],
             "quant": r[4], "context": r[5], "path": r[6], "status": r[7]} for r in rows]


def detect_runtimes() -> dict[str, Any]:
    def which(x: str) -> bool:
        return shutil.which(x) is not None
    import sys

    return {
        "python": True, "pythonVersion": sys.version.split()[0],
        "git": which("git"), "node": which("node"),
        "ollama": which("ollama"), "llamacpp": which("llama-server") or which("llama.cpp") or which("llamacpp"),
        "vllm": False,
    }


async def check_endpoint(base_url: str, timeout: float = 5.0) -> dict[str, Any]:
    import httpx

    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.get(base_url.rstrip("/") + "/models")
            return {"reachable": r.status_code < 500, "status": r.status_code}
    except Exception as e:
        return {"reachable": False, "error": str(e)[:300]}


def download_snapshot(root: Path, repo: str, token: str | None = None) -> dict[str, Any]:
    from huggingface_hub import snapshot_download

    dest = root / ".mtrini" / "models" / repo.replace("/", "__")
    dest.mkdir(parents=True, exist_ok=True)
    path = snapshot_download(repo_id=repo, local_dir=str(dest), token=token or None,
                             resume_download=True)
    return {"path": path}
