import importlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

import buffer_worker  # noqa: E402
import transcription_worker  # noqa: E402
from config import (  # noqa: E402
    AI_PROVIDER_OLLAMA,
    AI_PROVIDER_OPENAI_COMPATIBLE,
    SCENES,
    AppConfig,
)
from services.health import run_runtime_healthcheck  # noqa: E402


orchestrator_main = importlib.import_module("main")


class FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status
        self.closed = False

    def close(self) -> None:
        self.closed = True


class RuntimeHealthcheckEntrypointTests(unittest.TestCase):
    def test_buffer_healthcheck_reports_configured_dependencies(self) -> None:
        stream = io.StringIO()
        probes: list[Path] = []

        exit_code = run_runtime_healthcheck(
            "buffer-worker",
            app_config=_app_config(lookback_buffer_dir="/runtime/buffer"),
            ffmpeg_resolver=lambda executable: f"/usr/bin/{executable}",
            directory_exists=lambda path: True,
            directory_is_dir=lambda path: True,
            directory_probe_writer=probes.append,
            stream=stream,
        )

        payload = json.loads(stream.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "healthy")
        self.assertEqual(probes, [Path("/runtime/buffer")])
        self.assertIn("Stream input URLs are configured.", _messages(payload))

    def test_buffer_healthcheck_reports_missing_ffmpeg(self) -> None:
        stream = io.StringIO()

        exit_code = run_runtime_healthcheck(
            "buffer-worker",
            app_config=_app_config(ffmpeg_executable="ffmpeg-missing"),
            ffmpeg_resolver=lambda executable: None,
            directory_exists=lambda path: True,
            directory_is_dir=lambda path: True,
            directory_probe_writer=lambda path: None,
            stream=stream,
        )

        payload = json.loads(stream.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertEqual(payload["status"], "unhealthy")
        self.assertIn("FFMPEG_EXECUTABLE not found: ffmpeg-missing", _messages(payload))

    def test_buffer_healthcheck_reports_blank_runtime_directory(self) -> None:
        stream = io.StringIO()

        exit_code = run_runtime_healthcheck(
            "buffer-worker",
            app_config=_app_config(lookback_buffer_dir="  "),
            ffmpeg_resolver=lambda executable: f"/usr/bin/{executable}",
            directory_exists=lambda path: (_ for _ in ()).throw(
                AssertionError("blank directory should not hit filesystem")
            ),
            directory_is_dir=lambda path: True,
            directory_probe_writer=lambda path: None,
            stream=stream,
        )

        payload = json.loads(stream.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertEqual(payload["status"], "unhealthy")
        self.assertIn("LOOKBACK_BUFFER_DIR is not configured.", _messages(payload))

    def test_transcription_healthcheck_uses_env_endpoint_and_timeout(self) -> None:
        stream = io.StringIO()
        calls: list[tuple[str, dict[str, object]]] = []

        def opener(url, **kwargs):
            calls.append((url, kwargs))
            return FakeResponse(204)

        exit_code = run_runtime_healthcheck(
            "transcription-worker",
            app_config=_app_config(audio_extract_dir="/runtime/audio"),
            env={
                "TRANSCRIPTION_HEALTH_URL": "http://stt.example/ready",
                "RUNTIME_HEALTH_TIMEOUT_SECONDS": "1.25",
            },
            opener=opener,
            ffmpeg_resolver=lambda executable: f"/usr/bin/{executable}",
            directory_exists=lambda path: True,
            directory_is_dir=lambda path: True,
            directory_probe_writer=lambda path: None,
            stream=stream,
        )

        payload = json.loads(stream.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["status"], "healthy")
        self.assertEqual(calls, [("http://stt.example/ready", {"timeout": 1.25})])

    def test_ai_endpoint_healthcheck_defaults_ollama_to_tags(self) -> None:
        stream = io.StringIO()
        calls: list[str] = []

        def opener(url, **kwargs):
            del kwargs
            calls.append(url)
            return FakeResponse(200)

        exit_code = run_runtime_healthcheck(
            "ai-endpoint",
            app_config=_app_config(
                ai_provider=AI_PROVIDER_OLLAMA,
                gemma_api_url="http://ollama:11434",
            ),
            env={},
            opener=opener,
            stream=stream,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls, ["http://ollama:11434/api/tags"])

    def test_openai_compatible_ai_healthcheck_uses_base_readiness_url(self) -> None:
        stream = io.StringIO()
        calls: list[str] = []

        def opener(url, **kwargs):
            del kwargs
            calls.append(url)
            return FakeResponse(200)

        exit_code = run_runtime_healthcheck(
            "ai-endpoint",
            app_config=_app_config(
                ai_provider=AI_PROVIDER_OPENAI_COMPATIBLE,
                gemma_api_url="https://inference.example/v1/chat/completions",
            ),
            env={},
            opener=opener,
            stream=stream,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls, ["https://inference.example"])

    def test_orchestrator_healthcheck_returns_nonzero_for_degraded_http(self) -> None:
        stream = io.StringIO()

        exit_code = run_runtime_healthcheck(
            "orchestrator",
            app_config=_app_config(),
            env={},
            opener=lambda *args, **kwargs: FakeResponse(404),
            directory_exists=lambda path: True,
            directory_is_dir=lambda path: True,
            directory_probe_writer=lambda path: None,
            stream=stream,
        )

        payload = json.loads(stream.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertEqual(payload["status"], "degraded")
        self.assertIn("Endpoint returned status 404.", _messages(payload))

    def test_buffer_worker_health_flag_does_not_start_worker(self) -> None:
        with patch.object(
            buffer_worker,
            "run_runtime_healthcheck",
            return_value=0,
        ) as healthcheck:
            with patch.object(
                buffer_worker,
                "run_buffer_worker",
                side_effect=AssertionError("should not start worker"),
            ):
                exit_code = buffer_worker.main(["--healthcheck"])

        self.assertEqual(exit_code, 0)
        healthcheck.assert_called_once_with("buffer-worker")

    def test_transcription_worker_health_flag_does_not_build_worker(self) -> None:
        with patch.object(
            transcription_worker,
            "run_runtime_healthcheck",
            return_value=0,
        ) as healthcheck:
            with patch.object(
                transcription_worker,
                "build_worker",
                side_effect=AssertionError("should not build worker"),
            ):
                exit_code = transcription_worker.main(["--healthcheck"])

        self.assertEqual(exit_code, 0)
        healthcheck.assert_called_once_with("transcription-worker")

    def test_orchestrator_health_flag_does_not_load_runtime_config(self) -> None:
        with patch.object(
            orchestrator_main,
            "run_runtime_healthcheck",
            return_value=0,
        ) as healthcheck:
            with patch.object(
                orchestrator_main,
                "get_config",
                side_effect=AssertionError("should not load runtime config"),
            ):
                exit_code = orchestrator_main.main(["--healthcheck"])

        self.assertEqual(exit_code, 0)
        healthcheck.assert_called_once_with("orchestrator")


def _messages(payload: dict[str, object]) -> list[str]:
    return [str(result["message"]) for result in payload["results"]]


def _app_config(**overrides) -> AppConfig:
    values = {
        "obs_host": "host.docker.internal",
        "obs_port": 4455,
        "obs_password": "secret",
        "dry_run_obs": False,
        "ai_provider": AI_PROVIDER_OLLAMA,
        "ingest_api_url": "rtmp://media-server:1935/live",
        "transcription_api_url": "http://transcription.example",
        "transcription_request_timeout_seconds": 30.0,
        "gemma_api_url": "http://ollama:11434",
        "gemma_model": "gemma3:4b",
        "gemma_api_key": "",
        "lookback_buffer_dir": "/runtime/buffer",
        "lookback_window_seconds": 30,
        "switch_lookback_seconds": 15,
        "lookback_segment_seconds": 2.0,
        "lookback_input_urls": {
            "player_1": "rtmp://media-server:1935/live/player_1",
            "player_2": "rtmp://media-server:1935/live/player_2",
        },
        "ffmpeg_executable": "ffmpeg",
        "audio_extract_dir": "/runtime/audio",
        "audio_extract_sample_rate": 16000,
        "audio_extract_channels": 1,
        "audio_extract_chunk_seconds": 5.0,
        "audio_extract_codec": "pcm_s16le",
        "audio_extract_container": "wav",
        "audio_input_urls": {
            "player_1": "rtmp://media-server:1935/live/player_1",
            "player_2": "rtmp://media-server:1935/live/player_2",
        },
        "confidence_threshold": 0.75,
        "min_switch_interval_seconds": 8,
        "max_focus_duration_seconds": 20,
        "transcript_history_seconds": 30,
        "transcript_history_messages": 20,
        "transcript_prefilter_enabled": True,
        "transcript_prefilter_min_text_characters": 6,
        "transcript_prefilter_duplicate_window_seconds": 12.0,
        "transcript_prefilter_context_seconds": 30.0,
        "transcript_prefilter_min_confidence": 0.7,
        "default_scene": SCENES["quad"],
    }
    values.update(overrides)
    return AppConfig(**values)


if __name__ == "__main__":
    unittest.main()
