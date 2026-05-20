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
{extra_rules}
{facts_block}"""


def build_system_prompt(
    persona_text: str,
    auto_translate: bool = False,
    context_facts: str = "",
) -> str:
    extra = ""
    if auto_translate:
        extra = "- Detect the language of the incoming email and write your reply in that same language."

    facts_block = ""
    if context_facts.strip():
        facts_block = (
            "Facts about you that are ALWAYS true — treat these as ground truth, "
            "never hallucinate alternatives:\n"
            + context_facts.strip()
        )

    return _SYSTEM_WRAPPER.format(
        persona=persona_text.strip(),
        extra_rules=extra,
        facts_block=facts_block,
    ).strip()


def build_user_message(
    parsed: ParsedEmail,
    contact: Optional[ContactProfile],
    mode: Literal["reply", "bulk"],
    intent: str = "",
    template_body: str = "",
    attachment_summary: str = "",
) -> str:
    notes = _merge_notes(contact)
    tone_line = ""
    if contact and getattr(contact, "tone", ""):
        tone_line = f"\nTone: Write in a {contact.tone} tone for this sender."

    if mode == "reply":
        thread_block = _format_thread(parsed.thread_messages)
        extras = ""
        if attachment_summary:
            extras += f"\nAttachment context: {attachment_summary}"
        if template_body:
            extras += f"\nTemplate guide (personalise freely): {template_body}"
        return (
            f"Sender: {parsed.sender_name} <{parsed.sender_email}>\n"
            f"Contact notes: {notes or 'none'}{tone_line}\n\n"
            f"Thread history (oldest first):\n{thread_block}\n"
            f"{extras}\n"
            f"Task: Write a reply to {parsed.sender_first_name}. "
            "Output the reply body ONLY — no greeting line, no signature."
        )

    # bulk mode
    recipient_name = contact.name if contact and contact.name else parsed.sender_name
    first_name = recipient_name.split()[0] if recipient_name else parsed.sender_first_name
    extras = f"\nTemplate guide (personalise freely): {template_body}" if template_body else ""
    return (
        f"Recipient: {recipient_name} <{parsed.sender_email}>\n"
        f"Contact notes: {notes or 'none'}{tone_line}\n\n"
        f"Email intent: {intent.strip()}\n"
        f"{extras}\n"
        f"Task: Write a personalized email body to {first_name} based on the intent above. "
        "Output the email body ONLY — no greeting line, no signature."
    )


def build_classification_prompt(parsed: ParsedEmail, contact: Optional[ContactProfile]) -> str:
    return (
        "Classify this email into exactly one priority category.\n\n"
        f"Sender: {parsed.sender_name} <{parsed.sender_email}>\n"
        f"Subject: {parsed.subject}\n"
        f"Known contact: {contact is not None}\n"
        f"Email body (first 600 chars): {parsed.latest_body[:600]}\n\n"
        "Categories:\n"
        "- high: known VIP, urgent keywords (urgent, ASAP, deadline, critical), direct personal question\n"
        "- normal: standard business email, polite inquiry that needs a reply\n"
        "- low: company-wide announcement, FYI, low urgency\n"
        "- skip: newsletter, marketing, automated notification, no personal greeting, "
        "contains 'unsubscribe', 'you are receiving this', 'manage preferences', "
        "or is clearly bulk/promotional\n\n"
        "Return JSON only, no markdown fences:\n"
        '{"priority": "high|normal|low|skip", "reason": "one sentence"}'
    )


def build_summary_prompt(parsed: ParsedEmail) -> str:
    thread_block = _format_thread(parsed.thread_messages)
    return (
        "Summarize this email thread in ONE sentence (max 12 words).\n\n"
        f"Subject: {parsed.subject}\n"
        f"Thread:\n{thread_block}\n\n"
        "Output the summary sentence ONLY. No trailing period."
    )


# ── Helpers ────────────────────────────────────────────────────────────────────

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
