import uuid

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

from storage.app_config import load_templates, save_templates

templates_bp = Blueprint("templates", __name__)


@templates_bp.route("/templates")
def templates():
    all_templates = load_templates()
    categories = sorted({t["category"] for t in all_templates})
    return render_template("templates_page.html", templates=all_templates, categories=categories)


@templates_bp.route("/templates", methods=["POST"])
def templates_add():
    name = request.form.get("name", "").strip()
    category = request.form.get("category", "").strip() or "General"
    body = request.form.get("body", "").strip()

    if not name or not body:
        return redirect(url_for("templates.templates"))

    all_templates = load_templates()
    all_templates.append({"id": str(uuid.uuid4()), "category": category, "name": name, "body": body})
    save_templates(all_templates)
    return redirect(url_for("templates.templates"))


@templates_bp.route("/templates/<template_id>", methods=["POST"])
def templates_update(template_id: str):
    all_templates = load_templates()
    for t in all_templates:
        if t["id"] == template_id:
            t["name"] = request.form.get("name", t["name"]).strip()
            t["category"] = request.form.get("category", t["category"]).strip()
            t["body"] = request.form.get("body", t["body"]).strip()
            break
    save_templates(all_templates)
    return redirect(url_for("templates.templates"))


@templates_bp.route("/templates/<template_id>/delete", methods=["POST"])
def templates_delete(template_id: str):
    all_templates = [t for t in load_templates() if t["id"] != template_id]
    save_templates(all_templates)
    return redirect(url_for("templates.templates"))
