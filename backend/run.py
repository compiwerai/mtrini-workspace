"""Desktop entry point for the PyInstaller exe: serve API + UI, open browser."""

import threading
import webbrowser

import uvicorn

from mtrini.main import app

PORT = 8787


def _open_browser() -> None:
    try:
        webbrowser.open(f"http://127.0.0.1:{PORT}")
    except Exception:
        pass


if __name__ == "__main__":
    print(f"Mtrini Workspace — opening http://127.0.0.1:{PORT}")
    threading.Timer(1.5, _open_browser).start()
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
