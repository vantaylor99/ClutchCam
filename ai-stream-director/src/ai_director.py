import json
from dataclasses import dataclass
from typing import Any, Dict

import requests

from config import SCENES, VALID_SCENE_NAMES


@dataclass
class DirectorDecision:
    target_scene: str
    confidence: float
    duration_seconds: int
    reason: str


class AIDirector:
    def __init__(self, ollama_base_url: str, model: str, timeout_seconds: int = 60):
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def decide(self, transcript_context: str) -> DirectorDecision:
        prompt = self._build_prompt(transcript_context)
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

        payload = response.json()
        raw_decision = payload.get("response", "{}")
        data = json.loads(raw_decision)
        return self._normalize_decision(data)

    def _build_prompt(self, transcript_context: str) -> str:
        scene_list = "\n".join(f"- {scene}" for scene in SCENES.values())
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
