"""jarvis.cli: command-line entrypoint.

Subcommands:
  init        create a fresh state DB + set the default money goal
  status      show current goal / task counts
  dashboard   print the always-visible Jarvis dashboard
  run         execute exactly ONE cycle (the cron agent calls this)
  selftest    run offline structural checks (no network, no tokens)
"""
from __future__ import annotations
import argparse
import os
import sys

from .core import (
    State, Planner, Dispatcher, Verifier, Monitor, Defaults, DEFAULT_GOAL, Goal, JarvisError,
    ingest_worker_report,
)
from .dashboard import render_dashboard


def _state(db_path: str) -> State:
    return State(db_path)


def cmd_init(args):
    s = _state(args.db)
    if s.get_goal() is None:
        s.set_goal(Goal(statement=DEFAULT_GOAL))
        print(f"Goal set: {DEFAULT_GOAL}")
    else:
        print("Goal already set; leaving it.")
    print(f"State DB ready at {os.path.abspath(args.db)}")
    return 0


def cmd_status(args):
    s = _state(args.db)
    g = s.get_goal()
    print("Goal :", g.statement if g else "(none)")
    print("Open :", s.open_count(), "| Done24h:", s.done_today(), "| Failed:", s.failed_count())
    print("Cycle:", s.get_cycle())
    return 0


def cmd_dashboard(args):
    s = _state(args.db)
    print(render_dashboard(s))
    return 0


def cmd_run(args):
    s = _state(args.db)
    planner = Planner(s)
    dispatcher = Dispatcher(s, Defaults())
    verifier = Verifier(s)
    monitor = Monitor(Defaults().min_free_ram_mb, Defaults().max_cpu_percent)
    try:
        rep = __import__("jarvis.core.cycle", fromlist=["run_cycle"]).run_cycle(
            s, planner, dispatcher, verifier, monitor, Defaults()
        )
    except JarvisError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    print(render_dashboard(s))
    print("\nNEXT ACTION:", rep.next_action)
    if rep.dispatched:
        print("\nDISPATCH (hand this brief to a Hermes worker via delegate_task):")
        print(f"  task_id      : {rep.dispatched.task_id}")
        print(f"  sub_goal     : {rep.dispatched.sub_goal}")
        print(f"  verification : {rep.dispatched.verification}")
        print(f"  toolsets     : {rep.dispatched.toolsets}")
        print(f"  context      : {rep.dispatched.context}")
    if rep.escalated:
        print("\nESCALATION: too many idle cycles - operator input needed.")
    return 0


def cmd_report(args):
    """Record a worker's result for a task id and run the verification gate."""
    s = _state(args.db)
    verifier = Verifier(s)
    label = ingest_worker_report(s, verifier, args.task_id, args.status, args.text)
    print(f"[{label}] task {args.task_id} -> {s.get_task(args.task_id).status.value}")
    s.close()
    return 0


def cmd_tasks(args):
    s = _state(args.db)
    rows = s.list_tasks()
    if not rows:
        print("(no tasks)")
        return 0
    for t in rows:
        print(f"{t.id}  [{t.status.value:>6}] p{int(t.priority)}  {t.sub_goal}")
        print(f"         verify: {t.verification}")
        if t.result:
            print(f"         result: {t.result[:80]}")
    s.close()
    return 0


def cmd_selftest(args):
    import importlib.util
    ok = True
    checks = []

    def chk(name, cond):
        nonlocal ok
        ok = ok and cond
        checks.append(("OK" if cond else "FAIL", name))

    # 1) modules import
    try:
        from jarvis.core import State, Planner, Dispatcher, Verifier, Monitor, run_cycle  # noqa
        chk("import core modules", True)
    except Exception as e:  # noqa
        chk(f"import core modules ({e})", False)

    # 2) fresh state + goal
    tmp = os.path.join(os.path.dirname(__file__), "..", "_selftest.db")
    try:
        os.remove(tmp)
    except OSError:
        pass
    st = State(tmp)
    st.set_goal(Goal(statement="TEST GOAL"))
    chk("set/get goal", st.get_goal().statement == "TEST GOAL")

    # 3) decompose via default planner produces a task
    pl = Planner(st)
    subs = pl.next_subgoals(max_new=1)
    chk("default decompose returns a task", len(subs) == 1)
    for t in subs:
        st.add_task(t)
    chk("task persisted", st.get_task(subs[0].id) is not None)

    # 4) dispatch marks DOING and bumps attempts
    dp = Dispatcher(st, Defaults())
    t = dp.ready_task()
    d = dp.dispatch(t)
    chk("dispatch -> DOING", st.get_task(t.id).status.value == "doing")
    chk("dispatch bumps attempts", st.get_task(t.id).attempts == 1)
    chk("dispatch brief has verification", bool(d.verification))

    # 5) verify a file-exists task passes when file present
    import tempfile, pathlib
    f = pathlib.Path(tempfile.gettempdir()) / "jarvis_selftest_marker.txt"
    f.write_text("hello")
    vt = st.get_task(t.id)
    vt.verification = f"file exists at {f}"
    vt.result = ""
    vt.status = __import__("jarvis.core.state", fromlist=["TaskStatus"]).TaskStatus.OPEN
    st.update_task(vt)
    vr = Verifier(st)
    passed = vr.apply(st.get_task(vt.id))
    chk("verify file-exists -> PASS", passed is True and st.get_task(vt.id).status.value == "done")

    # 6) verify a fail when file absent
    vt2 = st.get_task(vt.id)
    vt2.verification = "file exists at /nope/missing.txt"
    vt2.status = __import__("jarvis.core.state", fromlist=["TaskStatus"]).TaskStatus.OPEN
    st.update_task(vt2)
    passed2 = vr.apply(st.get_task(vt2.id))
    chk("verify missing-file -> FAIL/RETRY", passed2 is False)

    # 7) full cycle runs and returns a report
    try:
        rep = run_cycle(st, Planner(st), Dispatcher(st, Defaults()), Verifier(st), Monitor(), Defaults())
        chk("run_cycle returns report", rep is not None and rep.cycle >= 1)
    except Exception as e:  # noqa
        chk(f"run_cycle ({e})", False)

    # 8) dashboard renders
    try:
        from jarvis.dashboard import render_dashboard
        out = render_dashboard(st)
        chk("dashboard renders", "J A R V I S" in out)
    except Exception as e:  # noqa
        chk(f"dashboard ({e})", False)

    st.close()
    try:
        os.remove(tmp)
    except OSError:
        pass

    print("SELFTEST RESULTS")
    for status, name in checks:
        print(f"  [{status}] {name}")
    print(f"\n{sum(1 for c,_ in checks if c=='OK')}/{len(checks)} checks passed")
    return 0 if ok else 1


def main(argv=None):
    p = argparse.ArgumentParser(prog="jarvis", description="Prems-Jarvis-Hermes orchestrator")
    p.add_argument("--db", default="jarvis_state.db", help="path to state DB")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create state DB + set default money goal").set_defaults(func=cmd_init)
    sub.add_parser("status", help="show goal/task counts").set_defaults(func=cmd_status)
    sub.add_parser("dashboard", help="print dashboard").set_defaults(func=cmd_dashboard)
    sub.add_parser("run", help="run exactly one cycle").set_defaults(func=cmd_run)

    p_report = sub.add_parser("report", help="record a worker result: TASK_ID STATUS TEXT")
    p_report.add_argument("task_id")
    p_report.add_argument("status", choices=["done", "failed"])
    p_report.add_argument("text", nargs="?", default="")
    p_report.set_defaults(func=cmd_report)

    sub.add_parser("tasks", help="list all tasks").set_defaults(func=cmd_tasks)

    sub.add_parser("selftest", help="offline structural self-test").set_defaults(func=cmd_selftest)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
