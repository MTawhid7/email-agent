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
_PRIORITY_LABEL = "agent-high-priority"
_MAX_RETRIES = 5
_INITIAL_BACKOFF = 1  # seconds


class GmailClient:
    def __init__(self, creds: Credentials) -> None:
        self._service = build("gmail", "v1", credentials=creds)
        self._processed_label_id: Optional[str] = None
        self._priority_label_id: Optional[str] = None

    # ── Public API ─────────────────────────────────────────────────────────────

    def list_unread_thread_ids(self, max_results: int = 20) -> list[str]:
        """Return IDs of unread threads not yet processed by the agent."""
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
        raw = self._build_raw_message(to, subject, body_html, in_reply_to, references)
        body: dict = {"message": {"raw": raw}}
        if thread_id:
            body["message"]["threadId"] = thread_id
        draft = self._execute(
            self._service.users().drafts().create(userId="me", body=body)
        )
        return draft["id"]

    def send_message(
        self,
        to: str,
        subject: str,
        body_html: str,
        thread_id: Optional[str] = None,
        in_reply_to: Optional[str] = None,
        references: Optional[str] = None,
    ) -> str:
        """Send an email immediately. Returns the sent message ID."""
        raw = self._build_raw_message(to, subject, body_html, in_reply_to, references)
        body: dict = {"raw": raw}
        if thread_id:
            body["threadId"] = thread_id
        result = self._execute(
            self._service.users().messages().send(userId="me", body=body)
        )
        return result["id"]

    def mark_as_processed(self, message_id: str) -> None:
        label_id = self._get_or_create_label(_PROCESSED_LABEL, "_processed_label_id", hide=True)
        self._execute(
            self._service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"addLabelIds": [label_id]},
            )
        )

    def apply_priority_label(self, message_id: str) -> None:
        """Apply the agent-high-priority label to a message."""
        label_id = self._get_or_create_label(_PRIORITY_LABEL, "_priority_label_id", hide=False)
        self._execute(
            self._service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"addLabelIds": [label_id]},
            )
        )

    def get_own_email(self) -> str:
        """Return the Gmail address of the authenticated account."""
        profile = self._execute(
            self._service.users().getProfile(userId="me")
        )
        return profile.get("emailAddress", "")

    def get_attachment(self, message_id: str, attachment_id: str) -> bytes:
        """Download an attachment and return its bytes."""
        import base64 as b64
        result = self._execute(
            self._service.users().messages().attachments().get(
                userId="me", messageId=message_id, id=attachment_id
            )
        )
        data = result.get("data", "")
        return b64.urlsafe_b64decode(data + "==")

    # ── Internals ──────────────────────────────────────────────────────────────

    def _build_raw_message(
        self,
        to: str,
        subject: str,
        body_html: str,
        in_reply_to: Optional[str],
        references: Optional[str],
    ) -> str:
        mime_msg = MIMEMultipart("alternative")
        mime_msg["To"] = to
        mime_msg["Subject"] = subject
        if in_reply_to:
            mime_msg["In-Reply-To"] = in_reply_to
        if references:
            mime_msg["References"] = references
        mime_msg.attach(MIMEText(body_html, "html"))
        return base64.urlsafe_b64encode(mime_msg.as_bytes()).decode()

    def _get_or_create_label(self, name: str, cache_attr: str, hide: bool) -> str:
        cached = getattr(self, cache_attr)
        if cached:
            return cached

        labels_response = self._execute(
            self._service.users().labels().list(userId="me")
        )
        for label in labels_response.get("labels", []):
            if label["name"] == name:
                setattr(self, cache_attr, label["id"])
                return label["id"]

        visibility = "labelHide" if hide else "labelShow"
        created = self._execute(
            self._service.users().labels().create(
                userId="me",
                body={
                    "name": name,
                    "labelListVisibility": visibility,
                    "messageListVisibility": "hide" if hide else "show",
                },
            )
        )
        setattr(self, cache_attr, created["id"])
        return created["id"]

    def _execute(self, request, attempt: int = 0):
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
