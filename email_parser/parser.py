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
class AttachmentInfo:
    filename: str
    mime_type: str
    attachment_id: str
    size: int = 0


@dataclass(frozen=True)
class ParsedEmail:
    sender_name: str
    sender_first_name: str
    sender_email: str
    subject: str
    latest_body: str
    latest_message_id: str
    message_id_header: str
    thread_id: str
    thread_messages: tuple
    attachments: tuple = ()   # tuple of AttachmentInfo


def parse_thread(thread: dict) -> Optional[ParsedEmail]:
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
    message_id_header = latest_headers.get("message-id", "")
    attachments = tuple(_extract_attachments(latest_msg))

    return ParsedEmail(
        sender_name=sender_name,
        sender_first_name=_first_name(sender_name, sender_email),
        sender_email=sender_email,
        subject=subject,
        latest_body=parsed_messages[-1].body,
        latest_message_id=latest_msg["id"],
        message_id_header=message_id_header,
        thread_id=thread_id,
        thread_messages=tuple(parsed_messages),
        attachments=attachments,
    )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _header_map(message: dict) -> dict[str, str]:
    headers = message.get("payload", {}).get("headers", [])
    return {h["name"].lower(): h["value"] for h in headers}


def _parse_address(address: str) -> tuple[str, str]:
    match = re.match(r"^(.*?)\s*<([^>]+)>$", address.strip())
    if match:
        name = match.group(1).strip().strip('"')
        email = match.group(2).strip()
        return name or email, email
    email = address.strip()
    return email, email


def _first_name(display_name: str, email: str) -> str:
    if display_name and "@" not in display_name:
        return display_name.split()[0]
    return email.split("@")[0]


def _extract_body(message: dict) -> str:
    payload = message.get("payload", {})
    text = _extract_from_part(payload)
    return text.strip() if text else ""


def _extract_from_part(part: dict) -> str:
    mime_type = part.get("mimeType", "")

    if mime_type == "text/plain":
        return _decode_body(part.get("body", {}).get("data", ""))

    if mime_type == "text/html":
        html = _decode_body(part.get("body", {}).get("data", ""))
        return BeautifulSoup(html, "html.parser").get_text(separator="\n")

    if mime_type.startswith("multipart/"):
        parts = part.get("parts", [])
        for sub in parts:
            if sub.get("mimeType") == "text/plain":
                result = _extract_from_part(sub)
                if result:
                    return result
        for sub in parts:
            result = _extract_from_part(sub)
            if result:
                return result

    return ""


def _extract_attachments(message: dict) -> list[AttachmentInfo]:
    """Recursively find all attachments in a message payload."""
    result: list[AttachmentInfo] = []
    _collect_attachments(message.get("payload", {}), result)
    return result


def _collect_attachments(part: dict, result: list) -> None:
    body = part.get("body", {})
    attachment_id = body.get("attachmentId")
    mime_type = part.get("mimeType", "")
    filename = part.get("filename", "")

    if attachment_id and filename and not mime_type.startswith("multipart/"):
        result.append(AttachmentInfo(
            filename=filename,
            mime_type=mime_type,
            attachment_id=attachment_id,
            size=body.get("size", 0),
        ))

    for sub in part.get("parts", []):
        _collect_attachments(sub, result)


def _decode_body(data: str) -> str:
    if not data:
        return ""
    return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
