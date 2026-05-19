import base64
import logging
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from exceptions import AuthError, GmailAPIError, GmailPermissionError

logger = logging.getLogger(__name__)

_PROCESSED_LABEL = "agent-processed"
_MAX_RETRIES = 5
_INITIAL_BACKOFF = 1  # seconds


class GmailClient:
    def __init__(self, creds: Credentials) -> None:
        self._service = build("gmail", "v1", credentials=creds)
        self._processed_label_id: Optional[str] = None

    # ── Public API ─────────────────────────────────────────────────────────────

    def list_unread_thread_ids(self, max_results: int = 20) -> list[str]:
        """Return IDs of unread threads not yet processed by the agent."""
        # Exclude automated/noreply senders and common notification patterns
        query = (
            f"is:unread -label:{_PROCESSED_LABEL} "
            "-from:noreply -from:no-reply -from:donotreply -from:do-not-reply "
            "-from:notifications -from:mailer-daemon -from:postmaster "
            "-category:promotions -category:updates"
        )
        response = self._execute(
            self._service.users().threads().list(
                userId="me", q=query, maxResults=max_results
            )
        )
        return [t["id"] for t in response.get("threads", [])]

    def get_thread(self, thread_id: str) -> dict:
        """Return the full thread object including all messages."""
        return self._execute(
            self._service.users().threads().get(
                userId="me", id=thread_id, format="full"
            )
        )

    def create_draft(
        self,
        to: str,
        subject: str,
        body_html: str,
        thread_id: Optional[str] = None,
        in_reply_to: Optional[str] = None,
        references: Optional[str] = None,
    ) -> str:
        """Create a Gmail draft. Returns the draft ID."""
        mime_msg = MIMEMultipart("alternative")
        mime_msg["To"] = to
        mime_msg["Subject"] = subject
        if in_reply_to:
            mime_msg["In-Reply-To"] = in_reply_to
        if references:
            mime_msg["References"] = references

        mime_msg.attach(MIMEText(body_html, "html"))
        raw = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode()

        body: dict = {"message": {"raw": raw}}
        if thread_id:
            body["message"]["threadId"] = thread_id

        draft = self._execute(
            self._service.users().drafts().create(userId="me", body=body)
        )
        return draft["id"]

    def mark_as_processed(self, message_id: str) -> None:
        """Apply the agent-processed label to prevent reprocessing on next poll."""
        label_id = self._get_or_create_processed_label()
        self._execute(
            self._service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"addLabelIds": [label_id]},
            )
        )

    # ── Internals ──────────────────────────────────────────────────────────────

    def _get_or_create_processed_label(self) -> str:
        if self._processed_label_id:
            return self._processed_label_id

        labels_response = self._execute(
            self._service.users().labels().list(userId="me")
        )
        for label in labels_response.get("labels", []):
            if label["name"] == _PROCESSED_LABEL:
                self._processed_label_id = label["id"]
                return self._processed_label_id

        # Label does not exist yet — create it
        created = self._execute(
            self._service.users().labels().create(
                userId="me",
                body={
                    "name": _PROCESSED_LABEL,
                    "labelListVisibility": "labelHide",
                    "messageListVisibility": "hide",
                },
            )
        )
        self._processed_label_id = created["id"]
        return self._processed_label_id

    def _execute(self, request, attempt: int = 0):
        """Execute a Gmail API request with exponential backoff on rate limits."""
        try:
            return request.execute()
        except HttpError as exc:
            status = exc.resp.status
            if status == 429 and attempt < _MAX_RETRIES:
                wait = _INITIAL_BACKOFF * (2 ** attempt)
                logger.warning("Gmail rate limit hit. Retrying in %ds...", wait)
                time.sleep(wait)
                return self._execute(request, attempt + 1)
            elif status == 401:
                raise AuthError(
                    "Gmail credentials expired or revoked. Delete credentials/token.json and re-run."
                ) from exc
            elif status == 403:
                raise GmailPermissionError(
                    f"Gmail API permission denied (403). Check OAuth scopes or quota. Detail: {exc}"
                ) from exc
            else:
                raise GmailAPIError(f"Gmail API error {status}: {exc}") from exc
