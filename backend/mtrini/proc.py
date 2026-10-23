"""Keep child processes from flashing console windows on Windows.

The desktop build has no console, so Windows gives every console program it starts (git, cmd.exe,
python, MCP servers) a new console window. CREATE_NO_WINDOW gives the child a hidden console
instead, and anything the child starts inherits it. Pass **NO_WINDOW to subprocess and asyncio calls.
"""
from __future__ import annotations

import subprocess
import sys
from typing import Any

NO_WINDOW: dict[str, Any] = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
