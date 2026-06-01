"""
System state snapshot — persisted to {DATA_DIR}/debug/state.json.

Written on every significant daemon event so the /debug dashboard can
show accurate system health even after a page refresh.
"""
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional


class StateManager:
    """
    Thread-safe manager for a persisted system-state snapshot.
    Every update is written atomically to state.json.
    """

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._state: dict = {
            "daemon_started_at": None,
            "last_poll_at": None,
            "last_imap_signal_at": None,
            "imap_connected": False,
            "imap_degraded": False,
            "token_expires_at": None,
            "last_history_id": None,
            "emails_processed_session": 0,
            "emails_queued_session": 0,
            "emails_skipped_session": 0,
            "review_queue_size": 0,
            "last_error": None,
            "last_error_at": None,
        }

    # ── Update helpers ─────────────────────────────────────────────────────────

    def daemon_started(self) -> None:
        self._update(
            daemon_started_at=_now(),
            emails_processed_session=0,
            emails_queued_session=0,
            emails_skipped_session=0,
            last_error=None,
            last_error_at=None,
        )

    def poll_completed(self, queued: int, skipped: int, queue_size: int) -> None:
        with self._lock:
            self._state["last_poll_at"] = _now()
            self._state["emails_processed_session"] += queued + skipped
            self._state["emails_queued_session"] += queued
            self._state["emails_skipped_session"] += skipped
            self._state["review_queue_size"] = queue_size
        self._persist()

    def imap_connected(self, connected: bool, degraded: bool = False) -> None:
        self._update(imap_connected=connected, imap_degraded=degraded)

    def imap_signal_received(self) -> None:
        self._update(last_imap_signal_at=_now())

    def token_refreshed(self, expires_at: Optional[str]) -> None:
        self._update(token_expires_at=expires_at)

    def history_id_updated(self, history_id: str) -> None:
        self._update(last_history_id=history_id)

    def error_occurred(self, message: str) -> None:
        self._update(last_error=message, last_error_at=_now())

    # ── Read ───────────────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        """Return a copy of the current state."""
        with self._lock:
            return dict(self._state)

    # ── Internals ──────────────────────────────────────────────────────────────

    def _update(self, **kwargs) -> None:
        with self._lock:
            self._state.update(kwargs)
        self._persist()

    def _persist(self) -> None:
        try:
            tmp = self._path.with_suffix(".tmp")
            with self._lock:
                data = dict(self._state)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            tmp.replace(self._path)
        except Exception:
            pass


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
