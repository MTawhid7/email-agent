import app as app_module
from flask import Blueprint, redirect, render_template, request, flash, url_for
from storage.app_config import load_config, save_config, config_exists

settings_bp = Blueprint("settings", __name__)


@settings_bp.route("/settings", methods=["GET", "POST"])
def settings():
    existing = load_config() if config_exists() else {}

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
        }

        if not updated["gemini_api_key"]:
            flash("Gemini API key is required.", "error")
            return render_template("settings.html", config=updated)
        if not updated["signature_name"]:
            flash("Your name is required.", "error")
            return render_template("settings.html", config=updated)

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

    return render_template("settings.html", config=existing)
