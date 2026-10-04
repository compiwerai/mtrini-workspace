"""Terminal, Git, search, project-inspection, python tools."""
from __future__ import annotations

import asyncio
import re
import subprocess
from pathlib import Path
from typing import Any

from . import Tool


async def _run(cmd: str, cwd: Path, timeout: float = 120.0) -> dict[str, Any]:
    import os as _os

    if _os.name == "nt":
        proc = await asyncio.create_subprocess_shell(
            cmd, cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    else:
        proc = await asyncio.create_subprocess_shell(
            cmd, cwd=str(cwd), executable="/bin/sh",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        out, err = await proc.communicate()
        return {"exitCode": 124, "stdout": out.decode(errors="replace"),
                "stderr": (err.decode(errors="replace") + "\n[TIMEOUT]"), "cmd": cmd}
    return {"exitCode": proc.returncode, "stdout": out.decode(errors="replace")[-20000:],
            "stderr": err.decode(errors="replace")[-20000:], "cmd": cmd}


def _h_exec(root: Path, a: dict[str, Any]):
    return _run(a["command"], Path(a.get("cwd") or root), float(a.get("timeout", 120)))


def _git(root: Path, args: list[str]) -> dict[str, Any]:
    p = subprocess.run(["git"] + args, cwd=str(root), capture_output=True, text=True, timeout=30)
    return {"exitCode": p.returncode, "stdout": p.stdout[-20000:], "stderr": p.stderr[-5000:]}


def _h_git_status(root: Path, a: dict[str, Any]):
    return _git(root, ["status", "--porcelain=v1", "-b"])

def _h_git_diff(root: Path, a: dict[str, Any]):
    return _git(root, ["diff", "--", a.get("path", ".")])

def _h_git_log(root: Path, a: dict[str, Any]):
    return _git(root, ["log", f"-{int(a.get('limit', 20))}", "--oneline"])

def _h_git_branch(root: Path, a: dict[str, Any]):
    return _git(root, ["branch", "--show-current"])

def _h_git_show(root: Path, a: dict[str, Any]):
    return _git(root, ["show", "--stat", a.get("ref", "HEAD")])


def _h_search_code(root: Path, a: dict[str, Any]):
    pat, limit = a["pattern"], int(a.get("limit", 50))
    rx = re.compile(pat, re.IGNORECASE if a.get("ignoreCase") else 0)
    hits = []
    skip = {".git", "node_modules", "__pycache__", "dist", ".venv", "venv"}
    for p in root.rglob("*"):
        if len(hits) >= limit:
            break
        if any(s in p.parts for s in skip) or not p.is_file():
            continue
        try:
            if p.stat().st_size > 300_000:
                continue
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if rx.search(line):
                    hits.append({"file": str(p.relative_to(root)), "line": i, "text": line[:300]})
                    if len(hits) >= limit:
                        break
        except OSError:
            continue
    return {"hits": hits}


def _h_search_filename(root: Path, a: dict[str, Any]):
    q = a["pattern"].lower()
    out = []
    for p in root.rglob("*"):
        if len(out) >= int(a.get("limit", 50)):
            break
        if q in p.name.lower():
            out.append(str(p.relative_to(root)))
    return {"files": out}


def _h_inspect(root: Path, a: dict[str, Any]):
    files = [str(p.relative_to(root)) for p in root.iterdir()]
    def has(*names: str) -> bool:
        return any(n in files for n in names)
    lang = "unknown"
    if has("package.json"):
        lang = "typescript/javascript"
    elif has("pyproject.toml", "requirements.txt", "setup.py"):
        lang = "python"
    elif has("Cargo.toml"):
        lang = "rust"
    elif has("go.mod"):
        lang = "go"
    pm = "npm" if has("package-lock.json") else "pnpm" if has("pnpm-lock.yaml") else \
         "yarn" if has("yarn.lock") else "pip" if has("requirements.txt") else "unknown"
    fw = "unknown"
    try:
        pj = (root / "package.json")
        if pj.exists():
            import json as _j
            deps = {**_j.loads(pj.read_text()).get("dependencies", {}),
                    **_j.loads(pj.read_text()).get("devDependencies", {})}
            for cand in ("react", "next", "vue", "svelte", "express", "fastify"):
                if cand in deps:
                    fw = cand
                    break
    except Exception:
        pass
    return {"root": str(root), "language": lang, "packageManager": pm, "framework": fw,
            "topLevel": files[:100]}


def _h_python(root: Path, a: dict[str, Any]):
    import sys

    p = subprocess.run([sys.executable, "-c", a["code"]], cwd=str(root),
                       capture_output=True, text=True, timeout=int(a.get("timeout", 30)))
    return {"exitCode": p.returncode, "stdout": p.stdout[-20000:], "stderr": p.stderr[-5000:]}


TOOLS = [
    Tool("execute_command", "Run a shell command in the workspace", "execute",
         {"type": "object", "properties": {"command": {"type": "string"},
                                           "cwd": {"type": "string"}, "timeout": {"type": "number"}},
          "required": ["command"]}, _h_exec),
    Tool("git_status", "git status porcelain", "read", {"type": "object", "properties": {}}, _h_git_status),
    Tool("git_diff", "git diff for a path", "read",
         {"type": "object", "properties": {"path": {"type": "string"}}}, _h_git_diff),
    Tool("git_log", "recent commits", "read",
         {"type": "object", "properties": {"limit": {"type": "number"}}}, _h_git_log),
    Tool("git_branch", "current branch", "read", {"type": "object", "properties": {}}, _h_git_branch),
    Tool("git_show", "show a ref", "read",
         {"type": "object", "properties": {"ref": {"type": "string"}}}, _h_git_show),
    Tool("search_code", "Regex search across repo", "read",
         {"type": "object", "properties": {"pattern": {"type": "string"}, "limit": {"type": "number"}},
          "required": ["pattern"]}, _h_search_code),
    Tool("search_filename", "Find files by name substring", "read",
         {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]}, _h_search_filename),
    Tool("inspect_project", "Detect language/pm/framework + top-level listing", "read",
         {"type": "object", "properties": {}}, _h_inspect),
    Tool("detect_language", "Alias of inspect_project.language", "read",
         {"type": "object", "properties": {}}, lambda r, a: {"language": _h_inspect(r, a)["language"]}),
    Tool("detect_package_manager", "Alias of inspect_project.packageManager", "read",
         {"type": "object", "properties": {}}, lambda r, a: {"packageManager": _h_inspect(r, a)["packageManager"]}),
    Tool("run_python", "Execute a Python snippet", "execute",
         {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}, _h_python),
]
