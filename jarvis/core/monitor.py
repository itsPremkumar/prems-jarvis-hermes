"""Monitor: company-health + resource guardrails.

Resource checks use best-effort stdlib probes. On Windows we read the process
working-set via ctypes when available; otherwise we degrade gracefully. This is
the gate that prevents Jarvis from spawning workers when the box is starved.
"""
from __future__ import annotations
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
        return (self.free_ram_mb() >= self.min_free_ram_mb
                and self.cpu_percent() <= self.max_cpu_percent)

    def health(self) -> dict:
        return {
            "free_ram_mb": round(self.free_ram_mb(), 1),
            "cpu_percent": round(self.cpu_percent(), 1),
            "can_spawn": self.can_spawn(),
        }
