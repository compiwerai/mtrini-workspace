"""Agent Swarm (parallel agents in git worktrees, merge/discard) and agent memory."""
from __future__ import annotations

import json
import re
import subprocess

import anyio
import pytest

from mtrini import memory, swarm
from mtrini.agent import engine
from mtrini.tools import registry


class FileWriter:
    """Writes one file named after its part ('agent N of'), or `fixed` for best-of-N, then reports."""

    def __init__(self, fixed: str | None = None):
        self.fixed = fixed

    async def chat(self, model, messages, tools=None, **kw):
        first = next(m.content for m in messages if m.role == "user")
        if any(m.role == "tool" for m in messages):
            return {"content": f"Done with {model}.", "tool_calls": []}
        m = re.search(r"agent (\d+) of", first)
        name = self.fixed or f"part{m.group(1) if m else 0}.txt"
        return {"content": "", "tool_calls": [{"id": "c1", "name": "write_file",
                                               "arguments": json.dumps({"path": name, "content": f"from {model}\n"})}]}


def _git(root, *a):
    return subprocess.run(["git", *a], cwd=root, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "proj"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "t")
    (r / "README.md").write_text("hi\n")
    _git(r, "add", ".")
    _git(r, "commit", "-qm", "init")
    return r


def _run_swarm(root, monkeypatch, provider, mode, agents, permission="auto"):
    monkeypatch.setattr(engine, "build_provider", lambda *a, **k: provider)

    async def go():
        sw = swarm.start(root, "Build two parts", mode, agents, permission)
        for _ in range(400):
            if not sw.to_dict()["running"]:
                return sw
            await anyio.sleep(0.05)
        raise AssertionError("swarm did not finish")
    return anyio.run(go)


def test_split_swarm_runs_agents_in_worktrees_and_merges(repo, monkeypatch):
    sw = _run_swarm(repo, monkeypatch, FileWriter(), "split",
                    [{"task": "Part one", "provider": "local", "model": "m1"},
                     {"task": "Part two", "provider": "local", "model": "m2"}])
    assert [w.status for w in sw.workers] == ["done", "done"], [(w.error, w.events[-3:]) for w in sw.workers]
    assert [w.files for w in sw.workers] == [["part1.txt"], ["part2.txt"]]
    assert all(w.branch.startswith(f"mtrini/swarm-{sw.id}-") for w in sw.workers)
    assert not (repo / "part1.txt").exists()  # your own folder is untouched until you merge
    assert "write_file" in [e.get("tool") for e in sw.workers[0].events]
    assert "+from m2" in swarm.diff(sw, 1)

    swarm.merge(sw, 0)
    swarm.merge(sw, 1)
    assert (repo / "part1.txt").read_text() == "from m1\n" and (repo / "part2.txt").exists()
    assert [w.status for w in sw.workers] == ["merged", "merged"]
    assert "mtrini/swarm" not in _git(repo, "branch")  # merged branches and worktrees are cleaned up
    assert "Merge swarm agent 2" in _git(repo, "log", "--format=%s", "-3")
    assert swarm.list_for(repo)[0]["id"] == sw.id


def test_best_of_n_conflict_changes_nothing(repo, monkeypatch):
    sw = _run_swarm(repo, monkeypatch, FileWriter(fixed="answer.txt"), "best",
                    [{"task": "Write the answer", "provider": "local", "model": "a"},
                     {"task": "Write the answer", "provider": "local", "model": "b"}])
    swarm.merge(sw, 1)
    head = _git(repo, "rev-parse", "HEAD")
    with pytest.raises(swarm.SwarmError, match="Conflicts with your branch in answer.txt"):
        swarm.merge(sw, 0)
    assert _git(repo, "rev-parse", "HEAD") == head and _git(repo, "status", "--porcelain") == ""
    assert (repo / "answer.txt").read_text() == "from b\n"
    swarm.discard(sw, 0)
    assert sw.workers[0].status == "discarded" and "mtrini/swarm" not in _git(repo, "branch")
    swarm.remove(sw)
    assert swarm.list_for(repo) == []


def test_readonly_swarm_commits_nothing(repo, monkeypatch):
    class Reader:
        async def chat(self, model, messages, tools=None, **kw):
            return {"content": "Found 1 file.", "tool_calls": []}
    sw = _run_swarm(repo, monkeypatch, Reader(), "best", [{"task": "Look around", "provider": "local", "model": "m"}],
                    permission="readonly")
    assert sw.workers[0].status == "done" and sw.workers[0].summary == "Found 1 file." and sw.workers[0].files == []
    with pytest.raises(swarm.SwarmError, match="didn't change any files"):
        swarm.merge(sw, 0)
    swarm.remove(sw)


def test_swarm_needs_a_repo_with_a_commit(tmp_path):
    async def go(path):
        swarm.start(path, "g", "split", [{"task": "t", "provider": "local"}])
    with pytest.raises(swarm.SwarmError, match="needs a git repository"):
        anyio.run(go, tmp_path)
    _git(tmp_path, "init", "-q")
    with pytest.raises(swarm.SwarmError, match="at least one commit"):
        anyio.run(go, tmp_path)


def test_parse_tasks_reads_json_or_a_list():
    assert swarm.parse_tasks('<think>x</think>Sure:\n["Add API", {"task": "Add UI"}]', 3) == ["Add API", "Add UI"]
    assert swarm.parse_tasks("1. Build the login page\n2. Write the auth tests", 4) == [
        "Build the login page", "Write the auth tests"]
    assert swarm.parse_tasks('["a part", "b part", "c part"]', 2) == ["a part", "b part"]


# ---- memory ----

def test_memory_add_refuses_secrets_and_duplicates(tmp_path):
    assert "Saved" in memory.add(tmp_path, "Run tests with `npm test -- --run`")
    assert memory.add(tmp_path, "run tests with `npm test -- --run`") == "Already in project memory."
    with pytest.raises(ValueError, match="secret"):
        memory.add(tmp_path, "the api_key = sk-abcdefghijklmnopqrstuv")
    memory.add(tmp_path, "Answer in French", "user")
    p = memory.for_prompt(tmp_path)
    assert "Your memory" in p and "Answer in French" in p and "npm test" in p and "<!--" not in p


def test_remember_tool_and_memory_in_system_prompt(tmp_path, monkeypatch):
    res = anyio.run(registry.BY_NAME["remember"].run, tmp_path, {"fact": "Use pnpm, not npm"})
    assert res.ok and "Saved" in res.output
    seen = []

    class Spy:
        async def chat(self, model, messages, tools=None, **kw):
            seen.append(messages[0].content)
            return {"content": "ok", "tool_calls": []}
    monkeypatch.setattr(engine, "build_provider", lambda *a, **k: Spy())

    async def go():
        return [ev async for ev in engine.run_agent(tmp_path, "local", "m", "hi", [])]
    anyio.run(go)
    assert "Memory from earlier sessions" in seen[0] and "Use pnpm, not npm" in seen[0]


def test_rate_limited_agent_waits_and_carries_on_without_committing_junk(repo, monkeypatch):
    monkeypatch.setattr(swarm, "RETRY_WAIT", 0)
    monkeypatch.setattr(swarm, "STAGGER", 0)

    class Flaky:
        calls = 0

        async def chat(self, model, messages, tools=None, **kw):
            Flaky.calls += 1
            if Flaky.calls == 1:
                return {"content": "", "tool_calls": [{"id": "c1", "name": "write_file", "arguments": json.dumps(
                    {"path": "__pycache__/x.cpython-312.pyc", "content": "junk"})}]}
            if Flaky.calls == 2:
                raise RuntimeError("429 Too many requests in a minute")
            if Flaky.calls == 3:
                assert "Continue the task where you left off" in messages[-1].content
                assert any(m.role == "tool" for m in messages)  # the same session, not a fresh start
                return {"content": "", "tool_calls": [{"id": "c2", "name": "write_file",
                                                       "arguments": json.dumps({"path": "real.py", "content": "x = 1\n"})}]}
            return {"content": "Done.", "tool_calls": []}

    sw = _run_swarm(repo, monkeypatch, Flaky(), "best", [{"task": "Do it", "provider": "local", "model": "m"}])
    w = sw.workers[0]
    assert w.status == "done", w.error
    assert w.files == ["real.py"]  # the .pyc was left out of the commit
    assert any("Rate limited" in (e.get("text") or "") for e in w.events)
    swarm.remove(sw)


def test_free_model_agents_take_turns(repo, monkeypatch):
    """The free relay allows one request in flight, so agents on it must never overlap."""
    monkeypatch.setattr(swarm, "STAGGER", 0)

    class Counting:
        active = 0
        peak = 0

        async def chat(self, model, messages, tools=None, **kw):
            Counting.active += 1
            Counting.peak = max(Counting.peak, Counting.active)
            await anyio.sleep(0.05)
            Counting.active -= 1
            return {"content": "Looked.", "tool_calls": []}

    agents = [{"task": f"Part {i}", "provider": "free", "model": "m"} for i in range(3)]
    sw = _run_swarm(repo, monkeypatch, Counting(), "split", agents, permission="readonly")
    assert [w.status for w in sw.workers] == ["done"] * 3 and Counting.peak == 1
    swarm.remove(sw)

    Counting.peak = 0
    agents = [{"task": f"Part {i}", "provider": "local", "model": "m"} for i in range(3)]
    sw = _run_swarm(repo, monkeypatch, Counting(), "split", agents, permission="readonly")
    assert Counting.peak > 1  # other providers really do run at once
    swarm.remove(sw)
    assert swarm._rate_limited("Another request is still running. Try again when it finishes.")


def test_agent_keeps_going_through_many_rate_limits_while_it_makes_progress(repo, monkeypatch):
    """A small API plan rate-limits every other call. Progress between limits resets the give-up counter."""
    monkeypatch.setattr(swarm, "RETRY_WAIT", 0)
    monkeypatch.setattr(swarm, "STAGGER", 0)

    class Stingy:
        calls = 0

        async def chat(self, model, messages, tools=None, **kw):
            Stingy.calls += 1
            if Stingy.calls % 2 == 0:
                raise RuntimeError("Client error '429 Too Many Requests'")
            n = (Stingy.calls + 1) // 2
            if n <= 6:  # six separate steps, each followed by a rate limit: more limits than RETRIES allows in a row
                return {"content": "", "tool_calls": [{"id": f"c{n}", "name": "write_file", "arguments": json.dumps(
                    {"path": f"f{n}.txt", "content": "x\n"})}]}
            return {"content": "Done.", "tool_calls": []}

    sw = _run_swarm(repo, monkeypatch, Stingy(), "best", [{"task": "Do it", "provider": "local", "model": "m"}])
    assert sw.workers[0].status == "done", sw.workers[0].error
    assert len(sw.workers[0].files) == 6
    swarm.remove(sw)

    class Dead:
        async def chat(self, model, messages, tools=None, **kw):
            raise RuntimeError("429 Too Many Requests")

    sw = _run_swarm(repo, monkeypatch, Dead(), "best", [{"task": "Do it", "provider": "local", "model": "m"}])
    assert sw.workers[0].status == "failed" and "429" in sw.workers[0].error  # no progress: gives up
    swarm.remove(sw)
