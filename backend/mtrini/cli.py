"""mtrini CLI: launch workspace (backend + frontend hint), version, model/provider flags."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import click


@click.command()
@click.argument("path", required=False, default=".")
@click.option("--model", default=None, help="Default model id")
@click.option("--provider", default=None, help="Default provider id")
@click.option("--port", default=8787, help="Backend port")
@click.option("--version", "show_version", is_flag=True, help="Print version")
def main(path: str, model: str | None, provider: str | None, port: int, show_version: bool):
    from . import __version__

    if show_version:
        click.echo(f"mtrini {__version__}")
        return
    root = Path(path).resolve()
    (root / ".mtrini").mkdir(parents=True, exist_ok=True)
    if model or provider:
        from .config import load_config, save_config

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
