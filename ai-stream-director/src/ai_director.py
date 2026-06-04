import json
import re
from dataclasses import dataclass
from typing import Any, Dict

import requests

from config import SCENES, VALID_SCENE_NAMES
from contracts import HypeSignal


@dataclass
class DirectorDecision:
    target_scene: str
    confidence: float
    duration_seconds: int
    reason: str


class AIDirectorError(RuntimeError):
    """User-facing AI director failure."""


class AIDirector:
    def __init__(self, ollama_base_url: str, model: str, timeout_seconds: int = 60):
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def check_readiness(self) -> None:
        try:
            response = requests.get(
                f"{self.ollama_base_url}/api/tags",
                timeout=5,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise AIDirectorError(
                "Ollama is not reachable at "
                f"{self.ollama_base_url}. Start Ollama or check OLLAMA_BASE_URL."
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
                f'Run: ollama pull {self.model}'
            )

    def decide(
        self,
        transcript_context: str,
        candidate_signal: HypeSignal | None = None,
    ) -> DirectorDecision:
        prompt = self._build_prompt(
            transcript_context,
            candidate_signal=candidate_signal,
        )
        try:
            response = requests.post(
                f"{self.ollama_base_url}/api/generate",
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
        raw_decision = payload["response"]
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
