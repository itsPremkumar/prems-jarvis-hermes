"""Planner: decides whether the goal is met, and what the next sub-goal is.

In production, `evaluate_goal` and `decompose` are backed by an LLM (Hermes).
This module defines the deterministic contract + a pluggable evaluator so the
core is testable without burning tokens and without network access.
"""
from __future__ import annotations
from typing import Callable, List, Optional

from .state import State, Task, TaskStatus, TaskPriority


class Planner:
    def __init__(
        self,
        state: State,
        evaluate_fn: Optional[Callable[[State], bool]] = None,
        decompose_fn: Optional[Callable[[State], List[dict]]] = None,
    ):
        # Default evaluators are explicit/deterministic so tests and offline
        # runs work. The Hermes skill overrides these with LLM-backed functions.
        self.state = state
        self.evaluate_fn = evaluate_fn or self._default_evaluate
        self.decompose_fn = decompose_fn or self._default_decompose

    def goal_accomplished(self) -> bool:
        goal = self.state.get_goal()
        if goal is None:
            return False
        if goal.accomplished:
            return True
        return bool(self.evaluate_fn(self.state))

    def next_subgoals(self, max_new: int = 1) -> List[Task]:
        """Return up to `max_new` new Task objects for the gap (dedup-aware)."""
        open_texts = {t.sub_goal.strip().lower() for t in self.state.list_tasks()
                      if t.status in (TaskStatus.OPEN, TaskStatus.DOING)}
        candidates = self.decompose_fn(self.state)
        created: List[Task] = []
        for c in candidates:
            sub = c.get("sub_goal", "").strip()
            if not sub:
                continue
            if sub.lower() in open_texts:
                continue  # dedup: don't recreate an in-flight task
            open_texts.add(sub.lower())
            created.append(self._make_task(c))
            if len(created) >= max_new:
                break
        return created

    def _make_task(self, c: dict) -> Task:
        import time, hashlib
        base = c.get("sub_goal", "") + c.get("goal_statement", "")
        tid = "t_" + hashlib.sha1(base.encode()).hexdigest()[:10] + str(int(time.time()))[-5:]
        return Task(
            id=tid,
            sub_goal=c.get("sub_goal", ""),
            goal_statement=c.get("goal_statement", ""),
            status=TaskStatus.OPEN,
            priority=TaskPriority(c.get("priority", TaskPriority.MEDIUM.value)),
            verification=c.get("verification", ""),
            context=c.get("context", ""),
            toolsets=c.get("toolsets", []),
            parent_id=c.get("parent_id"),
        )

    # --- deterministic defaults (overridable) ---
    def _default_evaluate(self, state: State) -> bool:
        # Without an LLM, "accomplished" only flips via explicit goal flag.
        return False

    def _default_decompose(self, state: State) -> List[dict]:
        # Without an LLM, fall back to a fixed first milestone so the loop can
        # actually start producing work in tests/offline. Real runs use LLM.
        goal = state.get_goal()
        if not goal:
            return []
        existing = {t.sub_goal.lower() for t in state.list_tasks()}
        milestones = [
            {
                "sub_goal": "Define a concrete, sellable product or lead magnet",
                "verification": "A written product spec file exists at spec.md with a price or offer",
                "priority": TaskPriority.HIGH.value,
                "toolsets": ["file", "web"],
            },
            {
                "sub_goal": "Build a landing page that captures leads or takes payment",
                "verification": "A deployed URL returns HTTP 200 and contains an email/payment input",
                "priority": TaskPriority.HIGH.value,
                "toolsets": ["terminal", "file", "web"],
            },
            {
                "sub_goal": "Drive the first 100 targeted visitors to the offer",
                "verification": "Traffic logs or analytics show >=100 unique visits",
                "priority": TaskPriority.MEDIUM.value,
                "toolsets": ["web"],
            },
        ]
        for m in milestones:
            if m["sub_goal"].lower() not in existing:
                m["goal_statement"] = goal.statement
                return [m]
        return []
