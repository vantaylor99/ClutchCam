import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from ai_director import AIDirector, AIDirectorError  # noqa: E402
from config import SCENES  # noqa: E402
from contracts import HypeSignal  # noqa: E402


class AIDirectorReadinessTests(unittest.TestCase):
    def test_readiness_accepts_configured_model_from_ollama_tags(self) -> None:
        response = Mock()
        response.json.return_value = {"models": [{"name": "gemma3:4b"}]}

        with patch("ai_director.requests.get", return_value=response) as get:
            AIDirector("http://ollama:11434", "gemma3:4b").check_readiness()

        get.assert_called_once_with("http://ollama:11434/api/tags", timeout=5)
        response.raise_for_status.assert_called_once()

    def test_readiness_accepts_ollama_model_alias_field(self) -> None:
        response = Mock()
        response.json.return_value = {"models": [{"model": "gemma3:4b"}]}

        with patch("ai_director.requests.get", return_value=response):
            AIDirector("http://ollama:11434", "gemma3:4b").check_readiness()

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
    def test_provider_injection_supplies_readiness_and_generation(self) -> None:
        class FakeProvider:
            def __init__(self) -> None:
                self.readiness_checks = 0
                self.prompts: list[str] = []

            def check_readiness(self) -> None:
                self.readiness_checks += 1

            def generate(self, prompt: str) -> str:
                self.prompts.append(prompt)
                return (
                    '{"target_scene": "Player 4 Fullscreen", '
                    '"confidence": 0.87, "duration_seconds": 11, '
                    '"reason": "Player 4 hit a clutch moment."}'
                )

        provider = FakeProvider()
        director = AIDirector(
            "http://unused-provider",
            "gemma3:4b",
            provider=provider,
        )
        signal = HypeSignal(
            stream_id="player_4",
            trigger_time_seconds=9.5,
            confidence=0.77,
            reason="Matched excitement phrase: clutch.",
        )

        director.check_readiness()
        decision = director.decide("player_4: clutch save", candidate_signal=signal)

        self.assertEqual(provider.readiness_checks, 1)
        self.assertEqual(len(provider.prompts), 1)
        self.assertIn("Candidate trigger:", provider.prompts[0])
        self.assertIn("stream_id: player_4", provider.prompts[0])
        self.assertEqual(decision.target_scene, SCENES["player_4"])
        self.assertEqual(decision.confidence, 0.87)
        self.assertEqual(decision.duration_seconds, 11)

    def test_decide_preserves_ollama_generate_payload(self) -> None:
        response = Mock()
        response.json.return_value = {
            "response": (
                '{"target_scene": "Player 2 Fullscreen", '
                '"confidence": 0.91, "duration_seconds": 12, '
                '"reason": "Player 2 found diamonds."}'
            )
        }

        with patch("ai_director.requests.post", return_value=response) as post:
            decision = AIDirector(
                "http://ollama:11434",
                "gemma3:4b",
                timeout_seconds=17,
            ).decide("player_2: no way, diamonds")

        post.assert_called_once()
        self.assertEqual(post.call_args.args[0], "http://ollama:11434/api/generate")
        self.assertEqual(post.call_args.kwargs["timeout"], 17)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "gemma3:4b")
        self.assertIn("player_2: no way, diamonds", payload["prompt"])
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["format"], "json")
        self.assertEqual(payload["options"], {"temperature": 0.2})
        response.raise_for_status.assert_called_once()
        self.assertEqual(decision.target_scene, SCENES["player_2"])

    def test_decide_rejects_missing_ollama_response_field(self) -> None:
        response = Mock()
        response.json.return_value = {"done": True}

        with patch("ai_director.requests.post", return_value=response):
            with self.assertRaisesRegex(AIDirectorError, "did not include a decision"):
                AIDirector("http://ollama:11434", "gemma3:4b").decide("player_1: hi")

    def test_prompt_includes_candidate_separately_from_recent_context(self) -> None:
        signal = HypeSignal(
            stream_id="player_3",
            trigger_time_seconds=42.25,
            confidence=0.9,
            reason="Matched excitement phrase: no way.",
        )

        prompt = AIDirector("http://ollama:11434", "gemma3:4b")._build_prompt(
            "player_1: older context",
            candidate_signal=signal,
        )

        self.assertIn("Candidate trigger:", prompt)
        self.assertIn("stream_id: player_3", prompt)
        self.assertIn("trigger_time_seconds: 42.250", prompt)
        self.assertIn("local_reason: Matched excitement phrase: no way.", prompt)
        self.assertIn("Recent transcript:\nplayer_1: older context", prompt)


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
