import threading

from flask import (
    Blueprint,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from gmail_client.auth import get_credentials
from storage.app_config import (
    config_exists,
    credentials_file_exists,
    get_credentials_path,
    get_token_path,
    load_config,
    merge_and_save_config,
    save_credentials_file,
)

setup_bp = Blueprint("setup", __name__, url_prefix="/setup")

# Shared OAuth state — one at a time (single user per machine)
_oauth_state: dict = {"done": False, "error": None, "thread": None}


def start_oauth_thread() -> None:
    """Start Gmail OAuth flow in the background. Updates _oauth_state when done."""
    _oauth_state["done"] = False
    _oauth_state["error"] = None

    def run():
        try:
            get_credentials(
                credentials_path=get_credentials_path(),
                token_path=get_token_path(),
            )
            _oauth_state["done"] = True
        except Exception as exc:
            _oauth_state["error"] = str(exc)

    t = threading.Thread(target=run, daemon=True)
    _oauth_state["thread"] = t
    t.start()


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
    # Auto-skip: credentials are bundled — users never need to upload anything
    if credentials_file_exists():
        creds_path = get_credentials_path()
        merge_and_save_config({"gmail_credentials_path": creds_path})
        return redirect(url_for("setup.step3"))

    # Fallback for development: allow manual upload
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
        # Parse dynamic social links from indexed form fields
        social_links = _parse_social_links_from_form(request.form)
        fields = {
            "signature_name": request.form.get("signature_name", "").strip(),
            "signature_title": request.form.get("signature_title", "").strip(),
            "signature_company": request.form.get("signature_company", "").strip(),
            "signature_phone": request.form.get("signature_phone", "").strip(),
            "social_links": social_links,
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
        social_links=existing.get("social_links", []),
    )


@setup_bp.route("/step4", methods=["GET", "POST"])
def step4():
    if request.method == "POST":
        persona = request.form.get("persona_prompt", "").strip()
        poll_interval = request.form.get("poll_interval_seconds", "300").strip()

        if not persona:
            return render_template("setup/step4.html", error="Persona instructions are required.",
                                   persona_prompt="", waiting=False)
        try:
            poll_interval = int(poll_interval)
        except ValueError:
            poll_interval = 300

        merge_and_save_config({
            "persona_prompt": persona,
            "poll_interval_seconds": poll_interval,
        })

        start_oauth_thread()
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
    """Polled by step4 and the dashboard reconnect flow."""
    return jsonify({
        "done": _oauth_state["done"],
        "error": _oauth_state["error"],
    })


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_social_links_from_form(form) -> list[dict]:
    """
    Extract social links from indexed form fields:
      social_label_0, social_url_0, social_label_1, social_url_1, ...
    """
    links = []
    i = 0
    while True:
        label = form.get(f"social_label_{i}", "").strip()
        url = form.get(f"social_url_{i}", "").strip()
        if not label and not url:
            break
        if label and url:
            links.append({"label": label, "url": url})
        i += 1
        if i > 20:  # safety cap
            break
    return links
