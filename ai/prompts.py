from typing import Literal, Optional

from contacts.contact_store import ContactProfile
from email_parser.parser import ParsedEmail

_SYSTEM_WRAPPER = """\
You are an email assistant. Your job is to write professional, personalized email \
replies or compose new emails on behalf of the user.

Follow the persona instructions below exactly:

{persona}

Rules:
- Output the email body ONLY — do NOT include a greeting (e.g. "Dear X," or "Hi X,"),
  do NOT include a farewell or sign-off, do NOT include a subject line.
  The greeting is prepended automatically; writing one creates unwanted duplication.
- Be concise. Do not pad the response.
- If you need to address the recipient by name inside the body, use their first name
  naturally in a sentence — never as a standalone greeting line.
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
    recent_interactions: Optional[list] = None,
    recurring_topics: Optional[list] = None,
) -> str:
    """
    Build the user-turn prompt for a reply or bulk email.

    recent_interactions: list of InteractionRecord objects (newest first).
    recurring_topics:    list of topic tag strings.
    Both default to None — all existing callers are unchanged.
    """
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

        history_block = _format_interaction_history(recent_interactions, recurring_topics)

        return (
            f"Sender: {parsed.sender_name} <{parsed.sender_email}>\n"
            f"Contact notes: {notes or 'none'}{tone_line}\n"
            f"{history_block}"
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


def build_classification_prompt(
    parsed: ParsedEmail,
    contact: Optional[ContactProfile],
    own_email: str = "",
    greeting_note: str = "",
) -> str:
    to_line = ", ".join(parsed.to_addresses) if parsed.to_addresses else "unknown"
    cc_line = ", ".join(parsed.cc_addresses) if parsed.cc_addresses else "none"
    own_line = f"My email: {own_email}\n" if own_email else ""
    greeting_line = f"Greeting analysis: {greeting_note}\n" if greeting_note else ""
    return (
        "Classify this email and determine whether it requires a reply.\n\n"
        f"{own_line}"
        f"To: {to_line}\n"
        f"CC: {cc_line}\n"
        f"{greeting_line}"
        f"Sender: {parsed.sender_name} <{parsed.sender_email}>\n"
        f"Subject: {parsed.subject}\n"
        f"Known contact: {contact is not None}\n"
        f"Email body (first 600 chars):\n{parsed.latest_body[:600]}\n\n"
        "1. Priority — pick exactly one:\n"
        "   - high: urgent keywords (urgent, ASAP, deadline, critical), VIP sender, direct personal ask\n"
        "   - normal: standard business email that warrants a reply\n"
        "   - low: FYI, company-wide announcement, low urgency\n"
        "   - skip: newsletter, marketing, automated notification, bulk/promotional, "
        "contains 'unsubscribe' / 'you are receiving this' / 'manage preferences'\n\n"
        "2. needs_reply — true or false:\n"
        "   - true: email contains a direct question, request, or action item addressed to me\n"
        "   - false: purely informational (FYI, announcement, confirmation receipt, "
        "out-of-office, group update where no individual reply is expected)\n\n"
        "Return JSON only, no markdown fences:\n"
        '{"priority": "high|normal|low|skip", "needs_reply": true, "reason": "one sentence"}'
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


def _format_interaction_history(
    interactions: Optional[list],
    topics: Optional[list],
    char_budget: int = 2000,
) -> str:
    """
    Format pre-computed interaction history for injection into the reply prompt.
    Returns an empty string when no history is available.
    Oldest records are dropped first if the total exceeds char_budget.
    """
    lines: list[str] = []
    budget = char_budget

    if topics:
        topics_line = f"Recurring topics with this contact: {', '.join(topics[:10])}\n"
        lines.append(topics_line)
        budget -= len(topics_line)

    if interactions:
        history_lines: list[str] = []
        for rec in interactions:  # already newest-first
            entry = (
                f"- [{rec.date}] {rec.subject}\n"
                f"  They said: {rec.summary}\n"
                f"  You replied: {rec.our_reply_summary}"
            )
            if len(entry) > budget:
                break
            history_lines.append(entry)
            budget -= len(entry)
        if history_lines:
            lines.append(
                "Recent interactions with this contact (newest first):\n"
                + "\n".join(history_lines)
                + "\n"
            )

    if not lines:
        return ""
    return "\n" + "\n".join(lines) + "\n"
