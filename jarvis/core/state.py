"""Persistent state for Jarvis: goals, tasks, and a durable SQLite store.

State is the real product. The orchestrator process can die and restart freely;
everything that matters lives in the SQLite file (jarvis_state.db).
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Optional


class TaskStatus(str, Enum):
    OPEN = "open"          # waiting for a worker to be assigned
    DOING = "doing"        # a worker has been (re)dispatched for it
    DONE = "done"          # verification passed
    FAILED = "failed"      # attempts exhausted or verified-fail
    BLOCKED = "blocked"    # waiting on a dependency


class TaskPriority(int, Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class Goal:
    statement: str
    created_at: float = field(default_factory=time.time)
    accomplished: bool = False
    context: str = ""  # long-term context the controller should always carry


@dataclass
class Task:
    id: str
    sub_goal: str
    goal_statement: str
    status: TaskStatus = TaskStatus.OPEN
    priority: TaskPriority = TaskPriority.MEDIUM
    verification: str = ""       # what "done" concretely means (must be checkable)
    context: str = ""            # brief handed to the worker (links, prior work, repo paths)
    toolsets: List[str] = field(default_factory=list)
    parent_id: Optional[str] = None
    attempts: int = 0
    max_attempts: int = 3
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    result: str = ""             # last report from the worker
    verification_result: Optional[bool] = None  # True/False/None(unverified)
    verification_notes: str = ""

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["status"] = self.status.value
        d["priority"] = int(self.priority)
        return d

    @classmethod
    def from_row(cls, row: Dict) -> "Task":
        t = cls(
            id=row["id"],
            sub_goal=row["sub_goal"],
            goal_statement=row["goal_statement"],
            status=TaskStatus(row["status"]),
            priority=TaskPriority(int(row["priority"])),
            verification=row["verification"],
            context=row["context"],
            parent_id=row["parent_id"],
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            result=row["result"],
            verification_result=_parse_bool(row["verification_result"]),
            verification_notes=row["verification_notes"],
        )
        t.toolsets = json.loads(row["toolsets"] or "[]")
        return t


def _parse_bool(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "t", "yes")


class State:
    """SQLite-backed store. Stdlib only so it runs on any box."""

    def __init__(self, db_path: str = "jarvis_state.db"):
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                sub_goal TEXT,
                goal_statement TEXT,
                status TEXT,
                priority INTEGER,
                verification TEXT,
                context TEXT,
                toolsets TEXT,
                parent_id TEXT,
                attempts INTEGER,
                max_attempts INTEGER,
                created_at REAL,
                updated_at REAL,
                result TEXT,
                verification_result TEXT,
                verification_notes TEXT
            )
            """
        )
        self._conn.commit()

    # --- meta helpers (goal + counters) ---
    def get_goal(self) -> Optional[Goal]:
        row = self._get_meta("goal")
        if not row:
            return None
        return Goal(**json.loads(row))

    def set_goal(self, goal: Goal):
        self._set_meta("goal", json.dumps(asdict(goal)))

    def get_cycle(self) -> int:
        return int(self._get_meta("cycle") or 0)

    def bump_cycle(self) -> int:
        n = self.get_cycle() + 1
        self._set_meta("cycle", str(n))
        return n

    def get_last_tick(self) -> float:
        return float(self._get_meta("last_tick") or 0.0)

    def set_last_tick(self, t: float):
        self._set_meta("last_tick", str(t))

    def _get_meta(self, key: str) -> Optional[str]:
        cur = self._conn.cursor()
        cur.execute("SELECT value FROM meta WHERE key=?", (key,))
        row = cur.fetchone()
        return row["value"] if row else None

    def _set_meta(self, key: str, value: str):
        cur = self._conn.cursor()
        cur.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self._conn.commit()

    # --- task CRUD ---
    def add_task(self, task: Task):
        cur = self._conn.cursor()
        d = task.to_dict()
        d["toolsets"] = json.dumps(d["toolsets"])
        d["verification_result"] = (
            "" if d["verification_result"] is None else str(d["verification_result"])
        )
        cols = list(d.keys())
        placeholders = ",".join("?" for _ in cols)
        cur.execute(
            f"INSERT OR REPLACE INTO tasks({','.join(cols)}) VALUES({placeholders})",
            [d[c] for c in cols],
        )
        self._conn.commit()

    def get_task(self, task_id: str) -> Optional[Task]:
        cur = self._conn.cursor()
        cur.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
        row = cur.fetchone()
        return Task.from_row(dict(row)) if row else None

    def update_task(self, task: Task):
        task.updated_at = time.time()
        self.add_task(task)

    def list_tasks(self, status: Optional[TaskStatus] = None) -> List[Task]:
        cur = self._conn.cursor()
        if status is None:
            cur.execute("SELECT * FROM tasks ORDER BY priority DESC, created_at ASC")
        else:
            cur.execute(
                "SELECT * FROM tasks WHERE status=? ORDER BY priority DESC, created_at ASC",
                (status.value,),
            )
        return [Task.from_row(dict(r)) for r in cur.fetchall()]

    def open_count(self) -> int:
        return len(self.list_tasks(TaskStatus.OPEN)) + len(self.list_tasks(TaskStatus.DOING))

    def done_today(self) -> int:
        start = time.time() - 86400
        cur = self._conn.cursor()
        cur.execute(
            "SELECT COUNT(*) AS c FROM tasks WHERE status=? AND updated_at>=?",
            (TaskStatus.DONE.value, start),
        )
        return cur.fetchone()["c"]

    def failed_count(self) -> int:
        return len(self.list_tasks(TaskStatus.FAILED))

    def close(self):
        self._conn.close()
