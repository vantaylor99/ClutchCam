import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch


PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(SRC_DIR))

from scripts import smoke_ai_endpoint  # noqa: E402
from scripts import smoke_buffer_worker  # noqa: E402
from scripts import smoke_media_server  # noqa: E402
from scripts import smoke_orchestrator_dry_run  # noqa: E402
from scripts import smoke_transcription_api  # noqa: E402


class FakeResponse:
    def __init__(self, payload, *, status_code=200, error=None) -> None:
        self.payload = payload
        self.status_code = status_code
        self.error = error

    def raise_for_status(self) -> None:
        if self.error is not None:
            raise self.error

    def json(self):
        return self.payload


class SmokeMediaServerTests(unittest.TestCase):
    def test_summaries_url_uses_host_and_port_overrides(self) -> None:
        url = smoke_media_server.summaries_url_from_env(
            {
                "SRS_HTTP_API_HOST": "media.example.test",
                "SRS_HTTP_API_PORT": "21985",
            }
        )

        self.assertEqual(url, "http://media.example.test:21985/api/v1/summaries")

    def test_generated_ffmpeg_lavfi_command_uses_env_overrides(self) -> None:
        command = smoke_media_server.build_ffmpeg_lavfi_command(
            "player_3",
            {
                "FFMPEG_EXECUTABLE": "ffmpeg-test",
                "SRS_RTMP_HOST": "127.0.0.2",
                "SRS_RTMP_PORT": "2935",
                "SMOKE_PUBLISH_SECONDS": "2.5",
                "SMOKE_VIDEO_LAVFI": "testsrc2=size=640x360:rate=15",
            },
        )

        self.assertEqual(command[0], "ffmpeg-test")
        self.assertIn("lavfi", command)
        self.assertIn("testsrc2=size=640x360:rate=15", command)
        self.assertIn("sine=frequency=660:sample_rate=48000", command)
        self.assertIn("2.5", command)
        self.assertEqual(command[-1], "rtmp://127.0.0.2:2935/live/player_3")

    def test_media_server_smoke_starts_compose_checks_srs_and_publishes(self) -> None:
        commands = []

        def run(command, **kwargs):
            commands.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

        def get(url, **kwargs):
            self.assertEqual(kwargs["timeout"], 1.25)
            return FakeResponse({"code": 0, "data": {"streams": []}})

        result = smoke_media_server.smoke_media_server(
            {
                "SMOKE_HTTP_TIMEOUT_SECONDS": "1.25",
                "SMOKE_READY_TIMEOUT_SECONDS": "0",
                "SMOKE_PUBLISH_STREAMS": "player_1,player_2",
                "SMOKE_PUBLISH_TIMEOUT_SECONDS": "7",
            },
            run=run,
            get=get,
            sleep=lambda seconds: None,
        )

        self.assertEqual(commands[0][0][:4], ["docker", "compose", "--profile", "media-server"])
        self.assertEqual(commands[1][0][-1], "rtmp://127.0.0.1:1935/live/player_1")
        self.assertEqual(commands[2][0][-1], "rtmp://127.0.0.1:1935/live/player_2")
        self.assertEqual(commands[1][1]["timeout"], 7.0)
        self.assertEqual(result.summaries.payload_keys, ("code", "data"))
        self.assertEqual([item.stream_id for item in result.publish_results], ["player_1", "player_2"])

    def test_publish_timeout_returns_cli_failure(self) -> None:
        def run(command, **kwargs):
            if command[:2] == ["docker", "compose"]:
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
            raise subprocess.TimeoutExpired(command, timeout=0.01)

        with self.assertRaisesRegex(
            smoke_media_server.SmokeFailure,
            "Timed out publishing",
        ):
            smoke_media_server.smoke_media_server(
                {
                    "SMOKE_READY_TIMEOUT_SECONDS": "0",
                    "SMOKE_PUBLISH_TIMEOUT_SECONDS": "0.01",
                },
                run=run,
                get=lambda *args, **kwargs: FakeResponse({}),
                sleep=lambda seconds: None,
            )


class SmokeBufferWorkerTests(unittest.TestCase):
    def test_buffer_inspection_reports_ready_clip_from_segment_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stream_dir = Path(temp_dir) / "player_1"
            stream_dir.mkdir()
            first = stream_dir / "000000000.ts"
            second = stream_dir / "000000001.ts"
            first.write_bytes(b"one")
            second.write_bytes(b"two")
            (stream_dir / "segments.csv").write_text(
                f"{first},0.0,2.0\n{second},2.0,4.0\n",
                encoding="utf-8",
            )

            result = smoke_buffer_worker.inspect_buffer(
                {
                    "LOOKBACK_BUFFER_DIR": temp_dir,
                    "SMOKE_BUFFER_STREAM_IDS": "player_1",
                }
            )

        self.assertEqual(result.ready_streams, ("player_1",))
        stream = result.streams[0]
        self.assertEqual(stream.segment_count, 2)
        self.assertEqual(stream.clip_status, "ready")
        self.assertIsNotNone(stream.latest_segment)
        self.assertTrue(stream.clip_media_uri.endswith(".m3u8"))

    def test_buffer_inspection_fails_when_no_clip_is_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = smoke_buffer_worker.inspect_buffer(
                {
                    "LOOKBACK_BUFFER_DIR": temp_dir,
                    "SMOKE_BUFFER_STREAM_IDS": "player_1",
                }
            )

        with self.assertRaisesRegex(smoke_buffer_worker.SmokeFailure, "No resolvable"):
            smoke_buffer_worker.assert_any_ready(result)


class SmokeTranscriptionApiTests(unittest.TestCase):
    def test_transcription_smoke_posts_audio_reference_with_timeout(self) -> None:
        calls = []

        def post(url, **kwargs):
            calls.append((url, kwargs))
            return FakeResponse({"segments": []})

        result = smoke_transcription_api.smoke_transcription_api(
            {
                "TRANSCRIPTION_API_URL": "http://whisper.test:9000",
                "SMOKE_TRANSCRIPTION_TIMEOUT_SECONDS": "4.5",
                "SMOKE_TRANSCRIPTION_STREAM_ID": "player_4",
                "SMOKE_TRANSCRIPTION_AUDIO_URI": "file:///fixture.wav",
            },
            post=post,
        )

        self.assertEqual(result.endpoint_url, "http://whisper.test:9000/transcribe")
        self.assertEqual(result.request_mode, "json")
        self.assertEqual(result.event_count, 0)
        self.assertEqual(calls[0][0], "http://whisper.test:9000/transcribe")
        self.assertEqual(calls[0][1]["timeout"], 4.5)
        self.assertEqual(calls[0][1]["json"]["stream_id"], "player_4")
        self.assertEqual(calls[0][1]["json"]["audio_uri"], "file:///fixture.wav")

    def test_transcription_smoke_supports_openai_compatible_uploads(self) -> None:
        calls = []

        def post(url, **kwargs):
            calls.append((url, kwargs))
            return FakeResponse({"segments": []})

        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "fixture.wav"
            audio_path.write_bytes(b"audio")

            result = smoke_transcription_api.smoke_transcription_api(
                {
                    "TRANSCRIPTION_API_URL": "http://whisper.test:9000",
                    "TRANSCRIPTION_REQUEST_MODE": "openai-compatible",
                    "TRANSCRIPTION_MODEL": "local-whisper",
                    "TRANSCRIPTION_RESPONSE_FORMAT": "verbose_json",
                    "SMOKE_TRANSCRIPTION_AUDIO_URI": audio_path.as_uri(),
                },
                post=post,
            )

        self.assertEqual(
            result.endpoint_url,
            "http://whisper.test:9000/v1/audio/transcriptions",
        )
        self.assertEqual(result.request_mode, "openai-compatible")
        self.assertEqual(calls[0][0], "http://whisper.test:9000/v1/audio/transcriptions")
        self.assertEqual(calls[0][1]["data"]["model"], "local-whisper")
        self.assertEqual(calls[0][1]["data"]["response_format"], "verbose_json")
        self.assertIn("file", calls[0][1]["files"])

    def test_transcription_smoke_surfaces_failed_request(self) -> None:
        def post(url, **kwargs):
            return FakeResponse({}, error=RuntimeError("offline"))

        with self.assertRaisesRegex(smoke_transcription_api.SmokeFailure, "offline"):
            smoke_transcription_api.smoke_transcription_api(
                {"TRANSCRIPTION_API_URL": "http://whisper.test:9000"},
                post=post,
            )


class SmokeAIEndpointTests(unittest.TestCase):
    def test_ollama_smoke_requires_configured_model(self) -> None:
        calls = []

        def get(url, **kwargs):
            calls.append((url, kwargs))
            return FakeResponse({"models": [{"name": "gemma3:4b"}]})

        result = smoke_ai_endpoint.smoke_ai_endpoint(
            {
                "AI_PROVIDER": "ollama",
                "GEMMA_API_URL": "http://ollama.test:11434",
                "GEMMA_MODEL": "gemma3:4b",
                "SMOKE_AI_TIMEOUT_SECONDS": "2",
            },
            get=get,
        )

        self.assertEqual(result.provider, "ollama")
        self.assertEqual(result.endpoint_url, "http://ollama.test:11434")
        self.assertEqual(result.probe_url, "http://ollama.test:11434/api/tags")
        self.assertEqual(result.url, "http://ollama.test:11434/api/tags")
        self.assertEqual(result.available_models, ("gemma3:4b",))
        self.assertEqual(result.detected_model_count, 1)
        self.assertEqual(calls[0][0], "http://ollama.test:11434/api/tags")
        self.assertEqual(calls[0][1]["timeout"], 2.0)

    def test_ollama_smoke_fails_with_pull_hint_for_missing_model(self) -> None:
        with self.assertRaises(smoke_ai_endpoint.SmokeFailure) as raised:
            smoke_ai_endpoint.smoke_ai_endpoint(
                {
                    "AI_PROVIDER": "ollama",
                    "GEMMA_API_URL": "http://ollama.test:11434",
                    "GEMMA_MODEL": "missing-model",
                },
                get=lambda *args, **kwargs: FakeResponse(
                    {"models": [{"name": "other"}, {"model": "smaller"}]}
                ),
            )

        message = str(raised.exception)
        self.assertIn("provider=ollama", message)
        self.assertIn("endpoint=http://ollama.test:11434", message)
        self.assertIn("model=missing-model", message)
        self.assertIn("Detected models: other, smaller", message)
        self.assertIn("Run: ollama pull missing-model", message)

    def test_ollama_smoke_fails_on_malformed_model_list(self) -> None:
        with self.assertRaises(smoke_ai_endpoint.SmokeFailure) as raised:
            smoke_ai_endpoint.smoke_ai_endpoint(
                {
                    "AI_PROVIDER": "ollama",
                    "GEMMA_API_URL": "http://ollama.test:11434",
                    "GEMMA_MODEL": "gemma3:4b",
                },
                get=lambda *args, **kwargs: FakeResponse(
                    {"models": [{"digest": "abc123"}, "gemma3:4b"]}
                ),
            )

        message = str(raised.exception)
        self.assertIn("provider=ollama", message)
        self.assertIn("endpoint=http://ollama.test:11434", message)
        self.assertIn("model=gemma3:4b", message)
        self.assertIn("model list did not contain any parseable model names", message)

    def test_openai_compatible_smoke_checks_provider_reachability(self) -> None:
        calls = []

        def get(url, **kwargs):
            calls.append((url, kwargs))
            return FakeResponse({"ok": True})

        result = smoke_ai_endpoint.smoke_ai_endpoint(
            {
                "AI_PROVIDER": "openai-compatible",
                "GEMMA_API_URL": "https://llm.example.test/v1/chat/completions",
                "GEMMA_MODEL": "google/gemma-3-4b-it",
            },
            get=get,
        )

        self.assertEqual(result.provider, "openai-compatible")
        self.assertEqual(result.endpoint_url, "https://llm.example.test/v1/chat/completions")
        self.assertEqual(result.probe_url, "https://llm.example.test")
        self.assertEqual(result.url, "https://llm.example.test")
        self.assertEqual(result.model, "google/gemma-3-4b-it")
        self.assertFalse(result.api_key_configured)
        self.assertIsNone(result.detected_model_count)
        self.assertEqual(calls[0][0], "https://llm.example.test")
        self.assertEqual(calls[0][1]["headers"], {})

    def test_openai_compatible_smoke_sends_auth_header_when_key_is_set(self) -> None:
        calls = []

        def get(url, **kwargs):
            calls.append((url, kwargs))
            return FakeResponse({"ok": True})

        result = smoke_ai_endpoint.smoke_ai_endpoint(
            {
                "AI_PROVIDER": "openai-compatible",
                "GEMMA_API_URL": "https://llm.example.test/v1/chat/completions",
                "GEMMA_MODEL": "gemma",
                "GEMMA_API_KEY": "secret",
            },
            get=get,
        )

        self.assertEqual(result.provider, "openai-compatible")
        self.assertEqual(result.url, "https://llm.example.test")
        self.assertTrue(result.api_key_configured)
        self.assertEqual(calls[0][0], "https://llm.example.test")
        self.assertEqual(calls[0][1]["headers"], {"Authorization": "Bearer secret"})

    def test_openai_compatible_smoke_result_does_not_serialize_api_key(self) -> None:
        secret = "super-secret-token"

        result = smoke_ai_endpoint.smoke_ai_endpoint(
            {
                "AI_PROVIDER": "openai-compatible",
                "GEMMA_API_URL": "https://llm.example.test/v1/chat/completions",
                "GEMMA_MODEL": "gemma",
                "GEMMA_API_KEY": secret,
            },
            get=lambda *args, **kwargs: FakeResponse({"ok": True}),
        )

        payload = json.dumps(asdict(result), sort_keys=True)
        self.assertTrue(result.api_key_configured)
        self.assertNotIn(secret, payload)


class SmokeOrchestratorDryRunTests(unittest.TestCase):
    def test_orchestrator_env_forces_dry_run_and_fake_ai_endpoint(self) -> None:
        env = smoke_orchestrator_dry_run.build_subprocess_env(
            {"DRY_RUN_OBS": "false", "AI_PROVIDER": "ollama"},
            fake_ai_url="http://127.0.0.1:9999",
        )

        self.assertEqual(env["DRY_RUN_OBS"], "true")
        self.assertEqual(env["AI_PROVIDER"], "openai-compatible")
        self.assertEqual(env["GEMMA_API_URL"], "http://127.0.0.1:9999")
        self.assertEqual(env["GEMMA_MODEL"], "smoke-model")

    def test_orchestrator_smoke_passes_bounded_input_to_subprocess(self) -> None:
        calls = []

        def run(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=(
                    "DRY_RUN_OBS enabled\n"
                    "[DRY RUN OBS] Starting scene: Quad View\n"
                    "Manual command applied.\n"
                    "Exiting.\n"
                ),
                stderr="",
            )

        result = smoke_orchestrator_dry_run.smoke_orchestrator_dry_run(
            {
                "SMOKE_ORCHESTRATOR_FAKE_AI": "false",
                "SMOKE_ORCHESTRATOR_TIMEOUT_SECONDS": "6",
                "SMOKE_ORCHESTRATOR_INPUT": "/status\\n/quit",
            },
            run=run,
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(calls[0][0][-1], "src/main.py")
        self.assertEqual(calls[0][1]["timeout"], 6.0)
        self.assertEqual(calls[0][1]["input"], "/status\n/quit\n")
        self.assertEqual(calls[0][1]["env"]["DRY_RUN_OBS"], "true")

    def test_orchestrator_smoke_fails_on_nonzero_exit(self) -> None:
        with self.assertRaisesRegex(smoke_orchestrator_dry_run.SmokeFailure, "code 1"):
            smoke_orchestrator_dry_run.smoke_orchestrator_dry_run(
                {"SMOKE_ORCHESTRATOR_FAKE_AI": "false"},
                run=lambda command, **kwargs: subprocess.CompletedProcess(
                    command,
                    1,
                    stdout="",
                    stderr="AI director is not ready",
                ),
            )


class SmokeEntrypointImportTests(unittest.TestCase):
    def test_importing_scripts_does_not_create_configured_runtime_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            buffer_dir = Path(temp_dir) / "buffer"
            audio_dir = Path(temp_dir) / "audio"
            script = f"""
import importlib
import os
import sys
from pathlib import Path
sys.path.insert(0, {str(PROJECT_DIR)!r})
os.environ["LOOKBACK_BUFFER_DIR"] = {str(buffer_dir)!r}
os.environ["AUDIO_EXTRACT_DIR"] = {str(audio_dir)!r}
for name in (
    "scripts.smoke_media_server",
    "scripts.smoke_buffer_worker",
    "scripts.smoke_transcription_api",
    "scripts.smoke_ai_endpoint",
    "scripts.smoke_orchestrator_dry_run",
):
    importlib.import_module(name)
if Path(os.environ["LOOKBACK_BUFFER_DIR"]).exists():
    raise SystemExit("buffer dir created on import")
if Path(os.environ["AUDIO_EXTRACT_DIR"]).exists():
    raise SystemExit("audio dir created on import")
"""

            result = subprocess.run(
                [sys.executable, "-B", "-c", script],
                check=False,
                capture_output=True,
                text=True,
                cwd=str(PROJECT_DIR),
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
