import logging
import sys
import time

import click

from ai.reply_generator import ReplyGenerator
from ai.prompts import build_user_message
from assembler import assemble
from bulk.bulk_sender import run_bulk
from config import load_settings
from contacts.contact_store import ContactStore
from email_parser.parser import parse_thread
from exceptions import AuthError, ConfigError, EmailAgentError
from gmail_client.auth import get_credentials
from gmail_client.gmail_client import GmailClient
from signature.signature import SignatureBuilder

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


# ── CLI root ───────────────────────────────────────────────────────────────────

@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Email Agent — personalized Gmail drafts powered by Gemini."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(run_daemon)


# ── Reply mode (daemon) ────────────────────────────────────────────────────────

@cli.command("run")
@click.option("--max", "max_results", default=20, show_default=True, help="Max threads per poll.")
def run_daemon(max_results: int = 20) -> None:
    """Start the polling daemon. Runs until Ctrl+C."""
    try:
        settings = load_settings()
    except ConfigError as exc:
        logger.error("Configuration error: %s", exc)
        sys.exit(1)

    try:
        creds = get_credentials(settings.gmail_credentials_path)
    except AuthError as exc:
        logger.error("Auth error: %s", exc)
        sys.exit(1)

    gmail = GmailClient(creds)
    generator = ReplyGenerator(settings)
    contact_store = ContactStore()
    sig_builder = SignatureBuilder(settings)
    signature_html = sig_builder.build_html()

    logger.info(
        "Polling inbox every %ds — press Ctrl+C to stop.",
        settings.poll_interval_seconds,
    )

    while True:
        try:
            _process_unread(gmail, generator, contact_store, signature_html, max_results)
        except AuthError as exc:
            logger.error("Auth error during poll: %s", exc)
            sys.exit(1)
        except EmailAgentError as exc:
            logger.error("Agent error during poll: %s", exc)
        except Exception as exc:
            logger.error("Unexpected error during poll: %s", exc, exc_info=True)

        time.sleep(settings.poll_interval_seconds)


def _process_unread(
    gmail: GmailClient,
    generator: ReplyGenerator,
    contact_store: ContactStore,
    signature_html: str,
    max_results: int,
) -> None:
    thread_ids = gmail.list_unread_thread_ids(max_results=max_results)

    if not thread_ids:
        logger.info("No new emails.")
        return

    for thread_id in thread_ids:
        try:
            thread = gmail.get_thread(thread_id)
            parsed = parse_thread(thread)
            if parsed is None:
                continue

            contact = contact_store.lookup(parsed.sender_email)
            user_message = build_user_message(parsed, contact, mode="reply")
            body = generator.generate(user_message)
            final_html = assemble(parsed.sender_first_name, body, signature_html)

            reply_subject = (
                parsed.subject
                if parsed.subject.lower().startswith("re:")
                else f"Re: {parsed.subject}"
            )

            gmail.create_draft(
                to=parsed.sender_email,
                subject=reply_subject,
                body_html=final_html,
                thread_id=parsed.thread_id,
                in_reply_to=parsed.message_id_header,
                references=parsed.message_id_header,
            )
            gmail.mark_as_processed(parsed.latest_message_id)

            logger.info(
                "Draft created for %s <%s>", parsed.sender_name, parsed.sender_email
            )
        except EmailAgentError as exc:
            logger.error("Skipping thread %s: %s", thread_id, exc)
        except Exception as exc:
            logger.error("Unexpected error on thread %s: %s", thread_id, exc, exc_info=True)


# ── Bulk send mode ─────────────────────────────────────────────────────────────

@cli.command("bulk")
@click.option(
    "--csv",
    "csv_path",
    required=True,
    type=click.Path(exists=True),
    help="Path to recipients CSV (columns: name, email, notes).",
)
@click.option(
    "--intent",
    required=True,
    help="What the email should communicate (used as the email subject and prompt context).",
)
def bulk_send(csv_path: str, intent: str) -> None:
    """Generate personalized drafts for every recipient in a CSV file."""
    try:
        settings = load_settings()
    except ConfigError as exc:
        logger.error("Configuration error: %s", exc)
        sys.exit(1)

    try:
        creds = get_credentials(settings.gmail_credentials_path)
    except AuthError as exc:
        logger.error("Auth error: %s", exc)
        sys.exit(1)

    gmail = GmailClient(creds)
    generator = ReplyGenerator(settings)
    contact_store = ContactStore()
    sig_builder = SignatureBuilder(settings)

    run_bulk(
        csv_path=csv_path,
        intent=intent,
        gmail=gmail,
        generator=generator,
        contact_store=contact_store,
        sig_builder=sig_builder,
        settings=settings,
    )
    logger.info("Bulk send complete. Check Gmail Drafts.")


# ── Contacts management ────────────────────────────────────────────────────────

@cli.group("contacts")
def contacts_group() -> None:
    """Manage the contact profile store."""


@contacts_group.command("list")
def contacts_list() -> None:
    """List all saved contact profiles."""
    store = ContactStore()
    profiles = store.list_all()
    if not profiles:
        click.echo("No contacts saved yet.")
        return
    for p in profiles:
        click.echo(f"  {p.email}  |  {p.name}  |  {p.company}  |  {p.notes}")


@contacts_group.command("add")
@click.option("--email", required=True)
@click.option("--name", default="")
@click.option("--company", default="")
@click.option("--relationship", default="")
@click.option("--notes", default="")
def contacts_add(
    email: str, name: str, company: str, relationship: str, notes: str
) -> None:
    """Add or update a contact profile."""
    from contacts.contact_store import ContactProfile

    store = ContactStore()
    profile = ContactProfile(
        email=email,
        name=name,
        company=company,
        relationship_type=relationship,
        notes=notes,
    )
    store.upsert(profile)
    click.echo(f"Saved contact: {email}")


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cli()
