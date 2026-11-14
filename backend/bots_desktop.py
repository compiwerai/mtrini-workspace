"""Mtrini Bots desktop app: the entry point of MtriniBots.exe.

Same launcher as Mtrini Workspace (desktop.py), started in Bots mode: its own server on its own port,
its own window, and `--background` to run with no window at sign-in.
"""
import os

os.environ["MTRINI_APP"] = "bots"

import desktop  # noqa: E402  (the mode must be set before the launcher picks its app)

if __name__ == "__main__":
    desktop.main()
