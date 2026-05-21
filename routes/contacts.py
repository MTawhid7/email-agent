import csv
import io

from flask import Blueprint, jsonify, redirect, render_template, request, url_for
from contacts.contact_store import ContactProfile, ContactStore
from storage.app_config import get_contacts_path

contacts_bp = Blueprint("contacts", __name__)


def _store() -> ContactStore:
    return ContactStore(path=get_contacts_path())


@contacts_bp.route("/contacts", methods=["GET"])
def contacts():
    all_contacts = _store().list_all()
    return render_template("contacts.html", contacts=all_contacts)


@contacts_bp.route("/contacts", methods=["POST"])
def contacts_add():
    email = request.form.get("email", "").strip()
    if not email:
        return redirect(url_for("contacts.contacts"))

    profile = ContactProfile(
        email=email,
        name=request.form.get("name", "").strip(),
        company=request.form.get("company", "").strip(),
        relationship_type=request.form.get("relationship_type", "").strip(),
        notes=request.form.get("notes", "").strip(),
        tone=request.form.get("tone", "").strip(),
        is_teammate=request.form.get("is_teammate") == "true",
    )
    _store().upsert(profile)
    return redirect(url_for("contacts.contacts"))


@contacts_bp.route("/contacts/import", methods=["POST"])
def contacts_import():
    file = request.files.get("csv_file")
    if not file or file.filename == "":
        return redirect(url_for("contacts.contacts"))

    store = _store()
    content = file.read().decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(content))
    for row in reader:
        email = row.get("email", "").strip()
        if not email:
            continue
        raw_teammate = row.get("is_teammate", "").strip().lower()
        profile = ContactProfile(
            email=email,
            name=row.get("name", "").strip(),
            company=row.get("company", "").strip(),
            relationship_type=row.get("relationship_type", "").strip(),
            notes=row.get("notes", "").strip(),
            tone=row.get("tone", "").strip(),
            is_teammate=raw_teammate in ("true", "1", "yes"),
        )
        store.upsert(profile)
    return redirect(url_for("contacts.contacts"))


@contacts_bp.route("/contacts/<path:email>", methods=["DELETE"])
def contacts_delete(email: str):
    store = _store()
    # Load, remove, save manually since ContactStore has no delete method
    data = store._load()
    data.pop(email.lower(), None)
    store._save(data)
    return jsonify({"ok": True})
