"""Project manager: .mtrini/ config, instructions, skills, agents."""
from __future__ import annotations

from pathlib import Path


def load_instructions(root: Path) -> str:
    p = root / ".mtrini" / "instructions.md"
    if p.exists():
        try:
            return p.read_text(encoding="utf-8")[:6000]
        except OSError:
            return ""
    return ""


def list_skills(root: Path) -> list[dict]:
    out = []
    for scope, base in (("project", root / ".mtrini" / "skills"),
                        ("global", Path.home() / ".mtrini" / "skills")):
        if not base.exists():
            continue
        for d in sorted(base.iterdir()):
            md = d / "SKILL.md"
            if d.is_dir() and md.exists():
                try:
                    text = md.read_text(encoding="utf-8")
                    first = next((l for l in text.splitlines() if l.strip()), d.name)
                    out.append({"name": d.name, "scope": scope, "summary": first[:200]})
                except OSError:
                    continue
    return out


def read_skill(root: Path, name: str) -> str:
    for base in (root / ".mtrini" / "skills" / name / "SKILL.md",
                 Path.home() / ".mtrini" / "skills" / name / "SKILL.md"):
        if base.exists():
            return base.read_text(encoding="utf-8")[:12000]
    raise FileNotFoundError(f"Skill not found: {name}")


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
