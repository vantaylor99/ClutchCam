"""Opt-in Docker Compose checkpoint for generated RTMP ingest and lookback clips."""

from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
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
DIAGNOSTIC_LOG_TAIL = 100
OUTPUT_LIMIT = 4000

STATUS_PASSED = "passed"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"
STATUS_NOT_RUN = "not_run"

RunCallable = Callable[..., subprocess.CompletedProcess[str]]
MediaSmokeCallable = Callable[..., object]
BufferInspectCallable = Callable[..., object]
BufferAssertCallable = Callable[[object], None]
WritablePathProbe = Callable[[Path], None]


@dataclass(frozen=True)
class GeneratedIngestOptions:
    run: bool = False
    stream_ids: tuple[str, ...] = DEFAULT_STREAM_IDS
    skip_compose: bool = False
    compose_build: bool = True
    preflight_timeout_seconds: float = 10.0
    compose_timeout_seconds: float = 120.0
    compose_ready_timeout_seconds: float = 30.0
    compose_poll_interval_seconds: float = 1.0
    diagnostic_timeout_seconds: float = 10.0
    buffer_ready_timeout_seconds: float = 30.0
    buffer_poll_interval_seconds: float = 1.0


def run_generated_ingest_checkpoint(
    env: Mapping[str, str] = os.environ,
    *,
    options: GeneratedIngestOptions | None = None,
    run: RunCallable = subprocess.run,
    probe_writable_path: WritablePathProbe | None = None,
    media_smoke: MediaSmokeCallable | None = None,
    buffer_inspect: BufferInspectCallable | None = None,
    buffer_assert_ready: BufferAssertCallable | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, object]:
    selected_options = options or options_from_env(env)
    started_at = clock()
    stream_ids = selected_options.stream_ids

    preflight_summary = _not_run_summary("live preflight has not run")
    compose_summary = _not_run_compose_summary(env, selected_options)
    publish_summary: dict[str, object] = _not_run_summary(
        "generated FFmpeg publish has not run"
    )
    buffer_summary: dict[str, object] = _not_run_summary(
        "buffer metadata inspection has not run"
    )
    diagnostics_summary = _not_run_summary(
        "failure diagnostics are collected only for live failures"
    )

    if not selected_options.run:
        return _checkpoint_report(
            status=STATUS_SKIPPED,
            duration_seconds=_duration_since(started_at, clock),
            stream_ids=stream_ids,
            preflight=preflight_summary,
            compose=compose_summary,
            publish=publish_summary,
            buffer=buffer_summary,
            diagnostics=diagnostics_summary,
            failure_reason=None,
            operator_hints=_operator_hints(
                STATUS_SKIPPED,
                "pass --run or set GENERATED_INGEST_CHECKPOINT_RUN=true",
            ),
        )

    compose_env = _compose_env(env)
    preflight_summary = _run_preflight(
        env,
        selected_options,
        run=run,
        probe_writable_path=probe_writable_path or _probe_writable_path,
    )
    if preflight_summary["status"] == STATUS_FAILED:
        return _failed_checkpoint_report(
            started_at=started_at,
            clock=clock,
            env=compose_env,
            options=selected_options,
            stream_ids=stream_ids,
            preflight=preflight_summary,
            compose=compose_summary,
            publish=publish_summary,
            buffer=buffer_summary,
            failure_reason=str(preflight_summary["failure_reason"]),
            run=run,
        )

    compose_summary = _run_compose_services(
        compose_env,
        selected_options,
        run=run,
        sleep=sleep,
        clock=clock,
    )
    if compose_summary["status"] == STATUS_FAILED:
        return _failed_checkpoint_report(
            started_at=started_at,
            clock=clock,
            env=compose_env,
            options=selected_options,
            stream_ids=stream_ids,
            preflight=preflight_summary,
            compose=compose_summary,
            publish=publish_summary,
            buffer=buffer_summary,
            failure_reason=str(compose_summary["failure_reason"]),
            run=run,
        )

    runtime_env = _runtime_env(env, stream_ids)
    try:
        media_result = (media_smoke or _load_media_smoke())(
            runtime_env,
            stream_ids=stream_ids,
        )
    except Exception as exc:
        detail = _redact_exception(exc, runtime_env)
        failure_reason = (
            "Generated RTMP publish or SRS readiness failed: "
            f"{detail}"
        )
        publish_summary = {
            "status": STATUS_FAILED,
            "failure_reason": failure_reason,
            "summaries": None,
            "streams": [],
            "published_stream_ids": [],
        }
        return _failed_checkpoint_report(
            started_at=started_at,
            clock=clock,
            env=compose_env,
            options=selected_options,
            stream_ids=stream_ids,
            preflight=preflight_summary,
            compose=compose_summary,
            publish=publish_summary,
            buffer=buffer_summary,
            failure_reason=failure_reason,
            run=run,
        )

    publish_summary = _summarize_media_smoke(media_result, runtime_env)
    buffer_summary = _wait_for_buffer_ready(
        runtime_env,
        stream_ids=stream_ids,
        timeout_seconds=selected_options.buffer_ready_timeout_seconds,
        poll_interval_seconds=selected_options.buffer_poll_interval_seconds,
        inspect_buffer=buffer_inspect or _load_buffer_inspect(),
        assert_ready=buffer_assert_ready or _assert_requested_streams_ready(stream_ids),
        sleep=sleep,
        clock=clock,
    )
    if buffer_summary["status"] != "ready":
        failure_reason = str(buffer_summary["failure_reason"])
        return _failed_checkpoint_report(
            started_at=started_at,
            clock=clock,
            env=compose_env,
            options=selected_options,
            stream_ids=stream_ids,
            preflight=preflight_summary,
            compose=compose_summary,
            publish=publish_summary,
            buffer=buffer_summary,
            failure_reason=failure_reason,
            run=run,
        )

    return _checkpoint_report(
        status=STATUS_PASSED,
        duration_seconds=_duration_since(started_at, clock),
        stream_ids=stream_ids,
        preflight=preflight_summary,
        compose=compose_summary,
        publish=publish_summary,
        buffer=buffer_summary,
        diagnostics=diagnostics_summary,
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
        preflight_timeout_seconds=(
            args.preflight_timeout_seconds
            if args.preflight_timeout_seconds is not None
            else base_options.preflight_timeout_seconds
        ),
        compose_timeout_seconds=(
            args.compose_timeout_seconds
            if args.compose_timeout_seconds is not None
            else base_options.compose_timeout_seconds
        ),
        compose_ready_timeout_seconds=(
            args.compose_ready_timeout_seconds
            if args.compose_ready_timeout_seconds is not None
            else base_options.compose_ready_timeout_seconds
        ),
        compose_poll_interval_seconds=(
            args.compose_poll_interval_seconds
            if args.compose_poll_interval_seconds is not None
            else base_options.compose_poll_interval_seconds
        ),
        diagnostic_timeout_seconds=(
            args.diagnostic_timeout_seconds
            if args.diagnostic_timeout_seconds is not None
            else base_options.diagnostic_timeout_seconds
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
        preflight_timeout_seconds=_env_float(
            env,
            "GENERATED_INGEST_PREFLIGHT_TIMEOUT_SECONDS",
            10.0,
        ),
        compose_timeout_seconds=_env_float(
            env,
            "GENERATED_INGEST_COMPOSE_TIMEOUT_SECONDS",
            120.0,
        ),
        compose_ready_timeout_seconds=_env_float(
            env,
            "GENERATED_INGEST_COMPOSE_READY_TIMEOUT_SECONDS",
            30.0,
        ),
        compose_poll_interval_seconds=_env_float(
            env,
            "GENERATED_INGEST_COMPOSE_POLL_SECONDS",
            1.0,
        ),
        diagnostic_timeout_seconds=_env_float(
            env,
            "GENERATED_INGEST_DIAGNOSTIC_TIMEOUT_SECONDS",
            10.0,
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
    command = _compose_prefix(env)
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
        "--preflight-timeout-seconds",
        type=float,
        help="Timeout for each external preflight command. Defaults to env or 10 seconds.",
    )
    parser.add_argument(
        "--compose-timeout-seconds",
        type=float,
        help="Timeout for docker compose up. Defaults to env or 120 seconds.",
    )
    parser.add_argument(
        "--compose-ready-timeout-seconds",
        type=float,
        help="Time to wait for required Compose services. Defaults to env or 30 seconds.",
    )
    parser.add_argument(
        "--compose-poll-interval-seconds",
        type=float,
        help="Polling interval for Compose service readiness. Defaults to env or 1 second.",
    )
    parser.add_argument(
        "--diagnostic-timeout-seconds",
        type=float,
        help="Timeout for each failure diagnostic command. Defaults to env or 10 seconds.",
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


def _run_preflight(
    env: Mapping[str, str],
    options: GeneratedIngestOptions,
    *,
    run: RunCallable,
    probe_writable_path: WritablePathProbe,
) -> dict[str, object]:
    docker = env.get("DOCKER_EXECUTABLE", "docker")
    ffmpeg = env.get("FFMPEG_EXECUTABLE", "ffmpeg")
    buffer_path = _host_buffer_path(env)
    requirements = [
        _run_preflight_command(
            "docker_engine",
            [docker, "info", "--format", "{{json .ServerVersion}}"],
            "Docker Engine is not accessible",
            env,
            timeout_seconds=options.preflight_timeout_seconds,
            run=run,
        ),
        _run_preflight_command(
            "docker_compose",
            [docker, "compose", "version", "--short"],
            "Docker Compose plugin is not available",
            env,
            timeout_seconds=options.preflight_timeout_seconds,
            run=run,
        ),
        _run_preflight_command(
            "host_ffmpeg",
            [ffmpeg, "-version"],
            "Host FFmpeg is not available",
            env,
            timeout_seconds=options.preflight_timeout_seconds,
            run=run,
        ),
        _run_path_preflight(buffer_path, probe_writable_path, env),
    ]
    failed = [
        str(requirement["name"])
        for requirement in requirements
        if requirement["status"] == STATUS_FAILED
    ]
    failure_reason = None
    if failed:
        details = "; ".join(
            str(requirement["failure_reason"])
            for requirement in requirements
            if requirement["status"] == STATUS_FAILED
        )
        failure_reason = (
            f"Preflight requirement failed ({', '.join(failed)}): {details}"
        )
    return {
        "status": STATUS_FAILED if failed else STATUS_PASSED,
        "timeout_seconds": options.preflight_timeout_seconds,
        "requirements": requirements,
        "failed_requirements": failed,
        "failure_reason": failure_reason,
    }


def _run_preflight_command(
    name: str,
    command: Sequence[str],
    failure_prefix: str,
    env: Mapping[str, str],
    *,
    timeout_seconds: float,
    run: RunCallable,
) -> dict[str, object]:
    result = _run_bounded_command(
        command,
        env,
        timeout_seconds=timeout_seconds,
        run=run,
    )
    status = STATUS_PASSED if result["returncode"] == 0 else STATUS_FAILED
    detail = _command_failure_detail(result)
    return {
        "name": name,
        "status": status,
        "command": list(command),
        "timeout_seconds": timeout_seconds,
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "failure_reason": (
            None if status == STATUS_PASSED else f"{failure_prefix}: {detail}"
        ),
    }


def _run_path_preflight(
    path: Path,
    probe_writable_path: WritablePathProbe,
    env: Mapping[str, str],
) -> dict[str, object]:
    try:
        probe_writable_path(path)
    except Exception as exc:
        detail = _redact_exception(exc, env)
        return {
            "name": "host_buffer_path",
            "status": STATUS_FAILED,
            "path": path.as_posix(),
            "failure_reason": f"Host buffer path is not writable: {detail}",
        }
    return {
        "name": "host_buffer_path",
        "status": STATUS_PASSED,
        "path": path.as_posix(),
        "failure_reason": None,
    }


def _run_compose_services(
    env: Mapping[str, str],
    options: GeneratedIngestOptions,
    *,
    run: RunCallable,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> dict[str, object]:
    startup_status = STATUS_SKIPPED if options.skip_compose else STATUS_PASSED
    command = None
    returncode = None
    stdout = ""
    stderr = ""

    if options.skip_compose:
        reason = "targeting already-running Compose services"
    else:
        reason = None
        command = build_compose_command(env, build=options.compose_build)
        result = _run_bounded_command(
            command,
            env,
            timeout_seconds=options.compose_timeout_seconds,
            run=run,
        )
        returncode = result["returncode"]
        stdout = str(result["stdout"])
        stderr = str(result["stderr"])
        if returncode != 0:
            return {
                "status": STATUS_FAILED,
                "startup_status": STATUS_FAILED,
                "command": command,
                "services": list(COMPOSE_SERVICES),
                "profiles": list(COMPOSE_PROFILES),
                "cwd": str(PROJECT_DIR),
                "timeout_seconds": options.compose_timeout_seconds,
                "returncode": returncode,
                "stdout": stdout,
                "stderr": stderr,
                "service_state": _not_run_summary(
                    "Compose startup did not complete successfully"
                ),
                "failure_reason": (
                    "Docker Compose failed while starting generated-ingest services: "
                    f"{_command_failure_detail(result)}"
                ),
            }

    service_state = _wait_for_compose_ready(
        env,
        timeout_seconds=options.compose_ready_timeout_seconds,
        poll_interval_seconds=options.compose_poll_interval_seconds,
        command_timeout_seconds=options.preflight_timeout_seconds,
        run=run,
        sleep=sleep,
        clock=clock,
    )
    return {
        "status": service_state["status"],
        "startup_status": startup_status,
        "command": command,
        "services": list(COMPOSE_SERVICES),
        "profiles": list(COMPOSE_PROFILES),
        "cwd": str(PROJECT_DIR),
        "timeout_seconds": options.compose_timeout_seconds,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "service_state": service_state,
        "failure_reason": service_state["failure_reason"],
        "reason": reason,
    }


def _wait_for_compose_ready(
    env: Mapping[str, str],
    *,
    timeout_seconds: float,
    poll_interval_seconds: float,
    command_timeout_seconds: float,
    run: RunCallable,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> dict[str, object]:
    started_at = clock()
    deadline = started_at + _finite_nonnegative(timeout_seconds)
    attempts = 0
    last_services: dict[str, dict[str, object]] = {}
    last_reason = "required services were not reported"
    command = _compose_state_command(env)
    last_result: dict[str, object] = {
        "returncode": None,
        "stdout": "",
        "stderr": "",
        "error": None,
    }

    while True:
        attempts += 1
        now = clock()
        remaining_seconds = max(0.0, deadline - now)
        attempt_timeout_seconds = min(
            _bounded_command_timeout(command_timeout_seconds),
            max(0.1, remaining_seconds),
        )
        last_result = _run_bounded_command(
            command,
            env,
            timeout_seconds=attempt_timeout_seconds,
            run=run,
        )
        if last_result["returncode"] != 0:
            return {
                "status": STATUS_FAILED,
                "command": command,
                "attempts": attempts,
                "duration_seconds": _duration_since(started_at, clock),
                "timeout_seconds": timeout_seconds,
                "poll_interval_seconds": poll_interval_seconds,
                "services": last_services,
                "returncode": last_result["returncode"],
                "stdout": last_result["stdout"],
                "stderr": last_result["stderr"],
                "failure_reason": (
                    "Docker Compose service-state query failed: "
                    f"{_command_failure_detail(last_result)}"
                ),
            }
        try:
            last_services = _parse_compose_service_state(
                str(last_result["stdout"])
            )
        except ValueError as exc:
            return {
                "status": STATUS_FAILED,
                "command": command,
                "attempts": attempts,
                "duration_seconds": _duration_since(started_at, clock),
                "timeout_seconds": timeout_seconds,
                "poll_interval_seconds": poll_interval_seconds,
                "services": {},
                "returncode": last_result["returncode"],
                "stdout": last_result["stdout"],
                "stderr": last_result["stderr"],
                "failure_reason": f"Could not parse Docker Compose service state: {exc}",
            }

        readiness, last_reason = _compose_readiness(last_services)
        if readiness == "ready":
            return {
                "status": STATUS_PASSED,
                "command": command,
                "attempts": attempts,
                "duration_seconds": _duration_since(started_at, clock),
                "timeout_seconds": timeout_seconds,
                "poll_interval_seconds": poll_interval_seconds,
                "services": last_services,
                "returncode": last_result["returncode"],
                "stdout": last_result["stdout"],
                "stderr": last_result["stderr"],
                "failure_reason": None,
            }
        if readiness == "failed":
            break

        now = clock()
        if now >= deadline:
            break
        sleep(min(max(0.1, poll_interval_seconds), deadline - now))

    return {
        "status": STATUS_FAILED,
        "command": command,
        "attempts": attempts,
        "duration_seconds": _duration_since(started_at, clock),
        "timeout_seconds": timeout_seconds,
        "poll_interval_seconds": poll_interval_seconds,
        "services": last_services,
        "returncode": last_result["returncode"],
        "stdout": last_result["stdout"],
        "stderr": last_result["stderr"],
        "failure_reason": f"Docker Compose services are not ready: {last_reason}",
    }


def _parse_compose_service_state(value: str) -> dict[str, dict[str, object]]:
    stripped = value.strip()
    if not stripped:
        return {}
    records: list[object]
    try:
        payload = json.loads(stripped)
        if isinstance(payload, list):
            records = payload
        elif isinstance(payload, Mapping):
            records = [payload]
        else:
            raise ValueError("expected a JSON object, array, or JSON-lines records")
    except json.JSONDecodeError:
        try:
            records = [json.loads(line) for line in stripped.splitlines() if line.strip()]
        except json.JSONDecodeError as exc:
            raise ValueError(str(exc)) from exc
    if any(not isinstance(record, Mapping) for record in records):
        raise ValueError("Compose service-state records must be JSON objects")

    services: dict[str, dict[str, object]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            continue
        service = str(record.get("Service", "") or "")
        if service not in COMPOSE_SERVICES:
            continue
        services[service] = {
            "name": record.get("Name"),
            "state": record.get("State"),
            "health": record.get("Health"),
            "status": record.get("Status"),
            "exit_code": record.get("ExitCode"),
        }
    return services


def _compose_readiness(
    services: Mapping[str, Mapping[str, object]],
) -> tuple[str, str]:
    missing = [service for service in COMPOSE_SERVICES if service not in services]
    if missing:
        return "pending", f"missing services: {', '.join(missing)}"

    pending: list[str] = []
    for service in COMPOSE_SERVICES:
        details = services[service]
        state = str(details.get("state") or "").strip().lower()
        health = str(details.get("health") or "").strip().lower()
        status = str(details.get("status") or "").strip().lower()
        terminal_status = any(
            marker in status
            for marker in ("exited", "dead", "removing", "restarting")
        )
        if state in {"exited", "dead", "removing", "restarting"} or terminal_status:
            return "failed", f"{service} state={state or 'unknown'} status={status or 'unknown'}"
        if health == "unhealthy":
            return "failed", f"{service} health=unhealthy"
        if state != "running":
            pending.append(f"{service} state={state or 'unknown'}")
        elif health in {"starting", "initializing"}:
            pending.append(f"{service} health={health}")
        elif health not in {"", "healthy"}:
            pending.append(f"{service} health={health}")
    if pending:
        return "pending", "; ".join(pending)
    return "ready", ""


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
    deadline = started_at + _finite_nonnegative(timeout_seconds)
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
            last_error = _redact_exception(exc, env)

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
    preflight: Mapping[str, object],
    compose: Mapping[str, object],
    publish: Mapping[str, object],
    buffer: Mapping[str, object],
    diagnostics: Mapping[str, object],
    failure_reason: str | None,
    operator_hints: Sequence[str],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "checkpoint": CHECKPOINT_NAME,
        "status": status,
        "duration_seconds": duration_seconds,
        "stream_ids": list(stream_ids),
        "preflight": dict(preflight),
        "compose": dict(compose),
        "publish": dict(publish),
        "buffer": dict(buffer),
        "diagnostics": dict(diagnostics),
        "failure_reason": failure_reason,
        "operator_hints": list(operator_hints),
    }


def _failed_checkpoint_report(
    *,
    started_at: float,
    clock: Callable[[], float],
    env: Mapping[str, str],
    options: GeneratedIngestOptions,
    stream_ids: Sequence[str],
    preflight: Mapping[str, object],
    compose: Mapping[str, object],
    publish: Mapping[str, object],
    buffer: Mapping[str, object],
    failure_reason: str,
    run: RunCallable,
) -> dict[str, object]:
    try:
        diagnostics = _collect_failure_diagnostics(
            env,
            timeout_seconds=options.diagnostic_timeout_seconds,
            run=run,
        )
    except Exception as exc:
        detail = _redact_exception(exc, env)
        diagnostics = {
            "status": STATUS_FAILED,
            "timeout_seconds": options.diagnostic_timeout_seconds,
            "log_tail": DIAGNOSTIC_LOG_TAIL,
            "service_state": _not_run_summary(
                "failure diagnostic collection raised an exception"
            ),
            "recent_logs": _not_run_summary(
                "failure diagnostic collection raised an exception"
            ),
            "failure_reason": (
                "Failure diagnostics could not be collected: "
                f"{detail}"
            ),
        }
    return _checkpoint_report(
        status=STATUS_FAILED,
        duration_seconds=_duration_since(started_at, clock),
        stream_ids=stream_ids,
        preflight=preflight,
        compose=compose,
        publish=publish,
        buffer=buffer,
        diagnostics=diagnostics,
        failure_reason=failure_reason,
        operator_hints=_operator_hints(STATUS_FAILED, failure_reason),
    )


def _collect_failure_diagnostics(
    env: Mapping[str, str],
    *,
    timeout_seconds: float,
    run: RunCallable,
) -> dict[str, object]:
    state = _run_diagnostic_command(
        "service_state",
        _compose_state_command(env),
        env,
        timeout_seconds=timeout_seconds,
        run=run,
    )
    logs = _run_diagnostic_command(
        "recent_logs",
        [
            *_compose_prefix(env),
            "logs",
            "--no-color",
            f"--tail={DIAGNOSTIC_LOG_TAIL}",
            *COMPOSE_SERVICES,
        ],
        env,
        timeout_seconds=timeout_seconds,
        run=run,
    )
    status = (
        STATUS_PASSED
        if state["status"] == STATUS_PASSED and logs["status"] == STATUS_PASSED
        else STATUS_FAILED
    )
    return {
        "status": status,
        "timeout_seconds": timeout_seconds,
        "log_tail": DIAGNOSTIC_LOG_TAIL,
        "service_state": state,
        "recent_logs": logs,
        "failure_reason": (
            None
            if status == STATUS_PASSED
            else "One or more Compose diagnostic commands failed."
        ),
    }


def _run_diagnostic_command(
    name: str,
    command: Sequence[str],
    env: Mapping[str, str],
    *,
    timeout_seconds: float,
    run: RunCallable,
) -> dict[str, object]:
    result = _run_bounded_command(
        command,
        env,
        timeout_seconds=timeout_seconds,
        run=run,
    )
    status = STATUS_PASSED if result["returncode"] == 0 else STATUS_FAILED
    return {
        "name": name,
        "status": status,
        "command": list(command),
        "timeout_seconds": timeout_seconds,
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "failure_reason": (
            None
            if status == STATUS_PASSED
            else f"Diagnostic command failed: {_command_failure_detail(result)}"
        ),
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
        "service_state": _not_run_summary("Compose services have not been inspected"),
        "failure_reason": None,
    }


def _not_run_summary(reason: str) -> dict[str, object]:
    return {
        "status": STATUS_NOT_RUN,
        "reason": reason,
        "failure_reason": None,
    }


def _summarize_media_smoke(
    result: object,
    env: Mapping[str, str],
) -> dict[str, object]:
    publish_results = tuple(getattr(result, "publish_results", ()) or ())
    return {
        "status": STATUS_PASSED,
        "summaries": _redact_jsonable(
            _jsonable(getattr(result, "summaries", None)),
            env,
        ),
        "compose_command": _redact_jsonable(
            _optional_command(getattr(result, "compose_command", None)),
            env,
        ),
        "published_stream_ids": [
            str(getattr(item, "stream_id", "")) for item in publish_results
        ],
        "streams": [
            {
                "stream_id": str(getattr(item, "stream_id", "")),
                "url": _redact_jsonable(getattr(item, "url", None), env),
                "command": _redact_jsonable(
                    list(getattr(item, "command", ()) or ()),
                    env,
                ),
                "returncode": getattr(item, "returncode", None),
                "stdout": _redact_output(
                    str(getattr(item, "stdout", "") or ""),
                    env,
                ),
                "stderr": _redact_output(
                    str(getattr(item, "stderr", "") or ""),
                    env,
                ),
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
    runtime_env["LOOKBACK_BUFFER_DIR"] = _host_buffer_path(env).as_posix()
    return runtime_env


def _compose_env(env: Mapping[str, str]) -> dict[str, str]:
    compose_env = dict(env)
    if compose_env.get("LOOKBACK_BUFFER_HOST_DIR"):
        compose_env["LOOKBACK_BUFFER_HOST_DIR"] = _host_buffer_path(env).as_posix()
    return compose_env


def _host_buffer_path(env: Mapping[str, str]) -> Path:
    value = (
        env.get("LOOKBACK_BUFFER_HOST_DIR")
        or env.get("LOOKBACK_BUFFER_DIR")
        or "/dev/shm/clutchcam"
    )
    path = Path(value).expanduser()
    if not path.is_absolute() and not (
        os.name == "nt" and _is_posix_root_path_on_windows(path)
    ):
        path = PROJECT_DIR / path
    return path


def _probe_writable_path(
    path: Path,
    *,
    platform_name: str | None = None,
) -> None:
    selected_platform = platform_name or os.name
    if selected_platform == "nt" and _is_posix_root_path_on_windows(path):
        raise OSError(
            "POSIX-root buffer paths are not host paths on Windows; set "
            "LOOKBACK_BUFFER_HOST_DIR to a Windows-accessible directory or "
            "run the checkpoint inside Linux/WSL"
        )
    path.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        prefix=".generated-ingest-probe-",
        dir=path,
    ) as probe:
        probe.write(b"probe")
        probe.flush()


def _compose_prefix(env: Mapping[str, str]) -> list[str]:
    command = [env.get("DOCKER_EXECUTABLE", "docker"), "compose"]
    for profile in COMPOSE_PROFILES:
        command.extend(["--profile", profile])
    return command


def _compose_state_command(env: Mapping[str, str]) -> list[str]:
    return [
        *_compose_prefix(env),
        "ps",
        "--all",
        "--format",
        "json",
        *COMPOSE_SERVICES,
    ]


def _run_bounded_command(
    command: Sequence[str],
    env: Mapping[str, str],
    *,
    timeout_seconds: float,
    run: RunCallable,
) -> dict[str, object]:
    try:
        result = run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=_bounded_command_timeout(timeout_seconds),
            cwd=str(PROJECT_DIR),
            env=dict(env),
        )
        return {
            "returncode": result.returncode,
            "stdout": _redact_output(result.stdout or "", env),
            "stderr": _redact_output(result.stderr or "", env),
            "error": None,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "returncode": None,
            "stdout": _redact_output(_exception_output(exc.stdout), env),
            "stderr": _redact_output(_exception_output(exc.stderr), env),
            "error": f"timed out after {timeout_seconds:g}s",
        }
    except Exception as exc:
        return {
            "returncode": None,
            "stdout": "",
            "stderr": "",
            "error": _redact_exception(exc, env),
        }


def _command_failure_detail(result: Mapping[str, object]) -> str:
    if result.get("error"):
        return str(result["error"])
    output = "\n".join(
        str(part) for part in (result.get("stdout"), result.get("stderr")) if part
    ).strip()
    return output or f"exit code {result.get('returncode')}"


def _exception_output(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value)


def _redact_output(
    value: str,
    env: Mapping[str, str],
    *,
    limit: int = OUTPUT_LIMIT,
) -> str:
    redacted = value
    for name, secret in env.items():
        if secret and _is_secret_name(name):
            redacted = redacted.replace(secret, "[REDACTED]")
    redacted = re.sub(
        r"(?i)([\"']?[A-Z0-9_]*(?:API_KEY|PASSWORD|TOKEN|SECRET)"
        r"[A-Z0-9_]*[\"']?\s*[=:]\s*)"
        r"(\"[^\"]*\"|'[^']*'|[^\s,;]+)",
        r"\1[REDACTED]",
        redacted,
    )
    redacted = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [REDACTED]", redacted)
    redacted = re.sub(
        r"(?i)([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@",
        r"\1[REDACTED]@",
        redacted,
    )
    return _trim_output(redacted, limit=limit)


def _is_secret_name(name: str) -> bool:
    upper = name.upper()
    return any(part in upper for part in ("API_KEY", "PASSWORD", "TOKEN", "SECRET"))


def _redact_exception(exc: Exception, env: Mapping[str, str]) -> str:
    return _redact_output(str(exc) or exc.__class__.__name__, env)


def _redact_jsonable(value: object, env: Mapping[str, str]) -> object:
    if isinstance(value, str):
        return _redact_output(value, env)
    if isinstance(value, Mapping):
        return {
            str(key): _redact_jsonable(item, env)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_jsonable(item, env) for item in value]
    return value


def _is_posix_root_path_on_windows(path: Path) -> bool:
    normalized = str(path).replace("\\", "/")
    return not path.drive and normalized.startswith("/")


def _finite_nonnegative(value: float) -> float:
    return value if math.isfinite(value) and value >= 0.0 else 0.0


def _bounded_command_timeout(value: float) -> float:
    return max(0.1, _finite_nonnegative(value))


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


def _assert_requested_streams_ready(stream_ids: Sequence[str]) -> BufferAssertCallable:
    expected_stream_ids = tuple(stream_ids)

    def assert_ready(result: object) -> None:
        streams = tuple(getattr(result, "streams", ()) or ())
        by_stream_id = {
            str(getattr(stream, "stream_id", "")): stream for stream in streams
        }
        failures: list[str] = []
        for stream_id in expected_stream_ids:
            stream = by_stream_id.get(stream_id)
            if stream is None:
                failures.append(f"{stream_id}=missing from buffer inspection")
                continue
            clip_status = str(getattr(stream, "clip_status", ""))
            if clip_status != "ready":
                clip_reason = str(getattr(stream, "clip_reason", "") or "")
                failures.append(f"{stream_id}={clip_status}: {clip_reason}")
                continue
            latest_segment = getattr(stream, "latest_segment", None)
            latest_exists = getattr(latest_segment, "exists", False)
            if not latest_exists:
                failures.append(f"{stream_id}=ready but latest segment is missing")
        if failures:
            buffer_root = getattr(result, "buffer_root", "<unknown>")
            raise RuntimeError(
                "Not all requested streams have resolvable clips under "
                f"{buffer_root}. " + "; ".join(failures)
            )

    return assert_ready


def _import_script_module(module_name: str) -> Any:
    try:
        return importlib.import_module(f"scripts.{module_name}")
    except ModuleNotFoundError as exc:
        if exc.name not in {"scripts", f"scripts.{module_name}"}:
            raise
        return importlib.import_module(module_name)


if __name__ == "__main__":
    raise SystemExit(main())
