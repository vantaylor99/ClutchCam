import io
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import ANY, Mock

import sys


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from ai_director import DirectorDecision  # noqa: E402
from config import SCENES  # noqa: E402
from contracts import HypeSignal, TranscriptEvent  # noqa: E402
from main import (  # noqa: E402
    RuntimeTranscriptEventHandler,
    build_runtime_switch_target,
    process_transcript_event,
)
from obs_controller import DryRunOBSController  # noqa: E402
from scheduler import SceneScheduler  # noqa: E402
from services.buffer import FixtureLookbackBuffer, SegmentRecord  # noqa: E402
from services.switcher import BufferBackedSwitcher, SwitchStatus  # noqa: E402
from transcript_router import TranscriptRouter  # noqa: E402


class RuntimeTranscriptEventPipelineTests(unittest.TestCase):
    def test_event_timestamp_drives_candidate_signal_trigger_time(self) -> None:
        scheduler = _started_scheduler()
        router = TranscriptRouter(history_seconds=30, max_messages=20)
        ai_director = Mock()
        ai_director.decide.return_value = DirectorDecision(
            target_scene=SCENES["player_3"],
            confidence=0.91,
            duration_seconds=11,
            reason="Player 3 found something rare.",
        )
        event = TranscriptEvent(
            stream_id="player_3",
            text="no way, I found something rare",
            start_time_seconds=119.5,
            end_time_seconds=123.25,
        )

        result = process_transcript_event(
            event,
            router,
            ai_director,
            scheduler,
            log=lambda message: None,
        )

        ai_director.decide.assert_called_once_with(
            "player_3: no way, I found something rare",
            candidate_signal=ANY,
        )
        candidate_signal = ai_director.decide.call_args.kwargs["candidate_signal"]
        self.assertEqual(candidate_signal.stream_id, "player_3")
        self.assertEqual(candidate_signal.trigger_time_seconds, 123.25)
        self.assertIs(result.candidate_signal, candidate_signal)
        self.assertIsNotNone(result.switch_target)
        self.assertEqual(
            result.switch_target.clip_request.trigger_time_seconds,
            123.25,
        )

    def test_ai_disabled_runtime_event_skips_model_call_after_routing(self) -> None:
        scheduler = _started_scheduler()
        scheduler.set_ai_enabled(False)
        router = TranscriptRouter(history_seconds=30, max_messages=20)
        ai_director = Mock()
        output = io.StringIO()

        result = process_transcript_event(
            TranscriptEvent(
                stream_id="player_2",
                text="holy cow, look at this",
                start_time_seconds=10.0,
                end_time_seconds=12.0,
            ),
            router,
            ai_director,
            scheduler,
            log=lambda message: print(message, file=output),
        )

        ai_director.decide.assert_not_called()
        self.assertTrue(result.accepted)
        self.assertEqual(result.reason, "ai_disabled")
        self.assertEqual(router.get_recent_context_text(), "player_2: holy cow, look at this")
        self.assertIn("AI evaluation skipped because AI mode is off", output.getvalue())

    def test_cooldown_runtime_event_skips_model_call_after_routing(self) -> None:
        scheduler = _started_scheduler(min_switch_interval_seconds=8)
        scheduler.last_switch_time = time.time()
        router = TranscriptRouter(history_seconds=30, max_messages=20)
        ai_director = Mock()
        output = io.StringIO()

        result = process_transcript_event(
            TranscriptEvent(
                stream_id="player_4",
                text="holy cow, rare boss",
                start_time_seconds=20.0,
                end_time_seconds=21.0,
            ),
            router,
            ai_director,
            scheduler,
            log=lambda message: print(message, file=output),
        )

        ai_director.decide.assert_not_called()
        self.assertTrue(result.accepted)
        self.assertEqual(result.reason, "scheduler_gate_blocked")
        self.assertEqual(router.get_recent_context_text(), "player_4: holy cow, rare boss")
        self.assertIn("switch cooldown has", output.getvalue())

    def test_accepted_ai_decision_resolves_buffered_switch_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_switcher = BufferBackedSwitcher(
                _fixture_buffer(
                    temp_dir,
                    [
                        ("player_1", "000.ts", 30.0, 36.0),
                        ("player_1", "001.ts", 36.0, 42.0),
                        ("player_1", "002.ts", 42.0, 47.0),
                    ],
                ),
                clock=lambda: 500.0,
            )
            scheduler = _started_scheduler()
            router = TranscriptRouter(history_seconds=30, max_messages=20)
            ai_director = Mock()
            ai_director.decide.return_value = DirectorDecision(
                target_scene=SCENES["player_1"],
                confidence=0.93,
                duration_seconds=9,
                reason="Player 1 found diamonds.",
            )

            result = RuntimeTranscriptEventHandler(
                transcript_router=router,
                ai_director=ai_director,
                scheduler=scheduler,
                output_switcher=output_switcher,
                switch_lookback_seconds=12,
                log=lambda message: None,
            )(
                TranscriptEvent(
                    stream_id="player_1",
                    text="no way, I found diamonds",
                    start_time_seconds=40.0,
                    end_time_seconds=42.0,
                )
            )

        self.assertIsNotNone(result)
        self.assertIsNotNone(result.switch_target)
        self.assertIsNotNone(result.switch_target.clip_request)
        self.assertEqual(result.switch_target.stream_id, "player_1")
        self.assertEqual(result.switch_target.scene_name, SCENES["player_1"])
        self.assertEqual(
            result.switch_target.clip_request.trigger_time_seconds,
            42.0,
        )
        self.assertEqual(result.switch_target.clip_request.start_time_seconds, 30.0)
        self.assertEqual(result.switch_target.clip_request.end_time_seconds, 47.0)
        self.assertIsNotNone(result.switch_result)
        self.assertEqual(result.switch_result.status, SwitchStatus.APPLIED)
        self.assertEqual(result.switch_result.switched_at_seconds, 500.0)
        self.assertIsNotNone(result.switch_result.target.media_uri)
        self.assertEqual(len(result.switch_result.segment_uris), 3)
        self.assertEqual(scheduler.status().current_scene, SCENES["player_1"])

    def test_mismatched_ai_scene_does_not_build_inconsistent_buffer_target(self) -> None:
        scheduler = _started_scheduler()

        target = build_runtime_switch_target(
            decision=DirectorDecision(
                target_scene=SCENES["player_2"],
                confidence=0.93,
                duration_seconds=9,
                reason="Model picked a different player.",
            ),
            candidate_signal=HypeSignal(
                stream_id="player_3",
                trigger_time_seconds=12.0,
                confidence=0.8,
                reason="Local trigger.",
            ),
            scheduler=scheduler,
            switch_lookback_seconds=12,
        )

        self.assertIsNone(target)


def _started_scheduler(min_switch_interval_seconds: int = 0) -> SceneScheduler:
    controller = DryRunOBSController(initial_scene=SCENES["quad"], log=lambda message: None)
    scheduler = SceneScheduler(
        obs_controller=controller,
        default_scene=SCENES["quad"],
        confidence_threshold=0.75,
        min_switch_interval_seconds=min_switch_interval_seconds,
        max_focus_duration_seconds=20,
        log=lambda message: None,
    )
    controller.connect()
    scheduler.start()
    return scheduler


def _fixture_buffer(
    temp_dir: str,
    segment_specs: list[tuple[str, str, float, float]],
) -> FixtureLookbackBuffer:
    records = []
    for stream_id, file_name, start, end in segment_specs:
        stream_dir = Path(temp_dir) / stream_id
        stream_dir.mkdir(parents=True, exist_ok=True)
        segment_path = stream_dir / file_name
        segment_path.write_bytes(b"segment")
        records.append(
            SegmentRecord(
                stream_id=stream_id,
                path=segment_path,
                start_time_seconds=start,
                end_time_seconds=end,
            )
        )

    return FixtureLookbackBuffer(records=records, buffer_root=temp_dir)


if __name__ == "__main__":
    unittest.main()
