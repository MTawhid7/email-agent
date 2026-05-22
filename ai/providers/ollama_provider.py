"""
Ollama local model provider.

Calls the Ollama REST API at localhost:11434 (default).
Free, runs entirely on the user's machine, requires no API key.
Raises ProviderUnavailableError if Ollama is not running.
"""
import logging

import httpx

from ai.providers.base import LLMProvider
from exceptions import ProviderUnavailableError

logger = logging.getLogger(__name__)

_TIMEOUT = 120.0  # local inference can be slow on CPU


class OllamaProvider(LLMProvider):
    """
    LLM provider backed by a locally running Ollama instance.
    Only raises ProviderUnavailableError — no hard failures since there
    is no auth and no content policy enforcement.
    """

    def __init__(
        self,
        model: str = "llama3.2",
        base_url: str = "http://localhost:11434",
        system_prompt: str = "",
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._system_prompt = system_prompt

    @property
    def name(self) -> str:
        return f"ollama:{self._model}"

    def generate(self, user_message: str, system: str, use_persona: bool = False) -> str:
        instruction = self._system_prompt if use_persona else system
        payload = {
            "model": self._model,
            "prompt": user_message,
            "system": instruction,
            "stream": False,
        }

        try:
            resp = httpx.post(
                f"{self._base_url}/api/generate",
                json=payload,
                timeout=_TIMEOUT,
            )
        except httpx.ConnectError as exc:
            raise ProviderUnavailableError(
                "Ollama is not running. Start it with `ollama serve` or disable it in Settings."
            ) from exc
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError(
                f"Ollama request timed out after {_TIMEOUT}s."
            ) from exc

        if resp.status_code >= 400:
            raise ProviderUnavailableError(
                f"Ollama error {resp.status_code}: {resp.text[:200]}"
            )

        try:
            text = resp.json().get("response", "").strip()
        except ValueError as exc:
            raise ProviderUnavailableError(
                f"Ollama response parse error: {exc}"
            ) from exc

        if not text:
            raise ProviderUnavailableError("Ollama returned an empty response.")

        return text
