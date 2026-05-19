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
