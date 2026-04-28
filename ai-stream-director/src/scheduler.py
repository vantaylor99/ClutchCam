import time
from dataclasses import dataclass
from typing import Optional

from ai_director import DirectorDecision
from config import SCENES


@dataclass
class SchedulerStatus:
    current_scene: str
    ai_enabled: bool
    focused_until: Optional[float]
    last_switch_time: float


class SceneScheduler:
    def __init__(
        self,
        obs_controller,
        default_scene: str,
        confidence_threshold: float,
        min_switch_interval_seconds: int,
        max_focus_duration_seconds: int,
    ):
        self.obs = obs_controller
        self.default_scene = default_scene
        self.confidence_threshold = confidence_threshold
        self.min_switch_interval_seconds = min_switch_interval_seconds
        self.max_focus_duration_seconds = max_focus_duration_seconds
        self.ai_enabled = True
        self.current_scene = default_scene
        self.focused_until: Optional[float] = None
        self.last_switch_time = 0.0

    def start(self) -> None:
        self.force_scene(self.default_scene)

    def apply_ai_decision(self, decision: DirectorDecision) -> None:
        if not self.ai_enabled:
            print("AI decision ignored because AI mode is off.")
            return

        if decision.target_scene == self.default_scene:
            print(f"AI chose Quad View: {decision.reason}")
            return

        if decision.confidence < self.confidence_threshold:
            print(
                "AI decision ignored because confidence "
                f"{decision.confidence:.2f} is below {self.confidence_threshold:.2f}."
            )
            return

        if not self._cooldown_has_passed():
            remaining = self._cooldown_remaining()
            print(f"AI decision ignored because switch cooldown has {remaining:.1f}s left.")
            return

        duration = min(decision.duration_seconds, self.max_focus_duration_seconds)
        duration = max(1, duration)
        self._switch_scene(decision.target_scene)
        self.focused_until = time.time() + duration
        print(
            f"AI focused {decision.target_scene} for {duration}s "
            f"(confidence {decision.confidence:.2f}): {decision.reason}"
        )

    def tick(self) -> None:
        if (
            self.focused_until is not None
            and time.time() >= self.focused_until
            and self.current_scene != self.default_scene
        ):
            if self._cooldown_has_passed():
                self._switch_scene(self.default_scene)
                self.focused_until = None
                print("Focus duration ended. Returned to Quad View.")

    def force_scene(self, scene_name: str) -> None:
        self._switch_scene(scene_name)
        self.focused_until = None

    def set_ai_enabled(self, enabled: bool) -> None:
        self.ai_enabled = enabled
        state = "on" if enabled else "off"
        print(f"AI mode is now {state}.")

    def status(self) -> SchedulerStatus:
        return SchedulerStatus(
            current_scene=self.current_scene,
            ai_enabled=self.ai_enabled,
            focused_until=self.focused_until,
            last_switch_time=self.last_switch_time,
        )

    def _switch_scene(self, scene_name: str) -> None:
        self.obs.set_scene(scene_name)
        self.current_scene = scene_name
        self.last_switch_time = time.time()

    def _cooldown_has_passed(self) -> bool:
        return (time.time() - self.last_switch_time) >= self.min_switch_interval_seconds

    def _cooldown_remaining(self) -> float:
        elapsed = time.time() - self.last_switch_time
        return max(0.0, self.min_switch_interval_seconds - elapsed)


MANUAL_COMMAND_SCENES = {
    "/quad": SCENES["quad"],
    "/p1": SCENES["player_1"],
    "/p2": SCENES["player_2"],
    "/p3": SCENES["player_3"],
    "/p4": SCENES["player_4"],
}
