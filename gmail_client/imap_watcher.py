"""
IMAP IDLE watcher — real-time inbox notification without polling.

Maintains a persistent TLS connection to imap.gmail.com and issues the
IDLE command (RFC 2177).  The server sends an unsolicited `* N EXISTS`
response the moment a new message arrives in INBOX, triggering the
processing pipeline immediately instead of after the next poll interval.

Token refresh:
  TokenManager calls on_token_refreshed() when a new access token is
  issued.  The watcher reconnects with the fresh XOAUTH2 credentials
  before re-entering IDLE.

Graceful degradation:
  If IMAP access is unavailable (disabled by admin, wrong credentials,
  network issue) the watcher sets wake_event on a 60-second heartbeat
  instead.  The processing loop continues to work as a fast poller.

Requirements: imapclient>=3.0.0  (pure Python, no native extensions)
"""
import base64
import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

_IMAP_HOST = "imap.gmail.com"
_IDLE_TIMEOUT_SECONDS = 1680    # 28 min — Gmail forces DONE after 29 min
_FALLBACK_INTERVAL_SECONDS = 60 # seconds between wake_event fires when degraded
_RECONNECT_BACKOFF = [1, 2, 4, 8, 15, 30, 60]  # seconds between reconnect attempts


def _build_xoauth2(email: str, access_token: str) -> str:
    raw = f"user={email}\x01auth=Bearer {access_token}\x01\x01"
    return base64.b64encode(raw.encode()).decode()


class ImapIdleWatcher:
    """
    Runs in its own daemon thread.  Fires wake_event whenever Gmail
    signals that the INBOX has new messages.
    """

    def __init__(
        self,
        token_manager,           # TokenManager instance
        wake_event: threading.Event,
        own_email: str,
    ) -> None:
        self._token_manager = token_manager
        self._wake_event = wake_event
        self._own_email = own_email
        self._stop_event = threading.Event()
        self._reconnect_flag = threading.Event()  # set by on_token_refreshed
        self._thread: Optional[threading.Thread] = None
        self._degraded = False

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the watcher in a background daemon thread."""
        if self._token_manager:
            self._token_manager.register_refresh_callback(self.on_token_refreshed)
        self._thread = threading.Thread(
            target=self._run, name="ImapIdleWatcher", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the watcher to exit."""
        self._stop_event.set()
        self._wake_event.set()  # unblock any waiter immediately

    def on_token_refreshed(self, creds) -> None:
        """Called by TokenManager when a new token is available."""
        self._reconnect_flag.set()

    # ── Main loop ──────────────────────────────────────────────────────────────

    def _run(self) -> None:
        if not self._own_email:
            logger.warning(
                "ImapIdleWatcher: own_email not set — falling back to timed polling."
            )
            self._degraded = True
            self._fallback_loop()
            return

        backoff_index = 0
        while not self._stop_event.is_set():
            try:
                self._idle_session()
                backoff_index = 0  # successful session resets back-off
            except Exception as exc:
                if self._stop_event.is_set():
                    break
                wait = _RECONNECT_BACKOFF[min(backoff_index, len(_RECONNECT_BACKOFF) - 1)]
                logger.warning(
                    "IMAP IDLE session ended (%s) — reconnecting in %ds", exc, wait
                )
                self._stop_event.wait(timeout=wait)
                backoff_index += 1

    def _idle_session(self) -> None:
        """
        Establish one IMAP session, enter IDLE mode, and loop until
        the session ends (token expiry, 28-min timeout, or stop signal).
        """
        try:
            import imapclient
        except ImportError:
            logger.error(
                "imapclient is not installed. "
                "Run `pip install imapclient` then restart the agent."
            )
            self._degraded = True
            self._fallback_loop()
            return

        creds = self._token_manager.get_credentials()
        xoauth2 = _build_xoauth2(self._own_email, creds.token)

        client = imapclient.IMAPClient(_IMAP_HOST, ssl=True)
        try:
            client.oauth2_login(self._own_email, xoauth2)
        except Exception as exc:
            client.logout()
            # If IMAP is permanently unavailable (e.g. disabled by admin),
            # degrade gracefully rather than reconnect-looping forever.
            err = str(exc).lower()
            if "authentication failed" in err or "invalid credentials" in err:
                logger.warning(
                    "IMAP authentication failed (%s). "
                    "Check that IMAP is enabled in Gmail settings. "
                    "Falling back to %ds polling.",
                    exc, _FALLBACK_INTERVAL_SECONDS,
                )
                self._degraded = True
                self._fallback_loop()
                return
            raise

        try:
            client.select_folder("INBOX", readonly=True)
            logger.info("IMAP IDLE watcher connected — watching INBOX for new mail.")

            while not self._stop_event.is_set():
                # Check if token was refreshed while we were idle
                if self._reconnect_flag.is_set():
                    self._reconnect_flag.clear()
                    logger.debug("Token refreshed — reconnecting IMAP session.")
                    return  # outer _run() will reconnect with fresh token

                client.idle()
                responses = client.idle_check(timeout=_IDLE_TIMEOUT_SECONDS)
                client.idle_done()

                if self._stop_event.is_set():
                    break

                # Any response containing EXISTS means new messages arrived
                if responses and any(b"EXISTS" in str(r).encode() for r in responses):
                    logger.debug("IMAP IDLE: new message signal received.")
                    self._wake_event.set()

                # Re-select INBOX to keep the session alive
                client.select_folder("INBOX", readonly=True)

        finally:
            try:
                client.logout()
            except Exception:
                pass

    def _fallback_loop(self) -> None:
        """
        When IMAP is unavailable, fire wake_event every 60 seconds so
        the processing loop still runs as a fast poller.
        """
        logger.info(
            "IMAP IDLE degraded to %ds polling fallback.", _FALLBACK_INTERVAL_SECONDS
        )
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=_FALLBACK_INTERVAL_SECONDS)
            if not self._stop_event.is_set():
                self._wake_event.set()
