import logging
import threading
import time
import uuid
from collections import deque
from datetime import date, datetime
from typing import Optional

from ai.prompts import build_classification_prompt, build_summary_prompt, build_user_message
from ai.reply_generator import ReplyGenerator
from agent.review_queue import review_queue
from assembler import assemble
from config import load_settings_from_dict
from contacts.contact_store import ContactStore
from email_parser.attachment_reader import fetch_and_summarise
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
_PRIORITY_EMOJI = {"high": "🔴", "normal": "🟡", "low": "⚪", "skip": "⏭"}


class AgentDaemon:
    """Background email processing daemon. All public methods are thread-safe."""

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
            self._thread = threading.Thread(target=self._run_loop, name="AgentDaemon", daemon=True)
            self._thread.start()
        # _append_log called OUTSIDE the lock — it acquires its own lock internally
        self._append_log("info", "Agent started.")

    def stop(self) -> None:
        self._stop_event.set()
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
                "review_count": review_queue.count(),
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
            sleep_seconds = settings.poll_interval_seconds
            try:
                count = self._process_unread(gmail, generator, contact_store, signature_html)
                if not count:
                    self._append_log("info", "No new emails.")
                else:
                    self._increment_draft_count(count)
            except AuthError as exc:
                self._set_error(f"Auth error: {exc}")
                return
            except EmailAgentError as exc:
                self._append_log("error", f"Agent error: {exc}")
                sleep_seconds = 30  # retry quickly after a recoverable error
            except Exception as exc:
                self._append_log("error", f"Unexpected error: {exc}")
                sleep_seconds = 30

            for _ in range(sleep_seconds * 2):
                if self._stop_event.is_set():
                    break
                time.sleep(0.5)

    def _build_components(self):
        raw = load_config()
        settings = load_settings_from_dict(raw)
        creds = get_credentials(
            credentials_path=get_credentials_path(),
            token_path=get_token_path(),
            allow_oauth_flow=False,   # never block the daemon thread waiting for a browser
        )
        gmail = GmailClient(creds)
        generator = ReplyGenerator(settings)
        contact_store = ContactStore(path=get_contacts_path())
        signature_html = SignatureBuilder(settings).build_html()
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

                # ── Feature 4: Thread summary ──────────────────────────────────
                summary = generator.summarise(build_summary_prompt(parsed))

                # ── Feature 2: Classify + newsletter detection ─────────────────
                classification = generator.classify(build_classification_prompt(parsed, contact))
                priority = classification["priority"]

                if classification["skip"]:
                    gmail.mark_as_processed(parsed.latest_message_id)
                    self._append_log(
                        "info",
                        f"⏭ Skipped ({classification['reason']}): {parsed.sender_name}",
                        summary=summary, priority="skip",
                    )
                    continue

                if priority == "high":
                    gmail.apply_priority_label(parsed.latest_message_id)

                # ── Feature 7: Attachment summarisation ────────────────────────
                attachment_summary = ""
                if parsed.attachments:
                    attachment_summary = fetch_and_summarise(
                        gmail_client=gmail,
                        message_id=parsed.latest_message_id,
                        attachments=parsed.attachments,
                        gemini_client=generator._client,
                        model=generator._model,
                    )

                # ── Generate reply ─────────────────────────────────────────────
                user_message = build_user_message(
                    parsed, contact, mode="reply",
                    attachment_summary=attachment_summary,
                )
                body = generator.generate(user_message)
                final_html = assemble(parsed.sender_first_name, body, signature_html)

                reply_subject = (
                    parsed.subject if parsed.subject.lower().startswith("re:")
                    else f"Re: {parsed.subject}"
                )

                # ── Feature 1: Push to review queue ────────────────────────────
                item_id = str(uuid.uuid4())   # defined here so _append_log can reference it
                review_queue.push({
                    "id": item_id,
                    "sender_name": parsed.sender_name,
                    "sender_email": parsed.sender_email,
                    "subject": reply_subject,
                    "thread_id": parsed.thread_id,
                    "message_id_header": parsed.message_id_header,
                    "latest_message_id": parsed.latest_message_id,
                    "body_html": final_html,
                    "created_at": datetime.now().isoformat(),
                    "priority": priority,
                    "summary": summary,
                })

                # Mark processed immediately so it won't be re-queued next poll
                gmail.mark_as_processed(parsed.latest_message_id)

                emoji = _PRIORITY_EMOJI.get(priority, "🟡")
                self._append_log(
                    "pending",   # amber — waiting for user action in Review Queue
                    f"{emoji} Queued for review: {parsed.sender_name} <{parsed.sender_email}>",
                    summary=summary, priority=priority, item_id=item_id,
                )
                count += 1

            except EmailAgentError as exc:
                self._append_log("error", f"Skipping thread {thread_id}: {exc}")
            except Exception as exc:
                self._append_log("error", f"Unexpected error on thread {thread_id}: {exc}")

        return count

    # ── Helpers ────────────────────────────────────────────────────────────────

    def resolve_review_item(self, item_id: str, action: str) -> None:
        """
        Update the activity log entry for a review item after the user acts.
        action: 'sent' → green success  |  'discarded' → gray discarded
        Called from routes/review.py after Send Now or Discard.
        """
        level = "success" if action == "sent" else "discarded"
        for entry in self._logs:
            if entry.get("item_id") == item_id:
                entry["level"] = level
                entry["resolved"] = action
                break

    def _append_log(self, level: str, message: str, summary: str = "",
                    priority: str = "", item_id: str = "") -> None:
        entry = {
            "level": level,
            "message": message,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "summary": summary,
            "priority": priority,
            "item_id": item_id,    # non-empty for review queue items
            "resolved": "",        # set to 'sent' or 'discarded' after user action
        }
        # deque.append() is thread-safe — no lock needed.
        # Never call this while holding self._lock (threading.Lock is not reentrant).
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
