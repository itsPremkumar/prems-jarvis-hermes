"""Structured event logging for Jarvis.

Every meaningful event (cycle start, dispatch, verify, escalation, error, reboot
recovery) is appended as one JSON line to jarvis.log. This is the "log everything"
resilience row, done for real and cheaply. Logs are rotated when they exceed a
size threshold so they can never fill the disk (the disk-full recovery row).

Format per line (JSON):
  {"ts": 1710000000.0, "event": "cycle", "cycle": 12, "status": "dispatched",
   "task_id": "t_...", "detail": "..."}
"""
from __future__ import annotations
import json
import os
import time
import threading

_LOCK = threading.Lock()
DEFAULT_LOG = "jarvis.log"
MAX_BYTES = 2_000_000  # ~2 MB before rotation


def log_event(log_path: str = DEFAULT_LOG, event: str = "", status: str = "",
              task_id: str = "", detail: str = "", cycle: int = 0,
              goal_accomplished: bool = False):
    """Append one structured event. Thread/process safe via file lock."""
    record = {
        "ts": round(time.time(), 3),
        "event": event,
        "status": status,
        "task_id": task_id,
        "cycle": cycle,
        "goal_accomplished": goal_accomplished,
        "detail": detail,
    }
    line = json.dumps(record, ensure_ascii=False)
    with _LOCK:
        _maybe_rotate(log_path)
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:  # noqa: never let logging crash the loop
            pass
    return record


def _maybe_rotate(log_path: str):
    try:
        if os.path.exists(log_path) and os.path.getsize(log_path) > MAX_BYTES:
            rotated = log_path + ".1"
            if os.path.exists(rotated):
                os.remove(rotated)
            os.rename(log_path, rotated)
    except OSError:  # noqa
        pass


def read_events(log_path: str = DEFAULT_LOG, limit: int = 50) -> list:
    """Return the last `limit` event dicts (newest last)."""
    if not os.path.exists(log_path):
        return []
    out = []
    with _LOCK:
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:  # noqa
            return out
    return out[-limit:]


def last_cycle_ts(log_path: str = DEFAULT_LOG) -> float:
    """Timestamp of the most recent cycle event, or 0.0 if none."""
    events = read_events(log_path, limit=2000)
    for e in reversed(events):
        if e.get("event") == "cycle":
            return float(e.get("ts", 0.0))
    return 0.0


def uptime_since_first(log_path: str = DEFAULT_LOG) -> float:
    """Seconds since the first recorded event (proxy for system uptime)."""
    if not os.path.exists(log_path):
        return 0.0
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            first = f.readline().strip()
            if not first:
                return 0.0
            return time.time() - float(json.loads(first).get("ts", time.time()))
    except (OSError, json.JSONDecodeError):
        return 0.0
