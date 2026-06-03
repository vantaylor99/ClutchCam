import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from config import SCENES, get_config  # noqa: E402
from ai_director import DirectorDecision  # noqa: E402
from main import find_missing_scenes  # noqa: E402
from obs_controller import DryRunOBSController, OBSController  # noqa: E402
from scheduler import SceneScheduler  # noqa: E402


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
