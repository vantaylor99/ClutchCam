import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Protocol
from urllib.parse import urlparse, urlunparse

import requests

from config import (
    AI_PROVIDER_OLLAMA,
    AI_PROVIDER_OPENAI_COMPATIBLE,
    SCENES,
    VALID_SCENE_NAMES,
    normalize_ai_provider,
)
from contracts import HypeSignal


@dataclass
class DirectorDecision:
    target_scene: str
    confidence: float
    duration_seconds: int
    reason: str


class AIDirectorError(RuntimeError):
    """User-facing AI director failure."""


class DirectorProvider(Protocol):
    def check_readiness(self) -> None:
        """Verify that the backing model provider can serve decisions."""

    def generate(self, prompt: str) -> Any:
        """Return the provider's raw decision payload for the director to parse."""


class OllamaDirectorProvider:
    def __init__(self, base_url: str, model: str, timeout_seconds: int = 60):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def check_readiness(self) -> None:
        try:
            response = requests.get(
                f"{self.base_url}/api/tags",
                timeout=5,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise AIDirectorError(
                "Ollama is not reachable at "
                f"{self.base_url}. Start Ollama or check OLLAMA_BASE_URL."
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise AIDirectorError(
                "Ollama responded to /api/tags, but the response was not valid JSON."
            ) from exc

        if not isinstance(payload, dict):
            raise AIDirectorError(
                "Ollama responded to /api/tags, but the model list was missing."
            )

        models = payload.get("models")
        if not isinstance(models, list):
            raise AIDirectorError(
                "Ollama responded to /api/tags, but the model list was missing."
            )

        available_models = {
            name
            for model_info in models
            if isinstance(model_info, dict)
            for name in (model_info.get("name"), model_info.get("model"))
            if isinstance(name, str)
        }
        if self.model not in available_models:
            raise AIDirectorError(
                f'Ollama model "{self.model}" is not installed. '
                f"Run: ollama pull {self.model}"
            )

    def generate(self, prompt: str) -> Any:
        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {
                        "temperature": 0.2,
                    },
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise AIDirectorError(
                "Ollama generation request failed. Check that Ollama is running "
                f"and model {self.model} is available."
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise AIDirectorError("Ollama returned a non-JSON HTTP response.") from exc

        if not isinstance(payload, dict):
            raise AIDirectorError("Ollama returned an unexpected response shape.")
        if "response" not in payload:
            raise AIDirectorError("Ollama response did not include a decision.")

        return payload["response"]


class OpenAICompatibleDirectorProvider:
    def __init__(
        self,
        api_url: str,
        model: str,
        timeout_seconds: int = 60,
        api_key: str | None = None,
        temperature: float = 0.2,
    ):
        self.api_url = api_url.strip()
        self.endpoint_url = _chat_completions_endpoint(self.api_url)
        self.readiness_url = _readiness_probe_url(self.api_url)
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.api_key = api_key or ""
        self.temperature = temperature

    def check_readiness(self) -> None:
        if not self.api_url:
            raise AIDirectorError(
                "GEMMA_API_URL is required for the OpenAI-compatible provider."
            )
        if not self.model:
            raise AIDirectorError(
                "GEMMA_MODEL is required for the OpenAI-compatible provider."
            )

        try:
            response = requests.get(self.readiness_url, timeout=5)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise AIDirectorError(
                "OpenAI-compatible AI provider is not reachable at "
                f"{self.readiness_url}. Check GEMMA_API_URL."
            ) from exc

    def generate(self, prompt: str) -> Any:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            response = requests.post(
                self.endpoint_url,
                json={
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Return only one JSON object matching the user's "
                                "requested scene-decision schema."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": self.temperature,
                    "stream": False,
                    "response_format": {"type": "json_object"},
                },
                headers=headers,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise AIDirectorError(
                "OpenAI-compatible generation request failed. Check "
                "AI_PROVIDER, GEMMA_API_URL, GEMMA_MODEL, and credentials."
            ) from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise AIDirectorError(
                "OpenAI-compatible provider returned a non-JSON HTTP response."
            ) from exc

        return _extract_openai_message_content(payload)


def create_director_provider(
    ai_provider: str,
    api_url: str,
    model: str,
    timeout_seconds: int = 60,
    api_key: str | None = None,
) -> DirectorProvider:
    provider = normalize_ai_provider(ai_provider)
    if provider == AI_PROVIDER_OLLAMA:
        return OllamaDirectorProvider(
            base_url=api_url,
            model=model,
            timeout_seconds=timeout_seconds,
        )
    if provider == AI_PROVIDER_OPENAI_COMPATIBLE:
        return OpenAICompatibleDirectorProvider(
            api_url=api_url,
            model=model,
            timeout_seconds=timeout_seconds,
            api_key=api_key,
        )

    raise AIDirectorError(f"Unsupported AI provider: {ai_provider}")


class AIDirector:
    def __init__(
        self,
        ollama_base_url: str,
        model: str,
        timeout_seconds: int = 60,
        provider: DirectorProvider | None = None,
        ai_provider: str | None = None,
        api_key: str | None = None,
    ):
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        if provider is not None:
            self.ai_provider = (
                normalize_ai_provider(ai_provider) if ai_provider else "injected"
            )
            self._provider = provider
            return

        provider_name = ai_provider or os.getenv("AI_PROVIDER", AI_PROVIDER_OLLAMA)
        self.ai_provider = normalize_ai_provider(provider_name)
        self._provider = create_director_provider(
            ai_provider=self.ai_provider,
            api_url=ollama_base_url,
            model=model,
            timeout_seconds=timeout_seconds,
            api_key=api_key if api_key is not None else os.getenv("GEMMA_API_KEY"),
        )

    def check_readiness(self) -> None:
        self._provider.check_readiness()

    def decide(
        self,
        transcript_context: str,
        candidate_signal: HypeSignal | None = None,
    ) -> DirectorDecision:
        prompt = self._build_prompt(
            transcript_context,
            candidate_signal=candidate_signal,
        )
        raw_decision = self._provider.generate(prompt)
        data = self._parse_decision_json(raw_decision)
        return self._normalize_decision(data)

    def _build_prompt(
        self,
        transcript_context: str,
        candidate_signal: HypeSignal | None = None,
    ) -> str:
        scene_list = "\n".join(f"- {scene}" for scene in SCENES.values())
        candidate_context = _candidate_context(candidate_signal)
        return f"""
You are an AI livestream director controlling OBS scenes for a 4-player stream.

Your job:
- Prefer "Quad View" most of the time.
- Choose a player fullscreen scene only when one player clearly says something exciting, urgent, surprising, funny, emotional, or visually important.
- Use only the exact scene names listed below.
- Return JSON only. Do not include markdown, commentary, or extra text.

Valid scenes:
{scene_list}

Decision rules:
- If there is no clear focus moment, choose "Quad View".
- Confidence should be between 0 and 1.
- Player focus duration should usually be 8-15 seconds.
- Never choose a duration above 20 seconds.
- Keep reasons short and concrete.
- The candidate trigger is the newest local signal. Treat older transcript lines
  as supporting context, not as replacement triggers.

Candidate trigger:
{candidate_context}

Recent transcript:
{transcript_context}

Return exactly this JSON shape:
{{
  "target_scene": "Quad View",
  "confidence": 0.0,
  "duration_seconds": 8,
  "reason": "Short reason."
}}
""".strip()

    def _parse_decision_json(self, raw_decision: Any) -> Dict[str, Any]:
        if isinstance(raw_decision, dict):
            return raw_decision

        if not isinstance(raw_decision, str):
            raise AIDirectorError("AI decision response was not a JSON object.")

        text = raw_decision.strip()
        text = self._strip_markdown_fence(text)
        text = self._remove_trailing_commas(text)
        if text.lstrip().startswith("["):
            raise AIDirectorError("AI decision response was not a JSON object.")

        decoder = json.JSONDecoder()
        for index, character in enumerate(text):
            if character != "{":
                continue

            try:
                data, _ = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue

            if isinstance(data, dict):
                return data

        raise AIDirectorError(
            "AI decision was not valid JSON. Expected an object with "
            "target_scene, confidence, duration_seconds, and reason."
        )

    def _strip_markdown_fence(self, text: str) -> str:
        fenced = re.fullmatch(
            r"```(?:json)?\s*(.*?)\s*```",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if fenced is None:
            return text
        return fenced.group(1).strip()

    def _remove_trailing_commas(self, text: str) -> str:
        return re.sub(r",\s*([}\]])", r"\1", text)

    def _normalize_decision(self, data: Dict[str, Any]) -> DirectorDecision:
        target_scene = str(data.get("target_scene", SCENES["quad"])).strip()
        if target_scene not in VALID_SCENE_NAMES:
            target_scene = SCENES["quad"]

        try:
            confidence = float(data.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        try:
            duration_seconds = int(data.get("duration_seconds", 8))
        except (TypeError, ValueError):
            duration_seconds = 8

        reason = str(data.get("reason", "No reason provided.")).strip()
        if not reason:
            reason = "No reason provided."

        return DirectorDecision(
            target_scene=target_scene,
            confidence=confidence,
            duration_seconds=duration_seconds,
            reason=reason,
        )


def _candidate_context(candidate_signal: HypeSignal | None) -> str:
    if candidate_signal is None:
        return "No local trigger candidate."

    return "\n".join(
        [
            f"stream_id: {candidate_signal.stream_id}",
            f"trigger_time_seconds: {candidate_signal.trigger_time_seconds:.3f}",
            f"local_confidence: {candidate_signal.confidence:.2f}",
            f"local_reason: {candidate_signal.reason}",
            f"source: {candidate_signal.source}",
        ]
    )


def _chat_completions_endpoint(api_url: str) -> str:
    stripped_url = api_url.strip().rstrip("/")
    parsed = urlparse(stripped_url)
    path = parsed.path.rstrip("/")

    if path.endswith("/chat/completions"):
        endpoint_path = path
    elif path.endswith("/v1"):
        endpoint_path = f"{path}/chat/completions"
    elif path:
        endpoint_path = f"{path}/v1/chat/completions"
    else:
        endpoint_path = "/v1/chat/completions"

    return urlunparse(parsed._replace(path=endpoint_path))


def _readiness_probe_url(api_url: str) -> str:
    stripped_url = api_url.strip().rstrip("/")
    parsed = urlparse(stripped_url)
    if parsed.scheme and parsed.netloc:
        return urlunparse(
            parsed._replace(path="", params="", query="", fragment="")
        ).rstrip("/")

    return stripped_url


def _extract_openai_message_content(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise AIDirectorError(
            "OpenAI-compatible provider returned an unexpected response shape."
        )

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise AIDirectorError(
            "OpenAI-compatible response did not include assistant message content."
        )

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise AIDirectorError(
            "OpenAI-compatible response did not include assistant message content."
        )

    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise AIDirectorError(
            "OpenAI-compatible response did not include assistant message content."
        )

    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise AIDirectorError(
            "OpenAI-compatible response did not include assistant message content."
        )

    return content
