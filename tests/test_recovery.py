import os, tempfile
import pytest
from jarvis.core.recovery import retry, CircuitBreaker, TransientError, PermanentError


def test_retry_succeeds_after_failures():
    calls = {"n": 0}
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise TransientError("boom")
        return "ok"
    assert retry(flaky, max_attempts=5, base_delay=0, backoff=1) == "ok"
    assert calls["n"] == 3


def test_retry_gives_up_after_max():
    def always():
        raise TransientError("x")
    with pytest.raises(TransientError):
        retry(always, max_attempts=3, base_delay=0, backoff=1)


def test_retry_infinite_allows_recovery():
    # max_attempts<=0 => never give up
    calls = {"n": 0}
    def always():
        calls["n"] += 1
        if calls["n"] < 50:
            raise TransientError("x")
        return "recovered"
    assert retry(always, max_attempts=0, base_delay=0, backoff=1) == "recovered"
    assert calls["n"] == 50


def test_permanent_error_short_circuits():
    def bad():
        raise PermanentError("nope")
    with pytest.raises(PermanentError):
        retry(bad, max_attempts=5, base_delay=0)


def test_circuit_breaker_opens_and_recovers():
    cb = CircuitBreaker(threshold=2, cooldown=0.01)
    for _ in range(2):
        try:
            cb.call(lambda: (_ for _ in ()).throw(TransientError()))
        except TransientError:
            pass
    assert cb.state == "open"
    assert not cb.allow()
    # after cooldown -> half-open -> success closes it
    import time; time.sleep(0.02)
    assert cb.call(lambda: "ok") == "ok"
    assert cb.state == "closed"


def test_monitor_disk_free_mb():
    from jarvis.core.monitor import Monitor
    m = Monitor()
    free = m.disk_free_mb(os.getcwd())
    assert free > 0
    assert "disk_free_mb" in m.health()
