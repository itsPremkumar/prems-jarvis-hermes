"""Verifier: the gate that stops the loop from spinning on lies.

A task is only DONE when its verification check passes. Without this, a worker
can claim success and Jarvis will loop forever re-creating the same gap. The
core ships deterministic checks (file exists, URL returns 200) so it is testable
offline; the Hermes skill can add LLM-based checks on top.
"""
from __future__ import annotations
import os
import urllib.request
from dataclasses import dataclass
from typing import Optional

from .state import State, Task, TaskStatus


@dataclass
class VerificationResult:
    passed: bool
    notes: str


class Verifier:
    def __init__(self, state: State, timeout: float = 8.0):
        self.state = state
        self.timeout = timeout

    def verify(self, task: Task) -> VerificationResult:
        v = (task.verification or "").strip()
        if not v:
            return VerificationResult(False, "no verification spec defined")
        low = v.lower()

        # 1) File existence check
        for token in ("file exists", "exists at", "at "):
            if token in low:
                # crude extraction: find a path-like substring
                path = self._extract_path(v)
                if path:
                    if os.path.exists(path):
                        return VerificationResult(True, f"file exists: {path}")
                    return VerificationResult(False, f"missing file: {path}")

        # 2) URL / HTTP 200 check
        if "http 200" in low or "returns 200" in low or "http://" in v or "https://" in v:
            url = self._extract_url(v)
            if url:
                try:
                    req = urllib.request.Request(url, method="HEAD")
                    with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                        if resp.status == 200:
                            return VerificationResult(True, f"HTTP 200: {url}")
                        return VerificationResult(False, f"HTTP {resp.status}: {url}")
                except Exception as e:  # noqa
                    return VerificationResult(False, f"url check failed: {e}")

        # 3) Generic marker text present in result (best-effort)
        if task.result and self._marker_in(v, task.result):
            return VerificationResult(True, "result contains expected marker")
        return VerificationResult(False, "no automated check matched; needs manual/LLM review")

    def apply(self, task: Task) -> bool:
        res = self.verify(task)
        task.verification_result = res.passed
        task.verification_notes = res.notes
        if res.passed:
            task.status = TaskStatus.DONE
        elif task.attempts >= task.max_attempts:
            task.status = TaskStatus.FAILED
        else:
            task.status = TaskStatus.OPEN  # requeue for another attempt
        self.state.update_task(task)
        return res.passed

    @staticmethod
    def _extract_path(text: str) -> Optional[str]:
        # "file exists at <path>" -> take everything after "at " (handles spaces
        # in paths like "C:\Users\PREM KUMAR\..."). Fall back to a path-like token.
        low = text.lower()
        if "exists at" in low:
            idx = low.index("exists at") + len("exists at")
            return text[idx:].strip().strip("'\"`")
        import re
        m = re.search(r"([A-Za-z]:)?[\\/][\w.\\/\\- ]+", text)
        return m.group(0).strip() if m else None

    @staticmethod
    def _extract_url(text: str) -> Optional[str]:
        import re
        m = re.search(r"https?://[^\s\"')]+", text)
        return m.group(0).rstrip(").,") if m else None

    @staticmethod
    def _marker_in(spec: str, result: str) -> bool:
        # Use trailing quoted phrase if present: ...'contains "<x>"'
        import re
        m = re.search(r'["\']([^"\']+)["\']', spec)
        if m:
            return m.group(1).lower() in result.lower()
        return False
