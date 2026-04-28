import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from config import SCENES, get_config  # noqa: E402
from obs_controller import DryRunOBSController  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()
