import os
import tempfile
import threading
import uuid
from typing import Optional

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

import app as app_module
from bulk.bulk_sender import run_bulk
from ai.reply_generator import ReplyGenerator
from contacts.contact_store import ContactStore
from gmail_client.auth import get_credentials
from gmail_client.gmail_client import GmailClient
from signature.signature import SignatureBuilder
from config import load_settings_from_dict
from storage.app_config import (
    get_contacts_path,
    get_credentials_path,
    get_token_path,
    load_config,
)

bulk_bp = Blueprint("bulk", __name__)

# In-memory job tracker: {job_id: {total, done, failed, log: []}}
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


@bulk_bp.route("/bulk", methods=["GET"])
def bulk():
    job_id = request.args.get("job")
    return render_template("bulk.html", job_id=job_id)


@bulk_bp.route("/bulk", methods=["POST"])
def bulk_submit():
    file = request.files.get("csv_file")
    intent = request.form.get("intent", "").strip()

    if not file or file.filename == "":
        return render_template("bulk.html", job_id=None, error="Please upload a CSV file.")
    if not intent:
        return render_template("bulk.html", job_id=None, error="Please enter an email intent.")

    # Save CSV to a temp file so the background thread can read it
    suffix = ".csv"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    file.save(tmp.name)
    tmp.close()

    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {"total": 0, "done": 0, "failed": 0, "log": [], "finished": False}

    t = threading.Thread(
        target=_run_bulk_job,
        args=(job_id, tmp.name, intent),
        daemon=True,
    )
    t.start()

    return redirect(url_for("bulk.bulk", job=job_id))


@bulk_bp.route("/api/bulk/status/<job_id>")
def bulk_status(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


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

        # Wrap run_bulk to capture per-row progress
        _run_bulk_tracked(job_id, csv_path, intent, gmail, generator, contact_store, sig_builder, settings)
    except Exception as exc:
        with _jobs_lock:
            _jobs[job_id]["log"].append({"level": "error", "message": f"Job failed: {exc}"})
            _jobs[job_id]["finished"] = True
    finally:
        try:
            os.unlink(csv_path)
        except OSError:
            pass


def _run_bulk_tracked(job_id, csv_path, intent, gmail, generator, contact_store, sig_builder, settings):
    import csv
    from bulk.bulk_sender import _load_csv, _process_row

    rows = _load_csv(csv_path)
    total = len(rows)

    with _jobs_lock:
        _jobs[job_id]["total"] = total

    from signature.signature import SignatureBuilder
    signature_html = sig_builder.build_html()

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
