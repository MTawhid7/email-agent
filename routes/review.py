from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

import app as app_module
from agent.queue import review_queue
from gmail.auth import get_credentials
from gmail.client import GmailClient
from storage.app_config import get_credentials_path, get_token_path

review_bp = Blueprint("review", __name__)


def _gmail() -> GmailClient:
    creds = get_credentials(
        credentials_path=get_credentials_path(),
        token_path=get_token_path(),
    )
    return GmailClient(creds)


@review_bp.route("/review")
def review():
    items = review_queue.all()
    return render_template("review.html", items=items)


@review_bp.route("/review/<item_id>/send", methods=["POST"])
def review_send(item_id: str):
    item = review_queue.get(item_id)
    if not item:
        return redirect(url_for("review.review"))

    body_html = request.form.get("body_html", item["body_html"])
    _gmail().send_message(
        to=item["sender_email"],
        subject=item["subject"],
        body_html=body_html,
        thread_id=item["thread_id"],
        in_reply_to=item["message_id_header"],
        references=item["message_id_header"],
    )
    review_queue.remove(item_id)
    app_module.daemon.resolve_review_item(item_id, "sent")
    return redirect(url_for("review.review"))


@review_bp.route("/review/<item_id>/draft", methods=["POST"])
def review_draft(item_id: str):
    item = review_queue.get(item_id)
    if not item:
        return redirect(url_for("review.review"))

    body_html = request.form.get("body_html", item["body_html"])
    _gmail().create_draft(
        to=item["sender_email"],
        subject=item["subject"],
        body_html=body_html,
        thread_id=item["thread_id"],
        in_reply_to=item["message_id_header"],
        references=item["message_id_header"],
    )
    review_queue.remove(item_id)
    app_module.daemon.resolve_review_item(item_id, "sent")
    return redirect(url_for("review.review"))


@review_bp.route("/review/<item_id>/discard", methods=["POST"])
def review_discard(item_id: str):
    review_queue.remove(item_id)
    app_module.daemon.resolve_review_item(item_id, "discarded")
    return redirect(url_for("review.review"))


@review_bp.route("/review/send-all", methods=["POST"])
def review_send_all():
    items = list(review_queue.all())
    if not items:
        return redirect(url_for("review.review"))

    gmail = _gmail()
    sent = 0
    failed = 0

    for snapshot in items:
        item = review_queue.get(snapshot["id"])
        if not item:
            continue
        try:
            gmail.send_message(
                to=item["sender_email"],
                subject=item["subject"],
                body_html=item["body_html"],
                thread_id=item.get("thread_id") or None,
                in_reply_to=item.get("message_id_header") or None,
                references=item.get("message_id_header") or None,
            )
            review_queue.remove(item["id"])
            app_module.daemon.resolve_review_item(item["id"], "sent")
            sent += 1
        except Exception:
            failed += 1

    if failed:
        flash(f"Sent {sent} email(s). {failed} failed — check the Debug log.", "error")
    else:
        flash(f"Sent {sent} email(s) successfully.", "success")

    return redirect(url_for("review.review"))


@review_bp.route("/api/review/count")
def review_count():
    return jsonify({"count": review_queue.count()})
