from flask import Blueprint, jsonify, render_template
import app as app_module

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")


@dashboard_bp.route("/api/status")
def status():
    return jsonify(app_module.daemon.get_status())


@dashboard_bp.route("/api/agent/start", methods=["POST"])
def agent_start():
    app_module.daemon.start()
    return jsonify({"ok": True})


@dashboard_bp.route("/api/agent/stop", methods=["POST"])
def agent_stop():
    app_module.daemon.stop()
    return jsonify({"ok": True})
