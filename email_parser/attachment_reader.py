import logging
import os
import tempfile

logger = logging.getLogger(__name__)

_SUPPORTED_TYPES = frozenset({
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/gif",
    "image/webp",
})
_MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


def fetch_and_summarise(
    gmail_client,
    message_id: str,
    attachments: tuple,
    gemini_client,
    model: str,
) -> str:
    """
    Download supported attachments, upload to Gemini Files API, and return a
    combined one-line summary. Silently skips individual failures so the main
    reply flow is never blocked.
    """
    summaries: list[str] = []

    for att in attachments:
        if att.mime_type not in _SUPPORTED_TYPES:
            continue
        if att.size > _MAX_SIZE_BYTES:
            logger.info("Skipping attachment %s — too large (%d bytes)", att.filename, att.size)
            continue
        try:
            data = gmail_client.get_attachment(message_id, att.attachment_id)
            summary = _summarise_bytes(data, att.mime_type, att.filename, gemini_client, model)
            if summary:
                summaries.append(f"{att.filename}: {summary}")
        except Exception as exc:
            logger.warning("Attachment summarisation failed for %s: %s", att.filename, exc)

    return " | ".join(summaries)


def _summarise_bytes(
    data: bytes,
    mime_type: str,
    filename: str,
    gemini_client,
    model: str,
) -> str:
    suffix = os.path.splitext(filename)[1] or ".bin"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(data)
        tmp.close()
        uploaded = gemini_client.files.upload(
            file=tmp.name,
            config={"mime_type": mime_type, "display_name": filename},
        )
        response = gemini_client.models.generate_content(
            model=model,
            contents=["Summarize this attachment in 2 sentences.", uploaded],
        )
        return (response.text or "").strip()
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
