import json
import logging
import time

from google import genai
from google.genai import types
from google.genai.errors import ClientError, ServerError

from ai.prompts import build_system_prompt
from config import Settings
from exceptions import GenerationError

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_INITIAL_BACKOFF = 2  # seconds


class ReplyGenerator:
    def __init__(self, settings: Settings) -> None:
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.gemini_model
        auto_translate = getattr(settings, "auto_translate", False)
        self._system_prompt = build_system_prompt(settings.persona_prompt, auto_translate)

    def generate(self, user_message: str) -> str:
        """Generate an email body. Retries on rate limit."""
        return self._call(
            user_message,
            system="You are an email assistant.",
            use_persona=True,
        )

    def classify(self, user_message: str) -> dict:
        """
        Classify an email's priority. Returns {"priority", "reason", "skip"}.
        Never raises — falls back to normal on any error.
        """
        try:
            text = self._call(user_message, system="You are an email classifier. Return JSON only.")
            # Strip markdown fences if present
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            data = json.loads(text.strip())
            priority = str(data.get("priority", "normal")).lower()
            if priority not in ("high", "normal", "low", "skip"):
                priority = "normal"
            return {"priority": priority, "reason": data.get("reason", ""), "skip": priority == "skip"}
        except Exception:
            return {"priority": "normal", "reason": "", "skip": False}

    def summarise(self, user_message: str) -> str:
        """Generate a one-sentence thread summary. Never raises."""
        try:
            return self._call(user_message, system="You are a concise email summariser.")
        except Exception:
            return ""

    # ── Internal ───────────────────────────────────────────────────────────────

    def _call(self, user_message: str, system: str, use_persona: bool = False) -> str:
        instruction = self._system_prompt if use_persona else system
        config = types.GenerateContentConfig(system_instruction=instruction)

        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = self._client.models.generate_content(
                    model=self._model,
                    contents=user_message,
                    config=config,
                )
                text = response.text
                if not text:
                    raise GenerationError("Gemini returned an empty response.")
                return text.strip()

            except ClientError as exc:
                code = exc.code if hasattr(exc, "code") else 0
                status = getattr(exc, "status", "")

                if code == 429 or "RESOURCE_EXHAUSTED" in str(status):
                    if attempt < _MAX_RETRIES:
                        wait = _INITIAL_BACKOFF * (2 ** attempt)
                        logger.warning("Gemini rate limit. Retrying in %ds...", wait)
                        time.sleep(wait)
                        continue
                    raise GenerationError("Gemini rate limit exceeded after retries.") from exc

                if code == 401 or "UNAUTHENTICATED" in str(status):
                    raise GenerationError(
                        "Invalid Gemini API key. Check GEMINI_API_KEY in your .env file."
                    ) from exc

                raise GenerationError(f"Gemini client error ({code}): {exc}") from exc

            except ServerError as exc:
                raise GenerationError(f"Gemini server error (5xx): {exc}") from exc

        raise GenerationError("Gemini generation failed after all retries.")
