import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from config import (  # noqa: E402
    TRANSCRIPTION_REQUEST_MODE_OPENAI_COMPATIBLE,
    get_config,
)
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
        text: str = "",
    ) -> None:
        self.payload = payload
        self.error = error
        self.json_error = json_error
        self.text = text

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

    def test_app_config_exposes_openai_compatible_transcription_settings(self) -> None:
        with patch.dict(
            os.environ,
            {
                "TRANSCRIPTION_REQUEST_MODE": "openai",
                "TRANSCRIPTION_ENDPOINT_PATH": "/custom/audio/transcriptions",
                "TRANSCRIPTION_MODEL": "local-whisper",
                "TRANSCRIPTION_LANGUAGE": "en",
                "TRANSCRIPTION_RESPONSE_FORMAT": "verbose_json",
            },
            clear=True,
        ):
            config = get_config()

        self.assertEqual(
            config.transcription_request_mode,
            TRANSCRIPTION_REQUEST_MODE_OPENAI_COMPATIBLE,
        )
        self.assertEqual(
            config.transcription_endpoint_path,
            "/custom/audio/transcriptions",
        )
        self.assertEqual(config.transcription_model, "local-whisper")
        self.assertEqual(config.transcription_language, "en")
        self.assertEqual(config.transcription_response_format, "verbose_json")

    def test_invalid_transcription_request_mode_fails_clearly(self) -> None:
        with patch.dict(
            os.environ,
            {"TRANSCRIPTION_REQUEST_MODE": "mystery"},
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "TRANSCRIPTION_REQUEST_MODE"):
                get_config()

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

    def test_openai_compatible_uploads_local_file_without_auth(self) -> None:
        calls = []

        def post(url, **kwargs):
            file_name, file_obj = kwargs["files"]["file"]
            calls.append(
                {
                    "url": url,
                    "timeout": kwargs["timeout"],
                    "data": dict(kwargs["data"]),
                    "file_name": file_name,
                    "file_bytes": file_obj.read(),
                    "has_json": "json" in kwargs,
                    "has_headers": "headers" in kwargs,
                }
            )
            return FakeResponse({"text": "rare fish", "start": 0, "end": 2})

        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = Path(tmpdir) / "chunk.wav"
            audio_path.write_bytes(b"wav-data")
            events = FasterWhisperTranscriber(
                "http://whisper:8000",
                timeout_seconds=8,
                request_mode="openai-compatible",
                model="Systran/faster-whisper-small",
                language="en",
                response_format="json",
                post=post,
            ).transcribe(
                AudioInputRef(
                    stream_id="player_1",
                    uri=audio_path.as_uri(),
                    starts_at_seconds=25,
                    duration_seconds=5,
                )
            )

        self.assertEqual(
            calls[0]["url"],
            "http://whisper:8000/v1/audio/transcriptions",
        )
        self.assertEqual(calls[0]["timeout"], 8.0)
        self.assertEqual(calls[0]["data"]["model"], "Systran/faster-whisper-small")
        self.assertEqual(calls[0]["data"]["language"], "en")
        self.assertEqual(calls[0]["data"]["response_format"], "json")
        self.assertEqual(calls[0]["file_name"], "chunk.wav")
        self.assertEqual(calls[0]["file_bytes"], b"wav-data")
        self.assertFalse(calls[0]["has_json"])
        self.assertFalse(calls[0]["has_headers"])
        self.assertEqual(events[0].stream_id, "player_1")
        self.assertEqual(events[0].start_time_seconds, 25.0)
        self.assertEqual(events[0].end_time_seconds, 27.0)

    def test_openai_compatible_text_response_uses_audio_ref_duration(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = Path(tmpdir) / "chunk.wav"
            audio_path.write_bytes(b"wav-data")
            transcriber = FasterWhisperTranscriber(
                "http://whisper:8000",
                request_mode="openai-compatible",
                response_format="text",
                post=lambda *args, **kwargs: FakeResponse(None, text="  rare fish  "),
            )

            events = transcriber.transcribe(
                AudioInputRef(
                    stream_id="player_2",
                    uri=str(audio_path),
                    starts_at_seconds=40.0,
                    duration_seconds=5.0,
                )
            )

        self.assertEqual(
            events,
            (
                TranscriptEvent(
                    stream_id="player_2",
                    text="rare fish",
                    start_time_seconds=40.0,
                    end_time_seconds=45.0,
                    is_final=True,
                ),
            ),
        )

    def test_openai_compatible_verbose_segments_preserve_chunk_offset(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = Path(tmpdir) / "chunk.wav"
            audio_path.write_bytes(b"wav-data")
            transcriber = FasterWhisperTranscriber(
                "http://whisper:8000",
                request_mode="openai-compatible",
                response_format="verbose_json",
                post=lambda *args, **kwargs: FakeResponse(
                    {
                        "text": "ignored aggregate",
                        "segments": [
                            {"text": "first", "start": 0.5, "end": 1.0},
                            {"text": "second", "start": 1.0, "end": 2.0},
                        ],
                    }
                ),
            )

            events = transcriber.transcribe(
                AudioInputRef(
                    stream_id="player_4",
                    uri=audio_path.as_uri(),
                    starts_at_seconds=10.0,
                    duration_seconds=5.0,
                )
            )

        self.assertEqual([event.text for event in events], ["first", "second"])
        self.assertEqual(events[0].start_time_seconds, 10.5)
        self.assertEqual(events[1].end_time_seconds, 12.0)

    def test_openai_compatible_rejects_remote_audio_ref(self) -> None:
        transcriber = FasterWhisperTranscriber(
            "http://whisper:8000",
            request_mode="openai-compatible",
            post=lambda *args, **kwargs: FakeResponse({}),
        )

        with self.assertRaisesRegex(TranscriptionError, "local file path"):
            transcriber.transcribe(
                AudioInputRef(
                    stream_id="player_1",
                    uri="https://media.example/chunk.wav",
                    duration_seconds=5,
                )
            )

    def test_openai_compatible_rejects_missing_audio_file(self) -> None:
        transcriber = FasterWhisperTranscriber(
            "http://whisper:8000",
            request_mode="openai-compatible",
            post=lambda *args, **kwargs: FakeResponse({}),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            missing_path = Path(tmpdir) / "missing.wav"
            with self.assertRaisesRegex(TranscriptionError, "not readable"):
                transcriber.transcribe(
                    AudioInputRef(
                        stream_id="player_1",
                        uri=str(missing_path),
                        duration_seconds=5,
                    )
                )

    def test_text_response_without_duration_fails_clearly(self) -> None:
        transcriber = FasterWhisperTranscriber(
            "http://whisper:8000",
            post=lambda *args, **kwargs: FakeResponse({"text": "no timestamps"}),
        )

        with self.assertRaisesRegex(TranscriptionError, "audio duration"):
            transcriber.transcribe(AudioInputRef(stream_id="player_1", uri="x"))

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
        self.assertEqual(recent_events[0].start_time_seconds, 10.0)
        self.assertEqual(recent_events[0].end_time_seconds, 12.0)

    def test_short_gap_same_stream_events_assemble_into_candidate(self) -> None:
        router = TranscriptRouter(history_seconds=30, max_messages=10)
        router.add_event(TranscriptEvent("player_2", " holy ", 10.0, 10.5))
        router.add_event(TranscriptEvent("player_2", " cow ", 11.0, 11.5))

        candidates = router.get_recent_utterance_candidates()

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].stream_id, "player_2")
        self.assertEqual(candidates[0].text, "holy cow")
        self.assertEqual(candidates[0].start_time_seconds, 10.0)
        self.assertEqual(candidates[0].end_time_seconds, 11.5)
        self.assertEqual(candidates[0].source_event_count, 2)
        self.assertEqual(candidates[0].source_start_index, 0)
        self.assertEqual(candidates[0].source_end_index, 1)
        self.assertEqual(router.get_recent_context_text(), "player_2: holy cow")
        self.assertEqual(router.get_recent_candidate_events()[0].text, "holy cow")

    def test_long_gap_splits_candidates_by_event_timestamps(self) -> None:
        router = TranscriptRouter(
            history_seconds=30,
            max_messages=10,
            utterance_max_gap_seconds=2.0,
        )
        router.add_event(TranscriptEvent("player_2", "holy", 10.0, 10.5))
        router.add_event(TranscriptEvent("player_2", "cow", 12.6, 13.0))

        self.assertEqual(
            [candidate.text for candidate in router.get_recent_utterance_candidates()],
            ["holy", "cow"],
        )

    def test_stream_change_splits_candidates(self) -> None:
        router = TranscriptRouter(history_seconds=30, max_messages=10)
        router.add_event(TranscriptEvent("player_1", "holy", 10.0, 10.5))
        router.add_event(TranscriptEvent("player_2", "cow", 10.6, 11.0))

        self.assertEqual(
            [
                (candidate.stream_id, candidate.text)
                for candidate in router.get_recent_utterance_candidates()
            ],
            [("player_1", "holy"), ("player_2", "cow")],
        )

    def test_duration_bound_splits_before_overflowing_event(self) -> None:
        router = TranscriptRouter(
            history_seconds=30,
            max_messages=10,
            utterance_max_duration_seconds=2.0,
        )
        router.add_event(TranscriptEvent("player_1", "first", 10.0, 10.5))
        router.add_event(TranscriptEvent("player_1", "second", 11.0, 12.5))

        self.assertEqual(
            [candidate.text for candidate in router.get_recent_utterance_candidates()],
            ["first", "second"],
        )

    def test_sentence_punctuation_splits_before_next_event(self) -> None:
        router = TranscriptRouter(history_seconds=30, max_messages=10)
        router.add_event(TranscriptEvent("player_1", "holy cow!", 10.0, 10.5))
        router.add_event(TranscriptEvent("player_1", "look", 10.6, 11.0))

        self.assertEqual(
            [candidate.text for candidate in router.get_recent_utterance_candidates()],
            ["holy cow!", "look"],
        )

    def test_comma_does_not_split_candidates(self) -> None:
        router = TranscriptRouter(history_seconds=30, max_messages=10)
        router.add_event(TranscriptEvent("player_1", "holy,", 10.0, 10.5))
        router.add_event(TranscriptEvent("player_1", "cow", 10.6, 11.0))

        self.assertEqual(
            [candidate.text for candidate in router.get_recent_utterance_candidates()],
            ["holy, cow"],
        )

    def test_character_bound_splits_before_overflowing_event(self) -> None:
        router = TranscriptRouter(
            history_seconds=30,
            max_messages=10,
            utterance_max_characters=10,
        )
        router.add_event(TranscriptEvent("player_3", "12345", 10.0, 10.5))
        router.add_event(TranscriptEvent("player_3", "67890", 10.6, 11.0))

        self.assertEqual(
            [candidate.text for candidate in router.get_recent_utterance_candidates()],
            ["12345", "67890"],
        )

    def test_event_count_bound_splits_before_overflowing_event(self) -> None:
        router = TranscriptRouter(
            history_seconds=30,
            max_messages=10,
            utterance_max_events=2,
        )
        router.add_event(TranscriptEvent("player_4", "one", 10.0, 10.1))
        router.add_event(TranscriptEvent("player_4", "two", 10.2, 10.3))
        router.add_event(TranscriptEvent("player_4", "three", 10.4, 10.5))

        self.assertEqual(
            [candidate.text for candidate in router.get_recent_utterance_candidates()],
            ["one two", "three"],
        )

    def test_candidates_reflect_trimmed_recent_history(self) -> None:
        router = TranscriptRouter(history_seconds=30, max_messages=2)
        router.add_event(TranscriptEvent("player_4", "one", 10.0, 10.1))
        router.add_event(TranscriptEvent("player_4", "two", 10.2, 10.3))
        router.add_event(TranscriptEvent("player_4", "three", 10.4, 10.5))

        candidates = router.get_recent_utterance_candidates()

        self.assertEqual([candidate.text for candidate in candidates], ["two three"])
        self.assertEqual(candidates[0].source_start_index, 0)
        self.assertEqual(candidates[0].source_end_index, 1)

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
