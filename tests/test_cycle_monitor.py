import os, tempfile, pathlib
import pytest
from jarvis.core.state import State, Task, Goal, TaskStatus
from jarvis.core.planner import Planner
from jarvis.core.dispatcher import Dispatcher
from jarvis.core.verifier import Verifier
from jarvis.core.monitor import Monitor
from jarvis.core.cycle import run_cycle, JarvisError
from jarvis.core.defaults import Defaults


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    s = State(path)
    s.set_goal(Goal(statement="income"))
    yield s
    s.close()
    os.remove(path)


def test_run_cycle_dispatches_first_task(db):
    mon = Monitor(min_free_ram_mb=0, max_cpu_percent=100)  # deterministic: ignore live RAM
    rep = run_cycle(db, Planner(db), Dispatcher(db, Defaults()), Verifier(db), mon, Defaults())
    assert rep.dispatched is not None
    assert rep.new_tasks
    assert db.get_task(rep.dispatched.task_id).status == TaskStatus.DOING

def test_run_cycle_no_goal_raises(db):
    import tempfile as _tf, os as _os
    fd, path = _tf.mkstemp(suffix=".db")
    _os.close(fd)
    empty = State(path)  # never had a goal set
    try:
        with pytest.raises(JarvisError):
            run_cycle(empty, Planner(empty), Dispatcher(empty, Defaults()),
                      Verifier(empty), Monitor(), Defaults())
    finally:
        empty.close()
        _os.remove(path)


class _OfflineMonitor(Monitor):
    def health(self):
        h = super().health()
        h["online"] = False
        return h


def test_run_cycle_offline_parks_internet_tasks(db):
    # dispatcher gives an internet-dependent ready task; offline -> parked, idle
    mon = _OfflineMonitor(min_free_ram_mb=0, max_cpu_percent=100)
    rep = run_cycle(db, Planner(db), Dispatcher(db, Defaults()),
                    Verifier(db), mon, Defaults())
    assert rep.online is False
    assert rep.idle is True
    assert "paused" in rep.next_action
    assert rep.dispatched is None


def test_run_cycle_ingests_worker_report(db):
    # create + dispatch a task, then feed a done report with a real file check
    f = pathlib.Path(tempfile.gettempdir()) / "rep_marker.txt"
    f.write_text("done")
    mon = Monitor(min_free_ram_mb=0, max_cpu_percent=100)
    rep = run_cycle(db, Planner(db), Dispatcher(db, Defaults()), Verifier(db), mon, Defaults())
    tid = rep.dispatched.task_id
    t = db.get_task(tid)
    t.verification = f"file exists at {f}"
    db.update_task(t)
    rep2 = run_cycle(db, Planner(db), Dispatcher(db, Defaults()), Verifier(db), mon,
                     Defaults(), reviewer_report=f"{tid}|done|file created")
    assert any(tid in v for v in rep2.verified)
    assert db.get_task(tid).status == TaskStatus.DONE
    f.unlink()


def test_run_cycle_escalates_when_stuck(db):
    # Cap open tasks to 0 so nothing ever dispatches; force many idle cycles.
    mon = Monitor(min_free_ram_mb=0, max_cpu_percent=100)  # ignore live RAM
    d = Defaults(max_open_tasks=0)
    last = None
    for _ in range(d.stuck_cycles_before_escalation + 1):
        last = run_cycle(db, Planner(db), Dispatcher(db, d), Verifier(db), mon, d)
    assert last.escalated is True


def test_monitor_reports_health(db):
    h = Monitor().health()
    assert "free_ram_mb" in h and "can_spawn" in h


def test_ingest_worker_report_pass(db):
    import tempfile, pathlib
    f = pathlib.Path(tempfile.gettempdir()) / "ing_marker.txt"
    f.write_text("x")
    db.add_task(Task(id="ing1", sub_goal="s", goal_statement="g",
                     verification=f"file exists at {f}"))
    v = Verifier(db)
    label = __import__("jarvis.core.cycle", fromlist=["ingest_worker_report"]).ingest_worker_report(
        db, v, "ing1", "done", "built it")
    assert label == "PASS"
    assert db.get_task("ing1").status == TaskStatus.DONE
    f.unlink()


def test_ingest_worker_report_failed_requetue(db):
    db.add_task(Task(id="ing2", sub_goal="s", goal_statement="g", attempts=1, max_attempts=3))
    v = Verifier(db)
    label = __import__("jarvis.core.cycle", fromlist=["ingest_worker_report"]).ingest_worker_report(
        db, v, "ing2", "failed", "could not")
    assert label == "REPORTED_FAIL"
    assert db.get_task("ing2").status == TaskStatus.OPEN
