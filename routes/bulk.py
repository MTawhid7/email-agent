import csv
import io
import os
import tempfile
import threading
import uuid

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from ai.reply_generator import ReplyGenerator
from config import load_settings_from_dict
from contacts.contact_store import ContactStore
from gmail_client.auth import get_credentials
from gmail_client.gmail_client import GmailClient
from signature.signature import SignatureBuilder
from storage.app_config import (
    get_contacts_path,
    get_credentials_path,
    get_token_path,
    load_config,
)

bulk_bp = Blueprint("bulk", __name__)

# In-memory job tracker: {job_id: {total, done, failed, log, finished}}
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


@bulk_bp.route("/bulk", methods=["GET"])
def bulk():
    job_id = request.args.get("job")
    return render_template("bulk.html", job_id=job_id)


@bulk_bp.route("/bulk", methods=["POST"])
def bulk_submit():
    intent = request.form.get("intent", "").strip()
    input_mode = request.form.get("input_mode", "csv")

    if not intent:
        return render_template("bulk.html", job_id=None, error="Please enter an email intent.")

    if input_mode == "manual":
        rows = _parse_manual_recipients(request.form)
        if not rows:
            return render_template("bulk.html", job_id=None, error="Please add at least one recipient with a valid email.")
        csv_path = _recipients_to_temp_csv(rows)
    else:
        file = request.files.get("csv_file")
        if not file or file.filename == "":
            return render_template("bulk.html", job_id=None, error="Please upload a CSV file.")
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
        file.save(tmp.name)
        tmp.close()
        csv_path = tmp.name

    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {"total": 0, "done": 0, "failed": 0, "log": [], "finished": False}

    threading.Thread(
        target=_run_bulk_job,
        args=(job_id, csv_path, intent),
        daemon=True,
    ).start()

    return redirect(url_for("bulk.bulk", job=job_id))


@bulk_bp.route("/api/bulk/status/<job_id>")
def bulk_status(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_manual_recipients(form) -> list[dict]:
    """Extract recipient rows from the manual entry form fields (r_name_0, r_email_0, ...)."""
    recipients = []
    i = 0
    while True:
        name = form.get(f"r_name_{i}", "").strip()
        email = form.get(f"r_email_{i}", "").strip()
        notes = form.get(f"r_notes_{i}", "").strip()
        if not name and not email:
            break
        if email:
            recipients.append({"name": name, "email": email, "notes": notes})
        i += 1
        if i > 100:
            break
    return recipients


def _recipients_to_temp_csv(rows: list[dict]) -> str:
    """Write recipient dicts to a temp CSV file and return its path."""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="w",
                                      newline="", encoding="utf-8")
    writer = csv.DictWriter(tmp, fieldnames=["name", "email", "notes"])
    writer.writeheader()
    writer.writerows(rows)
    tmp.close()
    return tmp.name


# ── Background job ─────────────────────────────────────────────────────────────

def _run_bulk_job(job_id: str, csv_path: str, intent: str) -> None:
    try:
        raw = load_config()
        settings = load_settings_from_dict(raw)
        creds = get_credentials(
            credentials_path=get_credentials_path(),
            token_path=get_token_path(),
        )
        gmail = GmailClient(creds)
        generator = ReplyGenerator(settings)
        contact_store = ContactStore(path=get_contacts_path())
        sig_builder = SignatureBuilder(settings)
        _run_bulk_tracked(job_id, csv_path, intent, gmail, generator, contact_store, sig_builder)
    except Exception as exc:
        with _jobs_lock:
            _jobs[job_id]["log"].append({"level": "error", "message": f"Job failed: {exc}"})
            _jobs[job_id]["finished"] = True
    finally:
        try:
            os.unlink(csv_path)
        except OSError:
            pass


def _run_bulk_tracked(job_id, csv_path, intent, gmail, generator, contact_store, sig_builder):
    from bulk.bulk_sender import _load_csv, _process_row

    rows = _load_csv(csv_path)
    signature_html = sig_builder.build_html()

    with _jobs_lock:
        _jobs[job_id]["total"] = len(rows)

    for row in rows:
        try:
            _process_row(row, intent, gmail, generator, contact_store, signature_html)
            with _jobs_lock:
                _jobs[job_id]["done"] += 1
                _jobs[job_id]["log"].append({
                    "level": "success",
                    "message": f"Draft created for {row.name} <{row.email}>",
                })
        except Exception as exc:
            with _jobs_lock:
                _jobs[job_id]["failed"] += 1
                _jobs[job_id]["log"].append({
                    "level": "error",
                    "message": f"Failed for {row.email}: {exc}",
                })

    with _jobs_lock:
        _jobs[job_id]["finished"] = True
