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

AI_PROVIDER_OLLAMA = "ollama"
AI_PROVIDER_OPENAI_COMPATIBLE = "openai-compatible"
SUPPORTED_AI_PROVIDERS = (AI_PROVIDER_OLLAMA, AI_PROVIDER_OPENAI_COMPATIBLE)

TRANSCRIPTION_REQUEST_MODE_JSON = "json"
TRANSCRIPTION_REQUEST_MODE_OPENAI_COMPATIBLE = "openai-compatible"
SUPPORTED_TRANSCRIPTION_REQUEST_MODES = (
    TRANSCRIPTION_REQUEST_MODE_JSON,
    TRANSCRIPTION_REQUEST_MODE_OPENAI_COMPATIBLE,
)

_AI_PROVIDER_ALIASES = {
    AI_PROVIDER_OLLAMA: AI_PROVIDER_OLLAMA,
    "ollama-native": AI_PROVIDER_OLLAMA,
    AI_PROVIDER_OPENAI_COMPATIBLE: AI_PROVIDER_OPENAI_COMPATIBLE,
    "openai": AI_PROVIDER_OPENAI_COMPATIBLE,
    "vllm": AI_PROVIDER_OPENAI_COMPATIBLE,
}

_TRANSCRIPTION_REQUEST_MODE_ALIASES = {
    TRANSCRIPTION_REQUEST_MODE_JSON: TRANSCRIPTION_REQUEST_MODE_JSON,
    "json-reference": TRANSCRIPTION_REQUEST_MODE_JSON,
    "reference": TRANSCRIPTION_REQUEST_MODE_JSON,
    "transcribe": TRANSCRIPTION_REQUEST_MODE_JSON,
    TRANSCRIPTION_REQUEST_MODE_OPENAI_COMPATIBLE: (
        TRANSCRIPTION_REQUEST_MODE_OPENAI_COMPATIBLE
    ),
    "openai": TRANSCRIPTION_REQUEST_MODE_OPENAI_COMPATIBLE,
    "multipart": TRANSCRIPTION_REQUEST_MODE_OPENAI_COMPATIBLE,
}


@dataclass(frozen=True)
class AppConfig:
    obs_host: str
    obs_port: int
    obs_password: str
    dry_run_obs: bool
    ai_provider: str
    ingest_api_url: str
    transcription_api_url: str
    transcription_request_mode: str
    transcription_endpoint_path: str
    transcription_model: str
    transcription_language: str
    transcription_response_format: str
    transcription_request_timeout_seconds: float
    gemma_api_url: str
    gemma_model: str
    gemma_api_key: str
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
    transcript_prefilter_enabled: bool
    transcript_prefilter_min_text_characters: int
    transcript_prefilter_duplicate_window_seconds: float
    transcript_prefilter_context_seconds: float
    transcript_prefilter_min_confidence: float
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
        ai_provider=normalize_ai_provider(
            os.getenv("AI_PROVIDER", AI_PROVIDER_OLLAMA)
        ),
        ingest_api_url=os.getenv("INGEST_API_URL", "rtmp://localhost/live"),
        transcription_api_url=os.getenv(
            "TRANSCRIPTION_API_URL",
            "http://faster-whisper:8000",
        ),
        transcription_request_mode=normalize_transcription_request_mode(
            os.getenv(
                "TRANSCRIPTION_REQUEST_MODE",
                TRANSCRIPTION_REQUEST_MODE_JSON,
            )
        ),
        transcription_endpoint_path=os.getenv("TRANSCRIPTION_ENDPOINT_PATH", ""),
        transcription_model=os.getenv(
            "TRANSCRIPTION_MODEL",
            os.getenv("FASTER_WHISPER_MODEL", "Systran/faster-whisper-small"),
        ),
        transcription_language=os.getenv("TRANSCRIPTION_LANGUAGE", ""),
        transcription_response_format=os.getenv(
            "TRANSCRIPTION_RESPONSE_FORMAT",
            "json",
        ),
        transcription_request_timeout_seconds=float(
            os.getenv("TRANSCRIPTION_REQUEST_TIMEOUT_SECONDS", "30")
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
        gemma_api_key=os.getenv("GEMMA_API_KEY", ""),
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
        transcript_prefilter_enabled=_parse_bool(
            os.getenv("TRANSCRIPT_PREFILTER_ENABLED", "true")
        ),
        transcript_prefilter_min_text_characters=int(
            os.getenv("TRANSCRIPT_PREFILTER_MIN_TEXT_CHARACTERS", "6")
        ),
        transcript_prefilter_duplicate_window_seconds=float(
            os.getenv("TRANSCRIPT_PREFILTER_DUPLICATE_WINDOW_SECONDS", "12")
        ),
        transcript_prefilter_context_seconds=float(
            os.getenv("TRANSCRIPT_PREFILTER_CONTEXT_SECONDS", "30")
        ),
        transcript_prefilter_min_confidence=float(
            os.getenv("TRANSCRIPT_PREFILTER_MIN_CONFIDENCE", "0.70")
        ),
        default_scene=SCENES["quad"],
    )


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def normalize_ai_provider(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    provider = _AI_PROVIDER_ALIASES.get(normalized)
    if provider is not None:
        return provider

    supported = ", ".join(SUPPORTED_AI_PROVIDERS)
    raise ValueError(
        f"Unsupported AI_PROVIDER {value!r}. Expected one of: {supported}."
    )


def normalize_transcription_request_mode(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    request_mode = _TRANSCRIPTION_REQUEST_MODE_ALIASES.get(normalized)
    if request_mode is not None:
        return request_mode

    supported = ", ".join(SUPPORTED_TRANSCRIPTION_REQUEST_MODES)
    raise ValueError(
        "Unsupported TRANSCRIPTION_REQUEST_MODE "
        f"{value!r}. Expected one of: {supported}."
    )


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
