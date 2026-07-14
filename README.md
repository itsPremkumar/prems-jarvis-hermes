# Prems-Jarvis-Hermes

A persistent **goal-decomposition orchestrator** that runs inside the Hermes AI
agent. Jarvis acts as a continuous CEO: it checks whether the main money-earning
goal is met, and if not, it breaks the remaining gap into a sub-goal and defines
a self-contained brief for a throwaway worker agent. Workers do the work; Jarvis
only thinks, decomposes, dispatches, and verifies.

> Jarvis (orchestrator / long-running) → decomposes goal → defines sub-agent goal
> → Hermes `delegate_task` spawns worker → worker returns report → Jarvis verifies
> → accepts/rejects → repeats forever.

## Why this design
- **Orchestrator ≠ doer.** One giant agent doing everything overflows context and
  can't parallelize. Delegation is the answer.
- **Workers are ephemeral; state is permanent.** Everything durable lives in
  `jarvis_state.db` (SQLite), so the loop survives crashes and reboots for free.
- **Verification gate.** A task is DONE only when its `verification` check passes
  (file exists / HTTP 200 / LLM review). This stops the loop from spinning on lies.
- **Resource guards.** On a low-RAM Windows box (this one has ~6 GB, often <400 MB
  free), the monitor blocks worker spawning when RAM/CPU are too tight. No OOM.

## Install
```bash
cd prems-jarvis-hermes
python -m pip install -e .            # runtime = stdlib only
python -m pip install -e ".[dev]"     # + pytest for tests
```

## Resilience layer (survives reboot + Hermes death)

- **Structured logging** — every cycle/dispatch/verify/escalation writes one
  JSON line to `jarvis.log`. View with `python -m jarvis.cli log --limit 30`.
  Logs rotate at ~2 MB so they can never fill the disk.
- **External watchdog** (`watchdog.py`) — runs *outside* Hermes (via Windows
  Task Scheduler), so it survives Hermes crashing. It checks whether a Jarvis
  cycle ran recently; exits 2 (alert) if stale. `python watchdog.py --db ... --max-age-min 40`
- **Reboot survival** — two Task Scheduler tasks are registered:
  - `JarvisBoot` (on login): runs one Jarvis cycle right after a reboot, so the
    queue resumes automatically. State is already durable in `jarvis_state.db`.
  - `JarvisWatchdog` (every 10 min): the liveness check above.

> Layering reality: Hermes (the desktop app) is the host; Jarvis is a cron guest
> inside it. So the recovery chain terminates at the OS (Task Scheduler), not at
> Jarvis. Jarvis cannot restart Hermes — only the OS trigger can. This is by
> design, not a gap.

## Commands
```bash
python -m jarvis.cli init        # create state DB + set default money goal
python -m jarvis.cli status      # show goal / task counts
python -m jarvis.cli dashboard   # always-visible Jarvis dashboard
python -m jarvis.cli run         # run EXACTLY ONE cycle (the cron agent calls this)
python -m jarvis.cli report <id> done|failed "summary"   # feed worker result
python -m jarvis.cli tasks       # list all tasks
python -m jarvis.cli log         # show structured event log
python -m jarvis.cli selftest    # offline structural self-test (no network/tokens)
python watchdog.py --db jarvis_state.db --max-age-min 40   # external liveness check
```

### Running as a 24/7 loop inside Hermes
Register the bundled `SKILL.md` (`jarvis` skill) and create a cron job:
```text
schedule: every 30m
prompt:   Act as Jarvis. Read state (`python -m jarvis.cli status`), run one cycle
          (`python -m jarvis.cli run`), and if a DISPATCH block appears, spawn the
          worker via delegate_task with that brief. Feed the worker report back next
          tick. If ESCALATION appears, message the operator. Never recreate in-flight
          sub-goals; respect the worker cap.
```
Each tick: evaluate goal → decompose gap → dispatch ≤1 new worker (cap 3) →
verify completed work → persist → sleep. Crashing/restarting is free (state in DB).

## Architecture
```
jarvis/
  core/
    state.py      SQLite store: Goal + Task, fully durable
    defaults.py   Guardrails: max_open_tasks=3, RAM/CPU caps, escalation threshold
    planner.py    evaluate_goal() + decompose()  (LLM-overridable, stdlib default)
    dispatcher.py turns an OPEN task into a Dispatch brief (the worker's goal)
    verifier.py   the gate: file-exists / HTTP-200 / marker checks
    monitor.py    RAM/CPU health + can_spawn() guard
    cycle.py      run_cycle(): one tick (pure Python, no network)
  dashboard.py    compact always-visible status block
  cli.py          init/status/dashboard/run/selftest
  prompts/        Hermes agent prompt + integration contract
tests/            pytest suite (20 tests) + selftest (11 checks)
```

## Tests
```bash
python -m pytest -q     # 20 tests, all stdlib, no network
python -m jarvis.cli selftest   # 11 offline structural checks
```

## Verified behavior
- Decompose produces the next missing sub-goal, never duplicates in-flight work.
- Dispatch marks a task DOING and bumps attempt count; respects the worker cap.
- Verification: file-exists passes/fails correctly (incl. paths with spaces);
  missing file → requeue; exhausted attempts → FAILED.
- Resource guard blocks dispatch when RAM/CPU too low (observed live on this box).
- Stuck-cycled loop escalates to the operator instead of burning tokens forever.

## License
MIT
