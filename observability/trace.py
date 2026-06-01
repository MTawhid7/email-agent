"""
Per-email processing traces.

A ProcessingTrace records every decision step for one email thread so that
developers can see exactly WHY an email was skipped, classified, or queued,
without reading log files line by line.

TraceStore keeps the last 50 traces in memory and persists them to
{DATA_DIR}/debug/traces.json for survival across /debug page refreshes.
"""
import json
import threading
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class ProcessingTrace:
    thread_id: str
    sender: str
    subject: str
    started_at: str
    steps: list = field(default_factory=list)
    outcome: str = ""           # "queued" / "skipped" / "error"
    outcome_reason: str = ""
    total_ms: int = 0

    def add_step(self, step: str, result: str, **details) -> None:
        self.steps.append({"step": step, "result": result, **details})

    def finish(self, outcome: str, reason: str = "", total_ms: int = 0) -> None:
        self.outcome = outcome
        self.outcome_reason = reason
        self.total_ms = total_ms


class TraceStore:
    """
    Thread-safe store of recent email processing traces.
    Keeps the last _MAX traces in memory.
    """
    _MAX = 50

    def __init__(self, path: Optional[str] = None) -> None:
        self._path = Path(path) if path else None
        self._lock = threading.Lock()
        self._traces: deque[ProcessingTrace] = deque(maxlen=self._MAX)

        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)

    def start(self, thread_id: str, sender: str, subject: str) -> ProcessingTrace:
        """Create and register a new trace for one email thread."""
        trace = ProcessingTrace(
            thread_id=thread_id,
            sender=sender,
            subject=subject,
            started_at=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        with self._lock:
            self._traces.append(trace)
        return trace

    def finish(self, trace: ProcessingTrace, outcome: str,
               reason: str = "", total_ms: int = 0) -> None:
        trace.finish(outcome=outcome, reason=reason, total_ms=total_ms)
        self._persist()

    def get_all(self) -> list[dict]:
        """Return all traces as dicts, newest first."""
        with self._lock:
            return [asdict(t) for t in reversed(list(self._traces))]

    def _persist(self) -> None:
        if not self._path:
            return
        try:
            data = self.get_all()
            tmp = self._path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            tmp.replace(self._path)
        except Exception:
            pass
