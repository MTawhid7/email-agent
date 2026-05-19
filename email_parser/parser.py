import base64
import re
from dataclasses import dataclass
from typing import Optional

from bs4 import BeautifulSoup


@dataclass(frozen=True)
class ThreadMessage:
    sender_name: str
    sender_email: str
    body: str


@dataclass(frozen=True)
class ParsedEmail:
    sender_name: str
    sender_first_name: str
    sender_email: str
    subject: str
    latest_body: str
    latest_message_id: str        # Gmail message ID (for mark_as_processed)
    message_id_header: str        # RFC 2822 Message-ID header (for In-Reply-To)
    thread_id: str
    thread_messages: tuple[ThreadMessage, ...]


def parse_thread(thread: dict) -> Optional[ParsedEmail]:
    """
    Parse a Gmail thread dict into a ParsedEmail.
    Returns None if the thread has no messages.
    """
    messages: list[dict] = thread.get("messages", [])
    if not messages:
        return None

    thread_id = thread["id"]
    parsed_messages: list[ThreadMessage] = []

    for msg in messages:
        headers = _header_map(msg)
        sender_name, sender_email = _parse_address(headers.get("from", ""))
        body = _extract_body(msg)
        parsed_messages.append(ThreadMessage(sender_name=sender_name, sender_email=sender_email, body=body))

    latest_msg = messages[-1]
    latest_headers = _header_map(latest_msg)
    sender_name, sender_email = _parse_address(latest_headers.get("from", ""))
    subject = latest_headers.get("subject", "(no subject)")
    latest_body = parsed_messages[-1].body
    message_id_header = latest_headers.get("message-id", "")

    return ParsedEmail(
        sender_name=sender_name,
        sender_first_name=_first_name(sender_name, sender_email),
        sender_email=sender_email,
        subject=subject,
        latest_body=latest_body,
        latest_message_id=latest_msg["id"],
        message_id_header=message_id_header,
        thread_id=thread_id,
        thread_messages=tuple(parsed_messages),
    )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _header_map(message: dict) -> dict[str, str]:
    """Return a lowercase-keyed dict of all headers for a message."""
    headers = message.get("payload", {}).get("headers", [])
    return {h["name"].lower(): h["value"] for h in headers}


def _parse_address(address: str) -> tuple[str, str]:
    """
    Parse 'Display Name <email@example.com>' or bare 'email@example.com'.
    Returns (display_name, email).
    """
    match = re.match(r"^(.*?)\s*<([^>]+)>$", address.strip())
    if match:
        name = match.group(1).strip().strip('"')
        email = match.group(2).strip()
        return name or email, email

    # Bare email address — use local part as name
    email = address.strip()
    return email, email


def _first_name(display_name: str, email: str) -> str:
    """Extract first name from display name, falling back to email local part."""
    if display_name and "@" not in display_name:
        return display_name.split()[0]
    return email.split("@")[0]


def _extract_body(message: dict) -> str:
    """Recursively extract the plain-text body from a Gmail message payload."""
    payload = message.get("payload", {})
    text = _extract_from_part(payload)
    return text.strip() if text else ""


def _extract_from_part(part: dict) -> str:
    mime_type = part.get("mimeType", "")

    # Prefer plain text; fall back to HTML stripped to text
    if mime_type == "text/plain":
        return _decode_body(part.get("body", {}).get("data", ""))

    if mime_type == "text/html":
        html = _decode_body(part.get("body", {}).get("data", ""))
        return BeautifulSoup(html, "html.parser").get_text(separator="\n")

    # Recurse into multipart
    if mime_type.startswith("multipart/"):
        parts = part.get("parts", [])
        # For multipart/alternative, prefer plain text (usually first)
        for sub in parts:
            if sub.get("mimeType") == "text/plain":
                result = _extract_from_part(sub)
                if result:
                    return result
        # Fall back to first part with any content
        for sub in parts:
            result = _extract_from_part(sub)
            if result:
                return result

    return ""


def _decode_body(data: str) -> str:
    if not data:
        return ""
    return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
