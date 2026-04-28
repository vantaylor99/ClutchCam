import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from ai_director import AIDirector, AIDirectorError  # noqa: E402
from config import SCENES  # noqa: E402


class AIDirectorReadinessTests(unittest.TestCase):
    def test_readiness_accepts_configured_model_from_ollama_tags(self) -> None:
        response = Mock()
        response.json.return_value = {"models": [{"name": "gemma3:4b"}]}

        with patch("ai_director.requests.get", return_value=response) as get:
            AIDirector("http://ollama:11434", "gemma3:4b").check_readiness()

        get.assert_called_once_with("http://ollama:11434/api/tags", timeout=5)
        response.raise_for_status.assert_called_once()

    def test_readiness_explains_missing_model_pull_command(self) -> None:
        response = Mock()
        response.json.return_value = {"models": [{"name": "llama3.2:3b"}]}

        with patch("ai_director.requests.get", return_value=response):
            with self.assertRaisesRegex(
                AIDirectorError,
                "ollama pull gemma3:4b",
            ):
                AIDirector("http://ollama:11434", "gemma3:4b").check_readiness()

    def test_readiness_rejects_unexpected_tags_response_shape(self) -> None:
        response = Mock()
        response.json.return_value = []

        with patch("ai_director.requests.get", return_value=response):
            with self.assertRaisesRegex(AIDirectorError, "model list was missing"):
                AIDirector("http://ollama:11434", "gemma3:4b").check_readiness()


class AIDirectorDecisionTests(unittest.TestCase):
    def test_decide_rejects_missing_ollama_response_field(self) -> None:
        response = Mock()
        response.json.return_value = {"done": True}

        with patch("ai_director.requests.post", return_value=response):
            with self.assertRaisesRegex(AIDirectorError, "did not include a decision"):
                AIDirector("http://ollama:11434", "gemma3:4b").decide("player_1: hi")


class AIDirectorParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.director = AIDirector("http://ollama:11434", "gemma3:4b")

    def test_parses_fenced_json(self) -> None:
        decision = self.director._parse_decision_json(
            """```json
{
  "target_scene": "Player 3 Fullscreen",
  "confidence": 0.9,
  "duration_seconds": 12,
  "reason": "Player 3 found something."
}
```"""
        )

        self.assertEqual(decision["target_scene"], SCENES["player_3"])

    def test_parses_json_with_short_leading_and_trailing_text(self) -> None:
        decision = self.director._parse_decision_json(
            'Here is the decision: {"target_scene": "Quad View", '
            '"confidence": 0.1, "duration_seconds": 8, "reason": "No focus."} thanks'
        )

        self.assertEqual(decision["target_scene"], SCENES["quad"])

    def test_parses_json_with_trailing_commas(self) -> None:
        decision = self.director._parse_decision_json(
            """
{
  "target_scene": "Player 1 Fullscreen",
  "confidence": 0.81,
  "duration_seconds": 10,
  "reason": "Player 1 reacted.",
}
"""
        )

        self.assertEqual(decision["target_scene"], SCENES["player_1"])

    def test_rejects_non_object_json(self) -> None:
        with self.assertRaisesRegex(AIDirectorError, "JSON object"):
            self.director._parse_decision_json('["Quad View"]')

    def test_normalizes_invalid_scene_to_quad_view(self) -> None:
        decision = self.director._normalize_decision(
            {
                "target_scene": "Player Three Fullscreen",
                "confidence": "0.8",
                "duration_seconds": "12",
                "reason": "Bad scene name.",
            }
        )

        self.assertEqual(decision.target_scene, SCENES["quad"])
        self.assertEqual(decision.confidence, 0.8)
        self.assertEqual(decision.duration_seconds, 12)


if __name__ == "__main__":
    unittest.main()
