import os, tempfile, pathlib
import pytest
from jarvis.core.state import State, Task, Goal, TaskStatus
from jarvis.core.verifier import Verifier


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    s = State(path)
    yield s
    s.close()
    os.remove(path)


def test_verify_file_exists_pass(db):
    f = pathlib.Path(tempfile.gettempdir()) / "vv_marker.txt"
    f.write_text("x")
    t = Task(id="t", sub_goal="s", goal_statement="g", verification=f"file exists at {f}")
    db.add_task(t)
    v = Verifier(db)
    passed = v.apply(db.get_task("t"))
    assert passed is True
    assert db.get_task("t").status == TaskStatus.DONE
    f.unlink()


def test_verify_file_missing_fail_requetue(db):
    t = Task(id="t", sub_goal="s", goal_statement="g", verification="file exists at /nope/x.txt")
    db.add_task(t)
    v = Verifier(db)
    passed = v.apply(db.get_task("t"))
    assert passed is False
    assert db.get_task("t").status == TaskStatus.OPEN


def test_verify_no_spec_fails(db):
    t = Task(id="t", sub_goal="s", goal_statement="g", verification="")
    db.add_task(t)
    v = Verifier(db)
    res = v.verify(db.get_task("t"))
    assert res.passed is False


def test_verify_exhausted_attempts_marks_failed(db):
    t = Task(id="t", sub_goal="s", goal_statement="g", verification="file exists at /nope/x.txt",
             attempts=3, max_attempts=3)
    db.add_task(t)
    v = Verifier(db)
    v.apply(db.get_task("t"))
    assert db.get_task("t").status == TaskStatus.FAILED
