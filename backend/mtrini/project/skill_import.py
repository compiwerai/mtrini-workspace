"""Import skills (SKILL.md files) from GitHub.

Accepts `owner/repo`, a repository URL, a folder URL (.../tree/<ref>/<path>) or a file URL
(.../blob/<ref>/<path>/SKILL.md). `preview` lists the skills found without writing anything;
`install` writes the ones the user picked. Everything goes through api.github.com (no git, no clone),
and only SKILL.md text is imported: scripts and other files in a skill folder are never downloaded or run.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import httpx

from .. import __version__
from . import MAX_SKILL_CHARS, parse_skill, read_skill, valid_skill_name, write_skill

API = "https://api.github.com"
MAX_SKILLS = 60
_PART = r"[A-Za-z0-9_.-]+"


@dataclass
class Source:
    owner: str
    repo: str
    ref: str | None = None
    path: str = ""
    is_file: bool = False


def parse_url(url: str) -> Source:
    s = (url or "").strip().removesuffix("/").removesuffix(".git")
    m = re.fullmatch(rf"({_PART})/({_PART})", s)
    if m:
        return Source(m[1], m[2])
    m = re.fullmatch(rf"(?:https?://)?(?:www\.)?github\.com/({_PART})/({_PART})(?:/(tree|blob)/([^/]+)(?:/(.*))?)?", s)
    if not m:
        raise ValueError("Paste a GitHub link like github.com/owner/repo, or owner/repo.")
    owner, repo, kind, ref, path = m[1], m[2], m[3], m[4], (m[5] or "").strip("/")
    return Source(owner, repo, ref, path, kind == "blob")


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9-]+", "-", (name or "").lower()).strip("-")
    s = re.sub(r"-{2,}", "-", s)[:63].strip("-")
    return s


def _client() -> httpx.Client:
    return httpx.Client(timeout=20, follow_redirects=True,
                        headers={"User-Agent": f"MtriniWorkspace/{__version__}", "Accept": "application/vnd.github+json"})


def _get(c: httpx.Client, path: str, raw: bool = False) -> httpx.Response:
    r = c.get(API + path, headers={"Accept": "application/vnd.github.raw"} if raw else None)
    if r.status_code == 404:
        raise ValueError("Not found on GitHub. Check the link, and that the repository is public.")
    if r.status_code in (403, 429):
        raise ValueError("GitHub is rate-limiting requests right now. Try again in a few minutes.")
    r.raise_for_status()
    return r


def _skill_paths(c: httpx.Client, src: Source) -> tuple[str, list[str]]:
    ref = src.ref or _get(c, f"/repos/{src.owner}/{src.repo}").json().get("default_branch", "main")
    if src.is_file:
        if not src.path.lower().endswith(".md"):
            raise ValueError("That file is not a Markdown skill. Link a SKILL.md file or a folder.")
        return ref, [src.path]
    tree = _get(c, f"/repos/{src.owner}/{src.repo}/git/trees/{quote(ref, safe='')}?recursive=1").json()
    prefix = (src.path + "/") if src.path else ""
    paths = [t["path"] for t in tree.get("tree", [])
             if t.get("type") == "blob" and t["path"].rsplit("/", 1)[-1] == "SKILL.md"
             and (t["path"].startswith(prefix) or not prefix)]
    return ref, sorted(paths)[:MAX_SKILLS]


def _name_for(path: str, meta: dict[str, str]) -> str:
    folder = path.rsplit("/", 2)[-2] if "/" in path else ""
    for candidate in (meta.get("name", ""), folder, Path(path).stem):
        s = slug(candidate)
        if valid_skill_name(s):
            return s
    return ""


def _existing(root: Path, name: str) -> bool:
    try:
        read_skill(root, name)
        return True
    except FileNotFoundError:
        return False


def preview(root: Path, url: str) -> dict:
    """Find SKILL.md files at the link and describe them, without writing anything."""
    src = parse_url(url)
    found = []
    with _client() as c:
        ref, paths = _skill_paths(c, src)
        if not paths:
            raise ValueError("No SKILL.md files found there.")
        for p in paths:
            text = _get(c, f"/repos/{src.owner}/{src.repo}/contents/{quote(p)}?ref={quote(ref, safe='')}", raw=True).text
            meta, body = parse_skill(text)
            name = _name_for(p, meta)
            item = {"path": p, "name": name, "description": " ".join(meta.get("description", "").split())[:300],
                    "chars": len(body), "exists": bool(name) and _existing(root, name), "ok": True, "reason": ""}
            if not name:
                item.update(ok=False, reason="No usable name")
            elif not body.strip():
                item.update(ok=False, reason="Empty")
            elif len(body.strip()) > MAX_SKILL_CHARS:
                item.update(ok=False, reason=f"Longer than {MAX_SKILL_CHARS:,} characters")
            if not item["description"]:
                item["description"] = next((l.strip().lstrip("#").strip() for l in body.splitlines() if l.strip()), name)[:300]
            item["_body"] = body
            found.append(item)
    return {"source": f"{src.owner}/{src.repo}", "ref": ref, "skills": found}


def install(root: Path, url: str, names: list[str], scope: str = "project", overwrite: bool = False) -> dict:
    """Write the picked skills. Existing skills are kept unless overwrite is set."""
    found = preview(root, url)
    want = set(names)
    added, skipped = [], []
    for s in found["skills"]:
        if s["name"] not in want:
            continue
        if not s["ok"]:
            skipped.append({"name": s["name"], "reason": s["reason"]})
        elif s["exists"] and not overwrite:
            skipped.append({"name": s["name"], "reason": "Already installed"})
        else:
            note = f"\n\n<!-- Imported from github.com/{found['source']} ({found['ref']}): {s['path']} -->"
            write_skill(root, s["name"], s["description"], s["_body"].strip()[: MAX_SKILL_CHARS - len(note)] + note, scope)
            added.append(s["name"])
    return {"added": added, "skipped": skipped, "source": found["source"]}


def public(found: dict) -> dict:
    """Preview result without the skill bodies (for the API)."""
    return {**found, "skills": [{k: v for k, v in s.items() if not k.startswith("_")} for s in found["skills"]]}
