import os, tempfile
import pytest
from jarvis.core.state import State, Task, Goal, TaskStatus, TaskPriority


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    s = State(path)
    yield s
    s.close()
    os.remove(path)


def test_set_get_goal(db):
    g = Goal(statement="Earn money")
    db.set_goal(g)
    assert db.get_goal().statement == "Earn money"


def test_add_get_update_task(db):
    t = Task(id="t1", sub_goal="Build landing page", goal_statement="G")
    db.add_task(t)
    got = db.get_task("t1")
    assert got.sub_goal == "Build landing page"
    assert got.status == TaskStatus.OPEN
    got.status = TaskStatus.DONE
    db.update_task(got)
    assert db.get_task("t1").status == TaskStatus.DONE


def test_open_count_and_done_today(db):
    t1 = Task(id="a", sub_goal="s1", goal_statement="g", status=TaskStatus.OPEN)
    t2 = Task(id="b", sub_goal="s2", goal_statement="g", status=TaskStatus.DONE)
    db.add_task(t1); db.add_task(t2)
    assert db.open_count() == 1
    assert db.done_today() == 1


def test_cycle_counter(db):
    assert db.get_cycle() == 0
    assert db.bump_cycle() == 1
    assert db.bump_cycle() == 2


def test_task_serialization_roundtrip_toollists(db):
    t = Task(id="x", sub_goal="s", goal_statement="g", toolsets=["terminal", "web"])
    db.add_task(t)
    got = db.get_task("x")
    assert got.toolsets == ["terminal", "web"]
