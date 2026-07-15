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

    # Resource ceilings checked by Monitor before dispatch.
    # NOTE: on the target 6 GB Windows box free RAM normally sits ~100-300 MB,
    # so a 400 MB floor makes can_spawn() ALWAYS False -> no worker ever
    # dispatches -> tasks stuck in DOING forever -> permanent escalation.
    # Lowered to a realistic floor; the guard now WARNS instead of hard-blocking
    # when below floor (see Monitor.can_spawn). 64 MB is enough for a thin
    # delegate_task worker spawn on this box.
    min_free_ram_mb: int = 64
    max_cpu_percent: int = 95

    # Cron cadence (informational; the cron job owns the timer)
    tick_interval_minutes: int = 30

    # A task that stays in DOING without any update for this long is considered
    # a lost/orphaned worker dispatch -> reset it to OPEN so the dedup releases
    # and it can be re-dispatched (prevents permanent DOING-stuck tasks).
    stale_doing_minutes: int = 90


# Avoid mutable default via class-level init
Defaults.default_toolsets = ["terminal", "file", "web"]


DEFAULT_GOAL = (
    "Build and operate a self-sustaining online income stream that earns "
    "revenue with minimal manual intervention, starting from a verifiable "
    "first sale or first 100 opted-in leads."
)
