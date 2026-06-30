"""Runtime entrypoint for the transcription worker."""

from __future__ import annotations

import json
import signal
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Callable, TextIO
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from config import (
    AppConfig,
    TRANSCRIPTION_SOURCE_MODE_CHUNKED,
    get_config,
)
from contracts import TranscriptEvent
from services.transcription import (
    AudioExtractionConfig,
    AudioExtractor,
    AudioInputRef,
    FFmpegAudioExtractor,
    FasterWhisperTranscriber,
    Transcriber,
    TranscriptionError,
    build_overlapped_audio_ref,
)
from services.health import run_runtime_healthcheck
from services.transcription_runtime import (
    TranscriptEventSource,
    TranscriptEventSink,
    TranscriptionRuntimeFailure,
    TranscriptionRuntimePump,
    TranscriptionRuntimeSummary,
)


POLL_INTERVAL_SECONDS = 0.5


@dataclass(frozen=True)
class _ChunkSnapshot:
    size_bytes: int
    modified_ns: int


class AudioChunkDiscovery:
    def discover(self) -> tuple[AudioInputRef, ...]:
        """Return audio references ready to transcribe."""


class JsonLinesTranscriptSink:
    """Writes transcript and worker status events as JSON lines."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream = stream or sys.stdout
        self._lock = threading.Lock()

    def __call__(self, event: TranscriptEvent) -> dict[str, object]:
        payload = transcript_event_payload(event)
        self.write(payload)
        return payload

    def write_failure(self, failure: TranscriptionRuntimeFailure) -> None:
        self.write(transcription_failure_payload(failure))

    def write_worker_error(self, error: Exception) -> None:
        self.write(
            {
                "type": "transcription_worker_error",
                "message": str(error),
            }
        )

    def write(self, payload: dict[str, object]) -> None:
        with self._lock:
            print(json.dumps(payload, sort_keys=True), file=self.stream, flush=True)


class CompletedAudioChunkDiscovery:
    """Discovers stable extracted audio chunks exactly once."""

    def __init__(
        self,
        config: AudioExtractionConfig,
        extractor: AudioExtractor,
        *,
        require_stable_snapshot: bool = True,
    ) -> None:
        self.config = config
        self.extractor = extractor
        self.require_stable_snapshot = require_stable_snapshot
        self._pending: dict[Path, _ChunkSnapshot] = {}
        self._processed: set[Path] = set()

    def discover(self) -> tuple[AudioInputRef, ...]:
        audio_refs: list[AudioInputRef] = []
        current_paths: set[Path] = set()

        for stream_id in self.config.stream_ids:
            stream_dir = self.config.output_dir / stream_id
            if not stream_dir.exists():
                continue

            for chunk_path in sorted(stream_dir.glob(f"*.{self.config.container}")):
                audio_ref = self._audio_ref_if_ready(stream_id, chunk_path)
                try:
                    current_paths.add(chunk_path.resolve())
                except FileNotFoundError:
                    continue
                if audio_ref is not None:
                    audio_refs.append(audio_ref)

        stale_paths = set(self._pending).difference(current_paths)
        for stale_path in stale_paths:
            self._pending.pop(stale_path, None)

        return tuple(audio_refs)

    def _audio_ref_if_ready(
        self,
        stream_id: str,
        chunk_path: Path,
    ) -> AudioInputRef | None:
        try:
            resolved_path = chunk_path.resolve()
            stat_result = resolved_path.stat()
        except FileNotFoundError:
            return None

        if not resolved_path.is_file() or resolved_path in self._processed:
            return None

        snapshot = _ChunkSnapshot(
            size_bytes=stat_result.st_size,
            modified_ns=stat_result.st_mtime_ns,
        )
        if snapshot.size_bytes <= 0:
            self._pending[resolved_path] = snapshot
            return None

        if self.require_stable_snapshot:
            previous_snapshot = self._pending.get(resolved_path)
            self._pending[resolved_path] = snapshot
            if previous_snapshot != snapshot:
                return None

        self._processed.add(resolved_path)
        self._pending.pop(resolved_path, None)
        return self.extractor.build_audio_ref(
            stream_id,
            resolved_path,
            starts_at_seconds=_infer_chunk_start_seconds(
                resolved_path,
                self.config.chunk_duration_seconds,
            ),
        )


class OverlappedAudioWindowDiscovery:
    """Adds a previous-chunk WAV tail to transcription requests when available."""

    def __init__(
        self,
        base_discovery: AudioChunkDiscovery,
        *,
        config: AudioExtractionConfig,
        overlap_seconds: float,
    ) -> None:
        self.base_discovery = base_discovery
        self.config = config
        self.overlap_seconds = float(overlap_seconds)
        self._last_original_chunk_paths: dict[str, Path] = {}
        self._retained_overlap_paths: set[Path] = set()

    def discover(self) -> tuple[AudioInputRef, ...]:
        base_refs = self.base_discovery.discover()
        overlapped_refs: list[AudioInputRef] = []
        current_overlap_paths: set[Path] = set()

        for audio_ref in base_refs:
            current_path = _local_file_path_from_uri(audio_ref.uri)
            previous_path = self._previous_chunk_path(audio_ref.stream_id, current_path)
            overlapped_ref = build_overlapped_audio_ref(
                audio_ref=audio_ref,
                current_chunk_path=current_path,
                previous_chunk_path=previous_path,
                overlap_seconds=self.overlap_seconds,
                config=self.config,
            )
            overlapped_refs.append(overlapped_ref)
            overlap_path = _overlap_path_if_local(overlapped_ref, audio_ref)
            if overlap_path is not None:
                current_overlap_paths.add(overlap_path)
            self._last_original_chunk_paths[audio_ref.stream_id] = current_path

        self._cleanup_stale_overlap_paths(current_overlap_paths)
        self._retained_overlap_paths = current_overlap_paths
        return tuple(overlapped_refs)

    def _previous_chunk_path(self, stream_id: str, current_path: Path) -> Path | None:
        numeric_previous_path = _numeric_previous_chunk_path(current_path)
        if numeric_previous_path is not None:
            return numeric_previous_path
        return self._last_original_chunk_paths.get(stream_id)

    def _cleanup_stale_overlap_paths(self, current_overlap_paths: set[Path]) -> None:
        stale_paths = self._retained_overlap_paths.difference(current_overlap_paths)
        for stale_path in stale_paths:
            try:
                stale_path.unlink(missing_ok=True)
            except OSError:
                continue


class TranscriptionWorker:
    """Owns extractor lifecycle and feeds discovered chunks into the pump."""

    def __init__(
        self,
        *,
        extraction_config: AudioExtractionConfig,
        extractor: AudioExtractor,
        transcriber: Transcriber,
        sink: TranscriptEventSink,
        failure_sink: Callable[[TranscriptionRuntimeFailure], object | None]
        | None = None,
        discovery: AudioChunkDiscovery | None = None,
        stop_event: threading.Event | None = None,
        started_event: threading.Event | None = None,
        poll_interval_seconds: float = POLL_INTERVAL_SECONDS,
        wait: Callable[[float], bool] | None = None,
        fail_fast: bool = False,
    ) -> None:
        self.extraction_config = extraction_config
        self.extractor = extractor
        self.transcriber = transcriber
        self.sink = sink
        self.failure_sink = failure_sink or (lambda failure: None)
        self.discovery = discovery or CompletedAudioChunkDiscovery(
            extraction_config,
            extractor,
        )
        self.stop_event = stop_event or threading.Event()
        self.started_event = started_event
        self.poll_interval_seconds = float(poll_interval_seconds)
        self._wait = wait or self.stop_event.wait
        self._pump = TranscriptionRuntimePump(
            transcriber=transcriber,
            sink=sink,
            fail_fast=fail_fast,
        )

    def run_once(self) -> TranscriptionRuntimeSummary:
        summary = self._pump.run_once(self.discovery.discover())
        for failure in summary.failures:
            self.failure_sink(failure)
        return summary

    def start(self) -> None:
        self.run_forever()

    def stop(self) -> None:
        self.stop_event.set()

    def run_forever(self) -> None:
        try:
            self.extractor.start()
            if self.started_event is not None:
                self.started_event.set()
            while not self.stop_event.is_set():
                self.run_once()
                if self._wait(self.poll_interval_seconds):
                    break
        finally:
            self.extractor.stop()


class SignalStopController:
    """Installs stop-only signal handlers for worker shutdown."""

    def __init__(
        self,
        stop_event: threading.Event | None = None,
        signals: tuple[int, ...] | None = None,
    ) -> None:
        self.stop_event = stop_event or threading.Event()
        self.signals = _default_stop_signals() if signals is None else signals
        self._previous_handlers: dict[int, signal.Handlers] = {}

    def __enter__(self) -> "SignalStopController":
        for signal_number in self.signals:
            try:
                self._previous_handlers[signal_number] = signal.getsignal(
                    signal_number
                )
                signal.signal(signal_number, self.request_stop)
            except (OSError, ValueError):
                continue
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        for signal_number, previous_handler in self._previous_handlers.items():
            try:
                signal.signal(signal_number, previous_handler)
            except (OSError, ValueError):
                continue
        return False

    def request_stop(
        self,
        signal_number: int | None = None,
        frame: FrameType | None = None,
    ) -> None:
        self.stop_event.set()


def build_worker(
    *,
    app_config: AppConfig | None = None,
    stdout: TextIO | None = None,
    sink: TranscriptEventSink | None = None,
    failure_sink: Callable[[TranscriptionRuntimeFailure], object | None]
    | None = None,
    stop_event: threading.Event | None = None,
    started_event: threading.Event | None = None,
    poll_interval_seconds: float = POLL_INTERVAL_SECONDS,
    fail_fast: bool = False,
) -> TranscriptionWorker:
    source = build_transcription_event_source(
        app_config=app_config,
        stdout=stdout,
        sink=sink,
        failure_sink=failure_sink,
        stop_event=stop_event,
        started_event=started_event,
        poll_interval_seconds=poll_interval_seconds,
        fail_fast=fail_fast,
    )
    if not isinstance(source, TranscriptionWorker):
        raise TranscriptionError(
            "build_worker requires the chunked transcription source."
        )
    return source


def build_transcription_event_source(
    *,
    app_config: AppConfig | None = None,
    stdout: TextIO | None = None,
    sink: TranscriptEventSink | None = None,
    failure_sink: Callable[[TranscriptionRuntimeFailure], object | None]
    | None = None,
    stop_event: threading.Event | None = None,
    started_event: threading.Event | None = None,
    poll_interval_seconds: float = POLL_INTERVAL_SECONDS,
    fail_fast: bool = False,
) -> TranscriptEventSource:
    app_config = app_config or get_config()
    if app_config.transcription_source_mode != TRANSCRIPTION_SOURCE_MODE_CHUNKED:
        raise TranscriptionError(
            "Unsupported TRANSCRIPTION_SOURCE_MODE "
            f"{app_config.transcription_source_mode!r}: this runtime only "
            f"implements {TRANSCRIPTION_SOURCE_MODE_CHUNKED!r}."
        )

    extraction_config = AudioExtractionConfig.from_app_config(app_config)
    extractor = FFmpegAudioExtractor(extraction_config)
    transcriber = FasterWhisperTranscriber.from_app_config(app_config)
    jsonl_sink = JsonLinesTranscriptSink(stdout)
    discovery: AudioChunkDiscovery = CompletedAudioChunkDiscovery(
        extraction_config,
        extractor,
    )
    if app_config.transcription_request_overlap_seconds > 0:
        discovery = OverlappedAudioWindowDiscovery(
            discovery,
            config=extraction_config,
            overlap_seconds=app_config.transcription_request_overlap_seconds,
        )
    return TranscriptionWorker(
        extraction_config=extraction_config,
        extractor=extractor,
        transcriber=transcriber,
        sink=sink or jsonl_sink,
        failure_sink=(
            failure_sink if failure_sink is not None else jsonl_sink.write_failure
        ),
        stop_event=stop_event,
        started_event=started_event,
        poll_interval_seconds=poll_interval_seconds,
        fail_fast=fail_fast,
        discovery=discovery,
    )


def main(argv: tuple[str, ...] | list[str] | None = None) -> int:
    args = tuple(sys.argv[1:] if argv is None else argv)
    if args == ("--healthcheck",):
        return run_runtime_healthcheck("transcription-worker")
    if args:
        JsonLinesTranscriptSink().write_worker_error(
            ValueError("Unknown transcription worker arguments: " + " ".join(args))
        )
        return 2

    jsonl_sink = JsonLinesTranscriptSink()
    try:
        with SignalStopController() as stop_controller:
            worker = build_worker(stop_event=stop_controller.stop_event)
            worker.run_forever()
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        jsonl_sink.write_worker_error(exc)
        return 1

    return 0


def transcript_event_payload(event: TranscriptEvent) -> dict[str, object]:
    return {
        "type": "transcript_event",
        "stream_id": event.stream_id,
        "text": event.text,
        "start_time_seconds": event.start_time_seconds,
        "end_time_seconds": event.end_time_seconds,
        "is_final": event.is_final,
    }


def transcription_failure_payload(
    failure: TranscriptionRuntimeFailure,
) -> dict[str, object]:
    return {
        "type": "transcription_failure",
        "stream_id": failure.audio_ref.stream_id,
        "audio_uri": failure.audio_ref.uri,
        "message": failure.message,
    }


def _infer_chunk_start_seconds(
    chunk_path: Path,
    chunk_duration_seconds: float,
) -> float | None:
    try:
        return int(chunk_path.stem) * chunk_duration_seconds
    except ValueError:
        return None


def _local_file_path_from_uri(uri: str) -> Path:
    parsed = urlparse(uri)
    windows_drive_path = len(parsed.scheme) == 1 and bool(Path(uri).drive)
    if parsed.scheme == "file":
        return Path(url2pathname(unquote(parsed.path))).resolve()
    if not parsed.scheme or windows_drive_path:
        return Path(uri).resolve()
    raise ValueError(f"Audio chunk URI is not local: {uri}")


def _numeric_previous_chunk_path(current_path: Path) -> Path | None:
    try:
        index = int(current_path.stem)
    except ValueError:
        return None
    if index <= 0:
        return None
    previous_stem = f"{index - 1:0{len(current_path.stem)}d}"
    return current_path.with_name(f"{previous_stem}{current_path.suffix}")


def _overlap_path_if_local(
    overlapped_ref: AudioInputRef,
    original_ref: AudioInputRef,
) -> Path | None:
    if overlapped_ref.uri == original_ref.uri:
        return None
    try:
        return _local_file_path_from_uri(overlapped_ref.uri)
    except ValueError:
        return None


def _default_stop_signals() -> tuple[int, ...]:
    signals: list[int] = []
    for signal_name in ("SIGINT", "SIGTERM"):
        signal_number = getattr(signal, signal_name, None)
        if signal_number is not None:
            signals.append(signal_number)
    return tuple(signals)


if __name__ == "__main__":
    sys.exit(main())
