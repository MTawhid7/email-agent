import json
import os
import sys
from pathlib import Path


def _data_dir() -> Path:
    """
    Resolve the writable data directory at call time so that launcher.py can set
    EMAIL_AGENT_DATA_DIR before any Flask code imports this module.
    """
    env_val = os.environ.get("EMAIL_AGENT_DATA_DIR", "").strip()
    if env_val:
        return Path(env_val)
    return Path(__file__).parent.parent / "data"


def _config_path() -> Path:
    return _data_dir() / "config.json"


def _user_credentials_path() -> Path:
    """Path where a manually uploaded credentials.json would be stored."""
    return _data_dir() / "credentials" / "credentials.json"


def _token_path() -> Path:
    return _data_dir() / "credentials" / "token.json"


def _contacts_path() -> Path:
    return _data_dir() / "contacts" / "contacts.json"


def _bundled_credentials_path() -> Path | None:
    """
    In a PyInstaller frozen build, credentials.json is bundled read-only inside
    sys._MEIPASS. Returns its path if it exists there, otherwise None.
    """
    if getattr(sys, "frozen", False):
        bundled = Path(sys._MEIPASS) / "credentials" / "credentials.json"  # type: ignore[attr-defined]
        if bundled.exists():
            return bundled
    # Development fallback: project-local credentials/ directory
    dev_path = Path(__file__).parent.parent / "credentials" / "credentials.json"
    if dev_path.exists():
        return dev_path
    return None


# ── Config file ────────────────────────────────────────────────────────────────

def config_exists() -> bool:
    p = _config_path()
    return p.exists() and p.stat().st_size > 0


def load_config() -> dict:
    with open(_config_path(), "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(data: dict) -> None:
    """Write config atomically: write to .tmp then rename."""
    p = _config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(p)


def merge_and_save_config(partial: dict) -> None:
    """Merge partial dict into existing config (or create fresh) and save."""
    existing = {}
    if config_exists():
        try:
            existing = load_config()
        except Exception:
            pass
    existing.update(partial)
    save_config(existing)


# ── Credentials file ───────────────────────────────────────────────────────────

def credentials_file_exists() -> bool:
    """True if a credentials.json is available (bundled or uploaded)."""
    return get_credentials_path() is not None


def save_credentials_file(file_bytes: bytes) -> str:
    """Save a manually uploaded credentials.json. Returns the path."""
    p = _user_credentials_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "wb") as f:
        f.write(file_bytes)
    return str(p)


# ── Path accessors ─────────────────────────────────────────────────────────────

def get_credentials_path() -> str | None:
    """
    Returns the path to credentials.json, preferring the bundled version.
    Returns None if no credentials file is found anywhere.
    """
    bundled = _bundled_credentials_path()
    if bundled:
        return str(bundled)
    user = _user_credentials_path()
    if user.exists():
        return str(user)
    return None


def get_token_path() -> str:
    """Token is always stored in the writable DATA_DIR, never bundled."""
    return str(_token_path())


def get_contacts_path() -> str:
    return str(_contacts_path())


def get_data_dir() -> str:
    return str(_data_dir())


# ── Templates ──────────────────────────────────────────────────────────────────

def get_templates_path() -> str:
    return str(_data_dir() / "templates.json")


def load_templates() -> list[dict]:
    p = Path(get_templates_path())
    if not p.exists():
        _seed_default_templates(p)
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def save_templates(templates: list[dict]) -> None:
    p = Path(get_templates_path())
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(templates, f, indent=2, ensure_ascii=False)


def _seed_default_templates(path: Path) -> None:
    import uuid as _uuid
    defaults = [
        {"id": str(_uuid.uuid4()), "category": "Acknowledgement", "name": "Received & reviewing",
         "body": "Thank you for reaching out. I've received your message and will review it shortly. I'll get back to you by [date]."},
        {"id": str(_uuid.uuid4()), "category": "Acknowledgement", "name": "Out of office",
         "body": "Thank you for your email. I'm currently out of the office until [date]. For urgent matters, please contact [name] at [email]."},
        {"id": str(_uuid.uuid4()), "category": "Meetings", "name": "Confirm meeting",
         "body": "Happy to connect. I'm available [day] at [time] or [alternative]. Please let me know which works best."},
        {"id": str(_uuid.uuid4()), "category": "Meetings", "name": "Decline meeting",
         "body": "Thank you for the invitation. Unfortunately I'm unavailable at that time. Could we explore [alternative date or format]?"},
        {"id": str(_uuid.uuid4()), "category": "Meetings", "name": "Reschedule request",
         "body": "I need to reschedule our meeting. Would [new day and time] work for you?"},
        {"id": str(_uuid.uuid4()), "category": "Business", "name": "Information request response",
         "body": "Thank you for your inquiry. I've included the relevant information below. Please don't hesitate to follow up if you have further questions."},
        {"id": str(_uuid.uuid4()), "category": "Business", "name": "Proposal acknowledgement",
         "body": "Thank you for sending over your proposal. I've had a chance to review it and would like to discuss a few points further."},
        {"id": str(_uuid.uuid4()), "category": "Business", "name": "Approval",
         "body": "I've reviewed the details and am happy to proceed. Please go ahead as discussed."},
        {"id": str(_uuid.uuid4()), "category": "Business", "name": "Decline / not interested",
         "body": "Thank you for thinking of us. After careful consideration, we won't be moving forward at this time. We appreciate the opportunity."},
        {"id": str(_uuid.uuid4()), "category": "Support", "name": "Issue acknowledged",
         "body": "Thank you for bringing this to our attention. I've escalated this to the relevant team and will keep you updated on the progress."},
        {"id": str(_uuid.uuid4()), "category": "Support", "name": "Issue resolved",
         "body": "I'm pleased to let you know that the issue has been resolved. Please don't hesitate to reach out if you experience anything further."},
        {"id": str(_uuid.uuid4()), "category": "Support", "name": "Delay / apology",
         "body": "I apologise for the delay in responding. Thank you for your patience — I'll address this right away."},
        {"id": str(_uuid.uuid4()), "category": "Networking", "name": "Introduction response",
         "body": "Great to connect! I'd love to learn more about what you're working on. Happy to schedule a brief call if that works for you."},
        {"id": str(_uuid.uuid4()), "category": "Networking", "name": "Referral / recommendation thanks",
         "body": "Thank you so much for the introduction and kind words. I really appreciate it."},
        {"id": str(_uuid.uuid4()), "category": "Networking", "name": "Job application acknowledgement",
         "body": "Thank you for your application. We've received it and will be in touch within [timeframe]."},
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(defaults, f, indent=2, ensure_ascii=False)
