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

## Install (one command → 24/7, reboot-surviving)

```bash
python -m jarvis.cli init       # create state DB + default money goal
python -m jarvis.cli install    # register 3 Windows Task Scheduler tasks
```

`install` registers (at this repo's real path, so the junction bug can't recur):
- **JarvisBoot** (on logon) — one cycle immediately after reboot/login.
- **JarvisSupervise** (every 5 min) — OS-level supervisor: wakes Hermes, runs a
  cycle, emits `SPAWN_WORKER` for Hermes to run. Jarvis is the boss.
- **JarvisWatchdog** (every 10 min) — external liveness check (survives Hermes).

Uninstall with `python -m jarvis.cli uninstall`.

## Self-healing layer (the 15 requirements, honestly mapped)

| # | Requirement | Status in this build | Mechanism |
|---|-------------|---------------------|-----------|
| 1 | Never-stop / recover from crashes | ✅ | SQLite state; idempotent cycles; OS tasks re-run |
| 2 | Self-healing runtime (monitor all) | 🟡 partial | Monitors RAM/CPU/disk/net/Hermes; per-component healing not yet (single process) |
| 3 | Automatic recovery (retry/backoff/CB) | ✅ | `recovery.py`: retry+backoff, infinite-retry, CircuitBreaker |
| 4 | Autonomous monitoring / watchdog | ✅ | `watchdog.py` + `JarvisWatchdog` task + `run_cycle` logging |
| 5 | Startup automation (boot/login) | ✅ | `install` registers 3 schtasks; resumes queue from DB |
| 6 | Persistent state recovery | ✅ | `jarvis_state.db` saved every cycle; restored on boot |
| 7 | Robust error handling | ✅ | excepthook + SIGINT/SIGTERM graceful shutdown; try/except in cycle |
| 8 | Intelligent retry system | ✅ | `retry()` with backoff/jitter/infinite option per req |
| 9 | Logging & diagnostics | ✅ | JSON-line `jarvis.log` + rotation; `cli log` viewer |
| 10 | Health monitoring | ✅ | `Monitor.health()`: RAM/CPU/disk/net; guards pause work |
| 11 | Modular failure isolation | 🟡 partial | Single Python process; components are functions, not separate procs |
| 12 | Autonomous scheduler (reboot-safe) | ✅ | schtasks resume after reboot; dedupe prevents double-exec |
| 13 | Background automation (continuous) | ✅ | 30-min Hermes cron + OS `JarvisSupervise` 5-min loop |
| 14 | Graceful shutdown | ✅ | atexit + signal handlers log shutdown, preserve state |
| 15 | Production-grade reliability | 🟡 partial | watchdog/health/logging/state yes; full metrics/alerting not |

> **Honest gaps (cannot fake):** True per-process isolation (req 11) would mean
> N OS processes on a 6 GB box — that would OOM it, so we use one bounded process
> with failure isolation *within* the cycle instead. Full observability/alerting
> (req 15) needs an external sink we haven't wired. And no software survives
> permanent hardware/power failure (the charter's own admission).

## Commands
```bash
python -m jarvis.cli init        # create state DB + set default money goal
python -m jarvis.cli install     # register Windows Task Scheduler tasks (reboot survival)
python -m jarvis.cli uninstall   # remove the scheduled tasks
python -m jarvis.cli status      # show goal / task counts
python -m jarvis.cli dashboard   # always-visible Jarvis dashboard
python -m jarvis.cli run         # run EXACTLY ONE cycle (the cron agent calls this)
python -m jarvis.cli report <id> done|failed "summary"   # feed worker result
python -m jarvis.cli tasks       # list all tasks
python -m jarvis.cli log         # show structured event log
python -m jarvis.cli selftest    # offline structural self-test (no network/tokens)
python supervise.py jarvis_state.db   # OS supervisor loop (wakes Hermes, dispatches)
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
    state.py            SQLite store: Goal + Task, fully durable
    defaults.py         Guardrails: max_open_tasks=3, RAM/CPU caps, escalation threshold
    planner.py          evaluate_goal() + decompose()  (LLM-overridable, stdlib default)
    dispatcher.py       turns an OPEN task into a Dispatch brief (the worker's goal)
    verifier.py         the gate: file-exists / HTTP-200 / content-clause checks
    monitor.py          RAM/CPU/disk/net health + can_spawn()/online() guards
    recovery.py         retry (exp backoff, infinite) + CircuitBreaker
    hermes_launcher.py  Jarvis's tool to keep the Hermes host alive (wake/launch)
    cycle.py            run_cycle(): one tick (pure Python, no network)
    logging.py          JSON-line event log + rotation
  dashboard.py          compact always-visible status block
  cli.py                init/install/uninstall/status/dashboard/run/report/tasks/log/selftest
  install.py            registers 3 Windows Task Scheduler tasks at this repo's path
  prompts/              Hermes agent prompt + integration contract
supervise.py            OS supervisor loop (wakes Hermes, dispatches, SPAWN_WORKER)
watchdog.py             external liveness check (survives Hermes)
tests/                  pytest suite (35 tests) + selftest (11 checks)
```

## Tests
```bash
python -m pytest -q     # 35 tests, all stdlib, no network
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
