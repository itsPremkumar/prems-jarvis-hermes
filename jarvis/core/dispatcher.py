"""Dispatcher: turns an open Task into a concrete worker assignment.

The pure-Python core does NOT call the network. It produces a structured
`Dispatch` (the exact brief a Hermes worker agent receives) and marks the task
DOING. The Hermes-side cron agent (see SKILL.md) reads the Dispatch and calls
the delegate_task tool with it. This separation keeps the core testable, and
keeps resource policy in one place.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional

from .state import State, Task, TaskStatus
from .defaults import Defaults


@dataclass
class Dispatch:
    task_id: str
    sub_goal: str
    goal_statement: str
    verification: str
    context: str
    toolsets: List[str]


class Dispatcher:
    def __init__(self, state: State, defaults: Optional[Defaults] = None):
        self.state = state
        self.d = defaults or Defaults()

    def ready_task(self) -> Optional[Task]:
        """Pick the highest-priority OPEN task that still has attempts left."""
        open_tasks = [t for t in self.state.list_tasks(TaskStatus.OPEN)
                      if t.attempts < t.max_attempts]
        if not open_tasks:
            return None
        open_tasks.sort(key=lambda t: (int(t.priority), t.created_at), reverse=True)
        return open_tasks[0]

    def dispatch(self, task: Task) -> Dispatch:
        task.status = TaskStatus.DOING
        task.attempts += 1
        self.state.update_task(task)
        return Dispatch(
            task_id=task.id,
            sub_goal=task.sub_goal,
            goal_statement=task.goal_statement,
            verification=task.verification,
            context=task.context,
            toolsets=task.toolsets or self.d.default_toolsets,
        )

    def can_dispatch(self) -> bool:
        """Concurrency + capacity gate (RAM/CPU checked by Monitor upstream)."""
        return self.state.open_count() < self.d.max_open_tasks
