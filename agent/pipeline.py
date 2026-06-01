"""
Email processing pipeline.

Extracted from AgentDaemon so the daemon can focus on lifecycle management
(start/stop, IMAP IDLE, token refresh, historyId) while this module handles
the per-email AI processing steps:

    fetch → parse → observer-skip → summarise → classify → generate → queue

Single-responsibility: EmailPipeline processes a batch of thread IDs.
It receives all its dependencies at construction time (dependency injection)
and communicates back to the daemon via the log_callback.
"""
import logging
import re
import uuid
from datetime import datetime
from typing import Callable, Optional

from ai.assembler import assemble
from ai.generator import ReplyGenerator
from ai.prompts import build_classification_prompt, build_summary_prompt, build_user_message
from agent.queue import review_queue
from contacts.contact_store import ContactStore
from core.exceptions import EmailAgentError
from email_parser.attachment_reader import fetch_and_summarise
from email_parser.parser import parse_thread
from gmail.client import GmailClient

logger = logging.getLogger(__name__)

_PRIORITY_EMOJI = {"high": "🔴", "normal": "🟡", "low": "⚪", "skip": "⏭"}

# ── Greeting name detection ────────────────────────────────────────────────────

_GREETING_RE = re.compile(
    r"\b(?:hi|hello|dear|hey|greetings?|good\s+(?:morning|afternoon|evening))"
    r"\s*[,!]?\s+(.{1,100}?)(?:[.!,\n]|$)",
    re.IGNORECASE,
)
_GENERIC_GREETING_WORDS = frozenset({
    "there", "all", "everyone", "team", "folks", "guys", "colleagues",
    "friends", "sir", "madam", "valued", "client", "clients", "customer",
    "customers", "community", "partner", "partners", "and", "the",
})


def _extract_greeting_names(body: str) -> frozenset[str]:
    """
    Extract all personal names from the opening greeting of an email body.
    Looks only at the first 250 characters.

    "Hi John"            → {"john"}
    "Hi John and Tawhid" → {"john", "tawhid"}
    "Hi team"            → set()  (generic word)
    No greeting          → set()
    """
    m = _GREETING_RE.search(body[:250])
    if not m:
        return frozenset()
    names = {
        word.lower()
        for word in re.findall(r"\b([A-Z][a-zA-Z'\-]{1,25})\b", m.group(1))
        if word.lower() not in _GENERIC_GREETING_WORDS
    }
    return frozenset(names)


class EmailPipeline:
    """
    Processes a batch of Gmail thread IDs through the full AI pipeline.

    Dependencies are injected at construction; the pipeline itself is stateless
    between batches except for the shared pending_history reference (which is
    owned by AgentDaemon and passed by reference).
    """

    def __init__(
        self,
        gmail: GmailClient,
        generator: ReplyGenerator,
        contact_store: ContactStore,
        interaction_store,           # Optional[InteractionStore] — may be None
        signature_html: str,
        settings,                    # core.config.Settings
        detected_email: str,
        pending_history: dict,       # reference to daemon._pending_history
        log_callback: Callable,      # daemon._append_log(level, message, **kwargs)
        obs_logger=None,             # observability.log_writer.AgentLogger
        obs_traces=None,             # observability.trace.TraceStore
        obs_state=None,              # observability.state.StateManager
    ) -> None:
        self._gmail = gmail
        self._generator = generator
        self._contact_store = contact_store
        self._interaction_store = interaction_store
        self._signature_html = signature_html
        self._settings = settings
        self._detected_email = detected_email
        self._pending_history = pending_history
        self._log = log_callback
        self._obs_logger = obs_logger
        self._obs_traces = obs_traces
        self._obs_state = obs_state

    # ── Public API ─────────────────────────────────────────────────────────────

    def process_batch(self, thread_ids: list) -> int:
        """
        Process a list of thread IDs through the full pipeline.
        Returns the count of items pushed to the review queue.
        """
        count = 0
        skipped = 0
        for thread_id in thread_ids:
            try:
                outcome = self._process_single(thread_id)
                if outcome == "queued":
                    count += 1
                elif outcome == "skipped":
                    skipped += 1
            except EmailAgentError as exc:
                self._log("error", f"Skipping thread {thread_id}: {exc}")
                if self._obs_logger:
                    self._obs_logger.error("pipeline_error", thread_id=thread_id, error=str(exc))
            except Exception as exc:
                self._log("error", f"Unexpected error on thread {thread_id}: {exc}")
                if self._obs_logger:
                    self._obs_logger.error("pipeline_error", thread_id=thread_id, error=str(exc))

        if self._obs_state and (count + skipped) > 0:
            from agent.queue import review_queue as _rq
            self._obs_state.poll_completed(
                queued=count, skipped=skipped, queue_size=_rq.count()
            )
        return count

    # ── Pipeline steps ──────────────────────────────────────────────────────────

    def _process_single(self, thread_id: str) -> str:
        """
        Run one email thread through the complete pipeline.
        Returns "queued", "skipped", or "none" (unparseable thread).
        """
        import time as _time
        t_start = _time.monotonic()

        thread = self._gmail.get_thread(thread_id)
        parsed = parse_thread(thread)
        if parsed is None:
            return "none"

        trace = None
        if self._obs_traces:
            trace = self._obs_traces.start(
                thread_id, parsed.sender_email, parsed.subject
            )

        contact = self._contact_store.lookup(parsed.sender_email)

        # Pre-compute greeting context (reused by skip check AND classifier)
        greeting_names = _extract_greeting_names(parsed.latest_body)
        user_name_variants = self._user_name_variants()

        # ── Tier 1: Structural skip (no Gemini call) ──────────────────────────
        should_skip, skip_reason = self._should_skip_as_observer(
            parsed, contact, greeting_names, user_name_variants
        )
        if should_skip:
            self._gmail.mark_as_processed(parsed.latest_message_id)
            self._log("info", f"⏭ Skipped ({skip_reason}): {parsed.sender_name}", priority="skip")
            if trace and self._obs_traces:
                self._obs_traces.finish(trace, "skipped", skip_reason)
            if self._obs_logger:
                self._obs_logger.log_skip(thread_id, parsed.sender_email, skip_reason)
            return "skipped"

        # ── Thread summary ────────────────────────────────────────────────────
        summary = self._generator.summarise(build_summary_prompt(parsed))

        # ── Tier 2: Semantic classification (Gemini) ──────────────────────────
        own_email = self._settings.own_email or self._detected_email or ""

        greeting_note = ""
        if greeting_names and user_name_variants:
            if not greeting_names.intersection(user_name_variants):
                greeted = " / ".join(sorted(greeting_names)[:2])
                greeting_note = (
                    f"The email opens with a greeting to '{greeted}', not to you — "
                    f"it may not require your reply."
                )

        classification = self._generator.classify(
            build_classification_prompt(
                parsed, contact,
                own_email=own_email,
                greeting_note=greeting_note,
            )
        )
        priority = classification["priority"]

        if classification["skip"] or not classification.get("needs_reply", True):
            self._gmail.mark_as_processed(parsed.latest_message_id)
            reason = classification["reason"]
            self._log("info", f"⏭ Skipped ({reason}): {parsed.sender_name}",
                      summary=summary, priority="skip")
            if trace and self._obs_traces:
                self._obs_traces.finish(trace, "skipped", reason)
            if self._obs_logger:
                self._obs_logger.log_skip(thread_id, parsed.sender_email, reason,
                                          priority=priority)
            return "skipped"

        if priority == "high":
            self._gmail.apply_priority_label(parsed.latest_message_id)

        # ── Attachment summarisation ───────────────────────────────────────────
        attachment_summary = ""
        if parsed.attachments:
            attachment_summary = fetch_and_summarise(
                gmail_client=self._gmail,
                message_id=parsed.latest_message_id,
                attachments=parsed.attachments,
                gemini_client=self._generator._client,
                model=self._generator._model,
            )

        # ── Interaction history context ────────────────────────────────────────
        recent_interactions = []
        recurring_topics = []
        if self._interaction_store:
            recent_interactions = self._interaction_store.get_recent(parsed.sender_email, n=5)
            recurring_topics = self._interaction_store.get_topics(parsed.sender_email)

        # ── Generate reply ─────────────────────────────────────────────────────
        user_message = build_user_message(
            parsed, contact, mode="reply",
            attachment_summary=attachment_summary,
            recent_interactions=recent_interactions or None,
            recurring_topics=recurring_topics or None,
        )
        body = self._generator.generate(user_message)
        final_html = assemble(parsed.sender_first_name, body, self._signature_html)

        reply_subject = (
            parsed.subject if parsed.subject.lower().startswith("re:")
            else f"Re: {parsed.subject}"
        )

        # ── Record history metadata for when user clicks Send ─────────────────
        item_id = str(uuid.uuid4())
        our_reply_summary = self._generator.summarise_reply(body)
        topics = self._generator.extract_topics(parsed.latest_body, body)
        self._pending_history[item_id] = {
            "sender_email": parsed.sender_email,
            "thread_id": parsed.thread_id,
            "date": datetime.now().date().isoformat(),
            "subject": parsed.subject,
            "summary": summary,
            "our_reply_summary": our_reply_summary,
            "topics": topics,
        }

        # ── Push to Review Queue ───────────────────────────────────────────────
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
            "thread_messages": [
                {
                    "sender_name": m.sender_name,
                    "sender_email": m.sender_email,
                    "body": m.body,
                }
                for m in parsed.thread_messages
            ],
        })

        self._gmail.mark_as_processed(parsed.latest_message_id)

        emoji = _PRIORITY_EMOJI.get(priority, "🟡")
        self._log(
            "pending",
            f"{emoji} Queued for review: {parsed.sender_name} <{parsed.sender_email}>",
            summary=summary, priority=priority, item_id=item_id,
        )

        total_ms = int((_time.monotonic() - t_start) * 1000)
        if trace and self._obs_traces:
            self._obs_traces.finish(trace, "queued", priority, total_ms=total_ms)
        if self._obs_logger:
            self._obs_logger.log_queued(thread_id, parsed.sender_email, priority, item_id)

        return "queued"

    # ── Skip logic ─────────────────────────────────────────────────────────────

    def _should_skip_as_observer(
        self,
        parsed,
        contact,
        greeting_names: frozenset = frozenset(),
        user_name_variants: frozenset = frozenset(),
    ) -> tuple[bool, str]:
        """
        Returns (True, reason) when the user should not reply because they are
        an observer (CC/BCC) or a teammate is keeping them informed.
        Runs before any Gemini API call to save tokens.
        """
        own = (self._settings.own_email or self._detected_email or "").lower().strip()
        team_domain = (self._settings.team_domain or "").lower().strip()
        sender_domain = parsed.sender_email.split("@")[-1].lower() if "@" in parsed.sender_email else ""
        sender_is_teammate = bool(
            (team_domain and sender_domain == team_domain)
            or (contact and getattr(contact, "is_teammate", False))
        )
        if own:
            user_in_to = any(own in addr for addr in parsed.to_addresses)
            user_in_cc = any(own in addr for addr in parsed.cc_addresses)
            bcc_or_forwarded = bool(parsed.to_addresses) and not user_in_to and not user_in_cc
            user_is_observer = (user_in_cc and not user_in_to) or bcc_or_forwarded
        else:
            user_is_observer = False

        if sender_is_teammate and user_is_observer:
            return True, "CC'd/BCC'd on teammate's outbound thread"
        if not sender_is_teammate and user_is_observer:
            return True, "CC'd/BCC'd as observer — not primary addressee"

        if greeting_names and user_name_variants:
            if not greeting_names.intersection(user_name_variants):
                if user_is_observer:
                    greeted = " / ".join(sorted(greeting_names)[:2])
                    return True, f"Greeting to '{greeted}' — not addressed to you"

        return False, ""

    def _user_name_variants(self) -> frozenset[str]:
        """Return lowercase name tokens the user is known by."""
        variants: set[str] = set()
        if self._settings.signature_name:
            for token in re.split(r"[\s.\-_]+", self._settings.signature_name):
                clean = re.sub(r"[^a-z]", "", token.lower())
                if len(clean) >= 2:
                    variants.add(clean)
        email = self._settings.own_email or self._detected_email or ""
        if "@" in email:
            prefix = email.split("@")[0].lower()
            for part in re.split(r"[.\-_]+", prefix):
                if len(part) >= 2:
                    variants.add(part)
        return frozenset(variants)
