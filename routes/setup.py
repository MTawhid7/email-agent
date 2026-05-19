import threading
from typing import Optional

from flask import (
    Blueprint,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from gmail_client.auth import get_credentials
from storage.app_config import (
    credentials_file_exists,
    get_credentials_path,
    get_token_path,
    merge_and_save_config,
    save_credentials_file,
    save_config,
    load_config,
    config_exists,
)

setup_bp = Blueprint("setup", __name__, url_prefix="/setup")

# Shared OAuth state — only one setup at a time (single user per machine)
_oauth_state: dict = {"done": False, "error": None, "thread": None}


@setup_bp.route("/step1", methods=["GET", "POST"])
def step1():
    if request.method == "POST":
        api_key = request.form.get("gemini_api_key", "").strip()
        model = request.form.get("gemini_model", "gemini-3.1-flash-lite").strip()
        if not api_key:
            return render_template("setup/step1.html", error="API key is required.")
        merge_and_save_config({"gemini_api_key": api_key, "gemini_model": model})
        return redirect(url_for("setup.step2"))
    return render_template("setup/step1.html", error=None)


@setup_bp.route("/step2", methods=["GET", "POST"])
def step2():
    if request.method == "POST":
        file = request.files.get("credentials_file")
        if not file or file.filename == "":
            return render_template("setup/step2.html", error="Please select a credentials.json file.")
        content = file.read()
        if len(content) < 10:
            return render_template("setup/step2.html", error="The uploaded file appears to be empty.")
        creds_path = save_credentials_file(content)
        merge_and_save_config({"gmail_credentials_path": creds_path})
        return redirect(url_for("setup.step3"))
    return render_template("setup/step2.html", error=None)


@setup_bp.route("/step3", methods=["GET", "POST"])
def step3():
    if request.method == "POST":
        fields = {
            "signature_name": request.form.get("signature_name", "").strip(),
            "signature_title": request.form.get("signature_title", "").strip(),
            "signature_company": request.form.get("signature_company", "").strip(),
            "signature_phone": request.form.get("signature_phone", "").strip(),
            "signature_linkedin": request.form.get("signature_linkedin", "").strip(),
            "signature_github": request.form.get("signature_github", "").strip(),
            "signature_website": request.form.get("signature_website", "").strip(),
        }
        if not fields["signature_name"]:
            return render_template("setup/step3.html", error="Your name is required.", **fields)
        merge_and_save_config(fields)
        return redirect(url_for("setup.step4"))

    existing = load_config() if config_exists() else {}
    return render_template(
        "setup/step3.html",
        error=None,
        signature_name=existing.get("signature_name", ""),
        signature_title=existing.get("signature_title", ""),
        signature_company=existing.get("signature_company", ""),
        signature_phone=existing.get("signature_phone", ""),
        signature_linkedin=existing.get("signature_linkedin", ""),
        signature_github=existing.get("signature_github", ""),
        signature_website=existing.get("signature_website", ""),
    )


@setup_bp.route("/step4", methods=["GET", "POST"])
def step4():
    if request.method == "POST":
        persona = request.form.get("persona_prompt", "").strip()
        poll_interval = request.form.get("poll_interval_seconds", "300").strip()

        if not persona:
            return render_template("setup/step4.html", error="Persona instructions are required.", persona_prompt="")

        try:
            poll_interval = int(poll_interval)
        except ValueError:
            poll_interval = 300

        merge_and_save_config({
            "persona_prompt": persona,
            "poll_interval_seconds": poll_interval,
        })

        # Start OAuth flow in background thread
        _oauth_state["done"] = False
        _oauth_state["error"] = None

        def run_oauth():
            try:
                get_credentials(
                    credentials_path=get_credentials_path(),
                    token_path=get_token_path(),
                )
                _oauth_state["done"] = True
            except Exception as exc:
                _oauth_state["error"] = str(exc)

        t = threading.Thread(target=run_oauth, daemon=True)
        _oauth_state["thread"] = t
        t.start()

        return render_template("setup/step4.html", waiting=True, error=None, persona_prompt=persona)

    existing = load_config() if config_exists() else {}
    return render_template(
        "setup/step4.html",
        waiting=False,
        error=None,
        persona_prompt=existing.get("persona_prompt", ""),
    )


@setup_bp.route("/api/oauth_status")
def oauth_status():
    """Polled by step4.html to detect when Gmail OAuth completes."""
    return jsonify({
        "done": _oauth_state["done"],
        "error": _oauth_state["error"],
    })
