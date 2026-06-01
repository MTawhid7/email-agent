"""
Debug dashboard — /debug

Shows system health, processing statistics, recent email traces,
and the live log tail. Intended for development and troubleshooting;
accessible only from localhost.
"""
import json
import os
from pathlib import Path

import app as app_module
from flask import Blueprint, jsonify, render_template
from storage.app_config import get_debug_state_path, get_log_path, get_traces_path

debug_bp = Blueprint("debug", __name__)

_LOG_TAIL_LINES = 100   # lines shown in the log viewer panel


@debug_bp.route("/debug")
def debug():
    return render_template("debug.html")


@debug_bp.route("/api/debug/state")
def debug_state():
    """System health snapshot from StateManager."""
    daemon = app_module.daemon
    state_path = Path(get_debug_state_path())

    state = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Live fields always come from the daemon directly
    state["is_running"] = daemon.is_running
    state["review_queue_size"] = app_module.review_queue.count()

    return jsonify(state)


@debug_bp.route("/api/debug/traces")
def debug_traces():
    """Recent email processing traces from TraceStore."""
    traces_path = Path(get_traces_path())
    if traces_path.exists():
        try:
            return jsonify(json.loads(traces_path.read_text(encoding="utf-8")))
        except Exception:
            pass
    return jsonify([])


@debug_bp.route("/api/debug/logs")
def debug_logs():
    """Last N lines from the structured log file, newest first."""
    log_path = Path(get_log_path())
    if not log_path.exists():
        return jsonify([])

    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = lines[-_LOG_TAIL_LINES:] if len(lines) > _LOG_TAIL_LINES else lines
        parsed = []
        for line in reversed(tail):
            line = line.strip()
            if not line:
                continue
            try:
                parsed.append(json.loads(line))
            except Exception:
                parsed.append({"ts": "", "level": "RAW", "event": line})
        return jsonify(parsed)
    except Exception as exc:
        return jsonify([{"level": "ERROR", "event": f"Failed to read log: {exc}"}])
