import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from config import get_config  # noqa: E402
from contracts import TranscriptEvent  # noqa: E402
from services.transcription import (  # noqa: E402
    AudioInputRef,
    FasterWhisperTranscriber,
    TranscriptionError,
)
from transcript_router import TranscriptRouter  # noqa: E402


class FakeResponse:
    def __init__(
        self,
        payload,
        error: Exception | None = None,
        json_error: Exception | None = None,
    ) -> None:
        self.payload = payload
        self.error = error
        self.json_error = json_error

    def raise_for_status(self) -> None:
        if self.error is not None:
            raise self.error

    def json(self):
        if self.json_error is not None:
            raise self.json_error
        return self.payload


class FasterWhisperTranscriberTests(unittest.TestCase):
    def test_app_config_exposes_transcription_timeout(self) -> None:
        with patch.dict(
            os.environ,
            {"TRANSCRIPTION_REQUEST_TIMEOUT_SECONDS": "12.5"},
            clear=True,
        ):
            config = get_config()

        self.assertEqual(config.transcription_request_timeout_seconds, 12.5)

    def test_transcribes_segments_and_shifts_chunk_relative_timestamps(self) -> None:
        calls = []

        def post(url, **kwargs):
            calls.append((url, kwargs))
            return FakeResponse(
                {
                    "segments": [
                        {"text": "holy cow", "start": 1.25, "end": 2.5},
                        {
                            "text": "look at this",
                            "start": 2.5,
                            "end": 3.0,
                            "is_final": False,
                        },
                    ]
                }
            )

        audio = AudioInputRef(
            stream_id="player_3",
            uri="file:///tmp/player_3.wav",
            starts_at_seconds=100.0,
            duration_seconds=5.0,
            sample_rate_hz=16000,
            channels=1,
        )

        events = FasterWhisperTranscriber(
            "http://whisper:8000",
            timeout_seconds=7,
            post=post,
        ).transcribe(audio)

        self.assertEqual(calls[0][0], "http://whisper:8000/transcribe")
        self.assertEqual(calls[0][1]["timeout"], 7.0)
        self.assertEqual(calls[0][1]["json"]["stream_id"], "player_3")
        self.assertEqual(calls[0][1]["json"]["audio_uri"], audio.uri)
        self.assertEqual(events[0].stream_id, "player_3")
        self.assertEqual(events[0].text, "holy cow")
        self.assertEqual(events[0].start_time_seconds, 101.25)
        self.assertEqual(events[0].end_time_seconds, 102.5)
        self.assertFalse(events[1].is_final)

    def test_accepts_single_text_response_shape(self) -> None:
        transcriber = FasterWhisperTranscriber(
            "http://whisper:8000",
            post=lambda *args, **kwargs: FakeResponse(
                {"text": "rare fish", "start_seconds": 0, "end_seconds": 1.5}
            ),
        )

        events = transcriber.transcribe(
            AudioInputRef(
                stream_id="player_2",
                uri="file:///tmp/player_2.wav",
                starts_at_seconds=40.0,
            )
        )

        self.assertEqual(
            events,
            (
                TranscriptEvent(
                    stream_id="player_2",
                    text="rare fish",
                    start_time_seconds=40.0,
                    end_time_seconds=41.5,
                    is_final=True,
                ),
            ),
        )

    def test_request_failures_surface_as_transcription_errors(self) -> None:
        transcriber = FasterWhisperTranscriber(
            "http://whisper:8000",
            post=lambda *args, **kwargs: FakeResponse({}, error=RuntimeError("boom")),
        )

        with self.assertRaisesRegex(TranscriptionError, "boom"):
            transcriber.transcribe(AudioInputRef(stream_id="player_1", uri="x"))

    def test_invalid_json_surfaces_as_transcription_error(self) -> None:
        transcriber = FasterWhisperTranscriber(
            "http://whisper:8000",
            post=lambda *args, **kwargs: FakeResponse(
                {},
                json_error=ValueError("not json"),
            ),
        )

        with self.assertRaisesRegex(TranscriptionError, "not json"):
            transcriber.transcribe(AudioInputRef(stream_id="player_1", uri="x"))

    def test_unexpected_response_shape_fails_clearly(self) -> None:
        transcriber = FasterWhisperTranscriber(
            "http://whisper:8000",
            post=lambda *args, **kwargs: FakeResponse({"segments": {"text": "nope"}}),
        )

        with self.assertRaisesRegex(TranscriptionError, "segments must be a list"):
            transcriber.transcribe(AudioInputRef(stream_id="player_1", uri="x"))

    def test_invalid_segment_timestamps_fail_clearly(self) -> None:
        transcriber = FasterWhisperTranscriber(
            "http://whisper:8000",
            post=lambda *args, **kwargs: FakeResponse(
                {"segments": [{"text": "bad time", "start": 2, "end": 1}]}
            ),
        )

        with self.assertRaisesRegex(TranscriptionError, "end must be after start"):
            transcriber.transcribe(AudioInputRef(stream_id="player_1", uri="x"))


class TranscriptRouterEventTests(unittest.TestCase):
    def test_add_event_preserves_stream_text_and_end_timestamp(self) -> None:
        router = TranscriptRouter(history_seconds=30, max_messages=10)
        event = TranscriptEvent(
            stream_id="player_4",
            text="found the boss room",
            start_time_seconds=10.0,
            end_time_seconds=12.0,
        )

        message = router.add_event(event)

        self.assertIsNotNone(message)
        self.assertEqual(message.speaker, "player_4")
        self.assertEqual(message.text, "found the boss room")
        self.assertEqual(message.timestamp, 12.0)
        self.assertEqual(
            router.get_recent_context_text(),
            "player_4: found the boss room",
        )
        recent_events = router.get_recent_events()
        self.assertEqual(len(recent_events), 1)
        self.assertEqual(recent_events[0].stream_id, "player_4")
        self.assertEqual(recent_events[0].text, "found the boss room")
        self.assertEqual(recent_events[0].end_time_seconds, 12.0)

    def test_add_event_rejects_unknown_streams(self) -> None:
        router = TranscriptRouter()

        self.assertIsNone(
            router.add_event(
                TranscriptEvent(
                    stream_id="player_9",
                    text="hello",
                    start_time_seconds=0,
                    end_time_seconds=1,
                )
            )
        )

    def test_add_event_rejects_blank_text_and_invalid_timestamps(self) -> None:
        router = TranscriptRouter()

        self.assertIsNone(
            router.add_event(
                TranscriptEvent(
                    stream_id="player_1",
                    text="   ",
                    start_time_seconds=0,
                    end_time_seconds=1,
                )
            )
        )
        self.assertIsNone(
            router.add_event(
                TranscriptEvent(
                    stream_id="player_1",
                    text="time broke",
                    start_time_seconds=2,
                    end_time_seconds=1,
                )
            )
        )


if __name__ == "__main__":
    unittest.main()
