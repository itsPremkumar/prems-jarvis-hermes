"""Dashboard: render a compact, always-visible status block (the 'Jarvis face')."""
from __future__ import annotations
from .core import State, Monitor, Defaults


def render_dashboard(state: State, monitor: Monitor = None, d: Defaults = None) -> str:
    d = d or Defaults()
    mon = monitor or Monitor(d.min_free_ram_mb, d.max_cpu_percent)
    goal = state.get_goal()
    health = mon.health()
    open_tasks = state.list_tasks()
    running = [t for t in open_tasks if t.status.value in ("open", "doing")]
    done = state.done_today()
    failed = state.failed_count()

    lines = []
    lines.append("=" * 40)
    lines.append("        J A R V I S  (Hermes)")
    lines.append("=" * 40)
    lines.append(f"Status : 🟢 ONLINE  (cycle #{state.get_cycle()})")
    lines.append(f"Goal   : {goal.statement if goal else '(none set)'}")
    lines.append(f"Open   : {len(running)}   (cap {d.max_open_tasks})")
    lines.append(f"Done24h: {done}    Failed: {failed}")
    lines.append(f"RAM    : {health['free_ram_mb']} MB free")
    lines.append(f"CPU    : {health['cpu_percent']}%")
    lines.append(f"Spawn? : {'yes' if health['can_spawn'] else 'NO (guard)'}")
    lines.append("-" * 40)
    for t in running[:5]:
        lines.append(f"[{t.status.value:>6}] {t.sub_goal[:46]}")
    if len(running) > 5:
        lines.append(f"... +{len(running) - 5} more")
    lines.append("=" * 40)
    return "\n".join(lines)
