import os, tempfile
import pytest
from jarvis.core.state import State, Task, Goal, TaskStatus, TaskPriority
from jarvis.core.planner import Planner
from jarvis.core.dispatcher import Dispatcher, Dispatch
from jarvis.core.defaults import Defaults


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    s = State(path)
    s.set_goal(Goal(statement="Make income"))
    yield s
    s.close()
    os.remove(path)


def test_default_decompose_returns_first_milestone(db):
    pl = Planner(db)
    subs = pl.next_subgoals(max_new=1)
    assert len(subs) == 1
    assert subs[0].verification


def test_dedup_does_not_recreate_in_flight(db):
    pl = Planner(db)
    subs = pl.next_subgoals(max_new=1)
    db.add_task(subs[0])
    # Running again should not return the same sub-goal while OPEN/DOING
    subs2 = pl.next_subgoals(max_new=1)
    texts = {s.sub_goal.lower() for s in subs2}
    assert subs[0].sub_goal.lower() not in texts


def test_custom_evaluator_marks_accomplished(db):
    pl = Planner(db, evaluate_fn=lambda s: True)
    assert pl.goal_accomplished() is True


def test_dispatcher_picks_highest_priority(db):
    db.add_task(Task(id="low", sub_goal="low", goal_statement="g", priority=TaskPriority.LOW))
    db.add_task(Task(id="high", sub_goal="high", goal_statement="g", priority=TaskPriority.HIGH))
    dp = Dispatcher(db, Defaults())
    ready = dp.ready_task()
    assert ready.id == "high"


def test_dispatch_marks_doing_and_bumps_attempts(db):
    db.add_task(Task(id="t", sub_goal="x", goal_statement="g"))
    dp = Dispatcher(db, Defaults())
    d = dp.dispatch(dp.ready_task())
    assert isinstance(d, Dispatch)
    assert db.get_task("t").status == TaskStatus.DOING
    assert db.get_task("t").attempts == 1


def test_can_dispatch_respects_cap(db):
    for i in range(3):
        db.add_task(Task(id=f"o{i}", sub_goal=f"x{i}", goal_statement="g", status=TaskStatus.OPEN))
    d = Defaults(max_open_tasks=3)
    dp = Dispatcher(db, d)
    assert dp.can_dispatch() is False  # 3 already open == cap
