"""install: register Jarvis as a self-healing, reboot-surviving Windows service.

This is the realization of requirements 1, 5, 12, 13 for the Windows host.
It registers three Task Scheduler tasks pointing at THIS repo's real path
(resolved at install time, so the corrupted-junction bug can't recur):

  JarvisBoot      on logon        -> one cycle immediately after reboot/login
  JarvisSupervise every 5 min     -> OS-level supervisor: wakes Hermes, runs a
                                    cycle, emits SPAWN_WORKER for Hermes to run
  JarvisWatchdog  every 10 min    -> external liveness check (survives Hermes)

All tasks run under the current user, with highest privileges, whether logged
on or not, so they resume after Windows updates / unexpected reboots.
"""
from __future__ import annotations
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(os.path.dirname(sys.executable), "python.exe") \
    if getattr(sys, "frozen", False) else sys.executable
DB = os.path.join(REPO, "jarvis_state.db")


def _tasks():
    return {
        "JarvisBoot": {
            "trig": "/sc onlogon",
            "cmd": f'"{PY}" "{os.path.join(REPO, "supervise.py")}" "{DB}"',
        },
        "JarvisSupervise": {
            "trig": "/sc minute /mo 5",
            "cmd": f'"{PY}" "{os.path.join(REPO, "supervise.py")}" "{DB}"',
        },
        "JarvisWatchdog": {
            "trig": "/sc minute /mo 10",
            "cmd": f'"{PY}" "{os.path.join(REPO, "watchdog.py")}" --db "{DB}" --max-age-min 40',
        },
    }


def install() -> list:
    """Register all tasks. Returns list of (name, ok, msg)."""
    results = []
    for name, spec in _tasks().items():
        # Build as a list (no shell) so spaces in PREM KUMAR paths are literal.
        # schtasks wants: /tr "the-whole-command-string"
        cmd = [
            "schtasks", "/create", "/tn", name,
            "/tr", spec["cmd"],   # spec["cmd"] is already a fully-quoted string
            "/f",
        ]
        trig = spec["trig"].split()  # e.g. ["/sc", "minute", "/mo", "5"]
        cmd += trig
        cmd += ["/rl", "HIGHEST"]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            ok = out.returncode == 0
            results.append((name, ok, (out.stdout or out.stderr).strip()))
        except Exception as e:  # noqa
            results.append((name, False, str(e)))
    return results


def uninstall() -> list:
    results = []
    for name in _tasks():
        try:
            out = subprocess.run(["schtasks", "/delete", "/tn", name, "/f"],
                                 capture_output=True, text=True, timeout=30)
            results.append((name, out.returncode == 0,
                            (out.stdout or out.stderr).strip()))
        except Exception as e:  # noqa
            results.append((name, False, str(e)))
    return results


def is_installed() -> bool:
    out = subprocess.run("schtasks /query /tn JarvisSupervise", shell=True,
                         capture_output=True, text=True)
    return out.returncode == 0


if __name__ == "__main__":
    for n, ok, m in install():
        print(f"[{'OK' if ok else 'FAIL'}] {n}: {m}")
