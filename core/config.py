import os
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv

from core.exceptions import ConfigError


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
    # Dynamic list of {"label": str, "url": str} dicts — replaces fixed social fields
    social_links: tuple
    auto_translate: bool = False
    context_facts: str = ""    # factual grounding — injected into AI system prompt
    own_email: str = ""        # agent user's Gmail address — used to detect To: vs CC:
    team_domain: str = ""      # e.g. "technyx.com" — senders from this domain are teammates
    # LLM fallback provider (any OpenAI-compatible API: Groq, xAI Grok, OpenAI, Mistral…)
    fallback_api_key: str = ""
    fallback_model: str = "llama-3.3-70b-versatile"
    fallback_base_url: str = "https://api.groq.com/openai/v1"
    # Ollama — local model, no API key needed
    ollama_enabled: bool = False
    ollama_model: str = "llama3.2"
    ollama_base_url: str = "http://localhost:11434"
    # Debug / observability
    debug_mode: bool = False


def _require(key: str) -> str:
    value = os.getenv(key, "").strip()
    if not value:
        raise ConfigError(f"Missing required environment variable: {key}")
    return value


def _optional(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _parse_social_links(data: dict) -> tuple:
    """
    Read social_links list from config dict.
    Falls back to migrating old individual fields for backward compatibility.
    """
    links = data.get("social_links")
    if links and isinstance(links, list):
        result = []
        for item in links:
            if isinstance(item, dict):
                label = str(item.get("label", "")).strip()
                url = str(item.get("url", "")).strip()
                if label and url:
                    result.append({"label": label, "url": url})
        return tuple(result)

    # Migrate old flat fields if present
    result = []
    for key, label in [
        ("signature_linkedin", "LinkedIn"),
        ("signature_github", "GitHub"),
        ("signature_website", "Website"),
    ]:
        url = str(data.get(key, "")).strip()
        if url:
            result.append({"label": label, "url": url})
    return tuple(result)


def load_settings_from_dict(data: dict) -> Settings:
    """
    Populate a Settings instance from a plain dict (e.g. parsed from config.json).
    Raises ConfigError for missing required fields.
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
        social_links=_parse_social_links(data),
        auto_translate=str(data.get("auto_translate", "false")).lower() in ("true", "1", "yes"),
        context_facts=optional("context_facts"),
        own_email=optional("own_email"),
        team_domain=optional("team_domain"),
        fallback_api_key=optional("fallback_api_key"),
        fallback_model=optional("fallback_model", "llama-3.3-70b-versatile"),
        fallback_base_url=optional("fallback_base_url", "https://api.groq.com/openai/v1"),
        ollama_enabled=str(data.get("ollama_enabled", "false")).lower() in ("true", "1", "yes"),
        ollama_model=optional("ollama_model", "llama3.2"),
        ollama_base_url=optional("ollama_base_url", "http://localhost:11434"),
        debug_mode=str(data.get("debug_mode", "false")).lower() in ("true", "1", "yes"),
    )


def load_settings() -> Settings:
    load_dotenv()

    try:
        poll_interval = int(os.getenv("POLL_INTERVAL_SECONDS", "300"))
    except ValueError:
        raise ConfigError("POLL_INTERVAL_SECONDS must be a valid integer.")

    social_links_data: dict[str, Any] = {}
    for key in ("signature_linkedin", "signature_github", "signature_website"):
        val = os.getenv(key.upper(), "").strip()
        if val:
            social_links_data[key] = val

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
        social_links=_parse_social_links(social_links_data),
    )
