"""Small features built on threads, git and the current model.

- Export a thread as Markdown or as one self-contained HTML page you can share.
- Write a commit message from the staged (or unstaged) diff.
- Improve a rough prompt before you send it.

Exports carry the conversation and the names of the steps the agent took (file paths,
commands), never tool outputs, which can hold file contents or secrets.
"""
from __future__ import annotations

import html
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from . import threads
from .proc import NO_WINDOW
from .providers import ChatMessage

BADGE = "Made with Mtrini Workspace · github.com/compiwerai/mtrini-workspace"
REPO_URL = "https://github.com/compiwerai/mtrini-workspace"


# ---- export ----------------------------------------------------------------------------

def _step(m: dict) -> str:
    """One line for a tool step: what it touched, never what it returned."""
    tool = str(m.get("tool") or "tool")
    a = m.get("args") if isinstance(m.get("args"), dict) else {}
    target = a.get("path") or a.get("file_path") or a.get("command") or a.get("query") or a.get("url") or ""
    if isinstance(target, list):
        target = " ".join(map(str, target))
    target = str(target).replace("\n", " ")[:160]
    mark = "" if m.get("ok", True) else " (failed)"
    return f"{tool} {target}".strip() + mark


def _turns(data: dict) -> list[tuple[str, Any]]:
    """Group the thread into (role, content) blocks; runs of tool steps become one 'steps' block."""
    out: list[tuple[str, Any]] = []
    for m in data.get("messages", []):
        role = m.get("role")
        if role == "tool":
            if out and out[-1][0] == "steps":
                out[-1][1].append(_step(m))
            else:
                out.append(("steps", [_step(m)]))
        elif role in ("user", "assistant") and str(m.get("content") or "").strip():
            out.append((role, str(m["content"]).strip()))
    return out


def to_markdown(data: dict) -> str:
    lines = [f"# {data.get('title') or 'Mtrini session'}", ""]
    for role, content in _turns(data):
        if role == "steps":
            lines += [f"<details><summary>{len(content)} step{'s' if len(content) != 1 else ''}</summary>", ""]
            lines += [f"- `{s}`" for s in content] + ["", "</details>", ""]
        else:
            lines += [f"**{'You' if role == 'user' else 'Mtrini'}**", "", content, ""]
    lines += ["---", f"[{BADGE.split(' · ')[0]}]({REPO_URL})", ""]
    return "\n".join(lines)


_FENCE = re.compile(r"```([\w+-]*)\n(.*?)```", re.S)
_BULLET = re.compile(r"^\s*([-*]|\d+\.)\s+")


def _inline(t: str) -> str:
    t = html.escape(t)
    t = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*([^*\n]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)", r'<a href="\2" rel="noopener">\1</a>', t)
    return t


def md_to_html(md: str) -> str:
    """Enough Markdown for chat replies: fences, headings, lists, paragraphs, inline code, bold, links.
    Everything is escaped first, so no HTML from the conversation runs in the page."""
    parts, pos = [], 0
    for m in _FENCE.finditer(md):
        parts.append(("text", md[pos:m.start()]))
        parts.append(("code", m.group(2)))
        pos = m.end()
    parts.append(("text", md[pos:]))
    out = []
    for kind, chunk in parts:
        if kind == "code":
            out.append(f"<pre><code>{html.escape(chunk.rstrip())}</code></pre>")
            continue
        for block in re.split(r"\n\s*\n", chunk.strip()):
            if not block.strip():
                continue
            rows = block.splitlines()
            if all(re.match(r"\s*([-*]|\d+\.)\s+", r) for r in rows):
                tag = "ol" if re.match(r"\s*\d+\.", rows[0]) else "ul"
                items = "".join("<li>" + _inline(_BULLET.sub("", r)) + "</li>" for r in rows)
                out.append(f"<{tag}>{items}</{tag}>")
            elif re.match(r"#{1,4}\s", rows[0]):
                level = min(4, len(rows[0].split()[0])) + 1
                out.append(f"<h{level}>{_inline(rows[0].lstrip('#').strip())}</h{level}>")
                if rows[1:]:
                    out.append(f"<p>{'<br>'.join(_inline(r) for r in rows[1:])}</p>")
            else:
                out.append(f"<p>{'<br>'.join(_inline(r) for r in rows)}</p>")
    return "\n".join(out)


_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
:root{{--bg:#fafaf9;--card:#fff;--ink:#1c1917;--muted:#6b6560;--line:rgba(28,25,23,.08);--code:#f3f2f0;--accent:#0f766e}}
@media (prefers-color-scheme:dark){{:root{{--bg:#121212;--card:#1b1b1b;--ink:#ecebe9;--muted:#9a9691;--line:rgba(236,235,233,.09);--code:#242424;--accent:#5eead4}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:760px;margin:0 auto;padding:40px 16px 64px}}h1{{font-size:24px;font-weight:600;letter-spacing:-.01em;margin:0 0 4px}}
.meta{{color:var(--muted);font-size:13px;margin-bottom:28px}}.turn{{margin:0 0 20px}}.who{{font-size:12px;color:var(--muted);margin-bottom:4px}}
.user .body{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 16px}}
.body p{{margin:0 0 10px}}.body p:last-child{{margin:0}}pre{{background:var(--code);border-radius:8px;padding:12px;overflow:auto;font-size:13px}}
code{{font-family:ui-monospace,"Cascadia Code",Menlo,monospace;font-size:.92em}}p code,li code{{background:var(--code);padding:1px 5px;border-radius:4px}}
details{{color:var(--muted);font-size:13px;margin:-8px 0 20px}}details ul{{margin:6px 0 0;padding-left:18px}}a{{color:var(--accent)}}
footer{{margin-top:40px;padding-top:16px;border-top:1px solid var(--line);font-size:13px;color:var(--muted)}}
</style></head><body><main>
<h1>{title}</h1><div class="meta">{count} messages · exported {date}</div>
{body}
<footer><a href="{repo}">Made with Mtrini Workspace</a>, the open-source coding agent by Compiwer AI</footer>
</main></body></html>
"""


def to_html(data: dict) -> str:
    body = []
    turns = _turns(data)
    for role, content in turns:
        if role == "steps":
            items = "".join(f"<li><code>{html.escape(s)}</code></li>" for s in content)
            body.append(f"<details><summary>{len(content)} step{'s' if len(content) != 1 else ''}</summary><ul>{items}</ul></details>")
        else:
            who = "You" if role == "user" else "Mtrini"
            body.append(f'<section class="turn {role}"><div class="who">{who}</div><div class="body">{md_to_html(content)}</div></section>')
    title = html.escape(str(data.get("title") or "Mtrini session"))
    n = sum(1 for r, _ in turns if r != "steps")
    return _PAGE.format(title=title, count=n, date=time.strftime("%Y-%m-%d"), body="\n".join(body), repo=REPO_URL)


def export_thread(root: Path, tid: str, fmt: str) -> tuple[str, str, str]:
    """(filename, content, media type)."""
    data = threads.get_thread(root, tid)
    slug = re.sub(r"[^\w-]+", "-", str(data.get("title") or "session")).strip("-").lower()[:50] or "session"
    if fmt == "md":
        return f"{slug}.md", to_markdown(data), "text/markdown"
    if fmt == "json":
        clean = {**data, "messages": [{k: v for k, v in m.items() if k not in ("output", "error")} for m in data.get("messages", [])]}
        return f"{slug}.json", json.dumps(clean, indent=2, ensure_ascii=False), "application/json"
    return f"{slug}.html", to_html(data), "text/html"


# ---- commit messages --------------------------------------------------------------------

DIFF_LIMIT = 24000

COMMIT_PROMPT = """Write a git commit message for this diff.

Rules:
- First line: imperative mood, at most 72 characters, no trailing period. Example: "Add retry to the upload client".
- Then, only if the change needs it, a blank line and up to 4 short lines saying why.
- Match the style of the recent commits below if there are any.
- Reply with the message only: no quotes, no code fences, no preamble.

Recent commits:
{log}

Diff ({which}):
{diff}"""


def _git(root: Path, *args: str) -> str:
    try:
        p = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True, timeout=30,
                           encoding="utf-8", errors="replace", **NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return p.stdout if p.returncode == 0 else ""


def clean_message(text: str) -> str:
    t = text.strip()
    t = re.sub(r"^```\w*\n?|```$", "", t).strip()
    t = re.sub(r"<think>.*?</think>", "", t, flags=re.S).strip()
    if len(t) > 1 and t[0] == t[-1] and t[0] in "\"'":
        t = t[1:-1].strip()
    t = re.sub(r"^(commit message|message)\s*:\s*", "", t, flags=re.I)
    lines = t.splitlines() or [""]
    lines[0] = lines[0].rstrip(".")[:100]
    return "\n".join(lines).strip()


async def commit_message(root: Path, provider: Any, model: str) -> dict[str, Any]:
    diff, which = _git(root, "diff", "--cached"), "staged changes"
    if not diff.strip():
        diff, which = _git(root, "diff"), "unstaged changes (nothing is staged)"
    if not diff.strip():
        return {"message": "", "error": "No changes to describe."}
    if len(diff) > DIFF_LIMIT:
        stat = _git(root, "diff", "--cached", "--stat") if which.startswith("staged") else _git(root, "diff", "--stat")
        diff = stat + "\n\n" + diff[:DIFF_LIMIT] + "\n…(diff truncated)"
    log = _git(root, "log", "-8", "--format=%s").strip() or "(none)"
    prompt = COMMIT_PROMPT.format(log=log, which=which, diff=diff)
    reply = await provider.chat(model, [ChatMessage(role="user", content=prompt)], None)
    return {"message": clean_message(reply.get("content") or ""), "source": which}


# ---- prompt improver --------------------------------------------------------------------

IMPROVE_PROMPT = """Rewrite this request to a coding agent so it gets better results.

Keep the user's intent and language exactly (if they wrote in Darija, French or Arabic, answer in
that language). Make it specific: name the goal, the files or area if the user gave them, what
done looks like, and constraints they implied. Don't invent requirements, file names or facts.
Keep it short: a few sentences or a short list. Reply with the rewritten request only.

Request:
{text}"""


async def improve_prompt(provider: Any, model: str, text: str) -> str:
    reply = await provider.chat(model, [ChatMessage(role="user", content=IMPROVE_PROMPT.format(text=text[:8000]))], None)
    out = re.sub(r"<think>.*?</think>", "", reply.get("content") or "", flags=re.S).strip()
    return out or text
