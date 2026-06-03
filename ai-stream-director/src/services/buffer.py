"""Rolling lookback buffer boundary and local segment implementations."""

from __future__ import annotations

import csv
import math
import os
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from config import AppConfig, STREAM_IDS
from contracts import LookbackClipRequest


class ClipResolutionStatus(str, Enum):
    READY = "ready"
    PENDING = "pending"
    UNAVAILABLE = "unavailable"


class LookbackBufferError(RuntimeError):
    """Raised when a buffer adapter cannot resolve a clip request."""


@dataclass(frozen=True)
class ClipResolution:
    """Implementation-neutral result for a lookback clip lookup."""

    request: LookbackClipRequest
    status: ClipResolutionStatus
    media_uri: str | None = None
    start_time_seconds: float | None = None
    end_time_seconds: float | None = None
    reason: str = ""
    segment_uris: tuple[str, ...] = ()

    @classmethod
    def ready(
        cls,
        request: LookbackClipRequest,
        media_uri: str,
        start_time_seconds: float | None = None,
        end_time_seconds: float | None = None,
        reason: str = "",
        segment_uris: Sequence[str] = (),
    ) -> "ClipResolution":
        return cls(
            request=request,
            status=ClipResolutionStatus.READY,
            media_uri=media_uri,
            start_time_seconds=(
                request.start_time_seconds
                if start_time_seconds is None
                else start_time_seconds
            ),
            end_time_seconds=(
                request.end_time_seconds if end_time_seconds is None else end_time_seconds
            ),
            reason=reason,
            segment_uris=tuple(segment_uris),
        )

    @classmethod
    def pending(
        cls,
        request: LookbackClipRequest,
        reason: str = "",
    ) -> "ClipResolution":
        return cls(
            request=request,
            status=ClipResolutionStatus.PENDING,
            reason=reason,
        )

    @classmethod
    def unavailable(
        cls,
        request: LookbackClipRequest,
        reason: str = "",
    ) -> "ClipResolution":
        return cls(
            request=request,
            status=ClipResolutionStatus.UNAVAILABLE,
            reason=reason,
        )


@dataclass(frozen=True)
class SegmentRecord:
    """One playable media segment in the stream's monotonic timeline."""

    stream_id: str
    path: Path | str
    start_time_seconds: float
    end_time_seconds: float
    sequence: int | None = None

    def __post_init__(self) -> None:
        start_time_seconds = float(self.start_time_seconds)
        end_time_seconds = float(self.end_time_seconds)
        if not self.stream_id:
            raise ValueError("SegmentRecord requires a stream_id.")
        if end_time_seconds <= start_time_seconds:
            raise ValueError("SegmentRecord end_time_seconds must be after start.")

        object.__setattr__(self, "path", Path(self.path))
        object.__setattr__(self, "start_time_seconds", start_time_seconds)
        object.__setattr__(self, "end_time_seconds", end_time_seconds)

    @property
    def duration_seconds(self) -> float:
        return self.end_time_seconds - self.start_time_seconds

    @property
    def media_uri(self) -> str:
        return _file_uri(self.path)

    def overlaps(self, start_time_seconds: float, end_time_seconds: float) -> bool:
        return (
            self.start_time_seconds < end_time_seconds
            and self.end_time_seconds > start_time_seconds
        )


@dataclass(frozen=True)
class RollingBufferConfig:
    """Runtime settings for segment-based lookback buffers."""

    buffer_root: Path | str
    stream_input_urls: Mapping[str, str]
    stream_ids: Sequence[str] = STREAM_IDS
    ffmpeg_executable: str = "ffmpeg"
    segment_duration_seconds: float = 2.0
    retention_window_seconds: float = 30.0
    retention_slack_seconds: float | None = None
    coverage_tolerance_seconds: float = 0.25
    segment_list_name: str = "segments.csv"
    clip_dir_name: str = "clips"
    segment_file_pattern: str = "%09d.ts"
    startup_probe_seconds: float = 0.0

    def __post_init__(self) -> None:
        segment_duration_seconds = float(self.segment_duration_seconds)
        retention_window_seconds = float(self.retention_window_seconds)
        if segment_duration_seconds <= 0:
            raise ValueError("segment_duration_seconds must be positive.")
        if retention_window_seconds <= 0:
            raise ValueError("retention_window_seconds must be positive.")
        if self.coverage_tolerance_seconds < 0:
            raise ValueError("coverage_tolerance_seconds cannot be negative.")
        if self.startup_probe_seconds < 0:
            raise ValueError("startup_probe_seconds cannot be negative.")

        stream_ids = tuple(self.stream_ids)
        input_urls = dict(self.stream_input_urls)
        unknown_input_ids = sorted(set(input_urls).difference(stream_ids))
        if unknown_input_ids:
            raise LookbackBufferError(
                "Input URLs configured for unknown stream IDs: "
                + ", ".join(unknown_input_ids)
            )

        retention_slack_seconds = self.retention_slack_seconds
        if retention_slack_seconds is None:
            retention_slack_seconds = segment_duration_seconds * 2
        retention_slack_seconds = float(retention_slack_seconds)
        if retention_slack_seconds < 0:
            raise ValueError("retention_slack_seconds cannot be negative.")

        object.__setattr__(self, "buffer_root", Path(self.buffer_root))
        object.__setattr__(self, "stream_ids", stream_ids)
        object.__setattr__(self, "stream_input_urls", input_urls)
        object.__setattr__(
            self,
            "segment_duration_seconds",
            segment_duration_seconds,
        )
        object.__setattr__(
            self,
            "retention_window_seconds",
            retention_window_seconds,
        )
        object.__setattr__(
            self,
            "retention_slack_seconds",
            retention_slack_seconds,
        )

    @classmethod
    def from_app_config(cls, app_config: AppConfig) -> "RollingBufferConfig":
        return cls(
            buffer_root=app_config.lookback_buffer_dir,
            stream_input_urls=app_config.lookback_input_urls,
            ffmpeg_executable=app_config.ffmpeg_executable,
            segment_duration_seconds=app_config.lookback_segment_seconds,
            retention_window_seconds=app_config.lookback_window_seconds,
        )

    @property
    def segment_list_size(self) -> int:
        retained_seconds = (
            self.retention_window_seconds + self.retention_slack_seconds
        )
        return max(2, math.ceil(retained_seconds / self.segment_duration_seconds) + 2)


class LookbackBuffer(Protocol):
    """Resolves lookback media requests without prescribing FFmpeg details."""

    def resolve_clip(self, request: LookbackClipRequest) -> ClipResolution:
        """Return ready, pending, or unavailable media for the requested range."""


class SegmentedLookbackBuffer:
    """Resolves clips from segment metadata and writes per-request playlists."""

    def __init__(
        self,
        config: RollingBufferConfig,
        records: Sequence[SegmentRecord] = (),
    ) -> None:
        self.config = config
        self._records_by_stream: dict[str, list[SegmentRecord]] = {
            stream_id: [] for stream_id in self.config.stream_ids
        }
        for record in records:
            self.add_segment(record)

    def add_segment(self, record: SegmentRecord) -> None:
        if record.stream_id not in self._records_by_stream:
            raise LookbackBufferError(f"Unknown stream ID: {record.stream_id}")

        records = self._records_by_stream[record.stream_id]
        records = [existing for existing in records if existing.path != record.path]
        records.append(record)
        self._records_by_stream[record.stream_id] = _ordered_segments(records)

    def replace_segments(
        self,
        stream_id: str,
        records: Sequence[SegmentRecord],
    ) -> None:
        if stream_id not in self._records_by_stream:
            raise LookbackBufferError(f"Unknown stream ID: {stream_id}")

        for record in records:
            if record.stream_id != stream_id:
                raise LookbackBufferError(
                    f"Segment for {record.stream_id} cannot be stored under {stream_id}."
                )
        self._records_by_stream[stream_id] = _ordered_segments(records)

    def list_segments(self, stream_id: str) -> tuple[SegmentRecord, ...]:
        if stream_id not in self._records_by_stream:
            raise LookbackBufferError(f"Unknown stream ID: {stream_id}")
        return tuple(self._records_by_stream[stream_id])

    def prune_retention(
        self,
        stream_id: str | None = None,
        *,
        delete_files: bool = False,
    ) -> tuple[SegmentRecord, ...]:
        stream_ids = (stream_id,) if stream_id is not None else self.config.stream_ids
        removed: list[SegmentRecord] = []

        for current_stream_id in stream_ids:
            if current_stream_id not in self._records_by_stream:
                raise LookbackBufferError(f"Unknown stream ID: {current_stream_id}")

            records = self._records_by_stream[current_stream_id]
            if not records:
                continue

            latest_end = max(record.end_time_seconds for record in records)
            cutoff = latest_end - (
                self.config.retention_window_seconds
                + self.config.retention_slack_seconds
            )
            kept = [
                record for record in records if record.end_time_seconds >= cutoff
            ]
            expired = [
                record for record in records if record.end_time_seconds < cutoff
            ]
            self._records_by_stream[current_stream_id] = kept
            removed.extend(expired)

            if delete_files:
                for record in expired:
                    _delete_file(record.path)

        return tuple(removed)

    def resolve_clip(self, request: LookbackClipRequest) -> ClipResolution:
        if request.stream_id not in self._records_by_stream:
            return ClipResolution.unavailable(
                request,
                reason=f"Unknown stream ID: {request.stream_id}",
            )
        if request.end_time_seconds <= request.start_time_seconds:
            return ClipResolution.unavailable(request, reason="Invalid clip range.")

        self.prune_retention(request.stream_id)
        records = self._records_by_stream[request.stream_id]
        if not records:
            return ClipResolution.unavailable(
                request,
                reason="No segment metadata for stream.",
            )

        selected = [
            record
            for record in records
            if record.overlaps(request.start_time_seconds, request.end_time_seconds)
        ]
        latest_end = records[-1].end_time_seconds
        tolerance = self.config.coverage_tolerance_seconds

        if not selected:
            if _is_plausibly_pending(request, latest_end, self.config):
                return ClipResolution.pending(
                    request,
                    reason="Requested end is newer than the latest segment.",
                )
            return ClipResolution.unavailable(
                request,
                reason="Requested range is outside retained segments.",
            )

        gap = _find_gap(selected, tolerance)
        if gap is not None:
            return ClipResolution.unavailable(
                request,
                reason=(
                    "Segment gap from "
                    f"{gap[0]:.3f}s to {gap[1]:.3f}s prevents clip resolution."
                ),
            )

        if selected[0].start_time_seconds > request.start_time_seconds + tolerance:
            return ClipResolution.unavailable(
                request,
                reason="Requested range starts before retained media.",
            )

        if selected[-1].end_time_seconds < request.end_time_seconds - tolerance:
            if _is_plausibly_pending(request, latest_end, self.config):
                return ClipResolution.pending(
                    request,
                    reason="Requested end is newer than the latest segment.",
                )
            return ClipResolution.unavailable(
                request,
                reason="Requested range ends after retained media.",
            )

        missing_segments = [
            record for record in selected if not record.path.exists()
        ]
        if missing_segments:
            return ClipResolution.unavailable(
                request,
                reason="Segment file is missing from the local buffer.",
            )

        media_uri = self._write_clip_playlist(request, selected)
        return ClipResolution.ready(
            request,
            media_uri=media_uri,
            start_time_seconds=selected[0].start_time_seconds,
            end_time_seconds=selected[-1].end_time_seconds,
            segment_uris=[record.media_uri for record in selected],
        )

    def _write_clip_playlist(
        self,
        request: LookbackClipRequest,
        segments: Sequence[SegmentRecord],
    ) -> str:
        clip_dir = (
            self.config.buffer_root
            / request.stream_id
            / self.config.clip_dir_name
        )
        clip_dir.mkdir(parents=True, exist_ok=True)
        playlist_path = clip_dir / _clip_playlist_name(request)
        max_duration = max(segment.duration_seconds for segment in segments)
        target_duration = max(1, math.ceil(max_duration))

        lines = [
            "#EXTM3U",
            "#EXT-X-VERSION:3",
            f"#EXT-X-TARGETDURATION:{target_duration}",
            "#EXT-X-MEDIA-SEQUENCE:0",
            "#EXT-X-PLAYLIST-TYPE:VOD",
        ]
        for segment in segments:
            lines.append(f"#EXTINF:{segment.duration_seconds:.3f},")
            lines.append(_playlist_reference(segment.path, playlist_path.parent))
        lines.append("#EXT-X-ENDLIST")

        try:
            playlist_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError as exc:
            raise LookbackBufferError(
                f"Unable to write clip playlist {playlist_path}: {exc}"
            ) from exc

        return _file_uri(playlist_path)


class FixtureLookbackBuffer(SegmentedLookbackBuffer):
    """Deterministic segment resolver for tests and dry-run validation."""

    def __init__(
        self,
        records: Sequence[SegmentRecord] = (),
        *,
        buffer_root: Path | str,
        stream_ids: Sequence[str] = STREAM_IDS,
        segment_duration_seconds: float = 2.0,
        retention_window_seconds: float = 30.0,
        retention_slack_seconds: float | None = None,
    ) -> None:
        config = RollingBufferConfig(
            buffer_root=buffer_root,
            stream_input_urls={},
            stream_ids=stream_ids,
            segment_duration_seconds=segment_duration_seconds,
            retention_window_seconds=retention_window_seconds,
            retention_slack_seconds=retention_slack_seconds,
        )
        super().__init__(config=config, records=records)


class FFmpegRollingLookbackBuffer(SegmentedLookbackBuffer):
    """FFmpeg segment writer backed by filesystem segment metadata."""

    def __init__(self, config: RollingBufferConfig) -> None:
        super().__init__(config=config)
        self._processes: dict[str, subprocess.Popen[bytes]] = {}

    def build_ffmpeg_command(self, stream_id: str) -> list[str]:
        self._ensure_known_stream(stream_id)
        input_url = self.config.stream_input_urls.get(stream_id, "")
        if not input_url:
            raise LookbackBufferError(f"Missing input URL for {stream_id}.")

        return [
            self.config.ffmpeg_executable,
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "warning",
            "-i",
            input_url,
            "-c",
            "copy",
            "-f",
            "segment",
            "-segment_time",
            _format_seconds(self.config.segment_duration_seconds),
            "-segment_format",
            "mpegts",
            "-reset_timestamps",
            "1",
            "-segment_list",
            str(self._segment_list_path(stream_id)),
            "-segment_list_type",
            "csv",
            "-segment_list_flags",
            "+live",
            "-segment_list_size",
            str(self.config.segment_list_size),
            "-segment_start_number",
            str(self._next_segment_number(stream_id)),
            str(self._segment_output_pattern(stream_id)),
        ]

    def start(self) -> None:
        if self._processes:
            return

        self._validate_runtime_config()
        self.config.buffer_root.mkdir(parents=True, exist_ok=True)

        for stream_id in self.config.stream_ids:
            stream_dir = self._stream_dir(stream_id)
            stream_dir.mkdir(parents=True, exist_ok=True)
            _assert_writable(stream_dir)
            self.refresh_metadata(stream_id)
            self.prune_retention(stream_id, delete_files=True)

        try:
            for stream_id in self.config.stream_ids:
                command = self.build_ffmpeg_command(stream_id)
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                if self.config.startup_probe_seconds:
                    time.sleep(self.config.startup_probe_seconds)
                exit_code = process.poll()
                if exit_code is not None:
                    raise LookbackBufferError(
                        f"FFmpeg exited early for {stream_id} with code {exit_code}."
                    )
                self._processes[stream_id] = process
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        for process in self._processes.values():
            if process.poll() is not None:
                continue
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        self._processes.clear()

    def refresh_metadata(self, stream_id: str | None = None) -> None:
        stream_ids = (stream_id,) if stream_id is not None else self.config.stream_ids
        for current_stream_id in stream_ids:
            self._ensure_known_stream(current_stream_id)
            self.replace_segments(
                current_stream_id,
                self._read_segment_list(current_stream_id),
            )

    def resolve_clip(self, request: LookbackClipRequest) -> ClipResolution:
        if request.stream_id in self._records_by_stream:
            self.refresh_metadata(request.stream_id)
            self.prune_retention(request.stream_id, delete_files=True)
        return super().resolve_clip(request)

    def _validate_runtime_config(self) -> None:
        missing = [
            stream_id
            for stream_id in self.config.stream_ids
            if not self.config.stream_input_urls.get(stream_id)
        ]
        if missing:
            raise LookbackBufferError(
                "Missing input URLs for stream IDs: " + ", ".join(missing)
            )

    def _read_segment_list(self, stream_id: str) -> tuple[SegmentRecord, ...]:
        segment_list_path = self._segment_list_path(stream_id)
        if not segment_list_path.exists():
            return ()

        records: list[SegmentRecord] = []
        try:
            with segment_list_path.open(newline="", encoding="utf-8") as handle:
                reader = csv.reader(handle)
                for row in reader:
                    record = self._record_from_segment_row(stream_id, row)
                    if record is not None:
                        records.append(record)
        except (OSError, csv.Error, ValueError) as exc:
            raise LookbackBufferError(
                f"Unable to read segment metadata {segment_list_path}: {exc}"
            ) from exc

        return tuple(_ordered_segments(records))

    def _record_from_segment_row(
        self,
        stream_id: str,
        row: Sequence[str],
    ) -> SegmentRecord | None:
        if len(row) < 3:
            return None

        path = Path(row[0])
        if not path.is_absolute():
            path = self._stream_dir(stream_id) / path
        try:
            path = path.resolve(strict=True)
            path.relative_to(self._stream_dir(stream_id).resolve())
        except (OSError, RuntimeError, ValueError):
            return None

        return SegmentRecord(
            stream_id=stream_id,
            path=path,
            start_time_seconds=float(row[1]),
            end_time_seconds=float(row[2]),
            sequence=_segment_sequence(path),
        )

    def _next_segment_number(self, stream_id: str) -> int:
        records = self._records_by_stream.get(stream_id, [])
        sequences = [
            record.sequence
            for record in records
            if record.sequence is not None
        ]
        if not sequences:
            return 0
        return max(sequences) + 1

    def _stream_dir(self, stream_id: str) -> Path:
        self._ensure_known_stream(stream_id)
        return self.config.buffer_root / stream_id

    def _segment_list_path(self, stream_id: str) -> Path:
        return self._stream_dir(stream_id) / self.config.segment_list_name

    def _segment_output_pattern(self, stream_id: str) -> Path:
        return self._stream_dir(stream_id) / self.config.segment_file_pattern

    def _ensure_known_stream(self, stream_id: str) -> None:
        if stream_id not in self._records_by_stream:
            raise LookbackBufferError(f"Unknown stream ID: {stream_id}")


def _ordered_segments(records: Sequence[SegmentRecord]) -> list[SegmentRecord]:
    return sorted(
        records,
        key=lambda record: (
            record.start_time_seconds,
            record.end_time_seconds,
            str(record.path),
        ),
    )


def _find_gap(
    records: Sequence[SegmentRecord],
    tolerance_seconds: float,
) -> tuple[float, float] | None:
    if not records:
        return None

    covered_until = records[0].end_time_seconds
    for current in records[1:]:
        if current.start_time_seconds > covered_until + tolerance_seconds:
            return (covered_until, current.start_time_seconds)
        covered_until = max(covered_until, current.end_time_seconds)
    return None


def _is_plausibly_pending(
    request: LookbackClipRequest,
    latest_end_seconds: float,
    config: RollingBufferConfig,
) -> bool:
    if request.end_time_seconds <= latest_end_seconds:
        return False

    pending_horizon = (
        latest_end_seconds
        + config.segment_duration_seconds
        + config.coverage_tolerance_seconds
    )
    return (
        request.start_time_seconds <= pending_horizon
        and request.trigger_time_seconds <= pending_horizon
    )


def _clip_playlist_name(request: LookbackClipRequest) -> str:
    start_ms = round(request.start_time_seconds * 1000)
    end_ms = round(request.end_time_seconds * 1000)
    return f"clip_{start_ms:012d}_{end_ms:012d}.m3u8"


def _playlist_reference(path: Path, playlist_dir: Path) -> str:
    try:
        return os.path.relpath(path, playlist_dir).replace(os.sep, "/")
    except ValueError:
        return _file_uri(path)


def _file_uri(path: Path | str) -> str:
    return Path(path).resolve().as_uri()


def _delete_file(path: Path | str) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except OSError as exc:
        raise LookbackBufferError(f"Unable to delete expired segment {path}: {exc}") from exc


def _assert_writable(directory: Path) -> None:
    probe = directory / ".clutchcam-write-test"
    try:
        probe.write_text("", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        raise LookbackBufferError(
            f"Buffer directory is not writable: {directory}"
        ) from exc


def _segment_sequence(path: Path) -> int | None:
    try:
        return int(path.stem)
    except ValueError:
        return None


def _format_seconds(value: float) -> str:
    formatted = f"{value:.3f}".rstrip("0").rstrip(".")
    return formatted or "0"
