"""
Email Agent daemon.

Responsible for lifecycle management only:
  - Start / stop / status
  - IMAP IDLE watcher (real-time push notifications)
  - TokenManager (proactive OAuth refresh)
  - historyId cursor (Gmail History API catch-up)
  - Activity log + draft counter

Per-email AI processing is delegated to agent.pipeline.EmailPipeline.
"""
import logging
import threading
import time
from collections import deque
from datetime import date, datetime
from typing import Optional

from agent.pipeline import EmailPipeline
from agent.queue import review_queue
from core.config import load_settings_from_dict
from core.exceptions import AuthError, EmailAgentError
from gmail.client import GmailClient
from contacts.contact_store import ContactStore
from signature.signature import SignatureBuilder
from storage.app_config import (
    get_contacts_path,
    get_credentials_path,
    get_token_path,
    load_config,
)

logger = logging.getLogger(__name__)

_MAX_LOG_ENTRIES = 100


class AgentDaemon:
    """
    Background email processing daemon. All public methods are thread-safe.

    Lifecycle:
        start() → _run_loop() [background thread]
            └─ _build_components(): initialise TokenManager, GmailClient,
               ReplyGenerator, ContactStore, EmailPipeline
            └─ ImapIdleWatcher: wakes _wake_event on new mail
            └─ loop: wait on _wake_event → _process_unread_incremental()
                     → pipeline.process_batch(thread_ids)
        stop() → signals _stop_event, stops IMAP watcher and TokenManager
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._logs: deque[dict] = deque(maxlen=_MAX_LOG_ENTRIES)
        self._draft_count_today: int = 0
        self._draft_count_date: date = date.today()
        self._error: Optional[str] = None
        self._detected_email: str = ""
        # Interaction history (set in _build_components)
        self._interaction_store = None
        self._pending_history: dict[str, dict] = {}
        # Infrastructure (set in _build_components)
        self._token_manager = None
        self._pipeline: Optional[EmailPipeline] = None
        # Observability (set in _build_components)
        self._obs_logger = None
        self._obs_state = None
        self._obs_traces = None

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._error = None
            self._thread = threading.Thread(target=self._run_loop, name="AgentDaemon", daemon=True)
            self._thread.start()
        self._append_log("info", "Agent started.")

    def stop(self) -> None:
        self._stop_event.set()
        if hasattr(self, "_wake_event"):
            self._wake_event.set()
        if self._imap_watcher:
            self._imap_watcher.stop()
        if self._token_manager:
            self._token_manager.stop()
        self._append_log("info", "Agent stopped.")

    def wait_for_stop(self, timeout: float = 3.0) -> None:
        """Block until the daemon thread exits or timeout elapses."""
        with self._lock:
            t = self._thread
        if t and t.is_alive():
            t.join(timeout=timeout)

    @property
    def is_running(self) -> bool:
        with self._lock:
            return bool(self._thread and self._thread.is_alive())

    def get_logs(self) -> list[dict]:
        with self._lock:
            return list(self._logs)

    def get_status(self) -> dict:
        with self._lock:
            self._reset_draft_count_if_new_day()
            return {
                "running": bool(self._thread and self._thread.is_alive()),
                "logs": list(self._logs),
                "draft_count": self._draft_count_today,
                "error": self._error,
                "review_count": review_queue.count(),
            }

    def resolve_review_item(self, item_id: str, action: str) -> None:
        """
        Update the activity log entry and record interaction history.
        action: 'sent' → green  |  'discarded' → gray
        Called from routes/review.py after Send Now or Discard.
        """
        level = "success" if action == "sent" else "discarded"
        for entry in self._logs:
            if entry.get("item_id") == item_id:
                entry["level"] = level
                entry["resolved"] = action
                break

        hist = self._pending_history.pop(item_id, None)
        if hist and action == "sent" and self._interaction_store:
            try:
                from history.interaction_store import InteractionRecord
                self._interaction_store.record(
                    hist["sender_email"],
                    InteractionRecord(
                        thread_id=hist["thread_id"],
                        date=hist["date"],
                        subject=hist["subject"],
                        summary=hist["summary"],
                        our_reply_summary=hist["our_reply_summary"],
                        topics=hist["topics"],
                    ),
                )
            except Exception as exc:
                logger.warning("Failed to record interaction history: %s", exc)

    # ── Internal loop ──────────────────────────────────────────────────────────

    _wake_event: threading.Event
    _imap_watcher = None

    def _run_loop(self) -> None:
        self._wake_event = threading.Event()

        try:
            settings, gmail = self._build_components()
        except AuthError as exc:
            self._set_error(f"Auth error: {exc}")
            return
        except Exception as exc:
            self._set_error(f"Startup failed: {exc}")
            return

        from gmail.imap_watcher import ImapIdleWatcher
        own_email = settings.own_email or self._detected_email or ""
        self._imap_watcher = ImapIdleWatcher(
            token_manager=self._token_manager,
            wake_event=self._wake_event,
            own_email=own_email,
        )
        self._imap_watcher.start()

        # Immediate check on startup catches emails that arrived while offline
        self._wake_event.set()

        while not self._stop_event.is_set():
            self._wake_event.wait(timeout=60)
            self._wake_event.clear()

            if self._stop_event.is_set():
                break

            try:
                count = self._process_unread_incremental(gmail, settings)
                if not count:
                    self._append_log("info", "No new emails.")
                else:
                    self._increment_draft_count(count)
            except AuthError as exc:
                self._set_error(f"Auth error: {exc}")
                return
            except EmailAgentError as exc:
                self._append_log("error", f"Agent error: {exc}")
            except Exception as exc:
                self._append_log("error", f"Unexpected error: {exc}")

    def _build_components(self):
        from gmail.token_manager import TokenManager
        from ai.generator import ReplyGenerator
        from history.interaction_store import InteractionStore
        from observability.log_writer import AgentLogger
        from observability.state import StateManager
        from observability.trace import TraceStore
        from storage.app_config import (
            get_history_path, get_log_path, get_debug_state_path,
            get_traces_path, merge_and_save_config,
        )

        raw = load_config()
        settings = load_settings_from_dict(raw)

        self._token_manager = TokenManager(
            credentials_path=get_credentials_path(),
            token_path=get_token_path(),
        )
        self._token_manager.start()
        creds = self._token_manager.get_credentials()
        gmail = GmailClient(creds)
        generator = ReplyGenerator(settings)
        contact_store = ContactStore(path=get_contacts_path())
        signature_html = SignatureBuilder(settings).build_html()

        if not settings.own_email:
            try:
                detected = gmail.get_own_email().lower()
                if detected:
                    self._detected_email = detected
                    merge_and_save_config({"own_email": detected})
            except Exception:
                pass
        else:
            self._detected_email = settings.own_email

        self._interaction_store = InteractionStore(path=get_history_path())

        # Observability
        self._obs_logger = AgentLogger(
            path=get_log_path(),
            debug_mode=getattr(settings, "debug_mode", False),
        )
        self._obs_state = StateManager(path=get_debug_state_path())
        self._obs_traces = TraceStore(path=get_traces_path())
        self._obs_state.daemon_started()

        self._pipeline = EmailPipeline(
            gmail=gmail,
            generator=generator,
            contact_store=contact_store,
            interaction_store=self._interaction_store,
            signature_html=signature_html,
            settings=settings,
            detected_email=self._detected_email,
            pending_history=self._pending_history,
            log_callback=self._append_log,
            obs_logger=self._obs_logger,
            obs_traces=self._obs_traces,
            obs_state=self._obs_state,
        )

        return settings, gmail

    def _process_unread_incremental(self, gmail: GmailClient, settings) -> int:
        """
        Fetch thread IDs since the last historyId cursor, then process via the pipeline.
        Falls back to full inbox scan when historyId is missing or expired.
        """
        from core.exceptions import HistoryExpiredError
        from storage.app_config import merge_and_save_config

        raw = load_config()
        last_id = raw.get("last_history_id", "")

        if last_id:
            try:
                thread_ids, new_id = gmail.history_list(last_id)
                merge_and_save_config({"last_history_id": new_id})
            except HistoryExpiredError:
                self._append_log("info", "History cursor expired — running full inbox scan.")
                thread_ids = gmail.list_unread_thread_ids(max_results=20)
                new_id = gmail.get_current_history_id()
                if new_id:
                    merge_and_save_config({"last_history_id": new_id})
        else:
            thread_ids = gmail.list_unread_thread_ids(max_results=20)
            new_id = gmail.get_current_history_id()
            if new_id:
                merge_and_save_config({"last_history_id": new_id})

        return self._pipeline.process_batch(thread_ids)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _append_log(self, level: str, message: str, summary: str = "",
                    priority: str = "", item_id: str = "") -> None:
        entry = {
            "level": level,
            "message": message,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "summary": summary,
            "priority": priority,
            "item_id": item_id,
            "resolved": "",
        }
        self._logs.append(entry)
        getattr(logger, "info" if level in ("info", "success", "pending", "discarded")
                else level, logger.info)(message)

    def _set_error(self, message: str) -> None:
        with self._lock:
            self._error = message
        self._append_log("error", message)

    def _increment_draft_count(self, n: int) -> None:
        with self._lock:
            self._reset_draft_count_if_new_day()
            self._draft_count_today += n

    def _reset_draft_count_if_new_day(self) -> None:
        today = date.today()
        if today != self._draft_count_date:
            self._draft_count_today = 0
            self._draft_count_date = today
