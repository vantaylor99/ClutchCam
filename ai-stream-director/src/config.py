import os
from dataclasses import dataclass


STREAM_IDS = ("player_1", "player_2", "player_3", "player_4")

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
    dry_run_obs: bool
    ingest_api_url: str
    transcription_api_url: str
    gemma_api_url: str
    gemma_model: str
    lookback_buffer_dir: str
    lookback_window_seconds: int
    switch_lookback_seconds: int
    lookback_segment_seconds: float
    lookback_input_urls: dict[str, str]
    ffmpeg_executable: str
    audio_extract_dir: str
    audio_extract_sample_rate: int
    audio_extract_channels: int
    audio_extract_chunk_seconds: float
    audio_extract_codec: str
    audio_extract_container: str
    audio_input_urls: dict[str, str]
    confidence_threshold: float
    min_switch_interval_seconds: int
    max_focus_duration_seconds: int
    transcript_history_seconds: int
    transcript_history_messages: int
    default_scene: str

    @property
    def ollama_base_url(self) -> str:
        return self.gemma_api_url

    @property
    def ollama_model(self) -> str:
        return self.gemma_model


def get_config() -> AppConfig:
    return AppConfig(
        obs_host=os.getenv("OBS_HOST", "host.docker.internal"),
        obs_port=int(os.getenv("OBS_PORT", "4455")),
        obs_password=os.getenv("OBS_PASSWORD", ""),
        dry_run_obs=_parse_bool(os.getenv("DRY_RUN_OBS", "false")),
        ingest_api_url=os.getenv("INGEST_API_URL", "rtmp://localhost/live"),
        transcription_api_url=os.getenv(
            "TRANSCRIPTION_API_URL",
            "http://faster-whisper:8000",
        ),
        gemma_api_url=_compat_env(
            primary_name="GEMMA_API_URL",
            fallback_name="OLLAMA_BASE_URL",
            default="http://ollama:11434",
        ),
        gemma_model=_compat_env(
            primary_name="GEMMA_MODEL",
            fallback_name="OLLAMA_MODEL",
            default="gemma3:4b",
        ),
        lookback_buffer_dir=os.getenv("LOOKBACK_BUFFER_DIR", "/dev/shm/clutchcam"),
        lookback_window_seconds=int(os.getenv("LOOKBACK_WINDOW_SECONDS", "30")),
        switch_lookback_seconds=int(os.getenv("SWITCH_LOOKBACK_SECONDS", "15")),
        lookback_segment_seconds=float(os.getenv("LOOKBACK_SEGMENT_SECONDS", "2")),
        lookback_input_urls=_build_lookback_input_urls(
            os.getenv("INGEST_API_URL", "rtmp://localhost/live")
        ),
        ffmpeg_executable=os.getenv("FFMPEG_EXECUTABLE", "ffmpeg"),
        audio_extract_dir=os.getenv(
            "AUDIO_EXTRACT_DIR",
            "/dev/shm/clutchcam-audio",
        ),
        audio_extract_sample_rate=int(os.getenv("AUDIO_EXTRACT_SAMPLE_RATE", "16000")),
        audio_extract_channels=int(os.getenv("AUDIO_EXTRACT_CHANNELS", "1")),
        audio_extract_chunk_seconds=float(os.getenv("AUDIO_EXTRACT_CHUNK_SECONDS", "5")),
        audio_extract_codec=os.getenv("AUDIO_EXTRACT_CODEC", "pcm_s16le"),
        audio_extract_container=os.getenv("AUDIO_EXTRACT_CONTAINER", "wav"),
        audio_input_urls=_build_audio_input_urls(
            os.getenv("INGEST_API_URL", "rtmp://localhost/live")
        ),
        confidence_threshold=float(os.getenv("CONFIDENCE_THRESHOLD", "0.75")),
        min_switch_interval_seconds=int(os.getenv("MIN_SWITCH_INTERVAL_SECONDS", "8")),
        max_focus_duration_seconds=int(os.getenv("MAX_FOCUS_DURATION_SECONDS", "20")),
        transcript_history_seconds=int(os.getenv("TRANSCRIPT_HISTORY_SECONDS", "30")),
        transcript_history_messages=int(os.getenv("TRANSCRIPT_HISTORY_MESSAGES", "20")),
        default_scene=SCENES["quad"],
    )


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _compat_env(primary_name: str, fallback_name: str, default: str) -> str:
    value = os.getenv(primary_name)
    if value is not None:
        return value

    value = os.getenv(fallback_name)
    if value is not None:
        return value

    return default


def _build_lookback_input_urls(ingest_base_url: str) -> dict[str, str]:
    base_url = ingest_base_url.rstrip("/")
    urls: dict[str, str] = {}
    for stream_id in STREAM_IDS:
        env_name = f"LOOKBACK_INPUT_URL_{stream_id.upper()}"
        urls[stream_id] = os.getenv(env_name, f"{base_url}/{stream_id}")

    return urls


def _build_audio_input_urls(ingest_base_url: str) -> dict[str, str]:
    base_url = ingest_base_url.rstrip("/")
    urls: dict[str, str] = {}
    for stream_id in STREAM_IDS:
        audio_env_name = f"AUDIO_INPUT_URL_{stream_id.upper()}"
        lookback_env_name = f"LOOKBACK_INPUT_URL_{stream_id.upper()}"
        urls[stream_id] = os.getenv(
            audio_env_name,
            os.getenv(lookback_env_name, f"{base_url}/{stream_id}"),
        )

    return urls
