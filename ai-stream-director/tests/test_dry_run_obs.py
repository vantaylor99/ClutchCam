import builtins
import io
import importlib
import os
import sys
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import ANY, Mock, patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from config import (  # noqa: E402
    AI_PROVIDER_OLLAMA,
    AI_PROVIDER_OPENAI_COMPATIBLE,
    SECRET_REDACTION,
    SCENES,
    TRANSCRIPTION_SOURCE_MODE_CHUNKED,
    TRANSCRIPTION_SOURCE_MODE_VAD_UTTERANCE,
    get_config,
    redact_secrets,
)
from ai_director import DirectorDecision  # noqa: E402
from main import TerminalOutput, process_line  # noqa: E402
from obs_controller import (  # noqa: E402
    DryRunOBSController,
    OBSController,
    collect_obs_preflight,
    find_missing_scenes,
)
from scheduler import SceneScheduler  # noqa: E402
from transcript_router import TranscriptRouter  # noqa: E402


class DryRunOBSConfigTests(unittest.TestCase):
    def test_dry_run_obs_defaults_to_false(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(get_config().dry_run_obs)

    def test_dry_run_obs_accepts_common_true_values(self) -> None:
        for value in ("1", "true", "yes", "y", "on", " TRUE "):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"DRY_RUN_OBS": value}, clear=True):
                    self.assertTrue(get_config().dry_run_obs)

    def test_ai_provider_defaults_to_ollama(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = get_config()

        self.assertEqual(config.ai_provider, AI_PROVIDER_OLLAMA)
        self.assertEqual(config.gemma_api_key, "")

    def test_ai_provider_accepts_openai_compatible_alias_and_api_key(self) -> None:
        with patch.dict(
            os.environ,
            {
                "AI_PROVIDER": "vllm",
                "GEMMA_API_URL": "http://vllm:8000",
                "GEMMA_MODEL": "google/gemma-3-4b-it",
                "GEMMA_API_KEY": "secret-token",
            },
            clear=True,
        ):
            config = get_config()

        self.assertEqual(config.ai_provider, AI_PROVIDER_OPENAI_COMPATIBLE)
        self.assertEqual(config.gemma_api_url, "http://vllm:8000")
        self.assertEqual(config.gemma_model, "google/gemma-3-4b-it")
        self.assertEqual(config.gemma_api_key, "secret-token")

    def test_ai_provider_rejects_unknown_value(self) -> None:
        with patch.dict(os.environ, {"AI_PROVIDER": "mystery"}, clear=True):
            with self.assertRaisesRegex(ValueError, "Unsupported AI_PROVIDER"):
                get_config()

    def test_rejects_invalid_runtime_config_values(self) -> None:
        cases = (
            ({"OBS_PORT": "70000"}, "OBS_PORT must be between 1 and 65535"),
            ({"OBS_PORT": "not-a-port"}, "OBS_PORT must be an integer"),
            ({"INGEST_API_URL": "localhost/live"}, "INGEST_API_URL must use"),
            (
                {"TRANSCRIPTION_API_URL": "rtmp://whisper/live"},
                "TRANSCRIPTION_API_URL must use",
            ),
            (
                {"GEMMA_API_URL": "http:///missing-host"},
                "GEMMA_API_URL must include a host",
            ),
            (
                {"GEMMA_API_URL": "https://user:pass@llm.example.test"},
                "GEMMA_API_URL cannot include embedded credentials",
            ),
            ({"LOOKBACK_BUFFER_DIR": "  "}, "LOOKBACK_BUFFER_DIR is required"),
            (
                {"LOOKBACK_WINDOW_SECONDS": "0"},
                "LOOKBACK_WINDOW_SECONDS must be positive",
            ),
            (
                {
                    "LOOKBACK_WINDOW_SECONDS": "10",
                    "SWITCH_LOOKBACK_SECONDS": "11",
                },
                "SWITCH_LOOKBACK_SECONDS cannot exceed LOOKBACK_WINDOW_SECONDS",
            ),
            (
                {"CONFIDENCE_THRESHOLD": "1.5"},
                "CONFIDENCE_THRESHOLD must be between 0 and 1",
            ),
            (
                {"TRANSCRIPTION_REQUEST_TIMEOUT_SECONDS": "0"},
                "TRANSCRIPTION_REQUEST_TIMEOUT_SECONDS must be positive",
            ),
            (
                {"LIVE_TRANSCRIPTION_QUEUE_SIZE": "0"},
                "LIVE_TRANSCRIPTION_QUEUE_SIZE must be positive",
            ),
            (
                {"TRANSCRIPTION_SOURCE_MODE": "mystery"},
                "Unsupported TRANSCRIPTION_SOURCE_MODE",
            ),
            (
                {"TRANSCRIPT_LOG_TEXT_MAX_CHARACTERS": "0"},
                "TRANSCRIPT_LOG_TEXT_MAX_CHARACTERS must be positive",
            ),
            (
                {"TRANSCRIPT_UTTERANCE_MAX_GAP_SECONDS": "0"},
                "TRANSCRIPT_UTTERANCE_MAX_GAP_SECONDS must be positive",
            ),
            (
                {"TRANSCRIPT_UTTERANCE_MAX_DURATION_SECONDS": "0"},
                "TRANSCRIPT_UTTERANCE_MAX_DURATION_SECONDS must be positive",
            ),
            (
                {"TRANSCRIPT_UTTERANCE_MAX_CHARACTERS": "0"},
                "TRANSCRIPT_UTTERANCE_MAX_CHARACTERS must be positive",
            ),
            (
                {"TRANSCRIPT_UTTERANCE_MAX_EVENTS": "0"},
                "TRANSCRIPT_UTTERANCE_MAX_EVENTS must be positive",
            ),
        )

        for env, message in cases:
            with self.subTest(env=env):
                with patch.dict(os.environ, env, clear=True):
                    with self.assertRaisesRegex(ValueError, message):
                        get_config()

    def test_stream_input_overrides_must_be_valid_urls(self) -> None:
        with patch.dict(
            os.environ,
            {"LOOKBACK_INPUT_URL_PLAYER_2": "media-server/live/player_2"},
            clear=True,
        ):
            with self.assertRaisesRegex(
                ValueError,
                "LOOKBACK_INPUT_URL_\\*:player_2 must use",
            ):
                get_config()

    def test_openai_compatible_provider_keeps_local_keyless_endpoint_ergonomics(self) -> None:
        with patch.dict(
            os.environ,
            {
                "AI_PROVIDER": "openai-compatible",
                "GEMMA_API_URL": "http://vllm:8000/v1/chat/completions",
                "GEMMA_MODEL": "google/gemma-3-4b-it",
            },
            clear=True,
        ):
            config = get_config()

        self.assertEqual(config.ai_provider, AI_PROVIDER_OPENAI_COMPATIBLE)
        self.assertEqual(config.gemma_api_key, "")

    def test_redact_secrets_handles_current_and_future_secret_names(self) -> None:
        redacted = redact_secrets(
            {
                "GEMMA_API_KEY": "gemma-secret",
                "OBS_PASSWORD": "obs-secret",
                "nested": {
                    "future_refresh_token": "refresh-secret",
                    "public_url": "https://example.test",
                    "signed_url": "https://example.test/path?api_key=url-secret&ok=1",
                    "empty_api_key": "",
                    "keyframe_count": 3,
                    "apiKey": "camel-secret",
                },
                "items": [{"client_secret": "client-secret"}],
            }
        )

        self.assertEqual(redacted["GEMMA_API_KEY"], SECRET_REDACTION)
        self.assertEqual(redacted["OBS_PASSWORD"], SECRET_REDACTION)
        self.assertEqual(redacted["nested"]["future_refresh_token"], SECRET_REDACTION)
        self.assertEqual(redacted["nested"]["public_url"], "https://example.test")
        self.assertEqual(
            redacted["nested"]["signed_url"],
            f"https://example.test/path?api_key={SECRET_REDACTION}&ok=1",
        )
        self.assertEqual(redacted["nested"]["empty_api_key"], "")
        self.assertEqual(redacted["nested"]["keyframe_count"], 3)
        self.assertEqual(redacted["nested"]["apiKey"], SECRET_REDACTION)
        self.assertEqual(redacted["items"][0]["client_secret"], SECRET_REDACTION)

    def test_prefers_gemma_env_names_over_ollama_compat_aliases(self) -> None:
        with patch.dict(
            os.environ,
            {
                "GEMMA_API_URL": "http://gemma:8000",
                "GEMMA_MODEL": "gemma4:e4b",
                "OLLAMA_BASE_URL": "http://ollama:11434",
                "OLLAMA_MODEL": "gemma3:4b",
            },
            clear=True,
        ):
            config = get_config()

        self.assertEqual(config.gemma_api_url, "http://gemma:8000")
        self.assertEqual(config.gemma_model, "gemma4:e4b")
        self.assertEqual(config.ollama_base_url, "http://gemma:8000")
        self.assertEqual(config.ollama_model, "gemma4:e4b")

    def test_transcript_prefilter_runtime_settings_are_configurable(self) -> None:
        with patch.dict(
            os.environ,
            {
                "TRANSCRIPT_PREFILTER_ENABLED": "false",
                "TRANSCRIPT_PREFILTER_MIN_TEXT_CHARACTERS": "9",
                "TRANSCRIPT_PREFILTER_DUPLICATE_WINDOW_SECONDS": "4.5",
                "TRANSCRIPT_PREFILTER_CONTEXT_SECONDS": "18",
                "TRANSCRIPT_PREFILTER_MIN_CONFIDENCE": "0.82",
            },
            clear=True,
        ):
            config = get_config()

        self.assertFalse(config.transcript_prefilter_enabled)
        self.assertEqual(config.transcript_prefilter_min_text_characters, 9)
        self.assertEqual(config.transcript_prefilter_duplicate_window_seconds, 4.5)
        self.assertEqual(config.transcript_prefilter_context_seconds, 18.0)
        self.assertEqual(config.transcript_prefilter_min_confidence, 0.82)

    def test_transcript_utterance_runtime_settings_are_configurable(self) -> None:
        with patch.dict(
            os.environ,
            {
                "TRANSCRIPT_UTTERANCE_MAX_GAP_SECONDS": "1.5",
                "TRANSCRIPT_UTTERANCE_MAX_DURATION_SECONDS": "6.5",
                "TRANSCRIPT_UTTERANCE_MAX_CHARACTERS": "120",
                "TRANSCRIPT_UTTERANCE_MAX_EVENTS": "4",
            },
            clear=True,
        ):
            config = get_config()

        self.assertEqual(config.transcript_utterance_max_gap_seconds, 1.5)
        self.assertEqual(config.transcript_utterance_max_duration_seconds, 6.5)
        self.assertEqual(config.transcript_utterance_max_characters, 120)
        self.assertEqual(config.transcript_utterance_max_events, 4)

    def test_production_boundary_defaults_are_available(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = get_config()

        self.assertEqual(config.ingest_api_url, "rtmp://localhost/live")
        self.assertEqual(config.transcription_api_url, "http://faster-whisper:8000")
        self.assertFalse(config.live_transcription_enabled)
        self.assertEqual(config.live_transcription_queue_size, 16)
        self.assertFalse(config.transcript_log_text_enabled)
        self.assertEqual(config.transcript_log_text_max_characters, 160)
        self.assertEqual(config.transcript_utterance_max_gap_seconds, 2.0)
        self.assertEqual(config.transcript_utterance_max_duration_seconds, 8.0)
        self.assertEqual(config.transcript_utterance_max_characters, 240)
        self.assertEqual(config.transcript_utterance_max_events, 8)
        self.assertEqual(config.lookback_buffer_dir, "/dev/shm/clutchcam")
        self.assertEqual(config.lookback_window_seconds, 30)
        self.assertEqual(config.switch_lookback_seconds, 15)
        self.assertEqual(config.lookback_segment_seconds, 2.0)
        self.assertEqual(config.ffmpeg_executable, "ffmpeg")
        self.assertEqual(
            config.lookback_input_urls["player_1"],
            "rtmp://localhost/live/player_1",
        )

    def test_lookback_input_urls_accept_per_stream_overrides(self) -> None:
        with patch.dict(
            os.environ,
            {
                "INGEST_API_URL": "srt://media-router/live",
                "LOOKBACK_INPUT_URL_PLAYER_3": "srt://player-three:9000",
            },
            clear=True,
        ):
            config = get_config()

        self.assertEqual(
            config.lookback_input_urls["player_1"],
            "srt://media-router/live/player_1",
        )
        self.assertEqual(
            config.lookback_input_urls["player_3"],
            "srt://player-three:9000",
        )

    def test_live_transcription_runtime_settings_are_configurable(self) -> None:
        with patch.dict(
            os.environ,
            {
                "LIVE_TRANSCRIPTION_ENABLED": "true",
                "LIVE_TRANSCRIPTION_QUEUE_SIZE": "3",
                "TRANSCRIPTION_SOURCE_MODE": "vad_utterance",
                "TRANSCRIPT_LOG_TEXT_ENABLED": "true",
                "TRANSCRIPT_LOG_TEXT_MAX_CHARACTERS": "42",
            },
            clear=True,
        ):
            config = get_config()

        self.assertTrue(config.live_transcription_enabled)
        self.assertEqual(config.live_transcription_queue_size, 3)
        self.assertEqual(
            config.transcription_source_mode,
            TRANSCRIPTION_SOURCE_MODE_VAD_UTTERANCE,
        )
        self.assertTrue(config.transcript_log_text_enabled)
        self.assertEqual(config.transcript_log_text_max_characters, 42)

    def test_transcription_source_mode_defaults_to_chunked(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = get_config()

        self.assertEqual(
            config.transcription_source_mode,
            TRANSCRIPTION_SOURCE_MODE_CHUNKED,
        )

    def test_transcription_source_mode_accepts_chunked_alias(self) -> None:
        with patch.dict(
            os.environ,
            {"TRANSCRIPTION_SOURCE_MODE": "fixed_chunks"},
            clear=True,
        ):
            config = get_config()

        self.assertEqual(
            config.transcription_source_mode,
            TRANSCRIPTION_SOURCE_MODE_CHUNKED,
        )


class DryRunOBSControllerTests(unittest.TestCase):
    def test_dry_run_imports_and_runs_without_obsws_python(self) -> None:
        original_import = builtins.__import__

        def reject_obsws_python(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "obsws_python" or name.startswith("obsws_python."):
                raise ModuleNotFoundError(
                    "No module named 'obsws_python'",
                    name="obsws_python",
                )
            return original_import(name, globals, locals, fromlist, level)

        saved_modules = {
            name: sys.modules.get(name)
            for name in ("main", "obs_controller", "obsws_python")
        }
        for name in saved_modules:
            sys.modules.pop(name, None)

        try:
            with patch("builtins.__import__", side_effect=reject_obsws_python):
                obs_controller = importlib.import_module("obs_controller")
                main = importlib.import_module("main")
                controller = obs_controller.DryRunOBSController(
                    initial_scene=SCENES["quad"]
                )

                controller.connect()
                controller.set_scene(SCENES["player_2"])

                self.assertEqual(controller.get_current_scene(), SCENES["player_2"])
                self.assertTrue(hasattr(main, "main"))
        finally:
            for name in saved_modules:
                sys.modules.pop(name, None)
            for name, module in saved_modules.items():
                if module is not None:
                    sys.modules[name] = module

    def test_requires_connect_before_use(self) -> None:
        controller = DryRunOBSController(initial_scene=SCENES["quad"])

        with self.assertRaises(RuntimeError):
            controller.get_current_scene()

        with self.assertRaises(RuntimeError):
            controller.set_scene(SCENES["player_1"])

    def test_tracks_scene_in_memory_after_connect(self) -> None:
        controller = DryRunOBSController(initial_scene=SCENES["quad"])

        controller.connect()
        self.assertEqual(controller.get_current_scene(), SCENES["quad"])

        controller.set_scene(SCENES["player_1"])
        self.assertEqual(controller.get_current_scene(), SCENES["player_1"])

    def test_dry_run_media_source_requires_connect(self) -> None:
        controller = DryRunOBSController(initial_scene=SCENES["quad"])

        with self.assertRaises(RuntimeError):
            controller.set_media_source(
                "ClutchCam Buffered Playback",
                "file:///buffer/player_1/clip.m3u8",
            )

    def test_dry_run_media_source_logs_without_obs(self) -> None:
        output = io.StringIO()
        controller = DryRunOBSController(
            initial_scene=SCENES["quad"],
            log=lambda message: print(message, file=output),
        )

        controller.connect()
        controller.set_media_source(
            "ClutchCam Buffered Playback",
            "file:///buffer/player_1/clip.m3u8",
        )

        self.assertIn(
            "[DRY RUN OBS] Media source ClutchCam Buffered Playback set to: "
            "file:///buffer/player_1/clip.m3u8",
            output.getvalue(),
        )


class OBSControllerSceneListTests(unittest.TestCase):
    def test_connect_explains_missing_obsws_python_in_real_mode(self) -> None:
        controller = OBSController(host="localhost", port=4455, password="")

        missing_obsws_python = ModuleNotFoundError(
            "No module named 'obsws_python'",
            name="obsws_python",
        )
        with patch(
            "obs_controller.importlib.import_module",
            side_effect=missing_obsws_python,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "obsws-python is required.*DRY_RUN_OBS=true",
            ):
                controller.connect()

    def test_list_scenes_reads_scene_names_from_obs_response(self) -> None:
        controller = OBSController(host="localhost", port=4455, password="")
        response = Mock()
        response.scenes = [
            {"sceneName": SCENES["quad"]},
            {"sceneName": SCENES["player_1"]},
        ]
        controller.client = Mock()
        controller.client.get_scene_list.return_value = response

        self.assertEqual(
            controller.list_scenes(),
            [SCENES["quad"], SCENES["player_1"]],
        )

    def test_get_obs_version_uses_cached_connect_result(self) -> None:
        controller = OBSController(host="localhost", port=4455, password="")
        controller.client = Mock()
        controller._obs_version = "30.2.3"

        self.assertEqual(controller.get_obs_version(), "30.2.3")
        controller.client.get_version.assert_not_called()

    def test_collect_obs_preflight_reads_version_scene_and_missing_required(self) -> None:
        controller = OBSController(host="localhost", port=4455, password="")
        controller.client = Mock()
        version_response = Mock()
        version_response.obs_version = "30.2.3"
        controller.client.get_version.return_value = version_response
        current_scene_response = Mock()
        current_scene_response.current_program_scene_name = SCENES["player_2"]
        controller.client.get_current_program_scene.return_value = current_scene_response
        scene_list_response = Mock()
        scene_list_response.scenes = [
            {"sceneName": SCENES["quad"]},
            {"sceneName": SCENES["player_2"]},
            {"sceneName": SCENES["player_4"]},
        ]
        controller.client.get_scene_list.return_value = scene_list_response

        preflight = collect_obs_preflight(
            controller,
            required_scenes=SCENES.values(),
        )

        self.assertEqual(preflight.obs_version, "30.2.3")
        self.assertEqual(preflight.current_program_scene, SCENES["player_2"])
        self.assertEqual(
            preflight.scenes,
            (SCENES["quad"], SCENES["player_2"], SCENES["player_4"]),
        )
        self.assertEqual(
            preflight.missing_required_scenes,
            (SCENES["player_1"], SCENES["player_3"]),
        )

    def test_set_media_source_updates_file_uri_input_settings(self) -> None:
        controller = OBSController(host="localhost", port=4455, password="")
        controller.client = Mock()
        response = Mock()
        response.input_settings = {
            "is_local_file": True,
            "local_file": "C:\\buffer\\player_2\\clip.m3u8",
            "restart_on_activate": True,
        }
        controller.client.get_input_settings.return_value = response

        controller.set_media_source(
            "ClutchCam Buffered Playback",
            "file:///C:/buffer/player_2/clip.m3u8",
        )

        controller.client.set_input_settings.assert_called_once_with(
            input_name="ClutchCam Buffered Playback",
            input_settings={
                "is_local_file": True,
                "local_file": "C:\\buffer\\player_2\\clip.m3u8",
                "restart_on_activate": True,
            },
            overlay=True,
        )
        controller.client.get_input_settings.assert_called_once_with(
            input_name="ClutchCam Buffered Playback",
        )

    def test_set_media_source_updates_url_input_settings(self) -> None:
        controller = OBSController(host="localhost", port=4455, password="")
        controller.client = Mock()
        response = Mock()
        response.input_settings = {
            "is_local_file": False,
            "input": "http://media.example/clip.m3u8",
            "restart_on_activate": True,
        }
        controller.client.get_input_settings.return_value = response

        controller.set_media_source(
            "ClutchCam Buffered Playback",
            "http://media.example/clip.m3u8",
        )

        controller.client.set_input_settings.assert_called_once_with(
            input_name="ClutchCam Buffered Playback",
            input_settings={
                "is_local_file": False,
                "input": "http://media.example/clip.m3u8",
                "restart_on_activate": True,
            },
            overlay=True,
        )

    def test_set_media_source_fails_when_readback_does_not_match(self) -> None:
        controller = OBSController(host="localhost", port=4455, password="")
        controller.client = Mock()
        response = Mock()
        response.input_settings = {
            "is_local_file": False,
            "input": "http://media.example/other.m3u8",
        }
        controller.client.get_input_settings.return_value = response

        with self.assertRaisesRegex(RuntimeError, "did not match"):
            controller.set_media_source(
                "ClutchCam Buffered Playback",
                "http://media.example/clip.m3u8",
            )

    def test_set_media_source_fails_when_readback_is_missing(self) -> None:
        controller = OBSController(host="localhost", port=4455, password="")
        controller.client = Mock()
        controller.client.get_input_settings.return_value = object()

        with self.assertRaisesRegex(RuntimeError, "could not be read back"):
            controller.set_media_source(
                "ClutchCam Buffered Playback",
                "http://media.example/clip.m3u8",
            )


class OBSSceneValidationTests(unittest.TestCase):
    def test_find_missing_scenes_preserves_required_scene_order(self) -> None:
        missing = find_missing_scenes(
            available_scenes=[
                SCENES["quad"],
                SCENES["player_2"],
                SCENES["player_4"],
            ],
            required_scenes=SCENES.values(),
        )

        self.assertEqual(missing, [SCENES["player_1"], SCENES["player_3"]])

    def test_find_missing_scenes_accepts_complete_scene_set(self) -> None:
        self.assertEqual(
            find_missing_scenes(
                available_scenes=SCENES.values(),
                required_scenes=SCENES.values(),
            ),
            [],
        )


class TerminalOutputTests(unittest.TestCase):
    def test_refresh_prompt_logs_on_fresh_line(self) -> None:
        stream = io.StringIO()
        output = TerminalOutput(stream=stream)
        output.enable_prompt_refresh()

        output.log("AI decision: Player 2 Fullscreen")

        self.assertEqual(stream.getvalue(), "\nAI decision: Player 2 Fullscreen\n> ")

    def test_quit_command_uses_supplied_terminal_log(self) -> None:
        stream = io.StringIO()
        output = TerminalOutput(stream=stream)
        output.enable_prompt_refresh()

        should_quit = process_line(
            "/quit",
            TranscriptRouter(),
            Mock(),
            Mock(),
            log=output.log,
        )

        self.assertTrue(should_quit)
        self.assertEqual(stream.getvalue(), "\nExiting.\n> ")


class TerminalProcessLineAITests(unittest.TestCase):
    def _build_started_scheduler(self) -> SceneScheduler:
        controller = DryRunOBSController(initial_scene=SCENES["quad"])
        scheduler = SceneScheduler(
            obs_controller=controller,
            default_scene=SCENES["quad"],
            confidence_threshold=0.75,
            min_switch_interval_seconds=0,
            max_focus_duration_seconds=20,
        )
        controller.connect()
        scheduler.start()
        return scheduler

    def test_ai_disabled_accepts_transcript_without_calling_director(self) -> None:
        scheduler = self._build_started_scheduler()
        scheduler.set_ai_enabled(False)
        transcript_router = TranscriptRouter(history_seconds=30, max_messages=20)
        ai_director = Mock()

        output = io.StringIO()
        with redirect_stdout(output):
            should_quit = process_line(
                "player_2: no way, I found diamonds",
                transcript_router,
                ai_director,
                scheduler,
            )

        self.assertFalse(should_quit)
        ai_director.decide.assert_not_called()
        self.assertIn(
            "player_2: no way, I found diamonds",
            transcript_router.get_recent_context_text(),
        )
        self.assertIn(
            "AI evaluation skipped because AI mode is off",
            output.getvalue(),
        )
        self.assertNotIn("Asking AI director", output.getvalue())

    def test_ai_enabled_process_line_calls_director_and_applies_decision(self) -> None:
        scheduler = self._build_started_scheduler()
        transcript_router = TranscriptRouter(history_seconds=30, max_messages=20)
        decision = DirectorDecision(
            target_scene=SCENES["player_2"],
            confidence=0.9,
            duration_seconds=12,
            reason="Player 2 found diamonds.",
        )
        ai_director = Mock()
        ai_director.decide.return_value = decision

        output = io.StringIO()
        with redirect_stdout(output):
            should_quit = process_line(
                "player_2: no way, I found diamonds",
                transcript_router,
                ai_director,
                scheduler,
            )

        self.assertFalse(should_quit)
        ai_director.decide.assert_called_once_with(
            "player_2: no way, I found diamonds",
            candidate_signal=ANY,
        )
        candidate_signal = ai_director.decide.call_args.kwargs["candidate_signal"]
        self.assertEqual(candidate_signal.stream_id, "player_2")
        self.assertIn("Asking AI director", output.getvalue())
        self.assertIn("AI decision: Player 2 Fullscreen", output.getvalue())
        self.assertEqual(scheduler.status().current_scene, SCENES["player_2"])

    def test_consecutive_manual_lines_can_assemble_before_ai_decision(self) -> None:
        scheduler = self._build_started_scheduler()
        transcript_router = TranscriptRouter(history_seconds=30, max_messages=20)
        ai_director = Mock()
        ai_director.decide.return_value = DirectorDecision(
            target_scene=SCENES["player_2"],
            confidence=0.9,
            duration_seconds=12,
            reason="Player 2 reacted.",
        )

        first_should_quit = process_line(
            "player_2: holy",
            transcript_router,
            ai_director,
            scheduler,
            log=lambda message: None,
        )
        second_should_quit = process_line(
            "player_2: cow",
            transcript_router,
            ai_director,
            scheduler,
            log=lambda message: None,
        )

        self.assertFalse(first_should_quit)
        self.assertFalse(second_should_quit)
        ai_director.decide.assert_called_once_with(
            "player_2: holy cow",
            candidate_signal=ANY,
        )
        self.assertEqual(transcript_router.get_recent_context_text(), "player_2: holy cow")

    def test_prefilter_skips_filler_without_calling_director(self) -> None:
        scheduler = self._build_started_scheduler()
        transcript_router = TranscriptRouter(history_seconds=30, max_messages=20)
        ai_director = Mock()

        output = io.StringIO()
        with redirect_stdout(output):
            should_quit = process_line(
                "player_1: yeah",
                transcript_router,
                ai_director,
                scheduler,
            )

        self.assertFalse(should_quit)
        ai_director.decide.assert_not_called()
        self.assertIn("player_1: yeah", transcript_router.get_recent_context_text())
        self.assertIn("Local prefilter found no trigger", output.getvalue())

    def test_active_cooldown_skips_model_call_after_accepting_transcript(self) -> None:
        controller = DryRunOBSController(initial_scene=SCENES["quad"])
        scheduler = SceneScheduler(
            obs_controller=controller,
            default_scene=SCENES["quad"],
            confidence_threshold=0.75,
            min_switch_interval_seconds=8,
            max_focus_duration_seconds=20,
        )
        controller.connect()
        scheduler.start()
        scheduler.last_switch_time = time.time()
        transcript_router = TranscriptRouter(history_seconds=30, max_messages=20)
        ai_director = Mock()

        output = io.StringIO()
        with redirect_stdout(output):
            should_quit = process_line(
                "player_4: holy cow, rare boss",
                transcript_router,
                ai_director,
                scheduler,
            )

        self.assertFalse(should_quit)
        ai_director.decide.assert_not_called()
        self.assertIn(
            "player_4: holy cow, rare boss",
            transcript_router.get_recent_context_text(),
        )
        self.assertIn("switch cooldown has", output.getvalue())


class DryRunSchedulerIntegrationTests(unittest.TestCase):
    def test_scheduler_status_tracks_manual_dry_run_scene_switches(self) -> None:
        controller = DryRunOBSController(initial_scene=SCENES["quad"])
        scheduler = SceneScheduler(
            obs_controller=controller,
            default_scene=SCENES["quad"],
            confidence_threshold=0.75,
            min_switch_interval_seconds=8,
            max_focus_duration_seconds=20,
        )

        controller.connect()
        scheduler.start()
        self.assertEqual(scheduler.status().current_scene, SCENES["quad"])

        scheduler.force_scene(SCENES["player_1"])
        self.assertEqual(scheduler.status().current_scene, SCENES["player_1"])
        self.assertEqual(controller.get_current_scene(), SCENES["player_1"])

        scheduler.force_scene(SCENES["quad"])
        self.assertEqual(scheduler.status().current_scene, SCENES["quad"])
        self.assertEqual(controller.get_current_scene(), SCENES["quad"])

    def test_startup_default_scene_does_not_block_first_ai_focus(self) -> None:
        controller = DryRunOBSController(initial_scene=SCENES["quad"])
        scheduler = SceneScheduler(
            obs_controller=controller,
            default_scene=SCENES["quad"],
            confidence_threshold=0.75,
            min_switch_interval_seconds=8,
            max_focus_duration_seconds=20,
        )
        decision = DirectorDecision(
            target_scene=SCENES["player_3"],
            confidence=0.9,
            duration_seconds=12,
            reason="Player 3 found something exciting.",
        )

        controller.connect()
        scheduler.start()
        scheduler.apply_ai_decision(decision)

        self.assertEqual(scheduler.status().current_scene, SCENES["player_3"])
        self.assertEqual(controller.get_current_scene(), SCENES["player_3"])

    def test_focus_timer_returns_to_quad_without_terminal_input(self) -> None:
        controller = DryRunOBSController(initial_scene=SCENES["quad"])
        scheduler = SceneScheduler(
            obs_controller=controller,
            default_scene=SCENES["quad"],
            confidence_threshold=0.75,
            min_switch_interval_seconds=8,
            max_focus_duration_seconds=20,
        )

        controller.connect()
        scheduler.start()
        scheduler.apply_ai_decision(
            DirectorDecision(
                target_scene=SCENES["player_2"],
                confidence=0.9,
                duration_seconds=12,
                reason="Player 2 hit a clear moment.",
            )
        )
        scheduler.focused_until = time.time() - 0.1
        scheduler.last_switch_time = time.time() - 8.1

        scheduler.tick()

        self.assertEqual(scheduler.status().current_scene, SCENES["quad"])
        self.assertEqual(controller.get_current_scene(), SCENES["quad"])


if __name__ == "__main__":
    unittest.main()
