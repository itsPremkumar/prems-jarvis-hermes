#!/usr/bin/env python
"""External Jarvis watchdog — lives OUTSIDE Hermes so it survives Hermes dying.

The cron that runs Jarvis lives inside the Hermes desktop app. If Hermes closes
or crashes, that cron stops too, and Jarvis can't restart it (correct layering:
Hermes is the host). This watchdog is the real recovery point: scheduled by
Windows Task Scheduler (independent of Hermes), it checks whether a Jarvis cycle
has run recently. If not, it alerts the operator so the single point of failure
(Hermes) can be reopened.

It does NOT restart Hermes itself (it can't launch a GUI app reliably in
session 0). It DETECTS the gap and reports it. Reopening Hermes / re-running the
cron is the human-or-scheduler recovery step.

Usage (run from Task Scheduler every 10 min):
    python watchdog.py --db C:\c\one\prems-jarvis-hermes\jarvis_state.db --max-age-min 40
Exit code 0 = healthy, 2 = stale (alert).
"""
from __future__ import annotations
import argparse
import os
import sys
import time


def check_stale(db_path: str, max_age_min: int) -> tuple[bool, str]:
    log_path = os.path.join(os.path.dirname(os.path.abspath(db_path)), "jarvis.log")
    if not os.path.exists(log_path):
        return True, "no event log found (Jarvis may never have run)"
    try:
        from jarvis.core.logging import last_cycle_ts
    except Exception:  # noqa: fall back to tail scan if package import fails
        last_cycle_ts = None
    if last_cycle_ts is not None:
        last = last_cycle_ts(log_path)
    else:
        last = 0.0
    if last <= 0:
        return True, "no cycle event recorded yet"
    age = time.time() - last
    if age > max_age_min * 60:
        return True, f"last cycle was {age/60:.1f} min ago (> {max_age_min} min)"
    return False, f"healthy; last cycle {age/60:.1f} min ago"


def main(argv=None):
    p = argparse.ArgumentParser(description="External Jarvis liveness watchdog")
    p.add_argument("--db", default="jarvis_state.db")
    p.add_argument("--max-age-min", type=int, default=40)
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    stale, msg = check_stale(args.db, args.max_age_min)
    if not args.quiet:
        print(f"[{'STALE' if stale else 'OK'}] {msg}")
    return 2 if stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
