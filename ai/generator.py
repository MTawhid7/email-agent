import json
import logging

from google import genai

from ai.providers.router import FallbackRouter
from ai.providers.gemini_provider import GeminiProvider
from ai.providers.openai_compatible_provider import OpenAICompatibleProvider
from ai.providers.ollama_provider import OllamaProvider
from ai.prompts import build_system_prompt
from core.config import Settings
from core.exceptions import GenerationError

logger = logging.getLogger(__name__)


def _build_providers(settings: Settings, system_prompt: str) -> list:
    """Build the ordered provider list from settings. Gemini is always first."""
    providers = [GeminiProvider(settings.gemini_api_key, settings.gemini_model, system_prompt)]

    if settings.fallback_api_key:
        providers.append(OpenAICompatibleProvider(
            api_key=settings.fallback_api_key,
            model=settings.fallback_model,
            base_url=settings.fallback_base_url,
            system_prompt=system_prompt,
        ))

    if settings.ollama_enabled:
        providers.append(OllamaProvider(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            system_prompt=system_prompt,
        ))

    return providers


class ReplyGenerator:
    def __init__(self, settings: Settings) -> None:
        auto_translate = getattr(settings, "auto_translate", False)
        context_facts = getattr(settings, "context_facts", "")
        self._system_prompt = build_system_prompt(settings.persona_prompt, auto_translate, context_facts)
        self._router = FallbackRouter(_build_providers(settings, self._system_prompt))
        # Keep _client and _model for attachment_reader compatibility
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.gemini_model

    def generate(self, user_message: str) -> str:
        """Generate an email body. Falls back to secondary providers on failure."""
        return self._call(user_message, system="You are an email assistant.", use_persona=True)

    def classify(self, user_message: str) -> dict:
        """
        Classify an email's priority and whether it needs a reply.
        Returns {"priority", "reason", "skip", "needs_reply"}.
        Never raises — falls back to normal/needs_reply:true on any error.
        """
        try:
            text = self._call(user_message, system="You are an email classifier. Return JSON only.")
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            data = json.loads(text.strip())
            priority = str(data.get("priority", "normal")).lower()
            if priority not in ("high", "normal", "low", "skip"):
                priority = "normal"
            needs_reply = bool(data.get("needs_reply", True))
            return {
                "priority": priority,
                "reason": data.get("reason", ""),
                "skip": priority == "skip",
                "needs_reply": needs_reply,
            }
        except Exception:
            return {"priority": "normal", "reason": "", "skip": False, "needs_reply": True}

    def summarise(self, user_message: str) -> str:
        """Generate a one-sentence thread summary. Never raises."""
        try:
            return self._call(user_message, system="You are a concise email summariser.")
        except Exception:
            return ""

    def summarise_reply(self, reply_body: str) -> str:
        """
        One-sentence summary of the reply we sent — stored in interaction history.
        Never raises; returns '' on failure.
        """
        try:
            prompt = (
                "Summarise this email reply in ONE sentence (max 15 words). "
                "Describe what was communicated, not the style.\n\n"
                f"Reply:\n{reply_body[:1000]}\n\n"
                "Output the summary sentence ONLY. No trailing period."
            )
            return self._call(prompt, system="You are a concise email summariser.")
        except Exception:
            return ""

    def extract_topics(self, email_body: str, reply_body: str) -> list[str]:
        """
        Extract 3–5 topic tags from the email + reply pair.
        Stored in interaction history for context injection on future emails.
        Never raises; returns [] on failure.
        """
        try:
            prompt = (
                "Extract 3 to 5 short topic tags from this email exchange. "
                "Tags should be 1–3 words, lowercase, hyphenated.\n\n"
                f"Their email:\n{email_body[:400]}\n\n"
                f"Our reply:\n{reply_body[:400]}\n\n"
                "Return a JSON array of strings only, e.g. [\"contract-renewal\", \"pricing\"]"
            )
            text = self._call(prompt, system="You are a topic extraction assistant. Return JSON only.")
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            tags = json.loads(text.strip())
            if isinstance(tags, list):
                return [str(t).strip().lower() for t in tags if t][:5]
        except Exception:
            pass
        return []

    # ── Internal ───────────────────────────────────────────────────────────────

    def _call(self, user_message: str, system: str, use_persona: bool = False) -> str:
        return self._router.generate(user_message, system, use_persona)
