#!/usr/bin/env python
"""Jarvis supervisor driver — the OS-level boss loop.

Runs OUTSIDE Hermes (via Windows Task Scheduler, every ~5 min). It:
  1. Wakes Hermes if it is not running (Jarvis is the supervisor; Hermes is the
     worker host and cannot restart itself).
  2. Runs one Jarvis cycle (evaluate goal -> decompose -> dispatch -> verify).
  3. If a worker was dispatched AND Hermes is up, prints the worker brief so the
     calling agent (or a Hermes cron) can spawn the subagent via delegate_task.
     This is the "Jarvis commands Hermes to do the work" hand-off.
"""
from __future__ import annotations
import json
import sys

from jarvis.core import State, Planner, Dispatcher, Verifier, Monitor, Defaults
from jarvis.core.cycle import run_cycle
from jarvis.core.hermes_launcher import hermes_running
from jarvis.dashboard import render_dashboard


def main(db_path: str = "jarvis_state.db") -> int:
    s = State(db_path)
    planner = Planner(s)
    dispatcher = Dispatcher(s, Defaults())
    verifier = Verifier(s)
    monitor = Monitor(Defaults().min_free_ram_mb, Defaults().max_cpu_percent)
    rep = run_cycle(s, planner, dispatcher, verifier, monitor, Defaults())

    print(render_dashboard(s, hermes_status=rep.hermes))
    print("\nNEXT ACTION:", rep.next_action)

    if rep.dispatched and hermes_running():
        brief = {
            "task_id": rep.dispatched.task_id,
            "sub_goal": rep.dispatched.sub_goal,
            "verification": rep.dispatched.verification,
            "context": rep.dispatched.context,
            "toolsets": rep.dispatched.toolsets,
        }
        print("\nSPAWN_WORKER:" + json.dumps(brief, ensure_ascii=False))
    s.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "jarvis_state.db"))
