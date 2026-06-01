"""
Structured rotating log writer for the Email Agent.

Writes JSON-formatted log lines to {DATA_DIR}/logs/agent.log with rotation
(5 MB × 3 backup files). Each line is a self-contained JSON object so the
log can be parsed with standard tools (grep, jq, the /debug dashboard).

Usage:
    from observability.log_writer import AgentLogger
    log = AgentLogger(path="/path/to/agent.log")
    log.info("email_skip", thread_id="abc", reason="newsletter")
    log.llm_call("classify", prompt="...", response="...", duration_ms=450, provider="gemini")
"""
import json
import logging
import logging.handlers
import os
import threading
from datetime import datetime
from pathlib import Path


class AgentLogger:
    """
    Thread-safe structured logger backed by a rotating JSON log file.

    In debug_mode=False (default): LLM prompts/responses are truncated to
    300 characters each to avoid filling the log with email content.
    In debug_mode=True: full prompts and responses are written.
    """

    def __init__(self, path: str, debug_mode: bool = False) -> None:
        self._debug_mode = debug_mode
        self._lock = threading.Lock()

        log_path = Path(path)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        self._logger = logging.getLogger("agent.structured")
        self._logger.setLevel(logging.DEBUG)
        self._logger.propagate = False

        if not self._logger.handlers:
            handler = logging.handlers.RotatingFileHandler(
                str(log_path),
                maxBytes=5 * 1024 * 1024,   # 5 MB
                backupCount=3,
                encoding="utf-8",
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(handler)

    def set_debug_mode(self, enabled: bool) -> None:
        self._debug_mode = enabled

    # ── Convenience methods ────────────────────────────────────────────────────

    def info(self, event: str, **kwargs) -> None:
        self._write("INFO", event, **kwargs)

    def debug(self, event: str, **kwargs) -> None:
        self._write("DEBUG", event, **kwargs)

    def warning(self, event: str, **kwargs) -> None:
        self._write("WARNING", event, **kwargs)

    def error(self, event: str, **kwargs) -> None:
        self._write("ERROR", event, **kwargs)

    # ── Specialised log methods ────────────────────────────────────────────────

    def log_email_step(
        self,
        thread_id: str,
        step: str,
        result: str,
        **details,
    ) -> None:
        """Log one step of the email processing pipeline."""
        self._write("INFO", "pipeline_step",
                    thread_id=thread_id, step=step, result=result, **details)

    def log_llm_call(
        self,
        call_type: str,
        prompt: str,
        response: str,
        duration_ms: int,
        provider: str,
    ) -> None:
        """Log an LLM API call. Truncates prompt/response unless debug_mode is on."""
        limit = None if self._debug_mode else 300
        self._write(
            "DEBUG" if not self._debug_mode else "INFO",
            "llm_call",
            call_type=call_type,
            provider=provider,
            duration_ms=duration_ms,
            prompt=prompt[:limit] if limit else prompt,
            response=response[:limit] if limit else response,
        )

    def log_skip(self, thread_id: str, sender: str, reason: str, **context) -> None:
        """Log why an email was skipped with full context."""
        self._write("INFO", "email_skip",
                    thread_id=thread_id, sender=sender, reason=reason, **context)

    def log_queued(self, thread_id: str, sender: str, priority: str, item_id: str) -> None:
        """Log that a reply was generated and queued for review."""
        self._write("INFO", "email_queued",
                    thread_id=thread_id, sender=sender,
                    priority=priority, item_id=item_id)

    def log_imap(self, event: str, **details) -> None:
        self._write("DEBUG", f"imap_{event}", **details)

    def log_token(self, event: str, **details) -> None:
        self._write("INFO", f"token_{event}", **details)

    # ── Internal ───────────────────────────────────────────────────────────────

    def _write(self, level: str, event: str, **kwargs) -> None:
        entry = {
            "ts": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "level": level,
            "event": event,
            **{k: v for k, v in kwargs.items() if v is not None},
        }
        line = json.dumps(entry, ensure_ascii=False, default=str)
        with self._lock:
            try:
                self._logger.info(line)
            except Exception:
                pass   # never crash the caller due to logging failure
