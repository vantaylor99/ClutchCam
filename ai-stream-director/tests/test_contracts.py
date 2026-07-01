import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from contracts import LookbackClipRequest  # noqa: E402
from transcript_router import TranscriptMessage  # noqa: E402


class LookbackClipRequestTests(unittest.TestCase):
    def test_computes_clip_bounds_from_trigger_time(self) -> None:
        request = LookbackClipRequest(
            stream_id="player_3",
            trigger_time_seconds=120.0,
            pre_roll_seconds=15,
            post_roll_seconds=5,
        )

        self.assertEqual(request.start_time_seconds, 105.0)
        self.assertEqual(request.end_time_seconds, 125.0)

    def test_clamps_start_time_at_zero(self) -> None:
        request = LookbackClipRequest(
            stream_id="player_1",
            trigger_time_seconds=8.0,
            pre_roll_seconds=15,
        )

        self.assertEqual(request.start_time_seconds, 0.0)


class TranscriptEventContractTests(unittest.TestCase):
    def test_terminal_mvp_message_can_be_promoted_to_event_contract(self) -> None:
        message = TranscriptMessage(
            speaker="player_2",
            text="holy cow, look at this",
            start_time_seconds=42.0,
            end_time_seconds=42.5,
        )

        event = message.to_event()

        self.assertEqual(event.stream_id, "player_2")
        self.assertEqual(event.text, "holy cow, look at this")
        self.assertEqual(event.start_time_seconds, 42.0)
        self.assertEqual(event.end_time_seconds, 42.5)
        self.assertTrue(event.is_final)


if __name__ == "__main__":
    unittest.main()
