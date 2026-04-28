import os
from dataclasses import dataclass


SCENES = {
    "quad": "Quad View",
    "player_1": "Player 1 Fullscreen",
    "player_2": "Player 2 Fullscreen",
    "player_3": "Player 3 Fullscreen",
    "player_4": "Player 4 Fullscreen",
}

VALID_SCENE_NAMES = set(SCENES.values())


@dataclass(frozen=True)
class AppConfig:
    obs_host: str
    obs_port: int
    obs_password: str
    ollama_base_url: str
    ollama_model: str
    confidence_threshold: float
    min_switch_interval_seconds: int
    max_focus_duration_seconds: int
    transcript_history_seconds: int
    transcript_history_messages: int
    default_scene: str


def get_config() -> AppConfig:
    return AppConfig(
        obs_host=os.getenv("OBS_HOST", "host.docker.internal"),
        obs_port=int(os.getenv("OBS_PORT", "4455")),
        obs_password=os.getenv("OBS_PASSWORD", ""),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://ollama:11434"),
        ollama_model=os.getenv("OLLAMA_MODEL", "gemma3:4b"),
        confidence_threshold=float(os.getenv("CONFIDENCE_THRESHOLD", "0.75")),
        min_switch_interval_seconds=int(os.getenv("MIN_SWITCH_INTERVAL_SECONDS", "8")),
        max_focus_duration_seconds=int(os.getenv("MAX_FOCUS_DURATION_SECONDS", "20")),
        transcript_history_seconds=int(os.getenv("TRANSCRIPT_HISTORY_SECONDS", "30")),
        transcript_history_messages=int(os.getenv("TRANSCRIPT_HISTORY_MESSAGES", "20")),
        default_scene=SCENES["quad"],
    )
