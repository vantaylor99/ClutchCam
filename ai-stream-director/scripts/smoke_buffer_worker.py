"""Inspect rolling-buffer segment metadata and verify clip resolution."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Sequence


PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from config import STREAM_IDS  # noqa: E402
from contracts import LookbackClipRequest  # noqa: E402
from services.buffer import (  # noqa: E402
    ClipResolutionStatus,
    FFmpegRollingLookbackBuffer,
    LookbackBufferError,
    RollingBufferConfig,
)


DEFAULT_STREAM_IDS = ("player_1",)


class SmokeFailure(RuntimeError):
    """Raised when the buffer smoke cannot find a resolvable clip."""


@dataclass(frozen=True)
class SegmentSummary:
    path: str
    start_time_seconds: float
    end_time_seconds: float
    sequence: int | None
    exists: bool


@dataclass(frozen=True)
class StreamBufferSummary:
    stream_id: str
    segment_count: int
    latest_segment: SegmentSummary | None
    clip_status: str
    clip_media_uri: str | None
    clip_reason: str
    segment_uris: tuple[str, ...]


@dataclass(frozen=True)
class BufferSmokeResult:
    buffer_root: str
    streams: tuple[StreamBufferSummary, ...]

    @property
    def ready_streams(self) -> tuple[str, ...]:
        return tuple(
            stream.stream_id
            for stream in self.streams
            if stream.clip_status == ClipResolutionStatus.READY.value
        )


def stream_ids_from_env(
    env: Mapping[str, str] = os.environ,
    *,
    default: Sequence[str] = DEFAULT_STREAM_IDS,
) -> tuple[str, ...]:
    value = env.get("SMOKE_BUFFER_STREAM_IDS") or env.get("SMOKE_STREAM_IDS")
    if value is None:
        return tuple(default)
    return tuple(part.strip() for part in value.split(",") if part.strip())


def build_buffer_config(
    env: Mapping[str, str] = os.environ,
    *,
    stream_ids: Sequence[str] | None = None,
) -> RollingBufferConfig:
    selected_stream_ids = tuple(stream_ids or stream_ids_from_env(env))
    unknown = sorted(set(selected_stream_ids).difference(STREAM_IDS))
    if unknown:
        raise SmokeFailure("Unknown smoke stream IDs: " + ", ".join(unknown))

    return RollingBufferConfig(
        buffer_root=env.get("LOOKBACK_BUFFER_DIR", "/dev/shm/clutchcam"),
        stream_input_urls={},
        stream_ids=selected_stream_ids,
        segment_duration_seconds=_env_float(env, "LOOKBACK_SEGMENT_SECONDS", 2.0),
        retention_window_seconds=_env_float(env, "LOOKBACK_WINDOW_SECONDS", 30.0),
    )


def inspect_buffer(
    env: Mapping[str, str] = os.environ,
    *,
    stream_ids: Sequence[str] | None = None,
) -> BufferSmokeResult:
    config = build_buffer_config(env, stream_ids=stream_ids)
    buffer = FFmpegRollingLookbackBuffer(config)
    streams = tuple(
        _inspect_stream(
            stream_id=stream_id,
            buffer=buffer,
            pre_roll_seconds=_env_int(env, "SMOKE_CLIP_PRE_ROLL_SECONDS", 4),
            post_roll_seconds=_env_int(env, "SMOKE_CLIP_POST_ROLL_SECONDS", 1),
        )
        for stream_id in config.stream_ids
    )
    return BufferSmokeResult(buffer_root=str(config.buffer_root), streams=streams)


def assert_any_ready(result: BufferSmokeResult) -> None:
    if result.ready_streams:
        return

    details = "; ".join(
        f"{stream.stream_id}={stream.clip_status}: {stream.clip_reason}"
        for stream in result.streams
    )
    raise SmokeFailure(
        "No resolvable clips were found under "
        f"{result.buffer_root}. {details or 'No streams inspected.'}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    try:
        result = inspect_buffer()
        assert_any_ready(result)
    except (SmokeFailure, LookbackBufferError, OSError, ValueError) as exc:
        print(f"buffer-worker smoke failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(asdict(result), indent=2, sort_keys=True))
    return 0


def _inspect_stream(
    *,
    stream_id: str,
    buffer: FFmpegRollingLookbackBuffer,
    pre_roll_seconds: int,
    post_roll_seconds: int,
) -> StreamBufferSummary:
    try:
        buffer.refresh_metadata(stream_id)
        segments = buffer.list_segments(stream_id)
    except LookbackBufferError as exc:
        return StreamBufferSummary(
            stream_id=stream_id,
            segment_count=0,
            latest_segment=None,
            clip_status=ClipResolutionStatus.UNAVAILABLE.value,
            clip_media_uri=None,
            clip_reason=str(exc),
            segment_uris=(),
        )

    if not segments:
        return StreamBufferSummary(
            stream_id=stream_id,
            segment_count=0,
            latest_segment=None,
            clip_status=ClipResolutionStatus.UNAVAILABLE.value,
            clip_media_uri=None,
            clip_reason="No segment metadata for stream.",
            segment_uris=(),
        )

    latest = segments[-1]
    earliest = segments[0]
    trigger_time = max(
        latest.start_time_seconds,
        latest.end_time_seconds - max(0, post_roll_seconds),
    )
    available_pre_roll = max(0, int(trigger_time - earliest.start_time_seconds))
    request = LookbackClipRequest(
        stream_id=stream_id,
        trigger_time_seconds=trigger_time,
        pre_roll_seconds=min(max(0, pre_roll_seconds), available_pre_roll),
        post_roll_seconds=max(0, post_roll_seconds),
    )
    resolution = buffer.resolve_clip(request)

    return StreamBufferSummary(
        stream_id=stream_id,
        segment_count=len(segments),
        latest_segment=SegmentSummary(
            path=str(latest.path),
            start_time_seconds=latest.start_time_seconds,
            end_time_seconds=latest.end_time_seconds,
            sequence=latest.sequence,
            exists=latest.path.exists(),
        ),
        clip_status=resolution.status.value,
        clip_media_uri=resolution.media_uri,
        clip_reason=resolution.reason,
        segment_uris=resolution.segment_uris,
    )


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
