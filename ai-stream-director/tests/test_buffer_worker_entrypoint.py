import logging
import os
import signal
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

import buffer_worker  # noqa: E402
from services.buffer import RollingBufferConfig  # noqa: E402


class BufferWorkerConfigTests(unittest.TestCase):
    def test_builds_rolling_buffer_config_from_app_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(
                os.environ,
                {
                    "INGEST_API_URL": "rtmp://media-server:1935/live",
                    "LOOKBACK_BUFFER_DIR": temp_dir,
                    "LOOKBACK_INPUT_URL_PLAYER_4": "srt://player-four:10080",
                    "LOOKBACK_SEGMENT_SECONDS": "3.5",
                    "LOOKBACK_WINDOW_SECONDS": "42",
                    "FFMPEG_EXECUTABLE": "ffmpeg-test",
                },
                clear=True,
            ):
                config = buffer_worker.build_buffer_config()

        self.assertIsInstance(config, RollingBufferConfig)
        self.assertEqual(config.buffer_root, Path(temp_dir))
        self.assertEqual(config.ffmpeg_executable, "ffmpeg-test")
        self.assertEqual(config.segment_duration_seconds, 3.5)
        self.assertEqual(config.retention_window_seconds, 42.0)
        self.assertEqual(
            config.stream_input_urls["player_1"],
            "rtmp://media-server:1935/live/player_1",
        )
        self.assertEqual(
            config.stream_input_urls["player_4"],
            "srt://player-four:10080",
        )

    def test_validation_fails_for_missing_input_urls(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(
                temp_dir,
                stream_input_urls={"player_1": ""},
            )

            with self.assertRaisesRegex(
                buffer_worker.BufferWorkerError,
                "Missing input URLs.*player_1",
            ):
                buffer_worker.validate_startup_config(
                    config,
                    ffmpeg_resolver=lambda executable: executable,
                )

    def test_validation_fails_for_missing_ffmpeg_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir, ffmpeg_executable="missing-ffmpeg")

            with self.assertRaisesRegex(
                buffer_worker.BufferWorkerError,
                "FFmpeg executable not found: missing-ffmpeg",
            ):
                buffer_worker.validate_startup_config(
                    config,
                    ffmpeg_resolver=lambda executable: None,
                )

    def test_validation_fails_for_unwritable_buffer_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(Path(temp_dir) / "lookback")

            with patch.object(
                Path,
                "write_text",
                side_effect=OSError("permission denied"),
            ):
                with self.assertRaisesRegex(
                    buffer_worker.BufferWorkerError,
                    "Buffer directory is not writable",
                ):
                    buffer_worker.validate_startup_config(
                        config,
                        ffmpeg_resolver=lambda executable: executable,
                    )


class BufferWorkerLifecycleTests(unittest.TestCase):
    def test_run_starts_logs_and_stops_buffer_on_normal_shutdown(self) -> None:
        events: list[str] = []

        class FakeBuffer:
            def __init__(self, config: RollingBufferConfig) -> None:
                events.append(f"factory:{config.stream_ids[0]}")

            def start(self) -> None:
                events.append("start")

            def stop(self) -> None:
                events.append("stop")

        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir)
            shutdown_event = threading.Event()
            shutdown_event.set()

            with self.assertLogs(buffer_worker.LOGGER.name, level="INFO") as logs:
                exit_code = buffer_worker.run_buffer_worker(
                    config,
                    buffer_factory=FakeBuffer,
                    ffmpeg_resolver=lambda executable: executable,
                    install_signal_handlers=False,
                    shutdown_event=shutdown_event,
                    wait_interval_seconds=0,
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(events, ["factory:player_1", "start", "stop"])
        self.assertEqual(len(logs.output), 1)
        self.assertIn("stream=player_1", logs.output[0])
        self.assertIn("input=rtmp://media-server:1935/live/player_1", logs.output[0])
        self.assertIn("dir=", logs.output[0])

    def test_sigterm_handler_requests_shutdown_and_stops_buffer(self) -> None:
        events: list[str] = []
        installed_handlers = {}

        def fake_signal(
            shutdown_signal: signal.Signals,
            handler,
        ):
            previous_handler = installed_handlers.get(shutdown_signal, signal.SIG_DFL)
            installed_handlers[shutdown_signal] = handler
            return previous_handler

        class FakeBuffer:
            def __init__(self, config: RollingBufferConfig) -> None:
                del config

            def start(self) -> None:
                events.append("start")
                installed_handlers[signal.SIGTERM](signal.SIGTERM, None)

            def stop(self) -> None:
                events.append("stop")

        with tempfile.TemporaryDirectory() as temp_dir:
            config = _config(temp_dir)

            with patch.object(
                buffer_worker.signal,
                "signal",
                side_effect=fake_signal,
            ):
                exit_code = buffer_worker.run_buffer_worker(
                    config,
                    buffer_factory=FakeBuffer,
                    ffmpeg_resolver=lambda executable: executable,
                    logger=logging.getLogger("buffer-worker-test"),
                    wait_interval_seconds=0.001,
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(events, ["start", "stop"])
        self.assertEqual(installed_handlers[signal.SIGTERM], signal.SIG_DFL)


class BufferWorkerImportTests(unittest.TestCase):
    def test_import_does_not_create_configured_buffer_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            buffer_dir = Path(temp_dir) / "lookback"
            script = textwrap.dedent(
                f"""
                import importlib
                import os
                import sys
                from pathlib import Path

                sys.path.insert(0, {str(SRC_DIR)!r})
                os.environ["LOOKBACK_BUFFER_DIR"] = {str(buffer_dir)!r}
                importlib.import_module("buffer_worker")
                if Path(os.environ["LOOKBACK_BUFFER_DIR"]).exists():
                    raise SystemExit("buffer_worker import created LOOKBACK_BUFFER_DIR")
                """
            )

            result = subprocess.run(
                [sys.executable, "-B", "-c", script],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)


def _config(
    buffer_root: str | Path,
    *,
    stream_input_urls: dict[str, str] | None = None,
    ffmpeg_executable: str = "ffmpeg",
) -> RollingBufferConfig:
    return RollingBufferConfig(
        buffer_root=buffer_root,
        stream_ids=("player_1",),
        stream_input_urls=stream_input_urls
        or {"player_1": "rtmp://media-server:1935/live/player_1"},
        ffmpeg_executable=ffmpeg_executable,
    )


if __name__ == "__main__":
    unittest.main()
