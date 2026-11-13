"""Thread export, AI commit messages and the prompt improver."""
from __future__ import annotations

import subprocess
import sys

import anyio
import pytest
from fastapi.testclient import TestClient

from mtrini import extras, threads


class Echo:
    """A provider that records the prompt and returns a fixed reply."""

    def __init__(self, reply: str):
        self.reply, self.prompts = reply, []

    async def chat(self, model, messages, tools=None, **kw):
        self.prompts.append(messages[-1].content)
        return {"content": self.reply}


def _thread(root):
    t = threads.create_thread(root, "Fix the login <bug>")
    tid = t["id"]
    threads.append_message(root, tid, "user", "Why does **login** fail? <script>alert(1)</script>")
    threads.append_message(root, tid, "tool", "", tool="read_file", args={"path": "auth.py"}, ok=True,
                           output="SECRET_KEY=hunter2")
    threads.append_message(root, tid, "tool", "", tool="run_command", args={"command": "pytest -q"}, ok=False,
                           error="1 failed")
    threads.append_message(root, tid, "assistant", "The token check is inverted.\n\n```python\nif not ok:\n    raise\n```\n\n- fixed `auth.py`\n- added a test")
    return tid


def test_html_export_is_escaped_and_leaves_out_tool_output(tmp_path):
    tid = _thread(tmp_path)
    name, page, media = extras.export_thread(tmp_path, tid, "html")
    assert name == "fix-the-login-bug.html" and media == "text/html"
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page
    assert "hunter2" not in page and "1 failed" not in page  # outputs never leave the machine in an export
    assert "<code>read_file auth.py</code>" in page and "run_command pytest -q (failed)" in page
    assert "<strong>login</strong>" in page and "<pre><code>if not ok:" in page and "<li>fixed <code>auth.py</code></li>" in page
    assert "Made with Mtrini Workspace" in page


def test_markdown_and_json_exports(tmp_path):
    tid = _thread(tmp_path)
    _, md, _ = extras.export_thread(tmp_path, tid, "md")
    assert md.startswith("# Fix the login <bug>") and "**You**" in md and "2 steps" in md and "hunter2" not in md
    _, js, _ = extras.export_thread(tmp_path, tid, "json")
    assert "hunter2" not in js and "1 failed" not in js and '"read_file"' in js


def test_export_route(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", None)
    monkeypatch.setenv("MTRINI_WORKSPACE", str(tmp_path))
    from mtrini.main import app

    tid = _thread(tmp_path)
    r = TestClient(app).get(f"/api/threads/{tid}/export?format=md")
    assert r.status_code == 200 and 'filename="fix-the-login-bug.md"' in r.headers["content-disposition"]
    assert TestClient(app).get("/api/threads/nope/export").status_code == 404
    assert TestClient(app).get(f"/api/threads/{tid}/export?format=exe").status_code == 400


def _git(root, *a):
    subprocess.run(["git", *a], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "a.py").write_text("x = 1\n")
    _git(tmp_path, "add", "a.py")
    _git(tmp_path, "commit", "-qm", "Add a")
    return tmp_path


def test_commit_message_prefers_staged_and_cleans_reply(repo):
    (repo / "a.py").write_text("x = 2\n")
    (repo / "b.py").write_text("y = 1\n")
    _git(repo, "add", "b.py")
    p = Echo('```\n"Add b module."\n```')
    out = anyio.run(extras.commit_message, repo, p, "m")
    assert out == {"message": "Add b module", "source": "staged changes"}
    assert "y = 1" in p.prompts[0] and "x = 2" not in p.prompts[0] and "Add a" in p.prompts[0]


def test_commit_message_falls_back_to_unstaged_then_nothing(repo):
    (repo / "a.py").write_text("x = 3\n")
    out = anyio.run(extras.commit_message, repo, Echo("Bump x"), "m")
    assert out["message"] == "Bump x" and out["source"].startswith("unstaged")
    _git(repo, "checkout", "--", "a.py")
    assert anyio.run(extras.commit_message, repo, Echo("x"), "m")["error"] == "No changes to describe."


def test_improve_prompt_keeps_text_when_model_says_nothing():
    p = Echo("<think>hmm</think>Add a dark mode toggle to the header; store the choice in localStorage.")
    assert anyio.run(extras.improve_prompt, p, "m", "dark mode pls").startswith("Add a dark mode")
    assert anyio.run(extras.improve_prompt, Echo(""), "m", "keep me") == "keep me"
