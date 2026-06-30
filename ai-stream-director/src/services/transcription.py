"""Speech-to-text boundary for stream audio references."""

from __future__ import annotations

import logging
import math
import subprocess
import threading
import time
import wave
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from config import (
    AppConfig,
    STREAM_IDS,
    TRANSCRIPTION_REQUEST_MODE_JSON,
    TRANSCRIPTION_REQUEST_MODE_OPENAI_COMPATIBLE,
)
from contracts import TranscriptEvent


LOGGER = logging.getLogger(__name__)


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
    emit_from_seconds: float | None = None


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


def build_overlapped_audio_ref(
    *,
    audio_ref: AudioInputRef,
    current_chunk_path: Path | str,
    previous_chunk_path: Path | str | None,
    overlap_seconds: float,
    config: AudioExtractionConfig,
    logger: logging.Logger = LOGGER,
) -> AudioInputRef:
    """Compose a WAV request window containing previous tail plus current chunk."""

    overlap_seconds = float(overlap_seconds)
    if overlap_seconds <= 0 or previous_chunk_path is None:
        return audio_ref
    if audio_ref.starts_at_seconds is None:
        logger.warning(
            "transcription_overlap_skipped stream=%s reason=missing_start_time "
            "chunk=%s",
            audio_ref.stream_id,
            current_chunk_path,
        )
        return audio_ref
    if str(config.container).strip().lower() != "wav":
        logger.warning(
            "transcription_overlap_skipped stream=%s reason=non_wav_container "
            "container=%s chunk=%s",
            audio_ref.stream_id,
            config.container,
            current_chunk_path,
        )
        return audio_ref

    current_path = Path(current_chunk_path)
    previous_path = Path(previous_chunk_path)
    try:
        current_path = current_path.resolve(strict=True)
        previous_path = previous_path.resolve(strict=True)
    except OSError as exc:
        logger.warning(
            "transcription_overlap_skipped stream=%s reason=missing_chunk "
            "previous=%s current=%s error=%r",
            audio_ref.stream_id,
            previous_chunk_path,
            current_chunk_path,
            exc,
        )
        return audio_ref

    if current_path.suffix.lower() != ".wav" or previous_path.suffix.lower() != ".wav":
        logger.warning(
            "transcription_overlap_skipped stream=%s reason=not_wav previous=%s "
            "current=%s",
            audio_ref.stream_id,
            previous_path,
            current_path,
        )
        return audio_ref

    overlap_dir = Path(config.output_dir) / "_overlap" / audio_ref.stream_id
    output_path = overlap_dir / f"{current_path.stem}.wav"

    try:
        with wave.open(str(previous_path), "rb") as previous_wav:
            previous_params = previous_wav.getparams()
            previous_frame_count = previous_wav.getnframes()
            previous_rate = previous_wav.getframerate()
            overlap_frames = min(
                previous_frame_count,
                max(0, int(round(overlap_seconds * previous_rate))),
            )
            previous_wav.setpos(previous_frame_count - overlap_frames)
            overlap_frames_data = previous_wav.readframes(overlap_frames)

        with wave.open(str(current_path), "rb") as current_wav:
            current_params = current_wav.getparams()
            current_frame_count = current_wav.getnframes()
            current_rate = current_wav.getframerate()
            if not _wav_params_compatible(previous_params, current_params):
                logger.warning(
                    "transcription_overlap_skipped stream=%s "
                    "reason=incompatible_wav previous=%s current=%s",
                    audio_ref.stream_id,
                    previous_path,
                    current_path,
                )
                return audio_ref
            current_frames_data = current_wav.readframes(current_frame_count)

        overlap_dir.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as output_wav:
            output_wav.setparams(current_params)
            output_wav.writeframes(overlap_frames_data)
            output_wav.writeframes(current_frames_data)
    except (EOFError, OSError, wave.Error) as exc:
        logger.warning(
            "transcription_overlap_skipped stream=%s reason=wav_error "
            "previous=%s current=%s error=%r",
            audio_ref.stream_id,
            previous_path,
            current_path,
            exc,
        )
        return audio_ref

    actual_overlap_seconds = overlap_frames / float(current_rate)
    current_duration_seconds = current_frame_count / float(current_rate)
    return AudioInputRef(
        stream_id=audio_ref.stream_id,
        uri=output_path.resolve().as_uri(),
        starts_at_seconds=max(
            0.0,
            float(audio_ref.starts_at_seconds) - actual_overlap_seconds,
        ),
        duration_seconds=actual_overlap_seconds + current_duration_seconds,
        codec=audio_ref.codec,
        sample_rate_hz=audio_ref.sample_rate_hz,
        channels=audio_ref.channels,
        emit_from_seconds=float(audio_ref.starts_at_seconds),
    )


def _wav_params_compatible(
    left: wave._wave_params,
    right: wave._wave_params,
) -> bool:
    return (
        left.nchannels == right.nchannels
        and left.sampwidth == right.sampwidth
        and left.framerate == right.framerate
        and left.comptype == right.comptype
    )


class FasterWhisperTranscriber:
    """HTTP adapter for Faster-Whisper-compatible transcription APIs."""

    def __init__(
        self,
        api_url: str,
        timeout_seconds: float = 30,
        request_mode: str = TRANSCRIPTION_REQUEST_MODE_JSON,
        endpoint_path: str | None = None,
        model: str = "Systran/faster-whisper-small",
        language: str = "",
        response_format: str = "json",
        post: Callable[..., Any] | None = None,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.timeout_seconds = float(timeout_seconds)
        self.request_mode = request_mode
        self.endpoint_path = _normalize_endpoint_path(
            endpoint_path,
            request_mode=request_mode,
        )
        self.model = model
        self.language = language
        self.response_format = response_format
        self._post = post

    @classmethod
    def from_app_config(cls, app_config: AppConfig) -> "FasterWhisperTranscriber":
        return cls(
            api_url=app_config.transcription_api_url,
            timeout_seconds=app_config.transcription_request_timeout_seconds,
            request_mode=app_config.transcription_request_mode,
            endpoint_path=app_config.transcription_endpoint_path or None,
            model=app_config.transcription_model,
            language=app_config.transcription_language,
            response_format=app_config.transcription_response_format,
        )

    def transcribe(self, audio: AudioInputRef) -> tuple[TranscriptEvent, ...]:
        payload = self._request_payload(audio)
        return tuple(_events_from_payload(payload, audio))

    def _request_payload(self, audio: AudioInputRef) -> Any:
        if self.request_mode == TRANSCRIPTION_REQUEST_MODE_OPENAI_COMPATIBLE:
            return self._request_openai_compatible_payload(audio)

        if self.request_mode != TRANSCRIPTION_REQUEST_MODE_JSON:
            raise TranscriptionError(
                f"Unsupported transcription request mode: {self.request_mode}"
            )

        request_payload = {
            "stream_id": audio.stream_id,
            "audio_uri": audio.uri,
            "starts_at_seconds": audio.starts_at_seconds,
            "duration_seconds": audio.duration_seconds,
            "codec": audio.codec,
            "sample_rate_hz": audio.sample_rate_hz,
            "channels": audio.channels,
        }

        try:
            response = self._post_json(
                f"{self.api_url}{self.endpoint_path}",
                json=request_payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            raise TranscriptionError(f"Transcription request failed: {exc}") from exc

    def _request_openai_compatible_payload(self, audio: AudioInputRef) -> Any:
        audio_path = _local_audio_path(audio.uri)
        data = {
            "model": self.model,
            "response_format": self.response_format,
        }
        if self.language:
            data["language"] = self.language

        try:
            with audio_path.open("rb") as audio_file:
                response = self._post_json(
                    f"{self.api_url}{self.endpoint_path}",
                    data=data,
                    files={"file": (audio_path.name, audio_file)},
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
                if self.response_format.strip().lower() == "text":
                    return {"text": str(getattr(response, "text", ""))}
                return response.json()
        except TranscriptionError:
            raise
        except Exception as exc:
            raise TranscriptionError(f"Transcription request failed: {exc}") from exc

    def _post_json(self, url: str, **kwargs: Any) -> Any:
        if self._post is not None:
            return self._post(url, **kwargs)

        import requests

        return requests.post(url, **kwargs)


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


class FFmpegProcess(Protocol):
    """Process operations needed by the audio extraction supervisor."""

    def poll(self) -> int | None:
        """Return the exit code when the child has stopped."""

    def terminate(self) -> None:
        """Request graceful child termination."""

    def kill(self) -> None:
        """Force child termination."""

    def wait(self, timeout: float | None = None) -> int:
        """Wait for child termination."""


ProcessFactory = Callable[..., FFmpegProcess]


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

    def __init__(
        self,
        config: AudioExtractionConfig,
        *,
        process_factory: ProcessFactory | None = None,
        logger: logging.Logger = LOGGER,
        supervision_poll_seconds: float = 0.25,
        restart_backoff_initial_seconds: float = 1.0,
        restart_backoff_max_seconds: float = 30.0,
        restart_stable_seconds: float = 30.0,
        termination_timeout_seconds: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if supervision_poll_seconds <= 0:
            raise ValueError("supervision_poll_seconds must be positive.")
        if restart_backoff_initial_seconds <= 0:
            raise ValueError("restart_backoff_initial_seconds must be positive.")
        if restart_backoff_max_seconds < restart_backoff_initial_seconds:
            raise ValueError(
                "restart_backoff_max_seconds must be at least the initial backoff."
            )
        if restart_stable_seconds < 0:
            raise ValueError("restart_stable_seconds cannot be negative.")
        if termination_timeout_seconds <= 0:
            raise ValueError("termination_timeout_seconds must be positive.")

        self.config = config
        self._process_factory = process_factory
        self._logger = logger
        self._supervision_poll_seconds = supervision_poll_seconds
        self._restart_backoff_initial_seconds = restart_backoff_initial_seconds
        self._restart_backoff_max_seconds = restart_backoff_max_seconds
        self._restart_stable_seconds = restart_stable_seconds
        self._termination_timeout_seconds = termination_timeout_seconds
        self._clock = clock
        self._processes: dict[str, FFmpegProcess] = {}
        self._supervisors: dict[str, threading.Thread] = {}
        self._stop_event = threading.Event()
        self._lifecycle_operation_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._started = False

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
        with self._lifecycle_operation_lock:
            with self._lifecycle_lock:
                if self._started:
                    return

            self._validate_runtime_config()
            self.config.output_dir.mkdir(parents=True, exist_ok=True)
            for stream_id in self.config.stream_ids:
                self._stream_dir(stream_id).mkdir(parents=True, exist_ok=True)

            supervisors = {
                stream_id: threading.Thread(
                    target=self._supervise_stream,
                    args=(stream_id,),
                    name=f"transcription-ffmpeg-{stream_id}",
                )
                for stream_id in self.config.stream_ids
            }
            with self._lifecycle_lock:
                self._stop_event.clear()
                self._started = True
                self._supervisors = supervisors

            started_supervisors: list[threading.Thread] = []
            try:
                for supervisor in supervisors.values():
                    supervisor.start()
                    started_supervisors.append(supervisor)
            except Exception:
                self._stop_event.set()
                for supervisor in started_supervisors:
                    supervisor.join()
                with self._lifecycle_lock:
                    self._processes.clear()
                    self._supervisors.clear()
                    self._started = False
                raise

    def stop(self) -> None:
        with self._lifecycle_operation_lock:
            self._stop_event.set()
            with self._lifecycle_lock:
                supervisors = tuple(self._supervisors.values())

            for supervisor in supervisors:
                if supervisor is threading.current_thread():
                    continue
                if supervisor.ident is None:
                    continue
                supervisor.join()

            with self._lifecycle_lock:
                self._processes.clear()
                self._supervisors.clear()
                self._started = False

    def sessions(self) -> tuple[AudioExtractionSession, ...]:
        with self._lifecycle_lock:
            active_streams = set(self._processes)
        return tuple(
            AudioExtractionSession(
                stream_id=stream_id,
                input_url=self.config.stream_input_urls.get(stream_id, ""),
                output_dir=self._stream_dir(stream_id),
                chunk_duration_seconds=self.config.chunk_duration_seconds,
                running=stream_id in active_streams,
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

    def _supervise_stream(self, stream_id: str) -> None:
        consecutive_failures = 0
        active_process: FFmpegProcess | None = None

        try:
            while not self._stop_event.is_set():
                try:
                    active_process = self._launch_process(stream_id)
                except Exception as exc:
                    consecutive_failures += 1
                    restart_delay = self._restart_delay(consecutive_failures)
                    error_type, error_message = self._diagnostic_error(exc)
                    self._logger.warning(
                        "transcription_ffmpeg_launch_failed stream=%s "
                        "consecutive_failures=%d restart_delay_seconds=%.3f "
                        "error_type=%s error=%r",
                        stream_id,
                        consecutive_failures,
                        restart_delay,
                        error_type,
                        error_message,
                    )
                    if self._stop_event.wait(restart_delay):
                        break
                    continue

                started_at = self._clock()
                with self._lifecycle_lock:
                    should_stop = self._stop_event.is_set()
                    if not should_stop:
                        self._processes[stream_id] = active_process

                if should_stop:
                    self._stop_process(stream_id, active_process)
                    active_process = None
                    break

                self._logger.info(
                    "transcription_ffmpeg_started stream=%s pid=%s "
                    "consecutive_failures=%d",
                    stream_id,
                    getattr(active_process, "pid", "unknown"),
                    consecutive_failures,
                )
                process_pid = getattr(active_process, "pid", "unknown")
                exit_code = self._wait_for_process_exit(active_process)
                runtime_seconds = max(0.0, self._clock() - started_at)
                self._remove_process(stream_id, active_process)

                if exit_code is None:
                    self._stop_process(stream_id, active_process)
                    active_process = None
                    break

                self._reap_exited_process(stream_id, active_process)
                active_process = None
                if runtime_seconds >= self._restart_stable_seconds:
                    consecutive_failures = 0
                consecutive_failures += 1
                restart_delay = self._restart_delay(consecutive_failures)
                self._logger.warning(
                    "transcription_ffmpeg_exited stream=%s pid=%s exit_code=%d "
                    "runtime_seconds=%.3f consecutive_failures=%d "
                    "restart_delay_seconds=%.3f",
                    stream_id,
                    process_pid,
                    exit_code,
                    runtime_seconds,
                    consecutive_failures,
                    restart_delay,
                )
                if self._stop_event.wait(restart_delay):
                    break
        finally:
            if active_process is not None:
                self._remove_process(stream_id, active_process)
                self._stop_process(stream_id, active_process)
            self._logger.info(
                "transcription_ffmpeg_supervisor_stopped stream=%s",
                stream_id,
            )

    def _launch_process(self, stream_id: str) -> FFmpegProcess:
        process_factory = self._process_factory or subprocess.Popen
        return process_factory(
            self.build_ffmpeg_command(stream_id),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _wait_for_process_exit(self, process: FFmpegProcess) -> int | None:
        while True:
            exit_code = process.poll()
            if exit_code is not None:
                return exit_code
            if self._stop_event.wait(self._supervision_poll_seconds):
                return None

    def _restart_delay(self, consecutive_failures: int) -> float:
        exponent = max(0, consecutive_failures - 1)
        max_exponent = math.ceil(
            math.log2(
                self._restart_backoff_max_seconds
                / self._restart_backoff_initial_seconds
            )
        )
        if exponent >= max_exponent:
            return self._restart_backoff_max_seconds
        return min(
            self._restart_backoff_initial_seconds * (2 ** exponent),
            self._restart_backoff_max_seconds,
        )

    def _diagnostic_error(self, error: Exception) -> tuple[str, str]:
        message = str(error)
        input_urls = sorted(
            set(self.config.stream_input_urls.values()),
            key=len,
            reverse=True,
        )
        for input_url in input_urls:
            if input_url:
                message = message.replace(input_url, "<redacted-input-url>")
        return type(error).__name__, message

    def _remove_process(
        self,
        stream_id: str,
        process: FFmpegProcess,
    ) -> None:
        with self._lifecycle_lock:
            if self._processes.get(stream_id) is process:
                self._processes.pop(stream_id, None)

    def _reap_exited_process(
        self,
        stream_id: str,
        process: FFmpegProcess,
    ) -> None:
        try:
            process.wait(timeout=self._termination_timeout_seconds)
        except subprocess.TimeoutExpired:
            self._logger.warning(
                "transcription_ffmpeg_reap_timeout stream=%s "
                "timeout_seconds=%.3f",
                stream_id,
                self._termination_timeout_seconds,
            )
        except OSError as exc:
            self._log_process_error(
                "transcription_ffmpeg_reap_failed",
                stream_id,
                exc,
            )

    def _stop_process(
        self,
        stream_id: str,
        process: FFmpegProcess,
    ) -> None:
        try:
            is_running = process.poll() is None
        except OSError as exc:
            self._log_process_error(
                "transcription_ffmpeg_poll_failed",
                stream_id,
                exc,
            )
            is_running = True

        if is_running:
            try:
                process.terminate()
            except OSError as exc:
                self._log_process_error(
                    "transcription_ffmpeg_terminate_failed",
                    stream_id,
                    exc,
                )
        try:
            process.wait(timeout=self._termination_timeout_seconds)
        except subprocess.TimeoutExpired:
            self._logger.warning(
                "transcription_ffmpeg_kill stream=%s timeout_seconds=%.3f",
                stream_id,
                self._termination_timeout_seconds,
            )
            try:
                process.kill()
            except OSError as exc:
                self._log_process_error(
                    "transcription_ffmpeg_kill_failed",
                    stream_id,
                    exc,
                )
            try:
                process.wait(timeout=self._termination_timeout_seconds)
            except subprocess.TimeoutExpired:
                self._logger.warning(
                    "transcription_ffmpeg_kill_timeout stream=%s "
                    "timeout_seconds=%.3f",
                    stream_id,
                    self._termination_timeout_seconds,
                )
            except OSError as exc:
                self._log_process_error(
                    "transcription_ffmpeg_wait_failed",
                    stream_id,
                    exc,
                )
        except OSError as exc:
            self._log_process_error(
                "transcription_ffmpeg_wait_failed",
                stream_id,
                exc,
            )

    def _log_process_error(
        self,
        event: str,
        stream_id: str,
        error: OSError,
    ) -> None:
        error_type, error_message = self._diagnostic_error(error)
        self._logger.warning(
            "%s stream=%s error_type=%s error=%r",
            event,
            stream_id,
            error_type,
            error_message,
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


def _events_from_payload(
    payload: Any,
    audio: AudioInputRef,
) -> tuple[TranscriptEvent, ...]:
    segments = _segments_from_payload(payload)
    events: list[TranscriptEvent] = []
    offset = audio.starts_at_seconds or 0.0

    for segment in segments:
        events.append(
            _event_from_segment(
                segment,
                audio.stream_id,
                offset,
                duration_seconds=audio.duration_seconds,
                require_timestamps=(
                    audio.emit_from_seconds is not None
                    and audio.starts_at_seconds is not None
                    and audio.emit_from_seconds > audio.starts_at_seconds
                ),
            )
        )

    return tuple(events)


def _segments_from_payload(payload: Any) -> tuple[dict[str, Any], ...]:
    if isinstance(payload, dict):
        segments = payload.get("segments")
        if segments is None and "text" in payload:
            segments = [payload]
    elif isinstance(payload, list):
        segments = payload
    else:
        raise TranscriptionError("Transcription response must be an object or list.")

    if not isinstance(segments, list):
        raise TranscriptionError("Transcription response segments must be a list.")

    normalized: list[dict[str, Any]] = []
    for segment in segments:
        if not isinstance(segment, dict):
            raise TranscriptionError("Transcription segment must be an object.")
        normalized.append(segment)

    return tuple(normalized)


def _event_from_segment(
    segment: dict[str, Any],
    stream_id: str,
    offset_seconds: float,
    duration_seconds: float | None = None,
    require_timestamps: bool = False,
) -> TranscriptEvent:
    text = str(segment.get("text", "")).strip()
    if not text:
        raise TranscriptionError("Transcription segment text is missing.")

    start = _segment_time_or_none(segment, "start", "start_seconds")
    end = _segment_time_or_none(segment, "end", "end_seconds")
    if start is None and end is None:
        if require_timestamps:
            raise TranscriptionError(
                "Transcription overlap requires timestamped transcription "
                "segments; text-only responses cannot be de-duplicated."
            )
        if duration_seconds is None:
            raise TranscriptionError(
                "Transcription segment is missing timestamps and audio duration."
            )
        start = 0.0
        end = float(duration_seconds)
    elif start is None or end is None:
        raise TranscriptionError("Transcription segment has incomplete timestamps.")

    if end <= start:
        raise TranscriptionError("Transcription segment end must be after start.")

    is_final = segment.get("is_final", segment.get("final", True))
    return TranscriptEvent(
        stream_id=stream_id,
        text=text,
        start_time_seconds=offset_seconds + start,
        end_time_seconds=offset_seconds + end,
        is_final=bool(is_final),
    )


def _segment_time(segment: dict[str, Any], *names: str) -> float:
    value = _segment_time_or_none(segment, *names)
    if value is None:
        raise TranscriptionError(f"Transcription segment is missing {names[0]}.")
    return value


def _segment_time_or_none(segment: dict[str, Any], *names: str) -> float | None:
    for name in names:
        if name not in segment:
            continue
        try:
            return float(segment[name])
        except (TypeError, ValueError) as exc:
            raise TranscriptionError(
                f"Transcription segment {name} must be numeric."
            ) from exc

    return None


def _normalize_endpoint_path(
    endpoint_path: str | None,
    *,
    request_mode: str,
) -> str:
    if endpoint_path:
        return endpoint_path if endpoint_path.startswith("/") else f"/{endpoint_path}"
    if request_mode == TRANSCRIPTION_REQUEST_MODE_OPENAI_COMPATIBLE:
        return "/v1/audio/transcriptions"
    return "/transcribe"


def _local_audio_path(uri: str) -> Path:
    parsed = urlparse(uri)
    windows_drive_path = len(parsed.scheme) == 1 and bool(Path(uri).drive)
    if parsed.scheme in ("http", "https", "rtmp", "rtsp", "srt"):
        raise TranscriptionError(
            "OpenAI-compatible transcription upload requires a local file path "
            f"or file:// URI, not remote URI: {uri}"
        )
    if parsed.scheme and parsed.scheme != "file" and not windows_drive_path:
        raise TranscriptionError(
            "OpenAI-compatible transcription upload requires a local file path "
            f"or file:// URI, not URI scheme {parsed.scheme!r}."
        )

    if parsed.scheme == "file":
        if parsed.netloc and parsed.netloc.lower() != "localhost":
            raise TranscriptionError(
                "OpenAI-compatible transcription upload requires a local file:// URI."
            )
        path = Path(url2pathname(unquote(parsed.path)))
    else:
        path = Path(uri)

    try:
        resolved = path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise TranscriptionError(
            f"OpenAI-compatible transcription audio is not readable: {uri}"
        ) from exc

    if not resolved.is_file():
        raise TranscriptionError(
            f"OpenAI-compatible transcription audio is not a file: {resolved}"
        )
    return resolved


def _format_seconds(value: float) -> str:
    formatted = f"{value:.3f}".rstrip("0").rstrip(".")
    return formatted or "0"
