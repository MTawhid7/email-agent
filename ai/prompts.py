from typing import Literal, Optional

from contacts.contact_store import ContactProfile
from email_parser.parser import ParsedEmail

_SYSTEM_WRAPPER = """\
You are an email assistant. Your job is to write professional, personalized email \
replies or compose new emails on behalf of the user.

Follow the persona instructions below exactly:

{persona}

Rules:
- Output the email body ONLY. No greeting line. No signature. No subject line.
- Be concise. Do not pad the response.
- Address the recipient by their first name only in the body if needed (not as a greeting).
"""


def build_system_prompt(persona_text: str) -> str:
    return _SYSTEM_WRAPPER.format(persona=persona_text.strip())


def build_user_message(
    parsed: ParsedEmail,
    contact: Optional[ContactProfile],
    mode: Literal["reply", "bulk"],
    intent: str = "",
) -> str:
    notes = _merge_notes(contact)

    if mode == "reply":
        thread_block = _format_thread(parsed.thread_messages)
        return (
            f"Sender: {parsed.sender_name} <{parsed.sender_email}>\n"
            f"Contact notes: {notes or 'none'}\n\n"
            f"Thread history (oldest first):\n{thread_block}\n\n"
            f"Task: Write a reply to {parsed.sender_first_name}. "
            "Output the reply body ONLY — no greeting line, no signature."
        )

    # bulk mode
    recipient_name = contact.name if contact and contact.name else parsed.sender_name
    first_name = recipient_name.split()[0] if recipient_name else parsed.sender_first_name
    return (
        f"Recipient: {recipient_name} <{parsed.sender_email}>\n"
        f"Contact notes: {notes or 'none'}\n\n"
        f"Email intent: {intent.strip()}\n\n"
        f"Task: Write a personalized email body to {first_name} based on the intent above. "
        "Output the email body ONLY — no greeting line, no signature."
    )


def _merge_notes(contact: Optional[ContactProfile]) -> str:
    if contact is None:
        return ""
    parts = [contact.notes]
    if contact.company:
        parts.insert(0, f"Company: {contact.company}")
    if contact.relationship_type:
        parts.insert(0, f"Relationship: {contact.relationship_type}")
    return "; ".join(p for p in parts if p)


def _format_thread(messages) -> str:
    lines: list[str] = []
    for msg in messages:
        header = f"[From: {msg.sender_name} <{msg.sender_email}>]"
        body = msg.body.strip().replace("\n", "\n  ")
        lines.append(f"{header}\n  {body}")
    return "\n\n".join(lines)
