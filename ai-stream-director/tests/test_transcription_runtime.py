import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from contracts import TranscriptEvent  # noqa: E402
from services.transcription import AudioInputRef, TranscriptionError  # noqa: E402
from services.transcription_runtime import (  # noqa: E402
    TranscriptionRuntimePump,
    run_transcription_pump,
)
from transcript_router import TranscriptRouter  # noqa: E402


def audio_ref(
    stream_id: str,
    uri: str = "file:///tmp/chunk.wav",
    *,
    emit_from_seconds: float | None = None,
) -> AudioInputRef:
    return AudioInputRef(
        stream_id=stream_id,
        uri=uri,
        emit_from_seconds=emit_from_seconds,
    )


class FakeTranscriber:
    def __init__(self, outputs) -> None:
        self.outputs = list(outputs)
        self.calls: list[AudioInputRef] = []

    def transcribe(self, audio: AudioInputRef):
        self.calls.append(audio)
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return output


class TranscriptionRuntimePumpTests(unittest.TestCase):
    def test_pumps_events_into_router_preserving_stream_and_end_timestamp(self) -> None:
        router = TranscriptRouter(history_seconds=30, max_messages=10)
        transcriber = FakeTranscriber(
            [
                [
                    TranscriptEvent(
                        stream_id="player_3",
                        text="found the boss room",
                        start_time_seconds=100.5,
                        end_time_seconds=102.25,
                    )
                ]
            ]
        )

        summary = TranscriptionRuntimePump(
            transcriber=transcriber,
            sink=router.add_event,
        ).run_once([audio_ref("player_3")])

        messages = router.get_recent_messages()
        self.assertEqual(summary.processed_audio_refs, 1)
        self.assertEqual(summary.emitted_transcript_events, 1)
        self.assertEqual(summary.accepted_events, 1)
        self.assertEqual(summary.rejected_events, 0)
        self.assertEqual(summary.failed_audio_refs, 0)
        self.assertEqual(messages[0].speaker, "player_3")
        self.assertEqual(messages[0].text, "found the boss room")
        self.assertEqual(messages[0].timestamp, 102.25)

    def test_counts_router_rejections_without_treating_them_as_failures(self) -> None:
        router = TranscriptRouter(history_seconds=30, max_messages=10)
        transcriber = FakeTranscriber(
            [
                [
                    TranscriptEvent(
                        stream_id="player_9",
                        text="wrong room",
                        start_time_seconds=5.0,
                        end_time_seconds=6.0,
                    )
                ]
            ]
        )

        summary = run_transcription_pump(
            [audio_ref("player_9")],
            transcriber,
            router.add_event,
        )

        self.assertEqual(summary.processed_audio_refs, 1)
        self.assertEqual(summary.emitted_transcript_events, 1)
        self.assertEqual(summary.accepted_events, 0)
        self.assertEqual(summary.rejected_events, 1)
        self.assertEqual(summary.failed_audio_refs, 0)
        self.assertEqual(router.get_recent_messages(), [])

    def test_overlap_only_events_are_rejected_without_calling_sink(self) -> None:
        sink_calls: list[TranscriptEvent] = []
        transcriber = FakeTranscriber(
            [
                [
                    TranscriptEvent(
                        stream_id="player_1",
                        text="old tail",
                        start_time_seconds=8.0,
                        end_time_seconds=10.0,
                    )
                ]
            ]
        )

        summary = run_transcription_pump(
            [audio_ref("player_1", emit_from_seconds=10.0)],
            transcriber,
            sink_calls.append,
        )

        self.assertEqual(summary.emitted_transcript_events, 1)
        self.assertEqual(summary.accepted_events, 0)
        self.assertEqual(summary.rejected_events, 1)
        self.assertEqual(summary.failed_audio_refs, 0)
        self.assertEqual(sink_calls, [])

    def test_boundary_spanning_overlap_events_are_emitted(self) -> None:
        sink_calls: list[TranscriptEvent] = []
        event = TranscriptEvent(
            stream_id="player_2",
            text="crosses boundary",
            start_time_seconds=9.75,
            end_time_seconds=10.25,
        )
        transcriber = FakeTranscriber([[event]])

        summary = run_transcription_pump(
            [audio_ref("player_2", emit_from_seconds=10.0)],
            transcriber,
            lambda emitted: sink_calls.append(emitted) or emitted,
        )

        self.assertEqual(summary.accepted_events, 1)
        self.assertEqual(summary.rejected_events, 0)
        self.assertEqual(sink_calls, [event])

    def test_overlap_filter_does_not_apply_to_other_stream_events(self) -> None:
        sink_calls: list[TranscriptEvent] = []
        event = TranscriptEvent(
            stream_id="player_4",
            text="wrong stream but not filtered here",
            start_time_seconds=8.0,
            end_time_seconds=9.0,
        )
        transcriber = FakeTranscriber([[event]])

        summary = run_transcription_pump(
            [audio_ref("player_3", emit_from_seconds=10.0)],
            transcriber,
            lambda emitted: sink_calls.append(emitted) or emitted,
        )

        self.assertEqual(summary.accepted_events, 1)
        self.assertEqual(summary.rejected_events, 0)
        self.assertEqual(sink_calls, [event])

    def test_transcription_errors_are_counted_and_later_refs_continue(self) -> None:
        router = TranscriptRouter(history_seconds=30, max_messages=10)
        transcriber = FakeTranscriber(
            [
                TranscriptionError("first chunk failed"),
                [
                    TranscriptEvent(
                        stream_id="player_2",
                        text="second chunk works",
                        start_time_seconds=8.0,
                        end_time_seconds=9.5,
                    )
                ],
            ]
        )

        summary = TranscriptionRuntimePump(
            transcriber=transcriber,
            sink=router.add_event,
        ).run_once([audio_ref("player_1"), audio_ref("player_2")])

        self.assertEqual(summary.processed_audio_refs, 2)
        self.assertEqual(summary.emitted_transcript_events, 1)
        self.assertEqual(summary.accepted_events, 1)
        self.assertEqual(summary.rejected_events, 0)
        self.assertEqual(summary.failed_audio_refs, 1)
        self.assertEqual(summary.failures[0].audio_ref.stream_id, "player_1")
        self.assertIn("first chunk failed", summary.failures[0].message)
        self.assertEqual(router.get_recent_context_text(), "player_2: second chunk works")

    def test_malformed_output_is_counted_and_later_refs_continue(self) -> None:
        router = TranscriptRouter(history_seconds=30, max_messages=10)
        transcriber = FakeTranscriber(
            [
                ["not an event"],
                [
                    TranscriptEvent(
                        stream_id="player_4",
                        text="still running",
                        start_time_seconds=12.0,
                        end_time_seconds=13.0,
                    )
                ],
            ]
        )

        summary = TranscriptionRuntimePump(
            transcriber=transcriber,
            sink=router.add_event,
        ).run_once([audio_ref("player_1"), audio_ref("player_4")])

        self.assertEqual(summary.processed_audio_refs, 2)
        self.assertEqual(summary.emitted_transcript_events, 1)
        self.assertEqual(summary.accepted_events, 1)
        self.assertEqual(summary.failed_audio_refs, 1)
        self.assertIn("non-TranscriptEvent", summary.failures[0].message)
        self.assertEqual(router.get_recent_context_text(), "player_4: still running")

    def test_fail_fast_raises_on_first_transcription_failure(self) -> None:
        transcriber = FakeTranscriber(
            [
                TranscriptionError("startup validation failed"),
                [
                    TranscriptEvent(
                        stream_id="player_2",
                        text="should not run",
                        start_time_seconds=1.0,
                        end_time_seconds=2.0,
                    )
                ],
            ]
        )
        accepted_events: list[TranscriptEvent] = []

        with self.assertRaisesRegex(TranscriptionError, "startup validation failed"):
            TranscriptionRuntimePump(
                transcriber=transcriber,
                sink=accepted_events.append,
                fail_fast=True,
            ).run_once([audio_ref("player_1"), audio_ref("player_2")])

        self.assertEqual([call.stream_id for call in transcriber.calls], ["player_1"])
        self.assertEqual(accepted_events, [])

    def test_none_transcriber_output_is_malformed(self) -> None:
        transcriber = FakeTranscriber([None, []])

        summary = TranscriptionRuntimePump(
            transcriber=transcriber,
            sink=lambda event: event,
        ).run_once([audio_ref("player_1"), audio_ref("player_2")])

        self.assertEqual(summary.processed_audio_refs, 2)
        self.assertEqual(summary.emitted_transcript_events, 0)
        self.assertEqual(summary.failed_audio_refs, 1)
        self.assertIn("returned None", summary.failures[0].message)

    def test_final_only_mode_rejects_provider_partials(self) -> None:
        partial = TranscriptEvent(
            stream_id="player_1",
            text="still talking",
            start_time_seconds=1.0,
            end_time_seconds=2.0,
            is_final=False,
        )
        sink_calls: list[TranscriptEvent] = []

        summary = TranscriptionRuntimePump(
            transcriber=FakeTranscriber([[partial]]),
            sink=sink_calls.append,
            final_events_only=True,
        ).run_once([audio_ref("player_1")])

        self.assertEqual(summary.emitted_transcript_events, 1)
        self.assertEqual(summary.accepted_events, 0)
        self.assertEqual(summary.rejected_events, 1)
        self.assertEqual(sink_calls, [])

    def test_non_newer_final_suppression_uses_timestamps_not_text(self) -> None:
        first = TranscriptEvent(
            stream_id="player_1",
            text="same phrase",
            start_time_seconds=1.0,
            end_time_seconds=2.0,
        )
        repeated_old = TranscriptEvent(
            stream_id="player_1",
            text="same phrase",
            start_time_seconds=1.0,
            end_time_seconds=2.0,
        )
        repeated_new = TranscriptEvent(
            stream_id="player_1",
            text="same phrase",
            start_time_seconds=3.0,
            end_time_seconds=4.0,
        )
        sink_calls: list[TranscriptEvent] = []

        pump = TranscriptionRuntimePump(
            transcriber=FakeTranscriber([[first], [repeated_old], [repeated_new]]),
            sink=lambda event: sink_calls.append(event) or event,
            suppress_non_newer_final_events=True,
        )
        first_summary = pump.run_once([audio_ref("player_1")])
        old_summary = pump.run_once([audio_ref("player_1")])
        new_summary = pump.run_once([audio_ref("player_1")])

        self.assertEqual(first_summary.accepted_events, 1)
        self.assertEqual(old_summary.accepted_events, 0)
        self.assertEqual(old_summary.rejected_events, 1)
        self.assertEqual(new_summary.accepted_events, 1)
        self.assertEqual(sink_calls, [first, repeated_new])


if __name__ == "__main__":
    unittest.main()
