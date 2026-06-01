import re

# Matches a leading greeting the AI generated despite the "no greeting" instruction.
# Handles both HTML (<p>Dear Ahmed,</p>) and plain-text ("Dear Ahmed,\n") forms.
_AI_GREETING_RE = re.compile(
    r"^(?:<p>\s*)?(?:dear|hi|hello|hey|greetings?|good\s+(?:morning|afternoon|evening))"
    r"[\s,]+[\w'\-]+[,!.]?\s*(?:</p>)?\s*\n?",
    re.IGNORECASE,
)


def assemble(first_name: str, reply_body: str, signature_html: str) -> str:
    """
    Combine greeting, AI-generated body, and HTML signature into a final email.
    Pure function — no I/O, no side effects.

    Strips any greeting line the AI produced to prevent double-greeting output
    (e.g. "Dear Ahmed, Hi Ahmed, …") before prepending the canonical greeting.
    """
    # Wrap plain-text body lines in paragraph tags if no HTML is detected
    if "<" not in reply_body:
        paragraphs = "\n".join(
            f"<p>{line}</p>" for line in reply_body.strip().splitlines() if line.strip()
        )
        body_html = paragraphs or f"<p>{reply_body.strip()}</p>"
    else:
        body_html = reply_body.strip()

    # Remove any AI-generated greeting so ours doesn't duplicate it
    body_html = _AI_GREETING_RE.sub("", body_html, count=1).lstrip()

    return (
        f"<p>Dear {first_name},</p>\n"
        f"{body_html}"
        f"{signature_html}"
    )
