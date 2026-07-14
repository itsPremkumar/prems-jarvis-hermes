"""hermes_launcher: Jarvis's tool to ensure the Hermes desktop app is alive.

Jarvis is the supervisor; Hermes is the worker host. Because Hermes is a GUI app,
Jarvis (running via OS Task Scheduler, outside Hermes) is the only component that
can launch it. This module detects a running Hermes and starts it if missing.

It does NOT kill/restart Hermes aggressively — only launches when no Hermes
process is found, to avoid disrupting an already-working session.
"""
from __future__ import annotations
import os
import subprocess
import time

# Hermes desktop executable (discovered via wmic)
HERMES_EXE = (
    r"C:\Users\PREM KUMAR\AppData\Local\hermes\hermes-agent"
    r"\apps\desktop\release\win-unpacked\Hermes.exe"
)
# Fallback: the CLI entry (used if the desktop app path is missing)
HERMES_CLI = (
    r"C:\Users\PREM KUMAR\AppData\Local\hermes\hermes-agent\venv\Scripts\hermes.exe"
)


def hermes_running() -> bool:
    """True if any Hermes process is currently running."""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Hermes.exe", "/NH"],
            capture_output=True, text=True, timeout=10,
        )
        return "Hermes.exe" in out.stdout
    except Exception:  # noqa: never let the check crash the loop
        return False


def launch_hermes() -> bool:
    """Launch the Hermes desktop app if not already running. Returns True if a
    launch was attempted (or already running)."""
    if hermes_running():
        return True
    exe = HERMES_EXE if os.path.exists(HERMES_EXE) else HERMES_CLI
    if not os.path.exists(exe):
        return False
    try:
        # start detached so the supervisor loop doesn't block on the GUI
        subprocess.Popen([exe], shell=False,
                         creationflags=subprocess.DETACHED_PROCESS | 0x08000000)
        for _ in range(10):
            time.sleep(1)
            if hermes_running():
                return True
        return hermes_running()
    except Exception:  # noqa
        return False


def ensure_hermes() -> dict:
    """Idempotent: report + guarantee Hermes is up. Returns a status dict."""
    if hermes_running():
        return {"running": True, "launched": False, "action": "already up"}
    ok = launch_hermes()
    return {
        "running": hermes_running(),
        "launched": ok,
        "action": "launched" if ok else "launch failed",
    }
