"""Opt-in Docker Compose checkpoint for generated RTMP ingest and lookback clips."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, TextIO


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

CHECKPOINT_NAME = "compose-generated-ingest"
DEFAULT_STREAM_IDS = ("player_1",)
COMPOSE_PROFILES = ("media-server", "buffer-worker")
COMPOSE_SERVICES = ("media-server", "buffer-worker")

STATUS_PASSED = "passed"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"
STATUS_NOT_RUN = "not_run"

RunCallable = Callable[..., subprocess.CompletedProcess[str]]
MediaSmokeCallable = Callable[..., object]
BufferInspectCallable = Callable[..., object]
BufferAssertCallable = Callable[[object], None]


@dataclass(frozen=True)
class GeneratedIngestOptions:
    run: bool = False
    stream_ids: tuple[str, ...] = DEFAULT_STREAM_IDS
    skip_compose: bool = False
    compose_build: bool = True
    compose_timeout_seconds: float = 120.0
    buffer_ready_timeout_seconds: float = 30.0
    buffer_poll_interval_seconds: float = 1.0


def run_generated_ingest_checkpoint(
    env: Mapping[str, str] = os.environ,
    *,
    options: GeneratedIngestOptions | None = None,
    run: RunCallable = subprocess.run,
    media_smoke: MediaSmokeCallable | None = None,
    buffer_inspect: BufferInspectCallable | None = None,
    buffer_assert_ready: BufferAssertCallable | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, object]:
    selected_options = options or options_from_env(env)
    started_at = clock()
    stream_ids = selected_options.stream_ids

    compose_summary = _not_run_compose_summary(env, selected_options)
    publish_summary: dict[str, object] = _not_run_summary(
        "generated FFmpeg publish has not run"
    )
    buffer_summary: dict[str, object] = _not_run_summary(
        "buffer metadata inspection has not run"
    )
    failure_reason: str | None = None

    if not selected_options.run:
        return _checkpoint_report(
            status=STATUS_SKIPPED,
            duration_seconds=_duration_since(started_at, clock),
            stream_ids=stream_ids,
            compose=compose_summary,
            publish=publish_summary,
            buffer=buffer_summary,
            failure_reason=None,
            operator_hints=_operator_hints(
                STATUS_SKIPPED,
                "pass --run or set GENERATED_INGEST_CHECKPOINT_RUN=true",
            ),
        )

    runtime_env = _runtime_env(env, stream_ids)
    compose_summary = _run_compose_services(
        runtime_env,
        selected_options,
        run=run,
    )
    if compose_summary["status"] == STATUS_FAILED:
        failure_reason = str(compose_summary["failure_reason"])
        return _checkpoint_report(
            status=STATUS_FAILED,
            duration_seconds=_duration_since(started_at, clock),
            stream_ids=stream_ids,
            compose=compose_summary,
            publish=publish_summary,
            buffer=buffer_summary,
            failure_reason=failure_reason,
            operator_hints=_operator_hints(STATUS_FAILED, failure_reason),
        )

    try:
        media_result = (media_smoke or _load_media_smoke())(
            runtime_env,
            stream_ids=stream_ids,
        )
    except Exception as exc:
        failure_reason = (
            "Generated RTMP publish or SRS readiness failed: "
            f"{str(exc) or exc.__class__.__name__}"
        )
        publish_summary = {
            "status": STATUS_FAILED,
            "failure_reason": failure_reason,
            "summaries": None,
            "streams": [],
            "published_stream_ids": [],
        }
        return _checkpoint_report(
            status=STATUS_FAILED,
            duration_seconds=_duration_since(started_at, clock),
            stream_ids=stream_ids,
            compose=compose_summary,
            publish=publish_summary,
            buffer=buffer_summary,
            failure_reason=failure_reason,
            operator_hints=_operator_hints(STATUS_FAILED, failure_reason),
        )

    publish_summary = _summarize_media_smoke(media_result)
    buffer_summary = _wait_for_buffer_ready(
        runtime_env,
        stream_ids=stream_ids,
        timeout_seconds=selected_options.buffer_ready_timeout_seconds,
        poll_interval_seconds=selected_options.buffer_poll_interval_seconds,
        inspect_buffer=buffer_inspect or _load_buffer_inspect(),
        assert_ready=buffer_assert_ready or _load_buffer_assert_ready(),
        sleep=sleep,
        clock=clock,
    )
    if buffer_summary["status"] != "ready":
        failure_reason = str(buffer_summary["failure_reason"])
        return _checkpoint_report(
            status=STATUS_FAILED,
            duration_seconds=_duration_since(started_at, clock),
            stream_ids=stream_ids,
            compose=compose_summary,
            publish=publish_summary,
            buffer=buffer_summary,
            failure_reason=failure_reason,
            operator_hints=_operator_hints(STATUS_FAILED, failure_reason),
        )

    return _checkpoint_report(
        status=STATUS_PASSED,
        duration_seconds=_duration_since(started_at, clock),
        stream_ids=stream_ids,
        compose=compose_summary,
        publish=publish_summary,
        buffer=buffer_summary,
        failure_reason=None,
        operator_hints=_operator_hints(STATUS_PASSED, None),
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    current_env = os.environ if env is None else env
    base_options = options_from_env(current_env)
    streams = _stream_ids_from_arg(args.streams) if args.streams else base_options.stream_ids
    if not streams:
        parser.error("at least one stream ID is required")

    options = GeneratedIngestOptions(
        run=args.run or base_options.run,
        stream_ids=streams,
        skip_compose=args.no_compose or base_options.skip_compose,
        compose_build=False if args.no_build else base_options.compose_build,
        compose_timeout_seconds=(
            args.compose_timeout_seconds
            if args.compose_timeout_seconds is not None
            else base_options.compose_timeout_seconds
        ),
        buffer_ready_timeout_seconds=(
            args.buffer_ready_timeout_seconds
            if args.buffer_ready_timeout_seconds is not None
            else base_options.buffer_ready_timeout_seconds
        ),
        buffer_poll_interval_seconds=(
            args.buffer_poll_interval_seconds
            if args.buffer_poll_interval_seconds is not None
            else base_options.buffer_poll_interval_seconds
        ),
    )
    report = run_generated_ingest_checkpoint(current_env, options=options)
    stream = stdout or sys.stdout
    print(json.dumps(report, indent=args.indent, sort_keys=True), file=stream)
    return 1 if report["status"] == STATUS_FAILED else 0


def options_from_env(env: Mapping[str, str] = os.environ) -> GeneratedIngestOptions:
    return GeneratedIngestOptions(
        run=_env_bool(env, "GENERATED_INGEST_CHECKPOINT_RUN", False),
        stream_ids=_stream_ids_from_env(env),
        skip_compose=_env_bool(env, "GENERATED_INGEST_SKIP_COMPOSE", False),
        compose_build=_env_bool(env, "GENERATED_INGEST_COMPOSE_BUILD", True),
        compose_timeout_seconds=_env_float(
            env,
            "GENERATED_INGEST_COMPOSE_TIMEOUT_SECONDS",
            120.0,
        ),
        buffer_ready_timeout_seconds=_env_float(
            env,
            "GENERATED_INGEST_BUFFER_READY_TIMEOUT_SECONDS",
            30.0,
        ),
        buffer_poll_interval_seconds=_env_float(
            env,
            "GENERATED_INGEST_BUFFER_POLL_SECONDS",
            1.0,
        ),
    )


def build_compose_command(
    env: Mapping[str, str] = os.environ,
    *,
    build: bool = True,
) -> list[str]:
    command = [env.get("DOCKER_EXECUTABLE", "docker"), "compose"]
    for profile in COMPOSE_PROFILES:
        command.extend(["--profile", profile])
    command.extend(["up", "-d"])
    if build:
        command.append("--build")
    command.extend(COMPOSE_SERVICES)
    return command


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run",
        action="store_true",
        help=(
            "Run the live checkpoint. This may start Docker Compose services "
            "and launch bounded FFmpeg publishers."
        ),
    )
    parser.add_argument(
        "--no-compose",
        action="store_true",
        help="Target already-running media-server and buffer-worker services.",
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="Do not pass --build to docker compose up.",
    )
    parser.add_argument(
        "--streams",
        help="Comma-separated stream IDs to publish and inspect.",
    )
    parser.add_argument(
        "--compose-timeout-seconds",
        type=float,
        help="Timeout for docker compose up. Defaults to env or 120 seconds.",
    )
    parser.add_argument(
        "--buffer-ready-timeout-seconds",
        type=float,
        help="Time to poll for resolvable buffer metadata. Defaults to env or 30 seconds.",
    )
    parser.add_argument(
        "--buffer-poll-interval-seconds",
        type=float,
        help="Polling interval for buffer metadata readiness. Defaults to env or 1 second.",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indentation. Defaults to 2.",
    )
    return parser


def _run_compose_services(
    env: Mapping[str, str],
    options: GeneratedIngestOptions,
    *,
    run: RunCallable,
) -> dict[str, object]:
    if options.skip_compose:
        return {
            "status": STATUS_SKIPPED,
            "command": None,
            "services": list(COMPOSE_SERVICES),
            "profiles": list(COMPOSE_PROFILES),
            "cwd": str(PROJECT_DIR),
            "timeout_seconds": options.compose_timeout_seconds,
            "returncode": None,
            "stdout": "",
            "stderr": "",
            "failure_reason": None,
            "reason": "targeting already-running Compose services",
        }

    command = build_compose_command(env, build=options.compose_build)
    try:
        result = run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=options.compose_timeout_seconds,
            cwd=str(PROJECT_DIR),
            env=dict(env),
        )
    except subprocess.TimeoutExpired:
        return {
            "status": STATUS_FAILED,
            "command": command,
            "services": list(COMPOSE_SERVICES),
            "profiles": list(COMPOSE_PROFILES),
            "cwd": str(PROJECT_DIR),
            "timeout_seconds": options.compose_timeout_seconds,
            "returncode": None,
            "stdout": "",
            "stderr": "",
            "failure_reason": (
                "Timed out starting Docker Compose services "
                f"{', '.join(COMPOSE_SERVICES)} after "
                f"{options.compose_timeout_seconds:g}s."
            ),
        }

    stdout = _trim_output(result.stdout or "")
    stderr = _trim_output(result.stderr or "")
    failure_reason = None
    status = STATUS_PASSED
    if result.returncode != 0:
        status = STATUS_FAILED
        failure_reason = (
            "Docker Compose failed while starting generated-ingest services: "
            f"{_completed_output(result)}"
        )

    return {
        "status": status,
        "command": command,
        "services": list(COMPOSE_SERVICES),
        "profiles": list(COMPOSE_PROFILES),
        "cwd": str(PROJECT_DIR),
        "timeout_seconds": options.compose_timeout_seconds,
        "returncode": result.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "failure_reason": failure_reason,
    }


def _wait_for_buffer_ready(
    env: Mapping[str, str],
    *,
    stream_ids: Sequence[str],
    timeout_seconds: float,
    poll_interval_seconds: float,
    inspect_buffer: BufferInspectCallable,
    assert_ready: BufferAssertCallable,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> dict[str, object]:
    started_at = clock()
    deadline = started_at + max(0.0, timeout_seconds)
    attempts = 0
    last_result: object | None = None
    last_error: str | None = None

    while True:
        attempts += 1
        try:
            last_result = inspect_buffer(env, stream_ids=stream_ids)
            assert_ready(last_result)
            return _summarize_buffer(
                last_result,
                status="ready",
                attempts=attempts,
                duration_seconds=_duration_since(started_at, clock),
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
                failure_reason=None,
                last_error=None,
            )
        except Exception as exc:
            last_error = str(exc) or exc.__class__.__name__

        now = clock()
        if now >= deadline:
            break
        sleep(min(max(0.1, poll_interval_seconds), deadline - now))

    failure_reason = (
        "Buffer metadata did not become ready within "
        f"{timeout_seconds:g}s: {last_error or 'no buffer inspection result'}"
    )
    return _summarize_buffer(
        last_result,
        status=STATUS_FAILED,
        attempts=attempts,
        duration_seconds=_duration_since(started_at, clock),
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        failure_reason=failure_reason,
        last_error=last_error,
    )


def _checkpoint_report(
    *,
    status: str,
    duration_seconds: float,
    stream_ids: Sequence[str],
    compose: Mapping[str, object],
    publish: Mapping[str, object],
    buffer: Mapping[str, object],
    failure_reason: str | None,
    operator_hints: Sequence[str],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "checkpoint": CHECKPOINT_NAME,
        "status": status,
        "duration_seconds": duration_seconds,
        "stream_ids": list(stream_ids),
        "compose": dict(compose),
        "publish": dict(publish),
        "buffer": dict(buffer),
        "failure_reason": failure_reason,
        "operator_hints": list(operator_hints),
    }


def _not_run_compose_summary(
    env: Mapping[str, str],
    options: GeneratedIngestOptions,
) -> dict[str, object]:
    return {
        "status": STATUS_NOT_RUN,
        "command": build_compose_command(env, build=options.compose_build),
        "services": list(COMPOSE_SERVICES),
        "profiles": list(COMPOSE_PROFILES),
        "cwd": str(PROJECT_DIR),
        "timeout_seconds": options.compose_timeout_seconds,
        "returncode": None,
        "stdout": "",
        "stderr": "",
        "failure_reason": None,
    }


def _not_run_summary(reason: str) -> dict[str, object]:
    return {
        "status": STATUS_NOT_RUN,
        "reason": reason,
        "failure_reason": None,
    }


def _summarize_media_smoke(result: object) -> dict[str, object]:
    publish_results = tuple(getattr(result, "publish_results", ()) or ())
    return {
        "status": STATUS_PASSED,
        "summaries": _jsonable(getattr(result, "summaries", None)),
        "compose_command": _optional_command(getattr(result, "compose_command", None)),
        "published_stream_ids": [
            str(getattr(item, "stream_id", "")) for item in publish_results
        ],
        "streams": [
            {
                "stream_id": str(getattr(item, "stream_id", "")),
                "url": getattr(item, "url", None),
                "command": list(getattr(item, "command", ()) or ()),
                "returncode": getattr(item, "returncode", None),
                "stdout": _trim_output(str(getattr(item, "stdout", "") or "")),
                "stderr": _trim_output(str(getattr(item, "stderr", "") or "")),
            }
            for item in publish_results
        ],
        "failure_reason": None,
    }


def _summarize_buffer(
    result: object | None,
    *,
    status: str,
    attempts: int,
    duration_seconds: float,
    timeout_seconds: float,
    poll_interval_seconds: float,
    failure_reason: str | None,
    last_error: str | None,
) -> dict[str, object]:
    streams = tuple(getattr(result, "streams", ()) or ()) if result is not None else ()
    ready_streams = (
        tuple(getattr(result, "ready_streams", ()) or ()) if result is not None else ()
    )
    return {
        "status": status,
        "attempts": attempts,
        "duration_seconds": duration_seconds,
        "timeout_seconds": timeout_seconds,
        "poll_interval_seconds": poll_interval_seconds,
        "buffer_root": getattr(result, "buffer_root", None) if result is not None else None,
        "ready_streams": [str(stream_id) for stream_id in ready_streams],
        "streams": [
            {
                "stream_id": str(getattr(stream, "stream_id", "")),
                "segment_count": getattr(stream, "segment_count", None),
                "latest_segment": _jsonable(getattr(stream, "latest_segment", None)),
                "clip_status": getattr(stream, "clip_status", None),
                "clip_media_uri": getattr(stream, "clip_media_uri", None),
                "clip_reason": getattr(stream, "clip_reason", None),
                "segment_uris": list(getattr(stream, "segment_uris", ()) or ()),
            }
            for stream in streams
        ],
        "failure_reason": failure_reason,
        "last_error": last_error,
    }


def _runtime_env(env: Mapping[str, str], stream_ids: Sequence[str]) -> dict[str, str]:
    runtime_env = dict(env)
    stream_list = ",".join(stream_ids)
    runtime_env["SMOKE_SKIP_COMPOSE"] = "true"
    runtime_env["SMOKE_SKIP_PUBLISH"] = "false"
    runtime_env["SMOKE_STREAM_IDS"] = stream_list
    runtime_env["SMOKE_PUBLISH_STREAMS"] = stream_list
    runtime_env["SMOKE_BUFFER_STREAM_IDS"] = stream_list
    runtime_env.setdefault("SMOKE_PUBLISH_SECONDS", "8")
    runtime_env.setdefault("SMOKE_PUBLISH_TIMEOUT_SECONDS", "20")
    runtime_env.setdefault("SMOKE_READY_TIMEOUT_SECONDS", "30")
    if "LOOKBACK_BUFFER_DIR" not in runtime_env and runtime_env.get(
        "LOOKBACK_BUFFER_HOST_DIR"
    ):
        runtime_env["LOOKBACK_BUFFER_DIR"] = runtime_env["LOOKBACK_BUFFER_HOST_DIR"]
    return runtime_env


def _operator_hints(status: str, failure_reason: str | None) -> tuple[str, ...]:
    if status == STATUS_SKIPPED:
        return (
            "Pass --run or set GENERATED_INGEST_CHECKPOINT_RUN=true to run the live Docker/FFmpeg checkpoint.",
            "Use --no-compose only when media-server and buffer-worker are already running.",
        )
    if status == STATUS_PASSED:
        return ()

    reason = (failure_reason or "").lower()
    hints = [
        "Inspect docker compose logs --tail=100 media-server buffer-worker from ai-stream-director/.",
        "Verify Docker is running, the compose plugin is installed, and SRS ports 1935 and 1985 are available.",
        "Confirm LOOKBACK_BUFFER_HOST_DIR and LOOKBACK_BUFFER_DIR point at the same writable Linux buffer path.",
    ]
    if "buffer" in reason or "metadata" in reason or "resolvable" in reason:
        hints.append(
            "Increase SMOKE_PUBLISH_SECONDS or GENERATED_INGEST_BUFFER_READY_TIMEOUT_SECONDS on slow hosts."
        )
    if "ffmpeg" in reason or "publish" in reason:
        hints.append(
            "Verify ffmpeg is installed on the host and the generated RTMP URL matches the SRS bind address."
        )
    return tuple(hints)


def _stream_ids_from_env(env: Mapping[str, str]) -> tuple[str, ...]:
    for name in (
        "GENERATED_INGEST_STREAM_IDS",
        "SMOKE_STREAM_IDS",
        "SMOKE_PUBLISH_STREAMS",
    ):
        value = env.get(name)
        if value is not None:
            return _stream_ids_from_arg(value)
    return DEFAULT_STREAM_IDS


def _stream_ids_from_arg(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _optional_command(command: object) -> list[str] | None:
    if command is None:
        return None
    return [str(part) for part in command]  # type: ignore[iteration-over-annotated-type]


def _duration_since(started_at: float, clock: Callable[[], float]) -> float:
    return round(max(0.0, clock() - started_at), 6)


def _jsonable(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, set):
        return sorted(_jsonable(item) for item in value)
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def _completed_output(result: subprocess.CompletedProcess[str]) -> str:
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    return output.strip() or f"exit code {result.returncode}"


def _trim_output(value: str, *, limit: int = 2000) -> str:
    if len(value) <= limit:
        return value
    return value[-limit:]


def _env_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    value = env.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_float(env: Mapping[str, str], name: str, default: float) -> float:
    value = env.get(name)
    if value is None or not value.strip():
        return default
    return float(value)


def _load_media_smoke() -> MediaSmokeCallable:
    module = _import_script_module("smoke_media_server")
    return module.smoke_media_server


def _load_buffer_inspect() -> BufferInspectCallable:
    module = _import_script_module("smoke_buffer_worker")
    return module.inspect_buffer


def _load_buffer_assert_ready() -> BufferAssertCallable:
    module = _import_script_module("smoke_buffer_worker")
    return module.assert_any_ready


def _import_script_module(module_name: str) -> Any:
    try:
        return importlib.import_module(f"scripts.{module_name}")
    except ModuleNotFoundError as exc:
        if exc.name not in {"scripts", f"scripts.{module_name}"}:
            raise
        return importlib.import_module(module_name)


if __name__ == "__main__":
    raise SystemExit(main())
