import io
import queue
import threading
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import ANY, Mock

import sys


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from ai_director import DirectorDecision  # noqa: E402
from config import SCENES  # noqa: E402
from contracts import HypeSignal, TranscriptEvent  # noqa: E402
from main import (  # noqa: E402
    INPUT_CLOSED,
    LiveTranscriptQueueSink,
    LiveTranscriptionSource,
    RuntimeTranscriptEventHandler,
    build_runtime_switch_target,
    process_transcript_event,
    run_orchestrator_loop,
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

    def test_added_gaming_callout_reaches_ai_director(self) -> None:
        scheduler = _started_scheduler()
        router = TranscriptRouter(history_seconds=30, max_messages=20)
        ai_director = Mock()
        ai_director.decide.return_value = DirectorDecision(
            target_scene=SCENES["player_2"],
            confidence=0.91,
            duration_seconds=11,
            reason="Player 2 made a strong play.",
        )

        result = process_transcript_event(
            TranscriptEvent(
                stream_id="player_2",
                text="that was nasty",
                start_time_seconds=20.0,
                end_time_seconds=21.0,
            ),
            router,
            ai_director,
            scheduler,
            log=lambda message: None,
        )

        ai_director.decide.assert_called_once_with(
            "player_2: that was nasty",
            candidate_signal=ANY,
        )
        candidate_signal = ai_director.decide.call_args.kwargs["candidate_signal"]
        self.assertEqual(candidate_signal.stream_id, "player_2")
        self.assertEqual(candidate_signal.trigger_time_seconds, 21.0)
        self.assertIn("gaming callout phrase", candidate_signal.reason)
        self.assertIs(result.candidate_signal, candidate_signal)
        self.assertTrue(result.ai_evaluation_attempted)
        self.assertEqual(result.reason, "decision_evaluated")

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

    def test_runtime_event_does_not_log_transcript_text_by_default(self) -> None:
        scheduler = _started_scheduler()
        scheduler.set_ai_enabled(False)
        router = TranscriptRouter(history_seconds=30, max_messages=20)
        output = io.StringIO()

        process_transcript_event(
            TranscriptEvent(
                stream_id="player_2",
                text="secret strat callout",
                start_time_seconds=14.0,
                end_time_seconds=15.0,
            ),
            router,
            Mock(),
            scheduler,
            log=lambda message: print(message, file=output),
        )

        logs = output.getvalue()
        self.assertNotIn("Transcript text from", logs)
        self.assertNotIn("secret strat callout", logs)

    def test_runtime_event_logs_transcript_text_when_enabled(self) -> None:
        scheduler = _started_scheduler()
        scheduler.set_ai_enabled(False)
        router = TranscriptRouter(history_seconds=30, max_messages=20)
        output = io.StringIO()

        process_transcript_event(
            TranscriptEvent(
                stream_id="player_2",
                text="holy   cow\nthat was unreal",
                start_time_seconds=14.0,
                end_time_seconds=15.0,
            ),
            router,
            Mock(),
            scheduler,
            log_transcript_text=True,
            log=lambda message: print(message, file=output),
        )

        self.assertIn(
            "Transcript text from player_2: holy cow that was unreal",
            output.getvalue(),
        )

    def test_runtime_event_truncates_logged_transcript_text(self) -> None:
        scheduler = _started_scheduler()
        scheduler.set_ai_enabled(False)
        router = TranscriptRouter(history_seconds=30, max_messages=20)
        output = io.StringIO()

        process_transcript_event(
            TranscriptEvent(
                stream_id="player_1",
                text="abcdefghijklmnopqrstuvwxyz",
                start_time_seconds=14.0,
                end_time_seconds=15.0,
            ),
            router,
            Mock(),
            scheduler,
            log_transcript_text=True,
            transcript_log_text_max_characters=10,
            log=lambda message: print(message, file=output),
        )

        logs = output.getvalue()
        self.assertIn("Transcript text from player_1: abcdefg...", logs)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", logs)

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

    def test_live_queue_sink_routes_final_event_on_orchestrator_thread(self) -> None:
        event_queue: queue.Queue[TranscriptEvent] = queue.Queue(maxsize=2)
        sink_output = io.StringIO()
        sink = LiveTranscriptQueueSink(
            event_queue,
            log=lambda message: print(message, file=sink_output),
        )
        event = TranscriptEvent(
            stream_id="player_2",
            text="no way, found diamonds",
            start_time_seconds=30.0,
            end_time_seconds=31.0,
        )

        accepted = sink(event)

        self.assertIs(accepted, event)
        queued_event = event_queue.get_nowait()
        scheduler = _started_scheduler()
        scheduler.set_ai_enabled(False)
        router = TranscriptRouter(history_seconds=30, max_messages=20)
        ai_director = Mock()
        result = RuntimeTranscriptEventHandler(
            transcript_router=router,
            ai_director=ai_director,
            scheduler=scheduler,
            log=lambda message: None,
        )(queued_event)

        ai_director.decide.assert_not_called()
        self.assertIsNotNone(result)
        self.assertTrue(result.accepted)
        self.assertEqual(
            router.get_recent_context_text(),
            "player_2: no way, found diamonds",
        )
        self.assertEqual(sink_output.getvalue(), "")

    def test_live_queue_sink_ignores_partial_events(self) -> None:
        event_queue: queue.Queue[TranscriptEvent] = queue.Queue(maxsize=2)
        output = io.StringIO()
        sink = LiveTranscriptQueueSink(
            event_queue,
            log=lambda message: print(message, file=output),
        )

        accepted = sink(
            TranscriptEvent(
                stream_id="player_3",
                text="still thinking",
                start_time_seconds=40.0,
                end_time_seconds=41.0,
                is_final=False,
            )
        )

        self.assertIsNone(accepted)
        self.assertTrue(event_queue.empty())
        self.assertIn("Ignoring partial live transcript event", output.getvalue())

    def test_live_queue_sink_drops_newest_event_when_queue_is_full(self) -> None:
        event_queue: queue.Queue[TranscriptEvent] = queue.Queue(maxsize=1)
        first_event = TranscriptEvent("player_1", "first", 1.0, 2.0)
        event_queue.put_nowait(first_event)
        output = io.StringIO()
        sink = LiveTranscriptQueueSink(
            event_queue,
            log=lambda message: print(message, file=output),
        )

        accepted = sink(TranscriptEvent("player_4", "newest", 3.0, 4.0))

        self.assertIsNone(accepted)
        self.assertIs(event_queue.get_nowait(), first_event)
        self.assertIn("queue full; dropping newest", output.getvalue())

    def test_partial_runtime_event_is_not_added_to_history(self) -> None:
        scheduler = _started_scheduler()
        router = TranscriptRouter(history_seconds=30, max_messages=20)
        ai_director = Mock()
        output = io.StringIO()

        result = process_transcript_event(
            TranscriptEvent(
                stream_id="player_1",
                text="partial phrase",
                start_time_seconds=50.0,
                end_time_seconds=51.0,
                is_final=False,
            ),
            router,
            ai_director,
            scheduler,
            log=lambda message: print(message, file=output),
        )

        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "partial_event")
        self.assertEqual(router.get_recent_messages(), [])
        ai_director.decide.assert_not_called()
        self.assertIn("Ignoring partial transcript event", output.getvalue())

    def test_orchestrator_loop_drains_live_events_and_stops_source_on_eof(self) -> None:
        scheduler = _started_scheduler()
        scheduler.set_ai_enabled(False)
        router = TranscriptRouter(history_seconds=30, max_messages=20)
        ai_director = Mock()
        input_queue: queue.Queue[str | None] = queue.Queue()
        input_queue.put(INPUT_CLOSED)
        source = FakeLiveTranscriptionSource(
            [
                TranscriptEvent(
                    stream_id="player_4",
                    text="holy cow, look",
                    start_time_seconds=60.0,
                    end_time_seconds=61.0,
                )
            ]
        )

        with redirect_stdout(io.StringIO()):
            exit_code = run_orchestrator_loop(
                input_queue=input_queue,
                transcript_router=router,
                ai_director=ai_director,
                scheduler=scheduler,
                live_transcription_source=source,
                tick_interval_seconds=0.001,
                log=lambda message: None,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(source.stop_calls, 1)
        ai_director.decide.assert_not_called()
        self.assertEqual(router.get_recent_context_text(), "player_4: holy cow, look")

    def test_orchestrator_loop_stops_live_source_on_quit_command(self) -> None:
        input_queue: queue.Queue[str | None] = queue.Queue()
        input_queue.put("/quit")
        source = FakeLiveTranscriptionSource()

        with redirect_stdout(io.StringIO()):
            exit_code = run_orchestrator_loop(
                input_queue=input_queue,
                transcript_router=TranscriptRouter(),
                ai_director=Mock(),
                scheduler=FakeLoopScheduler(),
                live_transcription_source=source,
                tick_interval_seconds=0.001,
                log=lambda message: None,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(source.stop_calls, 1)

    def test_orchestrator_loop_stops_live_source_on_keyboard_interrupt(self) -> None:
        source = FakeLiveTranscriptionSource()

        with redirect_stdout(io.StringIO()):
            exit_code = run_orchestrator_loop(
                input_queue=queue.Queue(),
                transcript_router=TranscriptRouter(),
                ai_director=Mock(),
                scheduler=FakeLoopScheduler(raise_keyboard_interrupt=True),
                live_transcription_source=source,
                tick_interval_seconds=0.001,
                log=lambda message: None,
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(source.stop_calls, 1)

    def test_live_transcription_source_surfaces_startup_failure(self) -> None:
        output = io.StringIO()
        worker = FakeLiveWorker(RuntimeError("input unavailable"))
        source = LiveTranscriptionSource(
            worker=worker,
            event_queue=queue.Queue(),
            startup_timeout_seconds=0.1,
            log=lambda message: print(message, file=output),
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "Live transcription source failed to start",
        ):
            source.start()

        self.assertTrue(worker.stop_event.is_set())
        self.assertEqual(worker.run_calls, 1)
        self.assertIn("input unavailable", output.getvalue())

    def test_live_transcription_source_waits_until_worker_has_started(self) -> None:
        started_event = threading.Event()
        worker = FakeLiveWorker(started_event=started_event)
        source = LiveTranscriptionSource(
            worker=worker,
            event_queue=queue.Queue(),
            started_event=started_event,
            startup_timeout_seconds=0.5,
            log=lambda message: None,
        )

        source.start()
        source.stop()

        self.assertEqual(worker.run_calls, 1)
        self.assertTrue(worker.stop_event.is_set())

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


class FakeLiveTranscriptionSource:
    def __init__(self, events: list[TranscriptEvent] | None = None) -> None:
        self.events: queue.Queue[TranscriptEvent] = queue.Queue()
        for event in events or []:
            self.events.put_nowait(event)
        self.stop_calls = 0

    def get_nowait(self) -> TranscriptEvent:
        return self.events.get_nowait()

    def stop(self) -> None:
        self.stop_calls += 1


class FakeLiveWorker:
    def __init__(
        self,
        error: Exception | None = None,
        *,
        started_event: threading.Event | None = None,
    ) -> None:
        self.error = error
        self.started_event = started_event
        self.stop_event = threading.Event()
        self.run_calls = 0

    def run_forever(self) -> None:
        self.run_calls += 1
        if self.error is not None:
            raise self.error
        if self.started_event is not None:
            self.started_event.set()
        self.stop_event.wait(1.0)


class FakeLoopScheduler:
    def __init__(self, *, raise_keyboard_interrupt: bool = False) -> None:
        self.raise_keyboard_interrupt = raise_keyboard_interrupt
        self.tick_calls = 0

    def tick(self) -> None:
        self.tick_calls += 1
        if self.raise_keyboard_interrupt:
            raise KeyboardInterrupt


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
