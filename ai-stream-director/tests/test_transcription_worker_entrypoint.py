import io
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from contracts import TranscriptEvent  # noqa: E402
from services.transcription import (  # noqa: E402
    AudioExtractionConfig,
    AudioInputRef,
    FixtureAudioExtractor,
    TranscriptionError,
)
from transcription_worker import (  # noqa: E402
    CompletedAudioChunkDiscovery,
    JsonLinesTranscriptSink,
    SignalStopController,
    TranscriptionWorker,
    build_worker,
)


def audio_ref(stream_id: str, uri: str = "file:///tmp/chunk.wav") -> AudioInputRef:
    return AudioInputRef(stream_id=stream_id, uri=uri)


class FakeDiscovery:
    def __init__(self, refs: tuple[AudioInputRef, ...] = ()) -> None:
        self.refs = refs
        self.calls = 0

    def discover(self) -> tuple[AudioInputRef, ...]:
        self.calls += 1
        return self.refs


class FakeExtractor:
    def __init__(self) -> None:
        self.starts = 0
        self.stops = 0

    def start(self) -> None:
        self.starts += 1

    def stop(self) -> None:
        self.stops += 1

    def build_audio_ref(
        self,
        stream_id: str,
        chunk_path,
        starts_at_seconds: float | None = None,
    ) -> AudioInputRef:
        return AudioInputRef(
            stream_id=stream_id,
            uri=Path(chunk_path).resolve().as_uri(),
            starts_at_seconds=starts_at_seconds,
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


class TranscriptionWorkerEntrypointTests(unittest.TestCase):
    def test_build_worker_uses_app_config_for_runtime_components(self) -> None:
        stream = io.StringIO()
        stop_event = threading.Event()
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(
                os.environ,
                {
                    "AUDIO_EXTRACT_DIR": tmpdir,
                    "FFMPEG_EXECUTABLE": "ffmpeg-test",
                    "AUDIO_EXTRACT_SAMPLE_RATE": "24000",
                    "AUDIO_EXTRACT_CHANNELS": "2",
                    "AUDIO_EXTRACT_CHUNK_SECONDS": "3",
                    "AUDIO_EXTRACT_CODEC": "pcm_f32le",
                    "AUDIO_EXTRACT_CONTAINER": "wav",
                    "INGEST_API_URL": "rtmp://media/live",
                    "LOOKBACK_INPUT_URL_PLAYER_2": "srt://lookback-two",
                    "AUDIO_INPUT_URL_PLAYER_3": "rtmp://audio-three",
                    "TRANSCRIPTION_API_URL": "http://whisper-local:9000",
                    "TRANSCRIPTION_REQUEST_TIMEOUT_SECONDS": "4.5",
                },
                clear=True,
            ):
                worker = build_worker(stdout=stream, stop_event=stop_event)

        config = worker.extraction_config
        self.assertEqual(config.output_dir, Path(tmpdir))
        self.assertEqual(config.ffmpeg_executable, "ffmpeg-test")
        self.assertEqual(config.sample_rate_hz, 24000)
        self.assertEqual(config.channels, 2)
        self.assertEqual(config.chunk_duration_seconds, 3.0)
        self.assertEqual(config.codec, "pcm_f32le")
        self.assertEqual(config.stream_input_urls["player_1"], "rtmp://media/live/player_1")
        self.assertEqual(config.stream_input_urls["player_2"], "srt://lookback-two")
        self.assertEqual(config.stream_input_urls["player_3"], "rtmp://audio-three")
        self.assertEqual(worker.transcriber.api_url, "http://whisper-local:9000")
        self.assertEqual(worker.transcriber.timeout_seconds, 4.5)
        self.assertIs(worker.stop_event, stop_event)

    def test_completed_chunk_discovery_deduplicates_processed_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            stream_dir = Path(tmpdir) / "player_1"
            stream_dir.mkdir()
            chunk_path = stream_dir / "000000002.wav"
            chunk_path.write_bytes(b"audio")
            config = AudioExtractionConfig(
                output_dir=tmpdir,
                stream_input_urls={"player_1": "rtmp://media/live/player_1"},
                stream_ids=("player_1",),
                chunk_duration_seconds=5,
            )
            extractor = FixtureAudioExtractor(config)
            discovery = CompletedAudioChunkDiscovery(config, extractor)

            self.assertEqual(discovery.discover(), ())
            first_ready_pass = discovery.discover()
            second_ready_pass = discovery.discover()

        self.assertEqual(len(first_ready_pass), 1)
        self.assertEqual(first_ready_pass[0].stream_id, "player_1")
        self.assertEqual(first_ready_pass[0].starts_at_seconds, 10.0)
        self.assertEqual(second_ready_pass, ())

    def test_per_chunk_failure_isolation_emits_failure_and_later_event(self) -> None:
        stream = io.StringIO()
        sink = JsonLinesTranscriptSink(stream)
        refs = (audio_ref("player_1", "file:///tmp/one.wav"), audio_ref("player_2"))
        transcriber = FakeTranscriber(
            [
                TranscriptionError("endpoint unavailable"),
                [
                    TranscriptEvent(
                        stream_id="player_2",
                        text="still works",
                        start_time_seconds=3.0,
                        end_time_seconds=4.0,
                    )
                ],
            ]
        )
        worker = TranscriptionWorker(
            extraction_config=AudioExtractionConfig(
                output_dir="audio-cache",
                stream_input_urls={"player_1": "x"},
                stream_ids=("player_1",),
            ),
            extractor=FakeExtractor(),
            transcriber=transcriber,
            sink=sink,
            failure_sink=sink.write_failure,
            discovery=FakeDiscovery(refs),
        )

        summary = worker.run_once()
        payloads = [json.loads(line) for line in stream.getvalue().splitlines()]

        self.assertEqual(summary.processed_audio_refs, 2)
        self.assertEqual(summary.failed_audio_refs, 1)
        self.assertEqual([call.stream_id for call in transcriber.calls], ["player_1", "player_2"])
        self.assertEqual(payloads[0]["type"], "transcript_event")
        self.assertEqual(payloads[0]["stream_id"], "player_2")
        self.assertEqual(payloads[0]["text"], "still works")
        self.assertEqual(payloads[1]["type"], "transcription_failure")
        self.assertEqual(payloads[1]["stream_id"], "player_1")
        self.assertIn("endpoint unavailable", payloads[1]["message"])

    def test_stdout_event_shape_is_normalized_json_line(self) -> None:
        stream = io.StringIO()
        sink = JsonLinesTranscriptSink(stream)

        sink(
            TranscriptEvent(
                stream_id="player_4",
                text="found it",
                start_time_seconds=12.5,
                end_time_seconds=14.0,
                is_final=False,
            )
        )

        payload = json.loads(stream.getvalue())
        self.assertEqual(
            payload,
            {
                "type": "transcript_event",
                "stream_id": "player_4",
                "text": "found it",
                "start_time_seconds": 12.5,
                "end_time_seconds": 14.0,
                "is_final": False,
            },
        )

    def test_signal_stop_request_allows_worker_cleanup(self) -> None:
        stop_event = threading.Event()
        stop_controller = SignalStopController(stop_event=stop_event, signals=())
        extractor = FakeExtractor()
        worker = TranscriptionWorker(
            extraction_config=AudioExtractionConfig(
                output_dir="audio-cache",
                stream_input_urls={"player_1": "x"},
                stream_ids=("player_1",),
            ),
            extractor=extractor,
            transcriber=FakeTranscriber([]),
            sink=lambda event: event,
            discovery=FakeDiscovery(),
            stop_event=stop_event,
            wait=lambda seconds: stop_controller.request_stop() or stop_event.is_set(),
        )

        worker.run_forever()

        self.assertTrue(stop_event.is_set())
        self.assertEqual(extractor.starts, 1)
        self.assertEqual(extractor.stops, 1)


if __name__ == "__main__":
    unittest.main()
