"""Mtrini Bots as its own app: its own server, port and window.

It shares two things with Mtrini Workspace, on purpose: the engine (this package) and the home folder
(`~/.mtrini`), so a model or key you set up in one app works in the other. Everything else is separate.
Only this app runs bots: the scheduler, Telegram and the starter crew live here, so installing both apps
never runs a routine twice.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .. import bots
from .. import main as _workspace  # for the endpoints both apps offer, and to find the built screens
from .api import router

PORT = 8789

app = FastAPI(title="Mtrini Bots", version=bots.__version__)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], allow_credentials=True)
app.include_router(router)
# The model picker needs these two; they are the same functions Mtrini Workspace serves.
app.add_api_route("/api/providers", _workspace.providers, methods=["GET"])
app.add_api_route("/api/models", _workspace.api_models, methods=["GET"])


@app.get("/api/health")
def health():
    return {"ok": True, "app": "mtrini-bots", "version": bots.__version__}


@app.on_event("startup")
async def _startup():
    from . import runner, telegram

    bots.seed_starters()
    runner.recover()
    runner.start_scheduler()
    telegram.start()


@app.on_event("shutdown")
async def _shutdown():
    from .. import browser
    from . import runner, telegram

    runner.stop_scheduler()
    telegram.stop()
    await browser.close_all()


_DIST = _workspace._DIST


@app.get("/")
def home():
    if _DIST is None or not (_DIST / "bots.html").exists():
        raise HTTPException(404, "The Mtrini Bots screens are not built. Run: npm run build (in frontend)")
    return FileResponse(str(_DIST / "bots.html"))


if _DIST is not None:  # assets, mounted last so it never shadows /api
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(_DIST)), name="ui")
