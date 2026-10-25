"""mtrini CLI: launch the workspace server, or run the agent headless with -p.

    mtrini .                              serve this folder
    mtrini -p "fix the failing test"      one agent turn, printed to the terminal
    echo "explain main.py" | mtrini -p -  prompt from stdin
    mtrini -p "..." --mode auto --json    no approvals, events as JSON lines (CI)
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import uuid
from pathlib import Path

import click


def _short(args: dict) -> str:
    for k in ("path", "command", "query", "url", "pattern", "description"):
        if args.get(k):
            return str(args[k])[:80]
    return ""


def _ask(question: str, choices: str) -> str:
    while True:
        a = click.prompt(question, default=choices[0], show_default=False).strip().lower()[:1]
        if a in choices:
            return a


async def _headless(root: Path, provider: str, model: str, prompt: str, mode: str, effort: str,
                    thread: str | None, as_json: bool) -> int:
    from . import project as project_mod
    from .agent.engine import run_agent
    from .config import load_config

    settings = load_config(root).get(f"provider.{provider}", {})
    settings = settings if isinstance(settings, dict) else {}
    instr = project_mod.load_instructions(root)
    system_extra = f"Project instructions (.mtrini/instructions.md):\n{instr}" if instr else ""
    tid = thread or "cli-" + uuid.uuid4().hex[:10]
    text, resume, code = prompt, None, 0
    out, err = sys.stdout, sys.stderr
    while True:
        pending = None
        async for ev in run_agent(root, provider, model, text, [], mode, settings, effort=effort,
                                  thread_id=tid, resume=resume, system_extra=system_extra,
                                  context=project_mod.skill_context(root, text) if text else ""):
            t = ev["type"]
            if as_json:
                print(json.dumps(ev, default=str), file=out, flush=True)
            elif t == "assistant_delta":
                print(ev["delta"], file=out, flush=True)
            elif t == "tool_start":
                print(f"  -> {ev['tool']} {_short(ev.get('args') or {})}", file=err, flush=True)
            elif t == "tool_result" and not ev.get("ok"):
                print(f"     x {ev.get('error')}", file=err, flush=True)
            elif t == "todos":
                for td in ev["todos"]:
                    mark = {"completed": "[x]", "in_progress": "[>]"}.get(td["status"], "[ ]")
                    print(f"  {mark} {td['content']}", file=err, flush=True)
            elif t == "plan":
                print("\n--- Plan ---\n" + ev["plan"] + "\n------------", file=out, flush=True)
            elif t == "subagent" and ev["status"] == "start":
                print(f"  -> subagent: {ev['description']}", file=err, flush=True)
            elif t == "compacted":
                print(f"  (summarized earlier conversation: ~{ev['before']} -> ~{ev['after']} tokens)", file=err)
            if t == "error":
                if not as_json:
                    print(f"error: {ev['message']}", file=err)
                code = 1
            if t == "done":
                pending = ev.get("pendingApproval") or ev.get("pendingPlan")
                if ev.get("pendingPlan"):
                    pending = {"plan": True}
        if not pending:
            break
        if not sys.stdin.isatty():
            print("Stopped: this step needs approval. Re-run with --mode auto, or run interactively. "
                  f"Continue later with --thread {tid}", file=err)
            return 2
        if pending.get("plan"):
            a = _ask("Approve this plan? [y]es / [a]uto mode / [n]o", "yan")
            resume = {"decision": "approve", "mode": "auto" if a == "a" else "ask"} if a in "ya" else \
                {"decision": "reject", "feedback": click.prompt("What should change?", default="")}
        else:
            a = _ask(f"Allow {pending['tool']} {_short(pending.get('args') or {})}? [y]es / [a]lways / [n]o", "yan")
            resume = {"decision": {"y": "allow", "a": "always", "n": "deny"}[a]}
        text = ""
    if not as_json:
        print(f"(thread: {tid}; continue with --thread {tid})", file=err)
    return code


@click.command()
@click.argument("path", required=False, default=".")
@click.option("--model", default=None, help="Model id (default: the workspace's active model)")
@click.option("--provider", default=None, help="Provider id (default: the workspace's active provider)")
@click.option("--port", default=8787, help="Backend port")
@click.option("-p", "--print", "prompt", default=None, help="Run one agent turn headless; '-' reads stdin")
@click.option("--mode", default="ask", type=click.Choice(["ask", "auto", "readonly", "plan"]),
              help="Permission mode for -p")
@click.option("--effort", default="off", type=click.Choice(["off", "low", "medium", "high", "xhigh", "max"]))
@click.option("--thread", default=None, help="Continue an earlier -p session")
@click.option("--json", "as_json", is_flag=True, help="With -p: print events as JSON lines")
@click.option("--version", "show_version", is_flag=True, help="Print version")
def main(path: str, model: str | None, provider: str | None, port: int, prompt: str | None, mode: str,
         effort: str, thread: str | None, as_json: bool, show_version: bool):
    from . import __version__

    if show_version:
        click.echo(f"mtrini {__version__}")
        return
    root = Path(path).resolve()
    (root / ".mtrini").mkdir(parents=True, exist_ok=True)
    from .config import load_config, save_config

    if prompt is not None:
        if prompt == "-":
            prompt = sys.stdin.read()
        cfg = load_config(root)
        prov = provider or cfg.get("activeProvider") or "local"
        mdl = model or cfg.get("activeModel") or ""
        sys.exit(asyncio.run(_headless(root, prov, mdl, prompt.strip(), mode, effort, thread, as_json)))

    if model or provider:
        cfg = load_config(root)
        if model:
            cfg["activeModel"] = model
        if provider:
            cfg["activeProvider"] = provider
        save_config(root, cfg)
    click.echo(f"Mtrini Workspace {__version__} — serving {root} on :{port}")
    click.echo("Frontend: cd frontend && npm run dev  (expects VITE_API=http://localhost:8787)")
    import os

    os.environ["MTRINI_WORKSPACE"] = str(root)
    subprocess.run([sys.executable, "-m", "uvicorn", "mtrini.main:app",
                    "--host", "127.0.0.1", "--port", str(port)], cwd=Path(__file__).parent.parent)


if __name__ == "__main__":
    main()
