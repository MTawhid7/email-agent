import logging
import threading
import time
from collections import deque
from datetime import date, datetime
from typing import Optional

from ai.prompts import build_user_message
from ai.reply_generator import ReplyGenerator
from assembler import assemble
from config import load_settings_from_dict
from contacts.contact_store import ContactStore
from email_parser.parser import parse_thread
from exceptions import AuthError, EmailAgentError
from gmail_client.auth import get_credentials
from gmail_client.gmail_client import GmailClient
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
    Wraps the email processing loop in a background thread.
    All public methods and properties are thread-safe.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._logs: deque[dict] = deque(maxlen=_MAX_LOG_ENTRIES)
        self._draft_count_today: int = 0
        self._draft_count_date: date = date.today()
        self._error: Optional[str] = None

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._error = None
            self._thread = threading.Thread(
                target=self._run_loop,
                name="AgentDaemon",
                daemon=True,
            )
            self._thread.start()
            self._append_log("info", "Agent started.")

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            self._append_log("info", "Agent stopped.")

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
            }

    # ── Internal loop ──────────────────────────────────────────────────────────

    def _run_loop(self) -> None:
        try:
            settings, gmail, generator, contact_store, signature_html = self._build_components()
        except AuthError as exc:
            self._set_error(f"Auth error: {exc}")
            return
        except Exception as exc:
            self._set_error(f"Startup failed: {exc}")
            return

        while not self._stop_event.is_set():
            try:
                count = self._process_unread(gmail, generator, contact_store, signature_html)
                if count:
                    self._increment_draft_count(count)
                else:
                    self._append_log("info", "No new emails.")
            except AuthError as exc:
                self._set_error(f"Auth error: {exc}")
                return
            except EmailAgentError as exc:
                self._append_log("error", f"Agent error: {exc}")
            except Exception as exc:
                self._append_log("error", f"Unexpected error: {exc}")

            # Sleep in 0.5s increments so stop_event is checked frequently
            for _ in range(settings.poll_interval_seconds * 2):
                if self._stop_event.is_set():
                    break
                time.sleep(0.5)

    def _build_components(self):
        raw = load_config()
        settings = load_settings_from_dict(raw)
        creds = get_credentials(
            credentials_path=get_credentials_path(),
            token_path=get_token_path(),
        )
        gmail = GmailClient(creds)
        generator = ReplyGenerator(settings)
        contact_store = ContactStore(path=get_contacts_path())
        sig_builder = SignatureBuilder(settings)
        signature_html = sig_builder.build_html()
        return settings, gmail, generator, contact_store, signature_html

    def _process_unread(
        self,
        gmail: GmailClient,
        generator: ReplyGenerator,
        contact_store: ContactStore,
        signature_html: str,
    ) -> int:
        thread_ids = gmail.list_unread_thread_ids(max_results=20)
        count = 0

        for thread_id in thread_ids:
            try:
                thread = gmail.get_thread(thread_id)
                parsed = parse_thread(thread)
                if parsed is None:
                    continue

                contact = contact_store.lookup(parsed.sender_email)
                user_message = build_user_message(parsed, contact, mode="reply")
                body = generator.generate(user_message)
                final_html = assemble(parsed.sender_first_name, body, signature_html)

                reply_subject = (
                    parsed.subject
                    if parsed.subject.lower().startswith("re:")
                    else f"Re: {parsed.subject}"
                )

                gmail.create_draft(
                    to=parsed.sender_email,
                    subject=reply_subject,
                    body_html=final_html,
                    thread_id=parsed.thread_id,
                    in_reply_to=parsed.message_id_header,
                    references=parsed.message_id_header,
                )
                gmail.mark_as_processed(parsed.latest_message_id)

                self._append_log(
                    "success",
                    f"Draft created for {parsed.sender_name} <{parsed.sender_email}>",
                )
                count += 1

            except EmailAgentError as exc:
                self._append_log("error", f"Skipping thread {thread_id}: {exc}")
            except Exception as exc:
                self._append_log("error", f"Unexpected error on thread {thread_id}: {exc}")

        return count

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _append_log(self, level: str, message: str) -> None:
        """Append a log entry. Must be called while self._lock is held or internally."""
        entry = {
            "level": level,
            "message": message,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._logs.append(entry)
        getattr(logger, "info" if level in ("info", "success") else level, logger.info)(message)

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
