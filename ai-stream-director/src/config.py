import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


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

SECRET_REDACTION = "[REDACTED]"
_SECRET_NAME_PARTS = ("key", "token", "password", "secret")
_HTTP_URL_SCHEMES = frozenset({"http", "https"})
_STREAM_URL_SCHEMES = frozenset({"rtmp", "rtmps", "srt", "http", "https", "file"})

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
    live_transcription_enabled: bool
    live_transcription_queue_size: int
    transcript_log_text_enabled: bool
    transcript_log_text_max_characters: int
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
    transcript_utterance_max_gap_seconds: float
    transcript_utterance_max_duration_seconds: float
    transcript_utterance_max_characters: int
    transcript_utterance_max_events: int
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
    ingest_api_url = os.getenv("INGEST_API_URL", "rtmp://localhost/live")
    config = AppConfig(
        obs_host=os.getenv("OBS_HOST", "host.docker.internal"),
        obs_port=_env_int("OBS_PORT", "4455"),
        obs_password=os.getenv("OBS_PASSWORD", ""),
        dry_run_obs=_parse_bool(os.getenv("DRY_RUN_OBS", "false")),
        ai_provider=normalize_ai_provider(
            os.getenv("AI_PROVIDER", AI_PROVIDER_OLLAMA)
        ),
        ingest_api_url=ingest_api_url,
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
        transcription_request_timeout_seconds=_env_float(
            "TRANSCRIPTION_REQUEST_TIMEOUT_SECONDS",
            "30",
        ),
        live_transcription_enabled=_parse_bool(
            os.getenv("LIVE_TRANSCRIPTION_ENABLED", "false")
        ),
        live_transcription_queue_size=_env_int("LIVE_TRANSCRIPTION_QUEUE_SIZE", "16"),
        transcript_log_text_enabled=_parse_bool(
            os.getenv("TRANSCRIPT_LOG_TEXT_ENABLED", "false")
        ),
        transcript_log_text_max_characters=_env_int(
            "TRANSCRIPT_LOG_TEXT_MAX_CHARACTERS",
            "160",
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
        lookback_window_seconds=_env_int("LOOKBACK_WINDOW_SECONDS", "30"),
        switch_lookback_seconds=_env_int("SWITCH_LOOKBACK_SECONDS", "15"),
        lookback_segment_seconds=_env_float("LOOKBACK_SEGMENT_SECONDS", "2"),
        lookback_input_urls=_build_lookback_input_urls(ingest_api_url),
        ffmpeg_executable=os.getenv("FFMPEG_EXECUTABLE", "ffmpeg"),
        audio_extract_dir=os.getenv(
            "AUDIO_EXTRACT_DIR",
            "/dev/shm/clutchcam-audio",
        ),
        audio_extract_sample_rate=_env_int("AUDIO_EXTRACT_SAMPLE_RATE", "16000"),
        audio_extract_channels=_env_int("AUDIO_EXTRACT_CHANNELS", "1"),
        audio_extract_chunk_seconds=_env_float("AUDIO_EXTRACT_CHUNK_SECONDS", "5"),
        audio_extract_codec=os.getenv("AUDIO_EXTRACT_CODEC", "pcm_s16le"),
        audio_extract_container=os.getenv("AUDIO_EXTRACT_CONTAINER", "wav"),
        audio_input_urls=_build_audio_input_urls(ingest_api_url),
        confidence_threshold=_env_float("CONFIDENCE_THRESHOLD", "0.75"),
        min_switch_interval_seconds=_env_int("MIN_SWITCH_INTERVAL_SECONDS", "8"),
        max_focus_duration_seconds=_env_int("MAX_FOCUS_DURATION_SECONDS", "20"),
        transcript_history_seconds=_env_int("TRANSCRIPT_HISTORY_SECONDS", "30"),
        transcript_history_messages=_env_int("TRANSCRIPT_HISTORY_MESSAGES", "20"),
        transcript_utterance_max_gap_seconds=_env_float(
            "TRANSCRIPT_UTTERANCE_MAX_GAP_SECONDS",
            "2.0",
        ),
        transcript_utterance_max_duration_seconds=_env_float(
            "TRANSCRIPT_UTTERANCE_MAX_DURATION_SECONDS",
            "8.0",
        ),
        transcript_utterance_max_characters=_env_int(
            "TRANSCRIPT_UTTERANCE_MAX_CHARACTERS",
            "240",
        ),
        transcript_utterance_max_events=_env_int(
            "TRANSCRIPT_UTTERANCE_MAX_EVENTS",
            "8",
        ),
        transcript_prefilter_enabled=_parse_bool(
            os.getenv("TRANSCRIPT_PREFILTER_ENABLED", "true")
        ),
        transcript_prefilter_min_text_characters=_env_int(
            "TRANSCRIPT_PREFILTER_MIN_TEXT_CHARACTERS",
            "6",
        ),
        transcript_prefilter_duplicate_window_seconds=_env_float(
            "TRANSCRIPT_PREFILTER_DUPLICATE_WINDOW_SECONDS",
            "12",
        ),
        transcript_prefilter_context_seconds=_env_float(
            "TRANSCRIPT_PREFILTER_CONTEXT_SECONDS",
            "30",
        ),
        transcript_prefilter_min_confidence=_env_float(
            "TRANSCRIPT_PREFILTER_MIN_CONFIDENCE",
            "0.70",
        ),
        default_scene=SCENES["quad"],
    )
    validate_config(config)
    return config


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: str) -> int:
    value = os.getenv(name, default)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer.") from exc


def _env_float(name: str, default: str) -> float:
    value = os.getenv(name, default)
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number.") from exc


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


def validate_config(config: AppConfig) -> None:
    _require_text("OBS_HOST", config.obs_host)
    _validate_port("OBS_PORT", config.obs_port)
    _validate_url("INGEST_API_URL", config.ingest_api_url, _STREAM_URL_SCHEMES)
    _validate_url(
        "TRANSCRIPTION_API_URL",
        config.transcription_api_url,
        _HTTP_URL_SCHEMES,
    )
    _validate_url("GEMMA_API_URL", config.gemma_api_url, _HTTP_URL_SCHEMES)
    _require_text("GEMMA_MODEL", config.gemma_model)
    _validate_endpoint_path(
        "TRANSCRIPTION_ENDPOINT_PATH",
        config.transcription_endpoint_path,
    )
    _require_text("TRANSCRIPTION_RESPONSE_FORMAT", config.transcription_response_format)
    _require_positive(
        "TRANSCRIPTION_REQUEST_TIMEOUT_SECONDS",
        config.transcription_request_timeout_seconds,
    )
    _require_positive_int(
        "LIVE_TRANSCRIPTION_QUEUE_SIZE",
        config.live_transcription_queue_size,
    )
    _require_positive_int(
        "TRANSCRIPT_LOG_TEXT_MAX_CHARACTERS",
        config.transcript_log_text_max_characters,
    )
    _validate_path_setting("LOOKBACK_BUFFER_DIR", config.lookback_buffer_dir)
    _validate_path_setting("AUDIO_EXTRACT_DIR", config.audio_extract_dir)
    _validate_path_setting("FFMPEG_EXECUTABLE", config.ffmpeg_executable)
    _require_positive_int("LOOKBACK_WINDOW_SECONDS", config.lookback_window_seconds)
    _require_non_negative_int("SWITCH_LOOKBACK_SECONDS", config.switch_lookback_seconds)
    _require_positive("LOOKBACK_SEGMENT_SECONDS", config.lookback_segment_seconds)
    if config.switch_lookback_seconds > config.lookback_window_seconds:
        raise ValueError(
            "SWITCH_LOOKBACK_SECONDS cannot exceed LOOKBACK_WINDOW_SECONDS."
        )
    _validate_stream_urls("LOOKBACK_INPUT_URL_*", config.lookback_input_urls)
    _validate_stream_urls("AUDIO_INPUT_URL_*", config.audio_input_urls)
    _require_positive_int("AUDIO_EXTRACT_SAMPLE_RATE", config.audio_extract_sample_rate)
    _require_positive_int("AUDIO_EXTRACT_CHANNELS", config.audio_extract_channels)
    _require_positive("AUDIO_EXTRACT_CHUNK_SECONDS", config.audio_extract_chunk_seconds)
    _require_text("AUDIO_EXTRACT_CODEC", config.audio_extract_codec)
    _require_text("AUDIO_EXTRACT_CONTAINER", config.audio_extract_container)
    _validate_unit_interval("CONFIDENCE_THRESHOLD", config.confidence_threshold)
    _require_non_negative_int(
        "MIN_SWITCH_INTERVAL_SECONDS",
        config.min_switch_interval_seconds,
    )
    _require_positive_int(
        "MAX_FOCUS_DURATION_SECONDS",
        config.max_focus_duration_seconds,
    )
    _require_positive_int("TRANSCRIPT_HISTORY_SECONDS", config.transcript_history_seconds)
    _require_positive_int(
        "TRANSCRIPT_HISTORY_MESSAGES",
        config.transcript_history_messages,
    )
    _require_positive(
        "TRANSCRIPT_UTTERANCE_MAX_GAP_SECONDS",
        config.transcript_utterance_max_gap_seconds,
    )
    _require_positive(
        "TRANSCRIPT_UTTERANCE_MAX_DURATION_SECONDS",
        config.transcript_utterance_max_duration_seconds,
    )
    _require_positive_int(
        "TRANSCRIPT_UTTERANCE_MAX_CHARACTERS",
        config.transcript_utterance_max_characters,
    )
    _require_positive_int(
        "TRANSCRIPT_UTTERANCE_MAX_EVENTS",
        config.transcript_utterance_max_events,
    )
    _require_non_negative_int(
        "TRANSCRIPT_PREFILTER_MIN_TEXT_CHARACTERS",
        config.transcript_prefilter_min_text_characters,
    )
    _require_non_negative(
        "TRANSCRIPT_PREFILTER_DUPLICATE_WINDOW_SECONDS",
        config.transcript_prefilter_duplicate_window_seconds,
    )
    _require_non_negative(
        "TRANSCRIPT_PREFILTER_CONTEXT_SECONDS",
        config.transcript_prefilter_context_seconds,
    )
    _validate_unit_interval(
        "TRANSCRIPT_PREFILTER_MIN_CONFIDENCE",
        config.transcript_prefilter_min_confidence,
    )
    if config.default_scene not in VALID_SCENE_NAMES:
        raise ValueError(f"DEFAULT_SCENE is not a known scene: {config.default_scene!r}.")


def redact_secrets(value: Any) -> Any:
    return _redact_value(value)


def _redact_value(value: Any, *, key_name: str = "") -> Any:
    if key_name and _is_secret_name(key_name):
        return SECRET_REDACTION if _has_configured_secret(value) else ""
    if isinstance(value, Mapping):
        return {
            str(key): _redact_value(item, key_name=str(key))
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return tuple(_redact_value(item) for item in value)
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, str):
        return _redact_url_secrets(value)
    return value


def _is_secret_name(name: str) -> bool:
    normalized = name.strip().lower()
    tokens = [token for token in re.split(r"[^a-z0-9]+", normalized) if token]
    if any(token in _SECRET_NAME_PARTS for token in tokens):
        return True
    return normalized.replace("_", "").replace("-", "").endswith(
        ("apikey", "accesstoken", "refreshtoken")
    )


def _has_configured_secret(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _require_text(name: str, value: str) -> None:
    if not str(value).strip():
        raise ValueError(f"{name} is required.")


def _validate_port(name: str, value: int) -> None:
    if not 0 < int(value) <= 65535:
        raise ValueError(f"{name} must be between 1 and 65535.")


def _validate_url(name: str, value: str, allowed_schemes: frozenset[str]) -> None:
    url = str(value).strip()
    if not url:
        raise ValueError(f"{name} is required.")
    parsed = urlparse(url)
    if parsed.scheme.lower() not in allowed_schemes:
        expected = ", ".join(sorted(allowed_schemes))
        raise ValueError(f"{name} must use one of these URL schemes: {expected}.")
    if parsed.scheme.lower() == "file":
        if not parsed.path:
            raise ValueError(f"{name} file URL must include a path.")
        return
    if not parsed.netloc:
        raise ValueError(f"{name} must include a host.")
    if parsed.username or parsed.password:
        raise ValueError(f"{name} cannot include embedded credentials.")


def _validate_endpoint_path(name: str, value: str) -> None:
    path = str(value).strip()
    if not path:
        return
    if "://" in path:
        raise ValueError(f"{name} must be a path, not a full URL.")
    if any(character.isspace() for character in path):
        raise ValueError(f"{name} cannot contain whitespace.")


def _validate_path_setting(name: str, value: str) -> None:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{name} is required.")
    if "\x00" in text:
        raise ValueError(f"{name} cannot contain NUL bytes.")
    Path(text)


def _validate_stream_urls(name: str, urls: Mapping[str, str]) -> None:
    stream_ids = set(STREAM_IDS)
    configured_ids = set(urls)
    missing_ids = sorted(stream_ids.difference(configured_ids))
    unknown_ids = sorted(configured_ids.difference(stream_ids))
    if missing_ids:
        raise ValueError(f"{name} missing stream IDs: {', '.join(missing_ids)}.")
    if unknown_ids:
        raise ValueError(f"{name} has unknown stream IDs: {', '.join(unknown_ids)}.")
    for stream_id in STREAM_IDS:
        _validate_stream_id(stream_id)
        _validate_url(f"{name}:{stream_id}", urls[stream_id], _STREAM_URL_SCHEMES)


def _validate_stream_id(stream_id: str) -> None:
    if stream_id not in STREAM_IDS:
        raise ValueError(f"Unsupported stream ID: {stream_id!r}.")


def _require_positive_int(name: str, value: int) -> None:
    if int(value) <= 0:
        raise ValueError(f"{name} must be positive.")


def _require_non_negative_int(name: str, value: int) -> None:
    if int(value) < 0:
        raise ValueError(f"{name} cannot be negative.")


def _require_positive(name: str, value: float) -> None:
    if float(value) <= 0:
        raise ValueError(f"{name} must be positive.")


def _require_non_negative(name: str, value: float) -> None:
    if float(value) < 0:
        raise ValueError(f"{name} cannot be negative.")


def _validate_unit_interval(name: str, value: float) -> None:
    number = float(value)
    if not 0 <= number <= 1:
        raise ValueError(f"{name} must be between 0 and 1.")


def _redact_url_secrets(value: str) -> str:
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return value

    netloc = parsed.netloc
    if parsed.username or parsed.password:
        host = parsed.hostname or ""
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        try:
            parsed_port = parsed.port
        except ValueError:
            parsed_port = None
        port = f":{parsed_port}" if parsed_port is not None else ""
        netloc = f"{SECRET_REDACTION}@{host}{port}"

    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    if not query_pairs:
        return urlunparse(parsed._replace(netloc=netloc))

    redacted_pairs = [
        (key, SECRET_REDACTION if _is_secret_name(key) and value else value)
        for key, value in query_pairs
    ]
    return urlunparse(
        parsed._replace(netloc=netloc, query=urlencode(redacted_pairs, safe="[]"))
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
