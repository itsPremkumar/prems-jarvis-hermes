"""Operational guardrails for Jarvis. Tuned for low-RAM Windows box by default."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class Defaults:
    # Goal decomposition
    max_open_tasks: int = 3          # hard cap on concurrent live tasks (RAM-bound)
    max_new_per_cycle: int = 1       # at most one new sub-goal per tick (avoid flood)
    stuck_cycles_before_escalation: int = 12  # escalate to human after N idle/zero-progress cycles

    # Worker dispatch (used by the Hermes agent side, not the pure-Python core)
    default_toolsets: list = None    # set below (dataclass default mutable issue)

    # Idle behaviour: when nothing to do, sleep, don't think expensively
    idle_sleep_seconds: int = 60

    # Resource ceilings checked by Monitor before dispatch
    min_free_ram_mb: int = 400
    max_cpu_percent: int = 85

    # Cron cadence (informational; the cron job owns the timer)
    tick_interval_minutes: int = 30


# Avoid mutable default via class-level init
Defaults.default_toolsets = ["terminal", "file", "web"]


DEFAULT_GOAL = (
    "Build and operate a self-sustaining online income stream that earns "
    "revenue with minimal manual intervention, starting from a verifiable "
    "first sale or first 100 opted-in leads."
)
