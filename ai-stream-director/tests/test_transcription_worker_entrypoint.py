import io
import json
import os
import sys
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from unittest.mock import patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from contracts import TranscriptEvent  # noqa: E402
from config import TRANSCRIPTION_SOURCE_MODE_VAD_UTTERANCE, get_config  # noqa: E402
from services.transcription import (  # noqa: E402
    AudioExtractionConfig,
    AudioInputRef,
    FixtureAudioExtractor,
    TranscriptionError,
)
from transcription_worker import (  # noqa: E402
    CompletedAudioChunkDiscovery,
    JsonLinesTranscriptSink,
    OverlappedAudioWindowDiscovery,
    SignalStopController,
    TranscriptionWorker,
    VadUtteranceAudioWindowDiscovery,
    VadUtteranceConfig,
    build_transcription_event_source,
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
    def __init__(self, start_error: Exception | None = None) -> None:
        self.start_error = start_error
        self.starts = 0
        self.stops = 0

    def start(self) -> None:
        self.starts += 1
        if self.start_error is not None:
            raise self.start_error

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
                    "TRANSCRIPTION_REQUEST_MODE": "openai-compatible",
                    "TRANSCRIPTION_MODEL": "local-whisper",
                    "TRANSCRIPTION_RESPONSE_FORMAT": "verbose_json",
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
        self.assertEqual(worker.transcriber.request_mode, "openai-compatible")
        self.assertEqual(
            worker.transcriber.endpoint_path,
            "/v1/audio/transcriptions",
        )
        self.assertEqual(worker.transcriber.model, "local-whisper")
        self.assertEqual(worker.transcriber.response_format, "verbose_json")
        self.assertIs(worker.stop_event, stop_event)
        self.assertIsInstance(worker.discovery, CompletedAudioChunkDiscovery)

    def test_build_worker_wraps_discovery_when_overlap_is_enabled(self) -> None:
        stream = io.StringIO()
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(
                os.environ,
                {
                    "AUDIO_EXTRACT_DIR": tmpdir,
                    "AUDIO_EXTRACT_CHUNK_SECONDS": "3",
                    "AUDIO_EXTRACT_CONTAINER": "wav",
                    "TRANSCRIPTION_REQUEST_OVERLAP_SECONDS": "1",
                },
                clear=True,
            ):
                worker = build_worker(stdout=stream)

        self.assertIsInstance(worker.discovery, OverlappedAudioWindowDiscovery)
        self.assertEqual(worker.discovery.overlap_seconds, 1.0)

    def test_build_source_accepts_vad_utterance_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(
                os.environ,
                {
                    "AUDIO_EXTRACT_DIR": tmpdir,
                    "TRANSCRIPTION_SOURCE_MODE": TRANSCRIPTION_SOURCE_MODE_VAD_UTTERANCE,
                },
                clear=True,
            ):
                config = get_config()

        source = build_transcription_event_source(app_config=config)

        self.assertIsInstance(source, TranscriptionWorker)
        self.assertIsInstance(source.discovery, VadUtteranceAudioWindowDiscovery)

    def test_chunked_source_start_and_stop_wrap_worker_lifecycle(self) -> None:
        stop_event = threading.Event()
        extractor = FakeExtractor()
        source = TranscriptionWorker(
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
            wait=lambda seconds: stop_event.is_set(),
        )
        source.stop()
        source.start()

        self.assertEqual(extractor.starts, 1)
        self.assertEqual(extractor.stops, 1)

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

    def test_overlap_discovery_builds_windows_after_first_chunk(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            stream_dir = root / "player_1"
            stream_dir.mkdir()
            first_path = stream_dir / "000000000.wav"
            second_path = stream_dir / "000000001.wav"
            _write_wav(first_path, frame_count=8, framerate=4)
            _write_wav(second_path, frame_count=8, framerate=4)
            config = AudioExtractionConfig(
                output_dir=root,
                stream_input_urls={"player_1": "rtmp://media/live/player_1"},
                stream_ids=("player_1",),
                chunk_duration_seconds=2,
            )
            discovery = OverlappedAudioWindowDiscovery(
                FakeDiscovery(
                    (
                        AudioInputRef(
                            stream_id="player_1",
                            uri=first_path.as_uri(),
                            starts_at_seconds=0.0,
                            duration_seconds=2.0,
                        ),
                        AudioInputRef(
                            stream_id="player_1",
                            uri=second_path.as_uri(),
                            starts_at_seconds=2.0,
                            duration_seconds=2.0,
                        ),
                    )
                ),
                config=config,
                overlap_seconds=0.5,
            )

            refs = discovery.discover()

        self.assertEqual(refs[0].uri, first_path.as_uri())
        self.assertNotEqual(refs[1].uri, second_path.as_uri())
        self.assertEqual(refs[1].starts_at_seconds, 1.5)
        self.assertEqual(refs[1].duration_seconds, 2.5)
        self.assertEqual(refs[1].emit_from_seconds, 2.0)
        self.assertIn("/_overlap/player_1/000000001.wav", refs[1].uri.replace("\\", "/"))

    def test_overlap_discovery_deletes_stale_composed_files_on_later_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            stream_dir = root / "player_1"
            stream_dir.mkdir()
            first_path = stream_dir / "000000000.wav"
            second_path = stream_dir / "000000001.wav"
            _write_wav(first_path, frame_count=8, framerate=4)
            _write_wav(second_path, frame_count=8, framerate=4)
            base = FakeDiscovery(
                (
                    AudioInputRef(
                        stream_id="player_1",
                        uri=second_path.as_uri(),
                        starts_at_seconds=2.0,
                        duration_seconds=2.0,
                    ),
                )
            )
            discovery = OverlappedAudioWindowDiscovery(
                base,
                config=AudioExtractionConfig(
                    output_dir=root,
                    stream_input_urls={"player_1": "rtmp://media/live/player_1"},
                    stream_ids=("player_1",),
                    chunk_duration_seconds=2,
                ),
                overlap_seconds=0.5,
            )
            refs = discovery.discover()
            overlap_path = root / "_overlap" / "player_1" / "000000001.wav"
            self.assertTrue(overlap_path.exists())

            base.refs = ()
            later_refs = discovery.discover()

            self.assertEqual(len(refs), 1)
            self.assertEqual(later_refs, ())
            self.assertFalse(overlap_path.exists())

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

    def test_startup_failure_still_stops_extractor(self) -> None:
        extractor = FakeExtractor(start_error=RuntimeError("input unavailable"))
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
        )

        with self.assertRaisesRegex(RuntimeError, "input unavailable"):
            worker.run_forever()

        self.assertEqual(extractor.starts, 1)
        self.assertEqual(extractor.stops, 1)


class VadUtteranceAudioWindowDiscoveryTests(unittest.TestCase):
    def test_silence_only_input_does_not_emit_provider_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            chunk = root / "000000000.wav"
            _write_pcm_wav(chunk, [0] * 20, framerate=10)
            discovery = self._discovery(root, (self._ref(chunk, 0.0),))

            refs = discovery.discover()

        self.assertEqual(refs, ())

    def test_trailing_silence_finalizes_speech_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            chunk = root / "000000000.wav"
            _write_pcm_wav(
                chunk,
                [0, 0, 10000, 10000, 10000, 0, 0, 0],
                framerate=10,
            )
            discovery = self._discovery(root, (self._ref(chunk, 0.0),))

            refs = discovery.discover()

            self.assertEqual(len(refs), 1)
            self.assertEqual(refs[0].starts_at_seconds, 0.1)
            self.assertAlmostEqual(refs[0].duration_seconds, 0.6)
            self.assertEqual(refs[0].sample_rate_hz, 10)
            self.assertEqual(refs[0].channels, 1)
            self.assertIn("/_vad/player_1/", refs[0].uri.replace("\\", "/"))
            output_path = next((root / "_vad" / "player_1").glob("*.wav"))
            with wave.open(str(output_path), "rb") as wav_file:
                self.assertEqual(wav_file.getnframes(), 6)

    def test_long_speech_finalizes_at_max_duration(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            chunk = root / "000000000.wav"
            _write_pcm_wav(chunk, [12000] * 10, framerate=10)
            discovery = self._discovery(
                root,
                (self._ref(chunk, 0.0),),
                vad_config=VadUtteranceConfig(
                    frame_seconds=0.1,
                    energy_threshold=0.01,
                    min_speech_seconds=0.1,
                    min_silence_seconds=0.2,
                    leading_padding_seconds=0,
                    trailing_padding_seconds=0,
                    max_utterance_seconds=0.5,
                ),
            )

            refs = discovery.discover()

        self.assertEqual(len(refs), 2)
        self.assertEqual([ref.duration_seconds for ref in refs], [0.5, 0.5])

    def test_unreadable_or_incompatible_wav_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bad = root / "000000000.wav"
            good = root / "000000001.wav"
            bad.write_bytes(b"not wav")
            _write_pcm_wav(good, [12000, 12000, 0, 0], framerate=10)
            discovery = self._discovery(
                root,
                (self._ref(bad, 0.0), self._ref(good, 0.4)),
            )

            refs = discovery.discover()

        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].starts_at_seconds, 0.4)

    def _discovery(
        self,
        root: Path,
        refs: tuple[AudioInputRef, ...],
        *,
        vad_config: VadUtteranceConfig | None = None,
    ) -> VadUtteranceAudioWindowDiscovery:
        extraction_config = AudioExtractionConfig(
            output_dir=root,
            stream_input_urls={"player_1": "rtmp://media/live/player_1"},
            stream_ids=("player_1",),
            sample_rate_hz=10,
            chunk_duration_seconds=1,
        )
        return VadUtteranceAudioWindowDiscovery(
            FakeDiscovery(refs),
            extraction_config=extraction_config,
            vad_config=vad_config
            or VadUtteranceConfig(
                frame_seconds=0.1,
                energy_threshold=0.01,
                min_speech_seconds=0.2,
                min_silence_seconds=0.2,
                leading_padding_seconds=0.1,
                trailing_padding_seconds=0.2,
                max_utterance_seconds=1.0,
            ),
        )

    def _ref(self, path: Path, starts_at_seconds: float) -> AudioInputRef:
        return AudioInputRef(
            stream_id="player_1",
            uri=path.resolve().as_uri(),
            starts_at_seconds=starts_at_seconds,
            duration_seconds=1.0,
            codec="pcm_s16le",
            sample_rate_hz=10,
            channels=1,
        )

def _write_wav(path: Path, *, frame_count: int, framerate: int = 8000) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(framerate)
        wav_file.writeframes(b"\x00\x00" * frame_count)


def _write_pcm_wav(path: Path, samples: list[int], *, framerate: int) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(framerate)
        wav_file.writeframes(
            b"".join(sample.to_bytes(2, "little", signed=True) for sample in samples)
        )


if __name__ == "__main__":
    unittest.main()
