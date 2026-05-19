def assemble(first_name: str, reply_body: str, signature_html: str) -> str:
    """
    Combine greeting, AI-generated body, and HTML signature into a final email.
    Pure function — no I/O, no side effects.
    """
    # Wrap plain-text body lines in paragraph tags if no HTML is detected
    if "<" not in reply_body:
        paragraphs = "\n".join(
            f"<p>{line}</p>" for line in reply_body.strip().splitlines() if line.strip()
        )
        body_html = paragraphs or f"<p>{reply_body.strip()}</p>"
    else:
        body_html = reply_body.strip()

    return (
        f"<p>Dear {first_name},</p>\n"
        f"{body_html}"
        f"{signature_html}"
    )
