"""Cycle: one Jarvis tick. Pure-Python, deterministic, testable.

run_cycle() is the heart of the orchestrator. It does NOT call the network or
the delegate_task tool itself. Instead it returns a CycleReport that includes a
`dispatch` (the worker brief) when a worker should be spawned. The Hermes-side
skill/cron agent reads that brief and actually calls delegate_task. This keeps
the core fully runnable and verifiable on its own, and makes the worker-spawn
boundary explicit.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import List, Optional

from .state import State, TaskStatus
from .defaults import Defaults
from .planner import Planner
from .dispatcher import Dispatcher, Dispatch
from .verifier import Verifier
from .monitor import Monitor
from .logging import log_event


class JarvisError(RuntimeError):
    pass


@dataclass
class CycleReport:
    cycle: int
    goal_accomplished: bool
    dispatched: Optional[Dispatch] = None
    new_tasks: List[str] = field(default_factory=list)
    verified: List[str] = field(default_factory=list)
    escalated: bool = False
    stuck_cycles: int = 0
    next_action: str = ""
    health: dict = field(default_factory=dict)
    idle: bool = False


def run_cycle(
    state: State,
    planner: Planner,
    dispatcher: Optional[Dispatcher] = None,
    verifier: Optional[Verifier] = None,
    monitor: Optional[Monitor] = None,
    defaults: Optional[Defaults] = None,
    reviewer_report: Optional[str] = None,
) -> CycleReport:
    d = defaults or Defaults()
    dispatcher = dispatcher or Dispatcher(state, d)
    verifier = verifier or Verifier(state)
    monitor = monitor or Monitor(d.min_free_ram_mb, d.max_cpu_percent)
    cycle = state.bump_cycle()
    state.set_last_tick(time.time())
    report = CycleReport(cycle=cycle, goal_accomplished=False, health=monitor.health())
    log_event(event="cycle", status="start", cycle=cycle)

    # 0) no goal set -> fatal, can't run
    goal = state.get_goal()
    if goal is None or not goal.statement.strip():
        log_event(event="cycle", status="error", cycle=cycle, detail="no goal set")
        raise JarvisError("No goal set. Call set_goal() before running cycles.")

    # 1) Consume a worker report if provided (Hermes agent passes it back)
    if reviewer_report:
        _ingest_report(state, verifier, reviewer_report, report)

    # 2) Goal accomplished?
    if planner.goal_accomplished():
        goal = state.get_goal()
        goal.accomplished = True
        state.set_goal(goal)
        report.goal_accomplished = True
        report.idle = True
        report.next_action = "Goal accomplished. Sleeping until re-eval."
        log_event(event="cycle", status="goal_accomplished", cycle=cycle)
        return report

    # 3) Resource gate before doing anything expensive
    if not monitor.can_spawn():
        report.next_action = "Resource guard: cannot spawn now (RAM/CPU). Sleeping."
        report.idle = True
        report.stuck_cycles = _bump_stuck(state)
        log_event(event="cycle", status="resource_guard", cycle=cycle,
                  detail=report.next_action)
        return report

    # 4) Decompose: create at most max_new_per_cycle sub-goals.
    # NOTE: creating a task is NOT progress; do NOT reset the stuck counter here.
    new = planner.next_subgoals(max_new=d.max_new_per_cycle)
    for t in new:
        state.add_task(t)
        report.new_tasks.append(t.id)

    # 5) Dispatch a worker if capacity allows
    if dispatcher.can_dispatch():
        task = dispatcher.ready_task()
        if task is not None:
            report.dispatched = dispatcher.dispatch(task)
            report.next_action = f"Dispatched worker for: {task.sub_goal}"
            log_event(event="dispatch", status="ok", cycle=cycle,
                      task_id=task.id, detail=task.sub_goal)
            _reset_stuck(state)
            return report

    # 6) Nothing to do -> idle. Track stuck cycles for escalation.
    report.stuck_cycles = _bump_stuck(state)
    if report.stuck_cycles >= d.stuck_cycles_before_escalation:
        report.escalated = True
        report.next_action = (
            f"Escalating to operator: {report.stuck_cycles} cycles with no progress."
        )
        log_event(event="cycle", status="escalation", cycle=cycle,
                  detail=report.next_action)
    else:
        report.idle = True
        report.next_action = "Queue clear / capacity full. Sleeping until next tick."
    return report


def ingest_worker_report(state, verifier, task_id: str, status: str, text: str, rep: Optional[CycleReport] = None) -> str:
    """Public: record a worker's result for a task and run the verification gate.
    Returns a short label like 'PASS' / 'RETRY' / 'REPORTED_FAIL'. Shared by the
    `run` reviewer_report path and the standalone `jarvis.cli report` command."""
    task = state.get_task(task_id.strip())
    if task is None:
        log_event(event="report", status="unknown_task", task_id=task_id.strip())
        return "UNKNOWN_TASK"
    task.result = (text or "").strip()
    if status.strip().lower() in ("done", "pass", "success"):
        passed = verifier.apply(task)
        label = "PASS" if passed else "RETRY"
        log_event(event="report", status=label, task_id=task.id,
                  detail=task.verification_notes)
    else:
        task.status = TaskStatus.OPEN if task.attempts < task.max_attempts else TaskStatus.FAILED
        task.verification_result = False
        state.update_task(task)
        label = "REPORTED_FAIL"
        log_event(event="report", status=label, task_id=task.id, detail=text)
    if rep is not None:
        rep.verified.append(f"{task.id}:{label}")
    return label


def _ingest_report(state, verifier, report_text, rep: CycleReport):
    """Parse a short worker report of form: TASK_ID|STATUS|free text.
    STATUS in {done, failed}. Delegates to ingest_worker_report()."""
    try:
        task_id, status, *rest = report_text.split("|", 2)
    except ValueError:
        return
    ingest_worker_report(state, verifier, task_id, status, " ".join(rest), rep)
    _reset_stuck(state)  # a verified outcome is real progress


def _bump_stuck(state: State) -> int:
    n = int(state._get_meta("stuck") or 0) + 1
    state._set_meta("stuck", str(n))
    return n


def _reset_stuck(state: State):
    state._set_meta("stuck", "0")
