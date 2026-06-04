import builtins
import io
import importlib
import os
import sys
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from config import SCENES, get_config  # noqa: E402
from ai_director import DirectorDecision  # noqa: E402
from main import TerminalOutput, find_missing_scenes, process_line  # noqa: E402
from obs_controller import DryRunOBSController, OBSController  # noqa: E402
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

    def test_production_boundary_defaults_are_available(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = get_config()

        self.assertEqual(config.ingest_api_url, "rtmp://localhost/live")
        self.assertEqual(config.transcription_api_url, "http://faster-whisper:8000")
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
            "player_2: no way, I found diamonds"
        )
        self.assertIn("Asking AI director", output.getvalue())
        self.assertIn("AI decision: Player 2 Fullscreen", output.getvalue())
        self.assertEqual(scheduler.status().current_scene, SCENES["player_2"])


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
