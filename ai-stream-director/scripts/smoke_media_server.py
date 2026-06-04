"""Smoke SRS HTTP readiness and generated FFmpeg ingest commands."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable, Mapping, Sequence

import requests


DEFAULT_STREAM_IDS = ("player_1",)
DEFAULT_FREQUENCIES = {
    "player_1": 440,
    "player_2": 550,
    "player_3": 660,
    "player_4": 770,
}
SUMMARIES_PATH = "/api/v1/summaries"


class SmokeFailure(RuntimeError):
    """Raised when the media-server smoke cannot complete."""


@dataclass(frozen=True)
class HttpSmokeResult:
    url: str
    status_code: int
    payload_keys: tuple[str, ...]


@dataclass(frozen=True)
class PublishSmokeResult:
    stream_id: str
    url: str
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class MediaServerSmokeResult:
    summaries: HttpSmokeResult
    publish_results: tuple[PublishSmokeResult, ...]
    compose_command: tuple[str, ...] | None


def summaries_url_from_env(env: Mapping[str, str] = os.environ) -> str:
    explicit_url = env.get("SRS_SUMMARIES_URL")
    if explicit_url:
        return explicit_url

    api_url = env.get("SRS_HTTP_API_URL")
    if api_url:
        api_url = api_url.rstrip("/")
        if api_url.endswith(SUMMARIES_PATH):
            return api_url
        return f"{api_url}{SUMMARIES_PATH}"

    host = env.get("SRS_HTTP_API_HOST") or env.get("SRS_BIND_ADDR") or "127.0.0.1"
    if host == "0.0.0.0":
        host = "127.0.0.1"
    port = env.get("SRS_HTTP_API_PORT", "1985")
    return f"http://{_format_host(host)}:{port}{SUMMARIES_PATH}"


def build_compose_command(env: Mapping[str, str] = os.environ) -> list[str]:
    docker_executable = env.get("DOCKER_EXECUTABLE", "docker")
    service = env.get("SMOKE_MEDIA_SERVER_SERVICE", "media-server")
    profile = env.get("SMOKE_MEDIA_SERVER_PROFILE", "media-server").strip()
    command = [docker_executable, "compose"]
    if profile:
        command.extend(["--profile", profile])
    command.extend(["up", "-d", service])
    return command


def run_compose_up(
    env: Mapping[str, str] = os.environ,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[str, ...] | None:
    if _env_bool(env, "SMOKE_SKIP_COMPOSE", False):
        return None
    if not _env_bool(env, "SMOKE_START_COMPOSE", True):
        return None

    command = build_compose_command(env)
    timeout_seconds = _env_float(env, "SMOKE_COMPOSE_TIMEOUT_SECONDS", 60.0)
    try:
        result = run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise SmokeFailure(
            "Timed out starting SRS with Docker Compose after "
            f"{timeout_seconds:g}s."
        ) from exc

    if result.returncode != 0:
        raise SmokeFailure(
            "Docker Compose failed while starting SRS media-server: "
            f"{_completed_output(result)}"
        )
    return tuple(command)


def wait_for_summaries(
    url: str,
    *,
    ready_timeout_seconds: float,
    request_timeout_seconds: float,
    get: Callable[..., Any] = requests.get,
    sleep: Callable[[float], None] = time.sleep,
) -> HttpSmokeResult:
    deadline = time.monotonic() + ready_timeout_seconds
    last_error: Exception | None = None
    while True:
        try:
            return check_summaries(
                url,
                request_timeout_seconds=request_timeout_seconds,
                get=get,
            )
        except SmokeFailure as exc:
            last_error = exc
            if time.monotonic() >= deadline:
                break
            sleep(min(0.5, max(0.0, deadline - time.monotonic())))

    raise SmokeFailure(
        f"SRS summaries endpoint did not become ready at {url}: {last_error}"
    )


def check_summaries(
    url: str,
    *,
    request_timeout_seconds: float,
    get: Callable[..., Any] = requests.get,
) -> HttpSmokeResult:
    try:
        response = get(url, timeout=request_timeout_seconds)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        raise SmokeFailure(
            "SRS summaries check failed for "
            f"{url} with timeout {request_timeout_seconds:g}s: {exc}"
        ) from exc

    if not isinstance(payload, dict):
        raise SmokeFailure("SRS summaries response was not a JSON object.")

    return HttpSmokeResult(
        url=url,
        status_code=int(getattr(response, "status_code", 200)),
        payload_keys=tuple(sorted(str(key) for key in payload.keys())),
    )


def stream_ids_from_env(
    env: Mapping[str, str] = os.environ,
    *,
    default: Sequence[str] = DEFAULT_STREAM_IDS,
) -> tuple[str, ...]:
    value = env.get("SMOKE_PUBLISH_STREAMS")
    if value is None:
        value = env.get("SMOKE_STREAM_IDS")
    if value is None:
        return tuple(default)
    return tuple(part.strip() for part in value.split(",") if part.strip())


def build_ffmpeg_lavfi_command(
    stream_id: str,
    env: Mapping[str, str] = os.environ,
) -> list[str]:
    ffmpeg = env.get("FFMPEG_EXECUTABLE", "ffmpeg")
    host = env.get("SRS_RTMP_HOST") or env.get("SRS_BIND_ADDR") or "127.0.0.1"
    if host == "0.0.0.0":
        host = "127.0.0.1"
    port = env.get("SRS_RTMP_PORT", "1935")
    app = env.get("SRS_RTMP_APP", "live").strip("/")
    duration_seconds = _env_float(env, "SMOKE_PUBLISH_SECONDS", 5.0)
    video_source = env.get("SMOKE_VIDEO_LAVFI", "testsrc=size=1280x720:rate=30")
    frequency = env.get(
        f"SMOKE_AUDIO_FREQUENCY_{stream_id.upper()}",
        str(DEFAULT_FREQUENCIES.get(stream_id, 440)),
    )
    audio_source = env.get(
        f"SMOKE_AUDIO_LAVFI_{stream_id.upper()}",
        f"sine=frequency={frequency}:sample_rate=48000",
    )
    publish_url = build_rtmp_publish_url(host=host, port=port, app=app, stream_id=stream_id)

    return [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "warning",
        "-re",
        "-f",
        "lavfi",
        "-i",
        video_source,
        "-f",
        "lavfi",
        "-i",
        audio_source,
        "-t",
        _format_seconds(duration_seconds),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-tune",
        "zerolatency",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-f",
        "flv",
        publish_url,
    ]


def build_rtmp_publish_url(host: str, port: str, app: str, stream_id: str) -> str:
    return f"rtmp://{_format_host(host)}:{port}/{app.strip('/')}/{stream_id}"


def publish_streams(
    stream_ids: Sequence[str],
    env: Mapping[str, str] = os.environ,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[PublishSmokeResult, ...]:
    if _env_bool(env, "SMOKE_SKIP_PUBLISH", False):
        return ()

    publish_timeout_seconds = _env_float(env, "SMOKE_PUBLISH_TIMEOUT_SECONDS", 15.0)
    results: list[PublishSmokeResult] = []
    for stream_id in stream_ids:
        command = build_ffmpeg_lavfi_command(stream_id, env)
        try:
            result = run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=publish_timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise SmokeFailure(
                "Timed out publishing generated FFmpeg source for "
                f"{stream_id} after {publish_timeout_seconds:g}s."
            ) from exc

        publish_result = PublishSmokeResult(
            stream_id=stream_id,
            url=command[-1],
            command=tuple(command),
            returncode=result.returncode,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
        )
        if result.returncode != 0:
            raise SmokeFailure(
                f"FFmpeg generated-source publish failed for {stream_id}: "
                f"{_completed_output(result)}"
            )
        results.append(publish_result)

    return tuple(results)


def smoke_media_server(
    env: Mapping[str, str] = os.environ,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    get: Callable[..., Any] = requests.get,
    sleep: Callable[[float], None] = time.sleep,
    stream_ids: Sequence[str] | None = None,
) -> MediaServerSmokeResult:
    compose_command = run_compose_up(env, run=run)
    url = summaries_url_from_env(env)
    summaries = wait_for_summaries(
        url,
        ready_timeout_seconds=_env_float(env, "SMOKE_READY_TIMEOUT_SECONDS", 20.0),
        request_timeout_seconds=_env_float(env, "SMOKE_HTTP_TIMEOUT_SECONDS", 3.0),
        get=get,
        sleep=sleep,
    )
    publish_results = publish_streams(
        stream_ids if stream_ids is not None else stream_ids_from_env(env),
        env,
        run=run,
    )
    return MediaServerSmokeResult(
        summaries=summaries,
        publish_results=publish_results,
        compose_command=compose_command,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-compose", action="store_true")
    parser.add_argument("--no-publish", action="store_true")
    parser.add_argument("--streams", help="Comma-separated player stream IDs to publish.")
    args = parser.parse_args(argv)

    env = dict(os.environ)
    if args.no_compose:
        env["SMOKE_SKIP_COMPOSE"] = "true"
    if args.no_publish:
        env["SMOKE_SKIP_PUBLISH"] = "true"
    streams = None
    if args.streams is not None:
        streams = tuple(part.strip() for part in args.streams.split(",") if part.strip())

    try:
        result = smoke_media_server(env, stream_ids=streams)
    except SmokeFailure as exc:
        print(f"media-server smoke failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(asdict(result), indent=2, sort_keys=True))
    return 0


def _completed_output(result: subprocess.CompletedProcess[str]) -> str:
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    return output.strip() or f"exit code {result.returncode}"


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


def _format_seconds(value: float) -> str:
    formatted = f"{value:.3f}".rstrip("0").rstrip(".")
    return formatted or "0"


def _format_host(host: str) -> str:
    if ":" in host and not (host.startswith("[") and host.endswith("]")):
        return f"[{host}]"
    return host


if __name__ == "__main__":
    raise SystemExit(main())
