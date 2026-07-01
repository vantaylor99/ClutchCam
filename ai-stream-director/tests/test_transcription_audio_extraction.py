import os
import logging
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from config import get_config  # noqa: E402
from services.transcription import (  # noqa: E402
    AudioExtractionConfig,
    AudioInputRef,
    FFmpegAudioExtractor,
    FixtureAudioExtractor,
    TranscriptionError,
    build_overlapped_audio_ref,
)


class _FakeProcess:
    _next_pid = 2000

    def __init__(
        self,
        poll_results: tuple[int | None, ...] = (None,),
        *,
        exit_after_seconds: float | None = None,
        exit_code: int = 1,
    ) -> None:
        self.pid = self._next_pid
        type(self)._next_pid += 1
        self._poll_results = list(poll_results)
        self._last_poll_result: int | None = None
        self._exit_after_seconds = exit_after_seconds
        self._exit_code = exit_code
        self._started_at: float | None = None
        self._lock = threading.Lock()
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        with self._lock:
            if self._started_at is None:
                self._started_at = time.monotonic()
            if self.terminated or self.killed:
                return 0
            if (
                self._exit_after_seconds is not None
                and time.monotonic() - self._started_at >= self._exit_after_seconds
            ):
                self._last_poll_result = self._exit_code
                return self._last_poll_result
            if self._poll_results:
                self._last_poll_result = self._poll_results.pop(0)
            return self._last_poll_result

    def terminate(self) -> None:
        with self._lock:
            self.terminated = True

    def kill(self) -> None:
        with self._lock:
            self.killed = True

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return self.poll() or 0


class _StubbornProcess(_FakeProcess):
    def __init__(self, terminate_error: OSError) -> None:
        super().__init__()
        self._terminate_error = terminate_error

    def terminate(self) -> None:
        raise self._terminate_error

    def wait(self, timeout: float | None = None) -> int:
        if not self.killed:
            raise subprocess.TimeoutExpired("ffmpeg", timeout)
        return 0


class AudioExtractionConfigTests(unittest.TestCase):
    def test_app_config_exposes_audio_extraction_defaults(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = get_config()

        self.assertEqual(config.audio_extract_dir, "/dev/shm/clutchcam-audio")
        self.assertEqual(config.audio_extract_sample_rate, 16000)
        self.assertEqual(config.audio_extract_channels, 1)
        self.assertEqual(config.audio_extract_chunk_seconds, 5.0)
        self.assertEqual(config.audio_extract_codec, "pcm_s16le")
        self.assertEqual(config.audio_extract_container, "wav")
        self.assertEqual(config.transcription_request_overlap_seconds, 0.0)
        self.assertEqual(config.transcription_vad_frame_ms, 30)
        self.assertEqual(config.transcription_vad_energy_threshold, 0.015)
        self.assertEqual(config.transcription_vad_min_speech_seconds, 0.18)
        self.assertEqual(config.transcription_vad_min_silence_seconds, 0.45)
        self.assertEqual(config.transcription_vad_leading_padding_seconds, 0.18)
        self.assertEqual(config.transcription_vad_trailing_padding_seconds, 0.24)
        self.assertEqual(config.transcription_vad_max_utterance_seconds, 12.0)
        self.assertEqual(
            config.audio_input_urls["player_1"],
            "rtmp://localhost/live/player_1",
        )

    def test_app_config_accepts_valid_transcription_overlap(self) -> None:
        with patch.dict(
            os.environ,
            {
                "AUDIO_EXTRACT_CHUNK_SECONDS": "5",
                "AUDIO_EXTRACT_CONTAINER": "wav",
                "TRANSCRIPTION_REQUEST_OVERLAP_SECONDS": "1.25",
            },
            clear=True,
        ):
            config = get_config()

        self.assertEqual(config.transcription_request_overlap_seconds, 1.25)

    def test_app_config_rejects_negative_transcription_overlap(self) -> None:
        with patch.dict(
            os.environ,
            {"TRANSCRIPTION_REQUEST_OVERLAP_SECONDS": "-0.1"},
            clear=True,
        ):
            with self.assertRaisesRegex(
                ValueError,
                "TRANSCRIPTION_REQUEST_OVERLAP_SECONDS",
            ):
                get_config()

    def test_app_config_rejects_overlap_at_or_above_chunk_duration(self) -> None:
        with patch.dict(
            os.environ,
            {
                "AUDIO_EXTRACT_CHUNK_SECONDS": "5",
                "TRANSCRIPTION_REQUEST_OVERLAP_SECONDS": "5",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "less than"):
                get_config()

    def test_app_config_rejects_non_wav_container_when_overlap_enabled(self) -> None:
        with patch.dict(
            os.environ,
            {
                "AUDIO_EXTRACT_CONTAINER": "mp3",
                "TRANSCRIPTION_REQUEST_OVERLAP_SECONDS": "1",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "AUDIO_EXTRACT_CONTAINER=wav"):
                get_config()

    def test_audio_input_urls_fall_back_through_lookback_inputs(self) -> None:
        with patch.dict(
            os.environ,
            {
                "INGEST_API_URL": "rtmp://media-server:1935/live",
                "LOOKBACK_INPUT_URL_PLAYER_2": "srt://lookback-player-two:10080",
                "AUDIO_INPUT_URL_PLAYER_3": "rtmp://audio-player-three/live",
            },
            clear=True,
        ):
            config = get_config()

        self.assertEqual(
            config.audio_input_urls["player_1"],
            "rtmp://media-server:1935/live/player_1",
        )
        self.assertEqual(
            config.audio_input_urls["player_2"],
            "srt://lookback-player-two:10080",
        )
        self.assertEqual(
            config.audio_input_urls["player_3"],
            "rtmp://audio-player-three/live",
        )

    def test_audio_extraction_config_rejects_unknown_input_ids(self) -> None:
        with self.assertRaisesRegex(TranscriptionError, "unknown stream IDs"):
            AudioExtractionConfig(
                output_dir="audio",
                stream_input_urls={"player_9": "rtmp://example/live/player_9"},
            )


class FFmpegAudioExtractorTests(unittest.TestCase):
    def test_ffmpeg_command_uses_configured_audio_values(self) -> None:
        config = AudioExtractionConfig(
            output_dir="audio-cache",
            stream_input_urls={"player_1": "rtmp://media/live/player_1"},
            stream_ids=("player_1",),
            ffmpeg_executable="ffmpeg-test",
            sample_rate_hz=24000,
            channels=2,
            chunk_duration_seconds=3,
            codec="pcm_s16le",
            container="wav",
        )

        command = FFmpegAudioExtractor(config).build_ffmpeg_command("player_1")

        self.assertEqual(command[0], "ffmpeg-test")
        self.assertIn("rtmp://media/live/player_1", command)
        self.assertIn("-vn", command)
        self.assertIn("2", command)
        self.assertIn("24000", command)
        self.assertIn("3", command)
        output_pattern = str(command[-1])
        self.assertTrue(
            output_pattern.endswith("player_1\\%09d.wav")
            or output_pattern.endswith("player_1/%09d.wav")
        )

    def test_missing_input_url_fails_before_subprocess_launch(self) -> None:
        config = AudioExtractionConfig(
            output_dir="audio-cache",
            stream_input_urls={},
            stream_ids=("player_1",),
        )

        with self.assertRaisesRegex(TranscriptionError, "Missing audio input URL"):
            FFmpegAudioExtractor(config).build_ffmpeg_command("player_1")

    def test_sessions_preserve_stream_identity_before_start(self) -> None:
        config = AudioExtractionConfig(
            output_dir="audio-cache",
            stream_input_urls={"player_1": "rtmp://media/live/player_1"},
            stream_ids=("player_1",),
        )

        sessions = FFmpegAudioExtractor(config).sessions()

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].stream_id, "player_1")
        self.assertFalse(sessions[0].running)

    def test_late_input_launch_failure_retries_with_redacted_diagnostics(self) -> None:
        input_url = "rtmp://user:secret@media/live/player_1"
        replacement_process = _FakeProcess()
        launches = 0
        launch_lock = threading.Lock()

        def process_factory(*args, **kwargs):
            nonlocal launches
            del args, kwargs
            with launch_lock:
                launches += 1
                if launches == 1:
                    raise OSError(f"connection refused for {input_url}")
                return replacement_process

        with tempfile.TemporaryDirectory() as tmpdir:
            extractor = self._extractor(
                tmpdir,
                process_factory=process_factory,
                input_urls={"player_1": input_url},
            )
            with self.assertLogs("services.transcription", level="WARNING") as logs:
                extractor.start()
                try:
                    self.assertTrue(_wait_until(lambda: launches == 2))
                finally:
                    extractor.stop()

        diagnostic = "\n".join(logs.output)
        self.assertTrue(replacement_process.terminated)
        self.assertIn("transcription_ffmpeg_launch_failed", diagnostic)
        self.assertIn("stream=player_1", diagnostic)
        self.assertIn("consecutive_failures=1", diagnostic)
        self.assertIn("restart_delay_seconds=0.010", diagnostic)
        self.assertIn("<redacted-input-url>", diagnostic)
        self.assertNotIn(input_url, diagnostic)

    def test_repeated_exits_use_capped_restart_backoff(self) -> None:
        launch_times: list[float] = []
        launch_lock = threading.Lock()

        def process_factory(*args, **kwargs):
            del args, kwargs
            with launch_lock:
                launch_times.append(time.monotonic())
            return _FakeProcess((1,))

        with tempfile.TemporaryDirectory() as tmpdir:
            extractor = self._extractor(
                tmpdir,
                process_factory=process_factory,
                restart_backoff_initial_seconds=0.02,
                restart_backoff_max_seconds=0.04,
            )
            extractor.start()
            try:
                self.assertTrue(_wait_until(lambda: len(launch_times) >= 4))
            finally:
                extractor.stop()

        intervals = [
            later - earlier
            for earlier, later in zip(launch_times, launch_times[1:])
        ]
        self.assertGreaterEqual(intervals[0], 0.015)
        self.assertGreaterEqual(intervals[1], 0.03)
        self.assertGreaterEqual(intervals[2], 0.03)
        self.assertEqual(extractor._restart_delay(1_000_000), 0.04)

    def test_stable_runtime_resets_consecutive_failure_backoff(self) -> None:
        processes = iter(
            (
                _FakeProcess((1,)),
                _FakeProcess(exit_after_seconds=0.04),
                _FakeProcess((1,)),
                _FakeProcess(),
            )
        )
        launches = 0
        launch_lock = threading.Lock()

        def process_factory(*args, **kwargs):
            nonlocal launches
            del args, kwargs
            with launch_lock:
                launches += 1
                return next(processes)

        with tempfile.TemporaryDirectory() as tmpdir:
            extractor = self._extractor(
                tmpdir,
                process_factory=process_factory,
                restart_stable_seconds=0.03,
            )
            with self.assertLogs("services.transcription", level="WARNING") as logs:
                extractor.start()
                try:
                    self.assertTrue(_wait_until(lambda: launches == 4))
                finally:
                    extractor.stop()

        exit_logs = [
            message
            for message in logs.output
            if "transcription_ffmpeg_exited" in message
        ]
        self.assertEqual(len(exit_logs), 3)
        self.assertIn("restart_delay_seconds=0.010", exit_logs[0])
        self.assertIn("restart_delay_seconds=0.010", exit_logs[1])
        self.assertIn("restart_delay_seconds=0.020", exit_logs[2])

    def test_stream_failure_does_not_restart_healthy_stream(self) -> None:
        failed_process = _FakeProcess((1,))
        recovered_process = _FakeProcess()
        healthy_process = _FakeProcess()
        launches = {"player_1": 0, "player_2": 0}
        launch_lock = threading.Lock()

        def process_factory(command, **kwargs):
            del kwargs
            input_url = command[command.index("-i") + 1]
            stream_id = "player_1" if input_url.endswith("player_1") else "player_2"
            with launch_lock:
                launches[stream_id] += 1
                if stream_id == "player_1":
                    if launches[stream_id] == 1:
                        return failed_process
                    return recovered_process
                return healthy_process

        with tempfile.TemporaryDirectory() as tmpdir:
            extractor = self._extractor(
                tmpdir,
                process_factory=process_factory,
                input_urls={
                    "player_1": "rtmp://media/live/player_1",
                    "player_2": "rtmp://media/live/player_2",
                },
            )
            extractor.start()
            try:
                self.assertTrue(_wait_until(lambda: launches["player_1"] == 2))
                self.assertTrue(_wait_until(lambda: launches["player_2"] == 1))
                time.sleep(0.03)
                self.assertEqual(launches["player_2"], 1)
                self.assertFalse(healthy_process.terminated)
            finally:
                extractor.stop()

        self.assertTrue(healthy_process.terminated)
        self.assertTrue(recovered_process.terminated)

    def test_shutdown_cleans_up_children_and_interrupts_restart_backoff(self) -> None:
        input_url = "rtmp://user:secret@media/live/player_1"
        process = _StubbornProcess(OSError(f"terminate failed for {input_url}"))
        attempted = threading.Event()
        launches = 0

        def failing_factory(*args, **kwargs):
            nonlocal launches
            del args, kwargs
            launches += 1
            attempted.set()
            raise OSError("input unavailable")

        with tempfile.TemporaryDirectory() as tmpdir:
            active_extractor = self._extractor(
                tmpdir,
                process_factory=lambda *args, **kwargs: process,
                input_urls={"player_1": input_url},
            )
            with self.assertLogs("services.transcription", level="WARNING") as logs:
                active_extractor.start()
                self.assertTrue(_wait_until(lambda: process._started_at is not None))
                active_extractor.stop()

            waiting_extractor = self._extractor(
                tmpdir,
                process_factory=failing_factory,
                restart_backoff_initial_seconds=5.0,
                restart_backoff_max_seconds=5.0,
            )
            waiting_extractor.start()
            self.assertTrue(attempted.wait(0.5))
            started_at = time.monotonic()
            waiting_extractor.stop()
            shutdown_seconds = time.monotonic() - started_at

        diagnostic = "\n".join(logs.output)
        self.assertTrue(process.killed)
        self.assertIn("transcription_ffmpeg_terminate_failed", diagnostic)
        self.assertIn("<redacted-input-url>", diagnostic)
        self.assertNotIn(input_url, diagnostic)
        self.assertLess(shutdown_seconds, 1.0)
        self.assertEqual(launches, 1)

    def _extractor(
        self,
        output_dir: str,
        *,
        process_factory,
        input_urls: dict[str, str] | None = None,
        restart_backoff_initial_seconds: float = 0.01,
        restart_backoff_max_seconds: float = 0.04,
        restart_stable_seconds: float = 1.0,
    ) -> FFmpegAudioExtractor:
        urls = input_urls or {"player_1": "rtmp://media/live/player_1"}
        return FFmpegAudioExtractor(
            AudioExtractionConfig(
                output_dir=output_dir,
                stream_input_urls=urls,
                stream_ids=tuple(urls),
            ),
            process_factory=process_factory,
            logger=logging.getLogger("services.transcription"),
            supervision_poll_seconds=0.005,
            restart_backoff_initial_seconds=restart_backoff_initial_seconds,
            restart_backoff_max_seconds=restart_backoff_max_seconds,
            restart_stable_seconds=restart_stable_seconds,
            termination_timeout_seconds=0.05,
        )


class FixtureAudioExtractorTests(unittest.TestCase):
    def test_fixture_audio_ref_preserves_timestamp_and_stream_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            chunk_path = Path(tmpdir) / "chunk.wav"
            chunk_path.write_bytes(b"fixture")
            config = AudioExtractionConfig(
                output_dir=tmpdir,
                stream_input_urls={"player_2": "rtmp://media/live/player_2"},
                stream_ids=("player_2",),
                chunk_duration_seconds=4,
            )

            audio_ref = FixtureAudioExtractor(config).build_audio_ref(
                "player_2",
                chunk_path,
                starts_at_seconds=12.5,
            )

        self.assertEqual(audio_ref.stream_id, "player_2")
        self.assertEqual(audio_ref.starts_at_seconds, 12.5)
        self.assertEqual(audio_ref.duration_seconds, 4.0)
        self.assertEqual(audio_ref.codec, "pcm_s16le")
        self.assertEqual(audio_ref.sample_rate_hz, 16000)
        self.assertEqual(audio_ref.channels, 1)

    def test_unknown_fixture_stream_id_fails_clearly(self) -> None:
        config = AudioExtractionConfig(
            output_dir="audio-cache",
            stream_input_urls={"player_1": "rtmp://media/live/player_1"},
            stream_ids=("player_1",),
        )

        with self.assertRaisesRegex(TranscriptionError, "Unknown stream ID"):
            FixtureAudioExtractor(config).build_audio_ref(
                "player_4",
                "missing.wav",
            )


class OverlappedAudioWindowBuilderTests(unittest.TestCase):
    def test_builds_local_wav_window_with_emit_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            stream_dir = root / "player_1"
            stream_dir.mkdir()
            previous_path = stream_dir / "000000000.wav"
            current_path = stream_dir / "000000001.wav"
            _write_wav(previous_path, frame_count=4, framerate=4)
            _write_wav(current_path, frame_count=8, framerate=4)
            config = AudioExtractionConfig(
                output_dir=root,
                stream_input_urls={"player_1": "rtmp://media/live/player_1"},
                stream_ids=("player_1",),
                chunk_duration_seconds=2,
            )
            original = AudioInputRef(
                stream_id="player_1",
                uri=current_path.as_uri(),
                starts_at_seconds=2.0,
                duration_seconds=2.0,
                codec="pcm_s16le",
                sample_rate_hz=4,
                channels=1,
            )

            overlapped = build_overlapped_audio_ref(
                audio_ref=original,
                current_chunk_path=current_path,
                previous_chunk_path=previous_path,
                overlap_seconds=0.5,
                config=config,
            )

            output_path = root / "_overlap" / "player_1" / "000000001.wav"

            self.assertNotEqual(overlapped.uri, original.uri)
            self.assertEqual(overlapped.starts_at_seconds, 1.5)
            self.assertEqual(overlapped.duration_seconds, 2.5)
            self.assertEqual(overlapped.emit_from_seconds, 2.0)
            self.assertIn("/_overlap/player_1/000000001.wav", overlapped.uri.replace("\\", "/"))
            with wave.open(str(output_path), "rb") as wav_file:
                self.assertEqual(wav_file.getnframes(), 10)

    def test_first_or_missing_previous_chunk_falls_back_to_original_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            current_path = Path(tmpdir) / "000000000.wav"
            _write_wav(current_path, frame_count=4, framerate=4)
            config = AudioExtractionConfig(
                output_dir=tmpdir,
                stream_input_urls={"player_1": "rtmp://media/live/player_1"},
                stream_ids=("player_1",),
            )
            original = AudioInputRef(
                stream_id="player_1",
                uri=current_path.as_uri(),
                starts_at_seconds=0.0,
                duration_seconds=1.0,
            )

            first = build_overlapped_audio_ref(
                audio_ref=original,
                current_chunk_path=current_path,
                previous_chunk_path=None,
                overlap_seconds=0.5,
                config=config,
            )
            missing = build_overlapped_audio_ref(
                audio_ref=original,
                current_chunk_path=current_path,
                previous_chunk_path=Path(tmpdir) / "missing.wav",
                overlap_seconds=0.5,
                config=config,
            )

        self.assertIs(first, original)
        self.assertIs(missing, original)


def _wait_until(predicate, timeout_seconds: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def _write_wav(path: Path, *, frame_count: int, framerate: int = 8000) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(framerate)
        wav_file.writeframes(b"\x00\x00" * frame_count)


if __name__ == "__main__":
    unittest.main()
