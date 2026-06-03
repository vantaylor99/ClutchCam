"""Speech-to-text boundary for stream audio references."""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from config import AppConfig, STREAM_IDS
from contracts import TranscriptEvent


class TranscriptionError(RuntimeError):
    """Raised when a transcription adapter cannot emit transcript events."""


@dataclass(frozen=True)
class AudioInputRef:
    """Implementation-neutral reference to stream audio."""

    stream_id: str
    uri: str
    starts_at_seconds: float | None = None
    duration_seconds: float | None = None
    codec: str | None = None
    sample_rate_hz: int | None = None
    channels: int | None = None


@dataclass(frozen=True)
class AudioExtractionConfig:
    """Runtime settings for per-stream audio extraction workers."""

    output_dir: Path | str
    stream_input_urls: dict[str, str]
    stream_ids: tuple[str, ...] = STREAM_IDS
    ffmpeg_executable: str = "ffmpeg"
    sample_rate_hz: int = 16000
    channels: int = 1
    chunk_duration_seconds: float = 5.0
    codec: str = "pcm_s16le"
    container: str = "wav"
    output_pattern: str = "%09d.{container}"

    def __post_init__(self) -> None:
        if self.sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be positive.")
        if self.channels <= 0:
            raise ValueError("channels must be positive.")
        if self.chunk_duration_seconds <= 0:
            raise ValueError("chunk_duration_seconds must be positive.")

        stream_ids = tuple(self.stream_ids)
        input_urls = dict(self.stream_input_urls)
        unknown_input_ids = sorted(set(input_urls).difference(stream_ids))
        if unknown_input_ids:
            raise TranscriptionError(
                "Audio input URLs configured for unknown stream IDs: "
                + ", ".join(unknown_input_ids)
            )

        object.__setattr__(self, "output_dir", Path(self.output_dir))
        object.__setattr__(self, "stream_ids", stream_ids)
        object.__setattr__(self, "stream_input_urls", input_urls)
        object.__setattr__(
            self,
            "chunk_duration_seconds",
            float(self.chunk_duration_seconds),
        )

    @classmethod
    def from_app_config(cls, app_config: AppConfig) -> "AudioExtractionConfig":
        return cls(
            output_dir=app_config.audio_extract_dir,
            stream_input_urls=app_config.audio_input_urls,
            ffmpeg_executable=app_config.ffmpeg_executable,
            sample_rate_hz=app_config.audio_extract_sample_rate,
            channels=app_config.audio_extract_channels,
            chunk_duration_seconds=app_config.audio_extract_chunk_seconds,
            codec=app_config.audio_extract_codec,
            container=app_config.audio_extract_container,
        )


@dataclass(frozen=True)
class AudioExtractionSession:
    """Describes one active or fixture audio extraction worker."""

    stream_id: str
    input_url: str
    output_dir: Path
    chunk_duration_seconds: float
    running: bool = False


class Transcriber(Protocol):
    """Turns audio references into transcript events."""

    def transcribe(self, audio: AudioInputRef) -> Iterable[TranscriptEvent]:
        """Yield transcript events for the supplied audio reference."""


class AudioExtractor(Protocol):
    """Produces audio references while preserving stream identity."""

    def start(self) -> None:
        """Start extraction workers."""

    def stop(self) -> None:
        """Stop extraction workers."""

    def build_audio_ref(
        self,
        stream_id: str,
        chunk_path: Path | str,
        starts_at_seconds: float | None = None,
    ) -> AudioInputRef:
        """Describe one extracted audio chunk."""


class FixtureAudioExtractor:
    """Deterministic extractor for tests and transcript fixture playback."""

    def __init__(
        self,
        config: AudioExtractionConfig,
        chunks: dict[str, tuple[AudioInputRef, ...]] | None = None,
    ) -> None:
        self.config = config
        self.chunks = chunks or {}
        self.running = False

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False

    def list_chunks(self, stream_id: str) -> tuple[AudioInputRef, ...]:
        _ensure_known_stream(self.config, stream_id)
        return tuple(self.chunks.get(stream_id, ()))

    def build_audio_ref(
        self,
        stream_id: str,
        chunk_path: Path | str,
        starts_at_seconds: float | None = None,
    ) -> AudioInputRef:
        return _audio_ref_from_config(
            config=self.config,
            stream_id=stream_id,
            chunk_path=chunk_path,
            starts_at_seconds=starts_at_seconds,
        )


class FFmpegAudioExtractor:
    """FFmpeg segment worker for normalized per-stream audio chunks."""

    def __init__(self, config: AudioExtractionConfig) -> None:
        self.config = config
        self._processes: dict[str, subprocess.Popen[bytes]] = {}

    def build_ffmpeg_command(self, stream_id: str) -> list[str]:
        _ensure_known_stream(self.config, stream_id)
        input_url = self.config.stream_input_urls.get(stream_id, "")
        if not input_url:
            raise TranscriptionError(f"Missing audio input URL for {stream_id}.")

        return [
            self.config.ffmpeg_executable,
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "warning",
            "-i",
            input_url,
            "-vn",
            "-ac",
            str(self.config.channels),
            "-ar",
            str(self.config.sample_rate_hz),
            "-c:a",
            self.config.codec,
            "-f",
            "segment",
            "-segment_time",
            _format_seconds(self.config.chunk_duration_seconds),
            "-reset_timestamps",
            "1",
            str(self._output_pattern(stream_id)),
        ]

    def start(self) -> None:
        if self._processes:
            return

        self._validate_runtime_config()
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        try:
            for stream_id in self.config.stream_ids:
                self._stream_dir(stream_id).mkdir(parents=True, exist_ok=True)
                process = subprocess.Popen(
                    self.build_ffmpeg_command(stream_id),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
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

    def sessions(self) -> tuple[AudioExtractionSession, ...]:
        return tuple(
            AudioExtractionSession(
                stream_id=stream_id,
                input_url=self.config.stream_input_urls.get(stream_id, ""),
                output_dir=self._stream_dir(stream_id),
                chunk_duration_seconds=self.config.chunk_duration_seconds,
                running=stream_id in self._processes,
            )
            for stream_id in self.config.stream_ids
        )

    def build_audio_ref(
        self,
        stream_id: str,
        chunk_path: Path | str,
        starts_at_seconds: float | None = None,
    ) -> AudioInputRef:
        return _audio_ref_from_config(
            config=self.config,
            stream_id=stream_id,
            chunk_path=chunk_path,
            starts_at_seconds=starts_at_seconds,
        )

    def _validate_runtime_config(self) -> None:
        missing = [
            stream_id
            for stream_id in self.config.stream_ids
            if not self.config.stream_input_urls.get(stream_id)
        ]
        if missing:
            raise TranscriptionError(
                "Missing audio input URLs for stream IDs: " + ", ".join(missing)
            )

    def _stream_dir(self, stream_id: str) -> Path:
        _ensure_known_stream(self.config, stream_id)
        return self.config.output_dir / stream_id

    def _output_pattern(self, stream_id: str) -> Path:
        pattern = self.config.output_pattern.format(container=self.config.container)
        return self._stream_dir(stream_id) / pattern


def _audio_ref_from_config(
    config: AudioExtractionConfig,
    stream_id: str,
    chunk_path: Path | str,
    starts_at_seconds: float | None,
) -> AudioInputRef:
    _ensure_known_stream(config, stream_id)
    return AudioInputRef(
        stream_id=stream_id,
        uri=Path(chunk_path).resolve().as_uri(),
        starts_at_seconds=starts_at_seconds,
        duration_seconds=config.chunk_duration_seconds,
        codec=config.codec,
        sample_rate_hz=config.sample_rate_hz,
        channels=config.channels,
    )


def _ensure_known_stream(config: AudioExtractionConfig, stream_id: str) -> None:
    if stream_id not in config.stream_ids:
        raise TranscriptionError(f"Unknown stream ID: {stream_id}")


def _format_seconds(value: float) -> str:
    formatted = f"{value:.3f}".rstrip("0").rstrip(".")
    return formatted or "0"
