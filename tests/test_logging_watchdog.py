import os, tempfile, time
import pytest
from jarvis.core.logging import log_event, read_events, last_cycle_ts, uptime_since_first


@pytest.fixture
def logf():
    fd, path = tempfile.mkstemp(suffix=".log")
    os.close(fd)
    os.remove(path)
    yield path
    try:
        os.remove(path)
    except OSError:
        pass
    try:
        os.remove(path + ".1")
    except OSError:
        pass


def test_log_event_written_and_read(logf):
    log_event(log_path=logf, event="cycle", status="start", cycle=1)
    evs = read_events(logf)
    assert len(evs) == 1
    assert evs[0]["event"] == "cycle"
    assert evs[0]["cycle"] == 1
    assert "ts" in evs[0]


def test_last_cycle_ts(logf):
    log_event(log_path=logf, event="other", status="x")
    log_event(log_path=logf, event="cycle", status="start", cycle=5)
    assert last_cycle_ts(logf) == pytest.approx(time.time(), abs=5)


def test_uptime_increases(logf):
    log_event(log_path=logf, event="cycle", status="start", cycle=1)
    time.sleep(0.01)
    assert uptime_since_first(logf) >= 0.01


def test_rotation_creates_backup(logf):
    from jarvis.core.logging import _maybe_rotate, MAX_BYTES
    with open(logf, "w") as f:
        # each line ~8 bytes; write just over the threshold
        f.write(('{"a":1}\n' * (MAX_BYTES // 8 + 10)))
    assert os.path.getsize(logf) > MAX_BYTES
    _maybe_rotate(logf)
    assert os.path.exists(logf + ".1")


def test_watchdog_detects_stale(tmp_path):
    db = tmp_path / "jarvis_state.db"
    # No log file -> stale
    import importlib.util
    spec = importlib.util.spec_from_file_location("watchdog",
        os.path.join(os.path.dirname(__file__), "..", "watchdog.py"))
    wd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wd)
    stale, msg = wd.check_stale(str(db), max_age_min=40)
    assert stale is True
