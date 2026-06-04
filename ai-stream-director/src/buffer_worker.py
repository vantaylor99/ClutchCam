"""Runtime entrypoint for the rolling lookback buffer worker."""

from __future__ import annotations

import logging
import shutil
import signal
import sys
import threading
from collections.abc import Callable, Sequence
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import FrameType
from typing import Protocol

from config import AppConfig, get_config
from services.buffer import (
    FFmpegRollingLookbackBuffer,
    LookbackBufferError,
    RollingBufferConfig,
)
from services.health import run_runtime_healthcheck


LOGGER = logging.getLogger(__name__)
SHUTDOWN_SIGNALS = tuple(
    current_signal
    for current_signal in (
        getattr(signal, "SIGTERM", None),
        getattr(signal, "SIGINT", None),
    )
    if current_signal is not None
)


class BufferWorkerError(RuntimeError):
    """Raised when the buffer worker cannot safely start."""


class BufferProcess(Protocol):
    def start(self) -> None:
        """Start child segment writers."""

    def stop(self) -> None:
        """Stop child segment writers and release resources."""


BufferFactory = Callable[[RollingBufferConfig], BufferProcess]
FFmpegResolver = Callable[[str], str | None]


def build_buffer_config(app_config: AppConfig | None = None) -> RollingBufferConfig:
    """Build the rolling buffer config from AppConfig."""

    return RollingBufferConfig.from_app_config(app_config or get_config())


def validate_startup_config(
    config: RollingBufferConfig,
    *,
    ffmpeg_resolver: FFmpegResolver = shutil.which,
) -> None:
    """Validate worker settings before starting FFmpeg processes."""

    if not config.stream_ids:
        raise BufferWorkerError("No stream IDs configured for the buffer worker.")

    missing_input_urls = [
        stream_id
        for stream_id in config.stream_ids
        if not config.stream_input_urls.get(stream_id)
    ]
    if missing_input_urls:
        raise BufferWorkerError(
            "Missing input URLs for stream IDs: " + ", ".join(missing_input_urls)
        )

    ffmpeg_executable = config.ffmpeg_executable.strip()
    if not ffmpeg_executable:
        raise BufferWorkerError("FFmpeg executable is not configured.")
    if ffmpeg_resolver(ffmpeg_executable) is None:
        raise BufferWorkerError(
            f"FFmpeg executable not found: {config.ffmpeg_executable}"
        )

    _ensure_writable_directory(config.buffer_root)


def run_buffer_worker(
    config: RollingBufferConfig | None = None,
    *,
    buffer_factory: BufferFactory = FFmpegRollingLookbackBuffer,
    ffmpeg_resolver: FFmpegResolver = shutil.which,
    install_signal_handlers: bool = True,
    logger: logging.Logger = LOGGER,
    shutdown_event: threading.Event | None = None,
    wait_interval_seconds: float = 1.0,
) -> int:
    """Start the rolling buffer worker and block until shutdown."""

    runtime_config = config or build_buffer_config()
    validate_startup_config(runtime_config, ffmpeg_resolver=ffmpeg_resolver)
    _log_startup_config(runtime_config, logger)

    stop_event = shutdown_event or threading.Event()
    signal_context = (
        _installed_signal_handlers(stop_event)
        if install_signal_handlers
        else nullcontext()
    )
    buffer = buffer_factory(runtime_config)

    with signal_context:
        try:
            buffer.start()
            _wait_for_shutdown(stop_event, wait_interval_seconds)
        except KeyboardInterrupt:
            stop_event.set()
        finally:
            buffer.stop()

    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint."""

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = tuple(sys.argv[1:] if argv is None else argv)
    if args == ("--healthcheck",):
        return run_runtime_healthcheck("buffer-worker")
    if args:
        LOGGER.error("Unknown buffer worker arguments: %s", " ".join(args))
        return 2

    try:
        return run_buffer_worker()
    except (BufferWorkerError, LookbackBufferError, OSError, ValueError) as exc:
        LOGGER.error("Buffer worker failed to start: %s", exc)
        return 1


def _log_startup_config(
    config: RollingBufferConfig,
    logger: logging.Logger,
) -> None:
    for stream_id in config.stream_ids:
        logger.info(
            "buffer stream=%s input=%s dir=%s",
            stream_id,
            config.stream_input_urls[stream_id],
            config.buffer_root / stream_id,
        )


def _wait_for_shutdown(
    stop_event: threading.Event,
    wait_interval_seconds: float,
) -> None:
    while not stop_event.wait(wait_interval_seconds):
        pass


@contextmanager
def _installed_signal_handlers(stop_event: threading.Event):
    previous_handlers = {}

    def request_shutdown(
        signum: int,
        frame: FrameType | None,
    ) -> None:
        del signum, frame
        stop_event.set()

    for shutdown_signal in SHUTDOWN_SIGNALS:
        previous_handlers[shutdown_signal] = signal.signal(
            shutdown_signal,
            request_shutdown,
        )

    try:
        yield
    finally:
        for shutdown_signal, previous_handler in previous_handlers.items():
            signal.signal(shutdown_signal, previous_handler)


def _ensure_writable_directory(directory: Path) -> None:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".clutchcam-buffer-worker-write-test"
        probe.write_text("", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        raise BufferWorkerError(
            f"Buffer directory is not writable: {directory}"
        ) from exc


if __name__ == "__main__":
    raise SystemExit(main())
