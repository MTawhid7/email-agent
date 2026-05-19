import json
import os
from pathlib import Path


def _data_dir() -> Path:
    """
    Resolve the writable data directory at call time (not import time) so that
    launcher.py can set EMAIL_AGENT_DATA_DIR before any Flask code imports this module.
    """
    env_val = os.environ.get("EMAIL_AGENT_DATA_DIR", "").strip()
    if env_val:
        return Path(env_val)
    return Path(__file__).parent.parent / "data"


def _config_path() -> Path:
    return _data_dir() / "config.json"


def _credentials_path() -> Path:
    return _data_dir() / "credentials" / "credentials.json"


def _token_path() -> Path:
    return _data_dir() / "credentials" / "token.json"


def _contacts_path() -> Path:
    return _data_dir() / "contacts" / "contacts.json"


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

def save_credentials_file(file_bytes: bytes) -> str:
    p = _credentials_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "wb") as f:
        f.write(file_bytes)
    return str(p)


def credentials_file_exists() -> bool:
    return _credentials_path().exists()


# ── Path accessors (used by daemon and routes) ─────────────────────────────────

def get_credentials_path() -> str:
    return str(_credentials_path())


def get_token_path() -> str:
    return str(_token_path())


def get_contacts_path() -> str:
    return str(_contacts_path())


def get_data_dir() -> str:
    return str(_data_dir())
