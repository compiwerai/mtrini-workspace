"""Project manager: .mtrini/ config, instructions, skills, agents."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

# Skill names are folder names: lowercase slugs, so they can never escape the skills directory.
SKILL_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
SKILL_SCOPES = ("project", "global")
MAX_SKILL_CHARS = 12000


def load_instructions(root: Path) -> str:
    p = root / ".mtrini" / "instructions.md"
    if p.exists():
        try:
            return p.read_text(encoding="utf-8")[:6000]
        except OSError:
            return ""
    return ""


def skills_dir(root: Path, scope: str) -> Path:
    if scope == "project":
        return root / ".mtrini" / "skills"
    if scope == "global":
        return Path.home() / ".mtrini" / "skills"
    raise ValueError(f"Unknown skill scope: {scope}")


def valid_skill_name(name: str) -> bool:
    return bool(SKILL_NAME.match(name or ""))


def parse_skill(text: str) -> tuple[dict[str, str], str]:
    """Split a SKILL.md into its front matter (simple `key: value` lines) and body."""
    meta: dict[str, str] = {}
    body = text
    if text.startswith("---"):
        lines = text.splitlines()
        for i, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                for raw in lines[1:i]:
                    if ":" in raw:
                        k, v = raw.split(":", 1)
                        meta[k.strip().lower()] = v.strip().strip('"').strip("'")
                body = "\n".join(lines[i + 1:]).lstrip("\n")
                break
    return meta, body


def _describe(meta: dict[str, str], body: str, fallback: str) -> str:
    if meta.get("description"):
        return meta["description"][:300]
    for line in body.splitlines():
        s = line.strip().lstrip("#").strip()
        if s:
            return s[:300]
    return fallback


def list_skills(root: Path) -> list[dict]:
    out = []
    for scope in SKILL_SCOPES:
        base = skills_dir(root, scope)
        if not base.exists():
            continue
        for d in sorted(base.iterdir()):
            md = d / "SKILL.md"
            if d.is_dir() and md.exists() and valid_skill_name(d.name):
                try:
                    meta, body = parse_skill(md.read_text(encoding="utf-8"))
                except OSError:
                    continue
                desc = _describe(meta, body, d.name)
                # `summary` kept for older clients.
                out.append({"name": d.name, "scope": scope, "description": desc, "summary": desc})
    return out


def read_skill(root: Path, name: str) -> str:
    if not valid_skill_name(name):
        raise FileNotFoundError(f"Skill not found: {name}")
    for scope in SKILL_SCOPES:
        p = skills_dir(root, scope) / name / "SKILL.md"
        if p.exists():
            return p.read_text(encoding="utf-8")[:MAX_SKILL_CHARS]
    raise FileNotFoundError(f"Skill not found: {name}")


def write_skill(root: Path, name: str, description: str, body: str, scope: str = "project") -> Path:
    """Create or replace a skill as <scope dir>/<name>/SKILL.md with front matter."""
    if not valid_skill_name(name):
        raise ValueError("Skill names use lowercase letters, numbers and dashes (max 63 characters).")
    desc = " ".join((description or "").split())[:300]
    if not desc:
        raise ValueError("A one-line description is required.")
    text = (body or "").strip()
    if not text:
        raise ValueError("Skill instructions cannot be empty.")
    if len(text) > MAX_SKILL_CHARS:
        raise ValueError(f"Skill instructions are limited to {MAX_SKILL_CHARS} characters.")
    folder = skills_dir(root, scope) / name
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "SKILL.md"
    path.write_text(f"---\nname: {name}\ndescription: {desc}\n---\n\n{text}\n", encoding="utf-8")
    return path


def delete_skill(root: Path, name: str, scope: str = "project") -> bool:
    if not valid_skill_name(name):
        return False
    folder = skills_dir(root, scope) / name
    if not (folder / "SKILL.md").exists():
        return False
    shutil.rmtree(folder)
    return True


INVOKE = re.compile(r"(?:^|\s)/([a-z0-9][a-z0-9-]{0,62})\b")


def skill_context(root: Path, message: str, limit: int = 3) -> str:
    """System context for the agent: the available skills, plus the full text of any
    skill the user invoked with /skill-name in this message."""
    skills = list_skills(root)
    if not skills:
        return ""
    names = {s["name"] for s in skills}
    invoked: list[str] = []
    for m in INVOKE.finditer(message or ""):
        n = m.group(1)
        if n in names and n not in invoked:
            invoked.append(n)
    lines = ["Available skills (the user can invoke one with /name):"]
    lines += [f"- {s['name']}: {s['description']}" for s in skills[:40]]
    for n in invoked[:limit]:
        try:
            _, body = parse_skill(read_skill(root, n))
        except FileNotFoundError:
            continue
        lines.append(f"\nThe user invoked the skill /{n}. Follow these instructions:\n{body}")
    return "\n".join(lines)


def list_agents(root: Path) -> list[dict]:
    out = []
    base = root / ".mtrini" / "agents"
    if base.exists():
        for f in sorted(base.glob("*.md")):
            try:
                out.append({"name": f.stem, "content": f.read_text(encoding="utf-8")[:8000]})
            except OSError:
                continue
    return out
