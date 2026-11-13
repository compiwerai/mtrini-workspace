"""Agent Swarm: several agents working at once, each in its own git worktree.

Two modes:
- split: one goal, cut into independent parts; each agent does one part.
- best:  the same task for every agent (usually different models); you keep the best result.

Every agent works in a separate checkout (git worktree) on its own branch, `mtrini/swarm-<id>-<n>`,
made from the current commit, so agents never edit the same files at the same time and your own
working folder is untouched. When an agent finishes, its changes are committed on its branch.
You then merge the branches you want into your current branch, or discard them.

Agents in a swarm can't stop to ask you, so they run in auto mode (edits and commands in their own
worktree, no prompts) or read-only mode (research only, nothing committed). A step that would
still need approval (a destructive command) ends that agent with status "blocked".
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .config import provider_settings, user_dir
from .proc import NO_WINDOW
from .providers import ChatMessage

MAX_AGENTS = 4
EVENTS_KEPT = 80
DIFF_LIMIT = 60000
IDENTITY = ["-c", "user.name=Mtrini Swarm", "-c", "user.email=swarm@mtrini.local"]


@dataclass
class Worker:
    n: int
    task: str
    provider: str
    model: str
    branch: str = ""
    path: str = ""
    status: str = "queued"  # queued | running | done | failed | blocked | stopped | merged | discarded
    summary: str = ""
    error: str = ""
    stat: str = ""
    files: list[str] = field(default_factory=list)
    steps: int = 0
    started: float = 0
    ended: float = 0
    events: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Swarm:
    id: str
    root: str
    goal: str
    mode: str  # split | best
    permission: str  # auto | readonly
    base: str  # commit the worktrees start from
    base_branch: str
    created: float
    workers: list[Worker] = field(default_factory=list)

    def to_dict(self, events: bool = True) -> dict[str, Any]:
        d = asdict(self)
        if not events:
            for w in d["workers"]:
                w["events"] = w["events"][-3:]
        d["running"] = any(w.status in ("queued", "running") for w in self.workers)
        return d


_SWARMS: dict[str, Swarm] = {}
_TASKS: dict[tuple[str, int], asyncio.Task] = {}


# ---- git helpers -----------------------------------------------------------------------

class SwarmError(Exception):
    pass


def _git(cwd: str | Path, *args: str, check: bool = True, timeout: int = 120) -> str:
    try:
        p = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace", **NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise SwarmError(f"git {args[0]} failed: {e}")
    if check and p.returncode != 0:
        raise SwarmError((p.stderr or p.stdout).strip()[-800:] or f"git {args[0]} failed")
    return p.stdout


def _identity(root: str | Path) -> list[str]:
    """Use the repo's own author if one is set; otherwise sign swarm commits as Mtrini Swarm."""
    return [] if _git(root, "config", "user.email", check=False).strip() else IDENTITY


def _home() -> Path:
    d = user_dir() / "swarms"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _worktree_dir(root: Path, sid: str, n: int) -> Path:
    tag = hashlib.sha1(str(root.resolve()).encode()).hexdigest()[:8]
    return user_dir() / "worktrees" / f"{tag}-{sid}-{n}"


def _save(sw: Swarm) -> None:
    try:
        (_home() / f"{sw.id}.json").write_text(json.dumps(sw.to_dict(), ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _load_all() -> None:
    for p in _home().glob("*.json"):
        sid = p.stem
        if sid in _SWARMS:
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            d.pop("running", None)
            workers = [Worker(**w) for w in d.pop("workers", [])]
            sw = Swarm(**d, workers=workers)
        except (OSError, ValueError, TypeError):
            continue
        for w in sw.workers:  # the app restarted while these were working
            if w.status in ("queued", "running"):
                w.status, w.error = "stopped", "Mtrini was closed while this agent was working."
        _SWARMS[sid] = sw


def get(sid: str) -> Swarm:
    _load_all()
    sw = _SWARMS.get(sid)
    if not sw:
        raise KeyError(sid)
    return sw


def list_for(root: Path) -> list[dict[str, Any]]:
    _load_all()
    r = str(root.resolve())
    return [s.to_dict(events=False) for s in sorted(_SWARMS.values(), key=lambda s: -s.created) if s.root == r]


# ---- planning --------------------------------------------------------------------------

PLAN_PROMPT = """You are splitting a software task between {k} coding agents that work at the same time,
each in its own copy of the repository. Their results are merged afterwards, so the parts must be
independent: different files or areas, no part waiting for another.

Goal:
{goal}

Project files (partial):
{files}

Reply with a JSON array of {k} or fewer strings, one instruction per agent. Each instruction says
what to build or change, where, and how to check it. Use fewer parts if the goal doesn't split
cleanly; one part is fine. Reply with the JSON array only."""


def _files_hint(root: Path) -> str:
    out = _git(root, "ls-files", check=False)
    files = [f for f in out.splitlines() if f][:300]
    return "\n".join(files) or "(no tracked files)"


def parse_tasks(text: str, k: int) -> list[str]:
    t = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    m = re.search(r"\[.*\]", t, re.S)
    if m:
        try:
            arr = json.loads(m.group(0))
            tasks = [str(x.get("task") if isinstance(x, dict) else x).strip() for x in arr]
            tasks = [x for x in tasks if x and x != "None"]
            if tasks:
                return tasks[:k]
        except ValueError:
            pass
    lines = [re.sub(r"^\s*(\d+[.)]|[-*])\s*", "", ln).strip() for ln in t.splitlines()]
    lines = [ln for ln in lines if len(ln) > 8]
    return lines[:k]


async def plan(root: Path, provider: Any, model: str, goal: str, k: int) -> list[str]:
    k = max(1, min(MAX_AGENTS, k))
    reply = await provider.chat(model, [ChatMessage(role="user", content=PLAN_PROMPT.format(
        k=k, goal=goal[:6000], files=_files_hint(root)[:6000]))], None)
    return parse_tasks(reply.get("content") or "", k) or [goal]


# ---- running ---------------------------------------------------------------------------

def _prompt(sw: Swarm, w: Worker) -> str:
    if sw.mode == "best":
        return w.task
    others = [f"- {o.task}" for o in sw.workers if o.n != w.n]
    lines = [f"You are agent {w.n + 1} of {len(sw.workers)} working at the same time on this goal:", sw.goal, "",
             "Your part:", w.task]
    if others:
        lines += ["", "Other agents are doing these parts, so leave their files alone:", *others]
    lines += ["", "Work only on your part, verify it (run the relevant tests or build), and finish with a short "
              "summary of what you changed and how you checked it."]
    return "\n".join(lines)


def _event(w: Worker, ev: dict[str, Any]) -> None:
    t = ev.get("type")
    item: dict[str, Any] | None = None
    if t == "tool_start":
        a = ev.get("args") or {}
        target = a.get("path") or a.get("file_path") or a.get("command") or a.get("query") or ""
        item = {"kind": "tool", "tool": ev.get("tool"), "target": str(target)[:160], "id": ev.get("id")}
        w.steps += 1
    elif t == "tool_result":
        for e in reversed(w.events):
            if e.get("kind") == "tool" and e.get("id") == ev.get("id") and "ok" not in e:
                e["ok"] = bool(ev.get("ok"))
                break
    elif t == "assistant_delta" and ev.get("delta"):
        if w.events and w.events[-1].get("kind") == "text":  # streamed pieces of the same message
            w.events[-1]["text"] = (w.events[-1]["text"] + ev["delta"])[-1200:]
            w.summary = w.events[-1]["text"]
        else:
            item = {"kind": "text", "text": str(ev["delta"])[-1200:]}
            w.summary = item["text"]
    elif t == "status" and ev.get("message"):
        item = {"kind": "status", "text": str(ev["message"])[:200]}
    if item:
        w.events.append(item)
        del w.events[:-EVENTS_KEPT]


# Never commit build junk, even in a repo with no .gitignore for it.
JUNK = [":(exclude).mtrini", ":(exclude,glob)**/__pycache__/**", ":(exclude,glob)**/*.pyc",
        ":(exclude,glob)**/.pytest_cache/**", ":(exclude,glob)**/node_modules/**", ":(exclude,glob)**/.DS_Store"]
RETRIES = 3
RETRY_WAIT = 20  # seconds, then 40, 60
CONTINUE = ("Continue the task where you left off (the model provider asked us to slow down for a moment). "
            "Check what is already done before repeating anything.")


def _rate_limited(msg: str) -> bool:
    return bool(re.search(r"\b429\b|rate.?limit|too many requests", msg, re.I))


def _finish_commit(sw: Swarm, w: Worker) -> None:
    """Commit the agent's work on its branch and record what changed."""
    if sw.permission == "readonly":
        return
    _git(w.path, "add", "-A", "--", ".", *JUNK)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=w.path, capture_output=True, **NO_WINDOW).returncode == 0:
        w.stat = w.stat or "No changes"
        return
    msg = f"Swarm agent {w.n + 1}: {w.task.splitlines()[0][:60]}"
    _git(w.path, *_identity(sw.root), "commit", "-q", "-m", msg, "-m", (w.summary or "")[:2000])
    w.stat = _git(w.path, "diff", "--shortstat", f"{sw.base}..HEAD").strip()
    w.files = [f for f in _git(w.path, "diff", "--name-only", f"{sw.base}..HEAD").splitlines() if f][:200]


async def _run_worker(sw: Swarm, w: Worker) -> None:
    from .agent.engine import friendly_error, run_agent

    w.status, w.started = "running", time.time()
    _save(sw)
    root = Path(sw.root)
    # The status stays "running" until the result is committed, so "done" always means ready to merge.
    outcome, error = "done", ""
    try:
        settings = provider_settings(root, w.provider)
        # A saved session (in the worktree) lets the agent carry on after a rate-limit pause.
        session = f"swarm-{sw.id}-{w.n + 1}"
        message = _prompt(sw, w)
        for attempt in range(RETRIES + 1):
            outcome, error = "done", ""
            async for ev in run_agent(Path(w.path), w.provider, w.model, message, [], sw.permission, settings,
                                      thread_id=session):
                _event(w, ev)
                t = ev.get("type")
                if t == "error":
                    outcome, error = "failed", str(ev.get("message", "failed"))[:1500]
                elif t == "done":
                    if ev.get("pendingApproval"):
                        tool = ev["pendingApproval"].get("tool", "a step")
                        outcome, error = "blocked", f"Stopped: {tool} needs your approval, which a swarm agent can't ask for."
                    elif ev.get("content"):
                        w.summary = str(ev["content"])[-2000:]
            if outcome != "failed" or not _rate_limited(error) or attempt == RETRIES:
                break
            wait = RETRY_WAIT * (attempt + 1)
            _event(w, {"type": "status", "message": f"Rate limited by the provider; trying again in {wait}s"})
            _save(sw)
            await asyncio.sleep(wait)
            message = CONTINUE
        # Keep whatever the agent did, even when it failed part way: you can still look at it or merge it.
        await asyncio.to_thread(_finish_commit, sw, w)
        w.status, w.error = outcome, error
    except asyncio.CancelledError:
        try:
            _finish_commit(sw, w)  # keep what it did so far
        except Exception:
            pass
        w.status, w.error = "stopped", "Stopped by you."
        raise
    except SwarmError as e:
        w.status, w.error = "failed", f"Could not commit the result: {e}"
    except Exception as e:
        w.status, w.error = "failed", friendly_error(e)
    finally:
        w.ended = time.time()
        _TASKS.pop((sw.id, w.n), None)
        _save(sw)


def start(root: Path, goal: str, mode: str, agents: list[dict[str, str]], permission: str = "auto") -> Swarm:
    """Create a worktree per agent and start them all."""
    root = root.resolve()
    if mode not in ("split", "best"):
        raise SwarmError("mode must be split or best")
    if permission not in ("auto", "readonly"):
        raise SwarmError("permission must be auto or readonly")
    agents = [a for a in agents if str(a.get("task", "")).strip() and a.get("provider")][:MAX_AGENTS]
    if not agents:
        raise SwarmError("Add at least one agent with a task.")
    if _git(root, "rev-parse", "--is-inside-work-tree", check=False).strip() != "true":
        raise SwarmError("Swarm needs a git repository. Run `git init` and make a first commit.")
    base = _git(root, "rev-parse", "--verify", "-q", "HEAD", check=False).strip()
    if not base:
        raise SwarmError("Swarm needs at least one commit to start from. Commit your files first.")
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD", check=False).strip() or "HEAD"
    sid = uuid.uuid4().hex[:8]
    sw = Swarm(id=sid, root=str(root), goal=goal.strip(), mode=mode, permission=permission, base=base,
               base_branch=branch, created=time.time())
    try:
        for n, a in enumerate(agents):
            w = Worker(n=n, task=str(a["task"]).strip(), provider=str(a["provider"]), model=str(a.get("model") or ""))
            w.branch = f"mtrini/swarm-{sid}-{n + 1}"
            path = _worktree_dir(root, sid, n + 1)
            path.parent.mkdir(parents=True, exist_ok=True)
            _git(root, "worktree", "add", "-q", "-b", w.branch, str(path), base)
            w.path = str(path)
            sw.workers.append(w)
    except SwarmError:
        for w in sw.workers:
            _remove_worktree(sw, w, delete_branch=True)
        raise
    _SWARMS[sid] = sw
    _save(sw)
    for w in sw.workers:
        _TASKS[(sid, w.n)] = asyncio.get_running_loop().create_task(_staggered(sw, w))
    return sw


STAGGER = 2.0  # seconds between agent starts, so a burst of first requests doesn't trip per-minute limits


async def _staggered(sw: Swarm, w: Worker) -> None:
    if w.n and STAGGER:
        await asyncio.sleep(STAGGER * w.n)
    await _run_worker(sw, w)


def stop(sw: Swarm, n: int | None = None) -> None:
    for w in sw.workers:
        if n is None or w.n == n:
            t = _TASKS.get((sw.id, w.n))
            if t:
                t.cancel()


def diff(sw: Swarm, n: int) -> str:
    w = sw.workers[n]
    if not w.branch:
        return ""
    out = _git(sw.root, "diff", f"{sw.base}..{w.branch}", "--", ".", ":(exclude).mtrini", check=False)
    return out if len(out) <= DIFF_LIMIT else out[:DIFF_LIMIT] + "\n…(diff truncated)"


def _remove_worktree(sw: Swarm, w: Worker, delete_branch: bool) -> None:
    if w.path and Path(w.path).exists():
        _git(sw.root, "worktree", "remove", "--force", w.path, check=False)
    _git(sw.root, "worktree", "prune", check=False)
    if delete_branch and w.branch:
        _git(sw.root, "branch", "-D", w.branch, check=False)


def merge(sw: Swarm, n: int) -> dict[str, Any]:
    """Merge one agent's branch into the branch you're on. On a conflict nothing changes."""
    w = sw.workers[n]
    if w.status in ("queued", "running"):
        raise SwarmError("This agent is still working.")
    if w.status in ("merged", "discarded"):
        raise SwarmError(f"Already {w.status}.")
    if not w.files:
        raise SwarmError("This agent didn't change any files.")
    current = _git(sw.root, "rev-parse", "--abbrev-ref", "HEAD", check=False).strip()
    if current != sw.base_branch:
        raise SwarmError(f"Switch back to {sw.base_branch} first (you're on {current}).")
    msg = f"Merge swarm agent {w.n + 1}: {w.task.splitlines()[0][:60]}"
    try:
        p = subprocess.run(["git", *_identity(sw.root), "merge", "--no-ff", "-m", msg, w.branch], cwd=sw.root,
                           capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace", **NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise SwarmError(str(e))
    if p.returncode != 0:
        _git(sw.root, "merge", "--abort", check=False)
        detail = (p.stdout + p.stderr).strip()
        if "CONFLICT" in detail:
            files = re.findall(r"CONFLICT \([^)]*\): (?:Merge conflict in )?(\S+)", detail)
            raise SwarmError("Conflicts with your branch in " + (", ".join(files[:6]) or "some files")
                             + ". Nothing was changed. Merge the others first, or ask an agent to redo this part.")
        raise SwarmError(detail[-800:] or "merge failed")
    w.status = "merged"
    _remove_worktree(sw, w, delete_branch=True)
    _save(sw)
    return {"ok": True, "message": msg}


def discard(sw: Swarm, n: int) -> None:
    w = sw.workers[n]
    stop(sw, n)
    _remove_worktree(sw, w, delete_branch=True)
    if w.status not in ("merged",):
        w.status = "discarded"
    _save(sw)


def remove(sw: Swarm) -> None:
    """Stop everything, delete worktrees and unmerged branches, forget the swarm."""
    stop(sw)
    for w in sw.workers:
        if w.status != "merged":
            _remove_worktree(sw, w, delete_branch=True)
    _SWARMS.pop(sw.id, None)
    try:
        (_home() / f"{sw.id}.json").unlink()
    except OSError:
        pass
