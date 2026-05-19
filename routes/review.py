from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from agent.review_queue import review_queue
from config import load_settings_from_dict
from gmail_client.auth import get_credentials
from gmail_client.gmail_client import GmailClient
from storage.app_config import get_credentials_path, get_token_path, load_config

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
    return redirect(url_for("review.review"))


@review_bp.route("/review/<item_id>/discard", methods=["POST"])
def review_discard(item_id: str):
    review_queue.remove(item_id)
    return redirect(url_for("review.review"))


@review_bp.route("/api/review/count")
def review_count():
    return jsonify({"count": review_queue.count()})
