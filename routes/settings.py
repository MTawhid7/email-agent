import app as app_module
from pathlib import Path
from flask import Blueprint, jsonify, redirect, render_template, request, flash, url_for
from storage.app_config import load_config, save_config, config_exists, get_token_path

settings_bp = Blueprint("settings", __name__)


@settings_bp.route("/settings", methods=["GET", "POST"])
def settings():
    existing = load_config() if config_exists() else {}
    gmail_connected = Path(get_token_path()).exists()
    detected_email = existing.get("own_email", "")

    if request.method == "POST":
        try:
            poll_interval = int(request.form.get("poll_interval_seconds", "300"))
        except ValueError:
            poll_interval = 300

        from routes.setup import _parse_social_links_from_form
        updated = {
            "gemini_api_key": request.form.get("gemini_api_key", "").strip(),
            "gemini_model": request.form.get("gemini_model", "gemini-3.1-flash-lite").strip(),
            "gmail_credentials_path": existing.get("gmail_credentials_path", ""),
            "poll_interval_seconds": poll_interval,
            "persona_prompt": request.form.get("persona_prompt", "").strip(),
            "signature_name": request.form.get("signature_name", "").strip(),
            "signature_title": request.form.get("signature_title", "").strip(),
            "signature_company": request.form.get("signature_company", "").strip(),
            "signature_phone": request.form.get("signature_phone", "").strip(),
            "social_links": _parse_social_links_from_form(request.form),
            "auto_translate": request.form.get("auto_translate") == "true",
            "context_facts": request.form.get("context_facts", "").strip(),
            "own_email": existing.get("own_email", ""),   # auto-detected, not submitted by form
            "team_domain": request.form.get("team_domain", "").strip().lower().lstrip("@"),
            "fallback_api_key": request.form.get("fallback_api_key", "").strip(),
            "fallback_model": request.form.get("fallback_model", "llama-3.3-70b-versatile").strip(),
            "fallback_base_url": request.form.get("fallback_base_url", "https://api.groq.com/openai/v1").strip(),
            "ollama_enabled": request.form.get("ollama_enabled") == "true",
            "ollama_model": request.form.get("ollama_model", "llama3.2").strip(),
            "ollama_base_url": request.form.get("ollama_base_url", "http://localhost:11434").strip(),
        }

        if not updated["gemini_api_key"]:
            flash("Gemini API key is required.", "error")
            return render_template("settings.html", config=updated, gmail_connected=gmail_connected, detected_email=detected_email)
        if not updated["signature_name"]:
            flash("Your name is required.", "error")
            return render_template("settings.html", config=updated, gmail_connected=gmail_connected, detected_email=detected_email)

        save_config(updated)

        # Restart daemon if it was running so it picks up new settings
        was_running = app_module.daemon.is_running
        if was_running:
            app_module.daemon.stop()
            import time
            time.sleep(1)
            app_module.daemon.start()

        flash("Settings saved successfully.", "success")
        return redirect(url_for("settings.settings"))

    # GET request fallback to .env for social links if not set
    if not existing.get("social_links"):
        import os
        from dotenv import load_dotenv
        load_dotenv()
        migrated = []
        for key, label in [
            ("SIGNATURE_LINKEDIN", "LinkedIn"),
            ("SIGNATURE_GITHUB", "GitHub"),
            ("SIGNATURE_WEBSITE", "Website"),
        ]:
            val = os.getenv(key, "").strip()
            if val:
                migrated.append({"label": label, "url": val})
        if migrated:
            existing["social_links"] = migrated

    return render_template("settings.html", config=existing, gmail_connected=gmail_connected, detected_email=detected_email)


@settings_bp.route("/api/auth/switch", methods=["POST"])
def auth_switch():
    """
    Stop the daemon, delete the OAuth token, and start a fresh OAuth flow.
    Works for both 'switch account' (deletes existing token) and
    'connect Gmail' (no token to delete) cases.
    """
    from routes.setup import start_oauth_thread
    app_module.daemon.stop()
    token = Path(get_token_path())
    if token.exists():
        token.unlink()
    start_oauth_thread()
    return jsonify({"ok": True})
