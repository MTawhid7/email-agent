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
    )
    _store().upsert(profile)
    return redirect(url_for("contacts.contacts"))


@contacts_bp.route("/contacts/<path:email>", methods=["DELETE"])
def contacts_delete(email: str):
    store = _store()
    # Load, remove, save manually since ContactStore has no delete method
    data = store._load()
    data.pop(email.lower(), None)
    store._save(data)
    return jsonify({"ok": True})
