"""Smoke a Faster-Whisper-compatible transcription HTTP endpoint."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from services.transcription import (  # noqa: E402
    AudioInputRef,
    FasterWhisperTranscriber,
    TranscriptionError,
)


class SmokeFailure(RuntimeError):
    """Raised when the transcription API smoke cannot complete."""


@dataclass(frozen=True)
class TranscriptionSmokeResult:
    endpoint_url: str
    audio_uri: str
    stream_id: str
    timeout_seconds: float
    event_count: int


def build_audio_ref(
    env: Mapping[str, str],
    *,
    fixture_path: Path | None = None,
) -> AudioInputRef:
    stream_id = env.get("SMOKE_TRANSCRIPTION_STREAM_ID", "player_1")
    audio_uri = env.get("SMOKE_TRANSCRIPTION_AUDIO_URI")
    if audio_uri is None:
        if fixture_path is None:
            raise SmokeFailure("fixture_path is required when no audio URI is set.")
        audio_uri = fixture_path.resolve().as_uri()

    return AudioInputRef(
        stream_id=stream_id,
        uri=audio_uri,
        starts_at_seconds=0.0,
        duration_seconds=_env_float(env, "SMOKE_TRANSCRIPTION_AUDIO_SECONDS", 0.25),
        codec="pcm_s16le",
        sample_rate_hz=_env_int(env, "SMOKE_TRANSCRIPTION_SAMPLE_RATE", 16000),
        channels=1,
    )


def smoke_transcription_api(
    env: Mapping[str, str] = os.environ,
    *,
    post: Callable[..., Any] | None = None,
) -> TranscriptionSmokeResult:
    api_url = env.get("TRANSCRIPTION_API_URL", "http://127.0.0.1:8000").rstrip("/")
    timeout_seconds = _env_float(
        env,
        "SMOKE_TRANSCRIPTION_TIMEOUT_SECONDS",
        _env_float(env, "TRANSCRIPTION_REQUEST_TIMEOUT_SECONDS", 30.0),
    )

    with tempfile.TemporaryDirectory(prefix="clutchcam-stt-smoke-") as temp_dir:
        fixture_path = Path(temp_dir) / "smoke.wav"
        if "SMOKE_TRANSCRIPTION_AUDIO_URI" not in env:
            write_silent_wav(
                fixture_path,
                sample_rate_hz=_env_int(env, "SMOKE_TRANSCRIPTION_SAMPLE_RATE", 16000),
                duration_seconds=_env_float(
                    env,
                    "SMOKE_TRANSCRIPTION_AUDIO_SECONDS",
                    0.25,
                ),
            )
        audio_ref = build_audio_ref(env, fixture_path=fixture_path)

        transcriber = FasterWhisperTranscriber(
            api_url,
            timeout_seconds=timeout_seconds,
            post=post,
        )
        try:
            events = transcriber.transcribe(audio_ref)
        except TranscriptionError as exc:
            raise SmokeFailure(
                f"Transcription API smoke failed at {api_url}/transcribe: {exc}"
            ) from exc

    return TranscriptionSmokeResult(
        endpoint_url=f"{api_url}/transcribe",
        audio_uri=audio_ref.uri,
        stream_id=audio_ref.stream_id,
        timeout_seconds=timeout_seconds,
        event_count=len(events),
    )


def write_silent_wav(
    path: Path,
    *,
    sample_rate_hz: int,
    duration_seconds: float,
) -> None:
    frame_count = max(1, int(sample_rate_hz * duration_seconds))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(b"\x00\x00" * frame_count)


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    try:
        result = smoke_transcription_api()
    except (SmokeFailure, OSError, ValueError) as exc:
        print(f"transcription-api smoke failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(asdict(result), indent=2, sort_keys=True))
    return 0


def _env_float(env: Mapping[str, str], name: str, default: float) -> float:
    value = env.get(name)
    if value is None or not value.strip():
        return default
    return float(value)


def _env_int(env: Mapping[str, str], name: str, default: int) -> int:
    value = env.get(name)
    if value is None or not value.strip():
        return default
    return int(float(value))


if __name__ == "__main__":
    raise SystemExit(main())
