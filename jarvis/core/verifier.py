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

        # 1) File existence + content check
        for token in ("file exists", "exists at", "exists"):
            if token in low:
                path, clause = self._split_file_and_clause(v)
                if not path:
                    return VerificationResult(False, "no path found in spec")
                if not os.path.exists(path):
                    return VerificationResult(False, f"missing file: {path}")
                if clause:
                    try:
                        text = open(path, "r", encoding="utf-8", errors="ignore").read()
                    except OSError as e:  # noqa
                        return VerificationResult(False, f"cannot read {path}: {e}")
                    if not self._content_matches(clause, text):
                        return VerificationResult(False, f"file exists but content missing: {clause}")
                return VerificationResult(True, f"file verified: {path}" + (f" ({clause})" if clause else ""))

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

    @staticmethod
    def _split_file_and_clause(text: str) -> tuple:
        """Return (path, content_clause). Path may contain spaces; the content
        clause (after 'with'/'containing'/'contains') is separated from the path."""
        import re
        # find the path: after 'exists at' / 'exists' token, up to the clause keyword
        m = re.search(r"exists\s+at\s+(.+)$", text, re.IGNORECASE) or \
            re.search(r"exists\s+(.+)$", text, re.IGNORECASE)
        if not m:
            return (None, None)
        tail = m.group(1).strip()
        # quoted path?
        if tail and tail[0] in "\"'":
            end = tail.find(tail[0], 1)
            path = tail[1:end] if end > 1 else tail[1:]
            clause = tail[end + 1:].strip() if end > 1 else ""
            clause = Verifier._extract_content_clause(clause or "")
            return (path, clause)
        # split path from clause at the FIRST content keyword
        kw = re.search(r"\s+(?:with|containing|contains)\s+", tail, re.IGNORECASE)
        if kw:
            path = tail[:kw.start()].strip()
            clause = tail[kw.end():].strip()
            return (path, clause)
        return (tail.strip(), None)

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
    def _extract_content_clause(text: str) -> Optional[str]:
        # Capture the content qualifier after "with"/"containing"/"contains".
        # "exists at spec.md with a price or offer" -> "a price or offer"
        import re
        m = re.search(r"\b(?:with|containing|contains)\b\s+(.+)$", text, re.IGNORECASE)
        return m.group(1).strip().strip("'\"") if m else None

    @staticmethod
    def _content_matches(clause: str, text: str) -> bool:
        low = clause.lower()
        txt = text.lower()
        filler = {"a", "an", "the", "with", "containing", "contains"}
        # "price or offer" -> require 'price' OR 'offer'
        # "email/payment input" -> require 'email' OR 'payment'
        # ">=100 unique visits" -> require '100' and 'visit'
        if "/" in clause:
            return any(tok.strip(" .") in txt for tok in clause.split("/"))
        if " or " in low:
            toks = [t for t in low.split(" or ") if t.strip()]
            return any(_strip_filler(t, filler) in txt for t in toks)
        if " and " in low:
            toks = [t for t in low.split(" and ") if t.strip()]
            return all(_strip_filler(t, filler) in txt for t in toks)
        # fallback: every significant word must appear
        words = [w for w in re.findall(r"[a-z0-9]+", low) if len(w) > 2 and w not in filler]
        return all(w in txt for w in words)


def _strip_filler(token: str, filler) -> str:
    token = token.strip()
    while token.split()[0] in filler if token.split() else False:
        token = " ".join(token.split()[1:])
    return token

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
