import csv
import logging
from dataclasses import dataclass
from typing import Optional

from ai.prompts import build_user_message
from ai.generator import ReplyGenerator
from ai.assembler import assemble
from core.config import Settings
from contacts.contact_store import ContactProfile, ContactStore
from email_parser.parser import ParsedEmail, ThreadMessage
from core.exceptions import GenerationError
from gmail.client import GmailClient
from signature.signature import SignatureBuilder

logger = logging.getLogger(__name__)

_REQUIRED_COLUMNS = {"name", "email"}


@dataclass(frozen=True)
class _RecipientRow:
    name: str
    email: str
    notes: str


def run_bulk(
    csv_path: str,
    intent: str,
    gmail: GmailClient,
    generator: ReplyGenerator,
    contact_store: ContactStore,
    sig_builder: SignatureBuilder,
    settings: Settings,
) -> None:
    """
    Read recipients from a CSV and create one personalized Gmail draft per row.
    Skips malformed rows with a warning rather than aborting the batch.
    """
    rows = _load_csv(csv_path)
    if not rows:
        logger.warning("No valid rows found in %s.", csv_path)
        return

    signature_html = sig_builder.build_html()

    for row in rows:
        try:
            _process_row(row, intent, gmail, generator, contact_store, signature_html)
        except Exception as exc:
            logger.error("Failed for %s: %s", row.email, exc)


def generate_bulk_draft(
    row: _RecipientRow,
    intent: str,
    subject_override: str,
    generator: ReplyGenerator,
    contact_store: ContactStore,
    signature_html: str,
) -> tuple[str, str]:
    """
    Generate personalised email content for one recipient.
    Returns (subject, body_html) — does NOT make any Gmail API call.
    Called by routes/bulk.py to push items into the in-app Review Queue.
    """
    contact = contact_store.lookup(row.email)

    merged_notes = _merge_notes(row.notes, contact.notes if contact else "")
    if contact and merged_notes != contact.notes:
        contact = ContactProfile(
            email=contact.email,
            name=contact.name or row.name,
            company=contact.company,
            relationship_type=contact.relationship_type,
            notes=merged_notes,
        )
    elif contact is None and row.notes:
        contact = ContactProfile(email=row.email, name=row.name, notes=row.notes)

    first_name = row.name.split()[0] if row.name else row.email.split("@")[0]
    parsed = _minimal_parsed_email(row.name, row.email, first_name)
    user_message = build_user_message(parsed, contact, mode="bulk", intent=intent)

    try:
        body = generator.generate(user_message)
    except GenerationError as exc:
        raise GenerationError(f"Generation failed for {row.email}: {exc}") from exc

    final_html = assemble(first_name, body, signature_html)
    subject = subject_override.strip() or (intent[:60] if intent else "Hello")
    return subject, final_html


def _process_row(
    row: _RecipientRow,
    intent: str,
    gmail: GmailClient,
    generator: ReplyGenerator,
    contact_store: ContactStore,
    signature_html: str,
) -> None:
    """Legacy: generate draft and create it in Gmail immediately."""
    subject, final_html = generate_bulk_draft(
        row, intent, "", generator, contact_store, signature_html
    )
    gmail.create_draft(to=row.email, subject=subject, body_html=final_html)
    logger.info("Draft created for %s <%s>", row.name, row.email)


def _load_csv(csv_path: str) -> list[_RecipientRow]:
    rows: list[_RecipientRow] = []
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None or not _REQUIRED_COLUMNS.issubset(
                {c.strip().lower() for c in reader.fieldnames}
            ):
                logger.error(
                    "CSV '%s' must have columns: %s", csv_path, ", ".join(_REQUIRED_COLUMNS)
                )
                return []

            for i, row in enumerate(reader, start=2):  # row 1 is the header
                name = row.get("name", "").strip()
                email = row.get("email", "").strip()
                if not email:
                    logger.warning("Row %d: missing email — skipped.", i)
                    continue
                rows.append(_RecipientRow(name=name, email=email, notes=row.get("notes", "").strip()))
    except FileNotFoundError:
        logger.error("CSV file not found: %s", csv_path)
    except Exception as exc:
        logger.error("Failed to read CSV '%s': %s", csv_path, exc)

    return rows


def _merge_notes(csv_notes: str, stored_notes: str) -> str:
    parts = [p for p in (stored_notes, csv_notes) if p]
    return "; ".join(parts)


def _minimal_parsed_email(name: str, email: str, first_name: str) -> ParsedEmail:
    """Create a ParsedEmail stub for bulk mode (no real thread)."""
    return ParsedEmail(
        sender_name=name,
        sender_first_name=first_name,
        sender_email=email,
        subject="",
        latest_body="",
        latest_message_id="",
        message_id_header="",
        thread_id="",
        thread_messages=(),
    )
