"""Monitor: company-health + resource guardrails.

Resource checks use best-effort stdlib probes. On Windows we read the process
working-set via ctypes when available; otherwise we degrade gracefully. This is
the gate that prevents Jarvis from spawning workers when the box is starved.
"""
from __future__ import annotations
import os
import sys


class Monitor:
    def __init__(self, min_free_ram_mb: int = 400, max_cpu_percent: int = 85):
        self.min_free_ram_mb = min_free_ram_mb
        self.max_cpu_percent = max_cpu_percent

    def free_ram_mb(self) -> float:
        try:
            if sys.platform == "win32":
                import ctypes
                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                    ]
                s = MEMORYSTATUSEX()
                s.dwLength = ctypes.sizeof(s)
                ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
                return s.ullAvailPhys / (1024 * 1024)
            else:
                with open("/proc/meminfo") as f:
                    for line in f:
                        if line.startswith("MemAvailable:"):
                            return int(line.split()[1]) / 1024
        except Exception:  # noqa
            pass
        return float("inf")  # unknown -> don't block

    def cpu_percent(self) -> float:
        try:
            import psutil
            return psutil.cpu_percent(interval=0.3)
        except Exception:  # noqa
            return 0.0  # unknown -> don't block

    def can_spawn(self) -> bool:
        # Historically this hard-blocked when free RAM < min_free_ram_mb, which
        # on a low-RAM box (free RAM often ~100-300 MB) meant NO worker EVER
        # dispatched -> tasks stuck in DOING -> permanent escalation. We now
        # only block on a genuine critical shortage (well below the floor) and
        # otherwise emit a 'low' warning so the cycle can still proceed. CPU is
        # a soft signal too: only block when pegged.
        free = self.free_ram_mb()
        cpu = self.cpu_percent()
        critical_ram = free < max(16, self.min_free_ram_mb // 4)
        critical_cpu = cpu > max(self.max_cpu_percent, 98)
        if critical_ram:
            self._warn(f"RAM critically low ({round(free,1)} MB) - blocking spawn")
            return False
        if critical_cpu:
            self._warn(f"CPU pegged ({round(cpu,1)}%) - blocking spawn")
            return False
        if free < self.min_free_ram_mb or cpu > self.max_cpu_percent:
            self._warn(f"resource headroom low (RAM {round(free,1)}/{self.min_free_ram_mb} MB, "
                       f"CPU {round(cpu,1)}/{self.max_cpu_percent}%) - proceeding")
        return True

    def _warn(self, msg: str):
        try:
            from .logging import log_event
            log_event(event="resource_warn", status="warn", detail=msg)
        except Exception:  # noqa
            pass

    def disk_free_mb(self, path: str = None) -> float:
        """Free bytes on the volume holding `path` (defaults to cwd)."""
        try:
            import shutil
            p = path or os.getcwd()
            return shutil.disk_usage(p).free / (1024 * 1024)
        except Exception:  # noqa
            return float("inf")

    def online(self, host: str = "8.8.8.8", timeout: float = 3.0) -> bool:
        """Cheap connectivity probe. Tries a TCP connect to a reliable host; no
        DNS lookup, no HTTP. Returns False fast if the network is down so the
        loop can pause internet-dependent work instead of failing workers."""
        import socket
        try:
            socket.setdefaulttimeout(timeout)
            sock = socket.create_connection((host, 53), timeout=timeout)
            sock.close()
            return True
        except OSError:  # noqa: no route / timeout / DNS down
            return False

    def health(self) -> dict:
        return {
            "free_ram_mb": round(self.free_ram_mb(), 1),
            "cpu_percent": round(self.cpu_percent(), 1),
            "disk_free_mb": round(self.disk_free_mb(), 1),
            "can_spawn": self.can_spawn(),
            "online": self.online(),
        }
