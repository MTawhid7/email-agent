import os
from dataclasses import dataclass

from dotenv import load_dotenv

from exceptions import ConfigError


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str
    gemini_model: str
    gmail_credentials_path: str
    poll_interval_seconds: int
    persona_prompt: str
    signature_name: str
    signature_title: str
    signature_company: str
    signature_phone: str
    signature_linkedin: str
    signature_github: str
    signature_website: str


def _require(key: str) -> str:
    value = os.getenv(key, "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable: {key}")
    return value


def _optional(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def load_settings_from_dict(data: dict) -> Settings:
    """
    Populate a Settings instance from a plain dict (e.g. parsed from config.json).
    Raises ConfigError for missing required fields, matching load_settings() behaviour.
    """
    def require(key: str) -> str:
        value = str(data.get(key, "")).strip()
        if not value:
            raise ConfigError(f"Missing required config field: {key}")
        return value

    def optional(key: str, default: str = "") -> str:
        return str(data.get(key, default)).strip()

    try:
        poll_interval = int(data.get("poll_interval_seconds", 300))
    except (ValueError, TypeError):
        raise ConfigError("poll_interval_seconds must be a valid integer.")

    return Settings(
        gemini_api_key=require("gemini_api_key"),
        gemini_model=require("gemini_model"),
        gmail_credentials_path=require("gmail_credentials_path"),
        poll_interval_seconds=poll_interval,
        persona_prompt=require("persona_prompt"),
        signature_name=require("signature_name"),
        signature_title=optional("signature_title"),
        signature_company=optional("signature_company"),
        signature_phone=optional("signature_phone"),
        signature_linkedin=optional("signature_linkedin"),
        signature_github=optional("signature_github"),
        signature_website=optional("signature_website"),
    )


def load_settings() -> Settings:
    load_dotenv()

    try:
        poll_interval = int(os.getenv("POLL_INTERVAL_SECONDS", "300"))
    except ValueError:
        raise ConfigError("POLL_INTERVAL_SECONDS must be a valid integer.")

    return Settings(
        gemini_api_key=_require("GEMINI_API_KEY"),
        gemini_model=_require("GEMINI_MODEL"),
        gmail_credentials_path=_require("GMAIL_CREDENTIALS_PATH"),
        poll_interval_seconds=poll_interval,
        persona_prompt=_require("PERSONA_PROMPT"),
        signature_name=_require("SIGNATURE_NAME"),
        signature_title=_optional("SIGNATURE_TITLE"),
        signature_company=_optional("SIGNATURE_COMPANY"),
        signature_phone=_optional("SIGNATURE_PHONE"),
        signature_linkedin=_optional("SIGNATURE_LINKEDIN"),
        signature_github=_optional("SIGNATURE_GITHUB"),
        signature_website=_optional("SIGNATURE_WEBSITE"),
    )
