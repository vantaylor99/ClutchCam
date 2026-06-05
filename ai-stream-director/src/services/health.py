"""Health-check primitives for production service diagnostics."""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, TextIO
from urllib.parse import urlparse, urlunparse

from config import (
    AI_PROVIDER_OLLAMA,
    AI_PROVIDER_OPENAI_COMPATIBLE,
    AppConfig,
    get_config,
    redact_secrets,
)


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class HealthCheckError(RuntimeError):
    """Raised when a health-check adapter cannot evaluate a component."""


DEFAULT_HEALTH_TIMEOUT_SECONDS = 2.0
RUNTIME_HEALTH_TARGETS = (
    "media-server",
    "buffer-worker",
    "transcription-worker",
    "ai-endpoint",
    "orchestrator",
)


class HealthCheck(Protocol):
    """Evaluates one component and returns a health result."""

    def check(self) -> "HealthResult":
        """Return one health result."""


@dataclass(frozen=True)
class HealthResult:
    component: str
    status: HealthStatus
    message: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)
    duration_seconds: float = 0.0

    def __post_init__(self) -> None:
        component = self.component.strip()
        if not component:
            raise ValueError("Health result component is required.")
        if self.duration_seconds < 0:
            raise ValueError("Health duration cannot be negative.")
        object.__setattr__(self, "component", component)
        object.__setattr__(self, "details", dict(self.details))

    @classmethod
    def healthy(
        cls,
        component: str,
        message: str = "ok",
        *,
        details: Mapping[str, Any] | None = None,
        duration_seconds: float = 0.0,
    ) -> "HealthResult":
        return cls(
            component=component,
            status=HealthStatus.HEALTHY,
            message=message,
            details=details or {},
            duration_seconds=duration_seconds,
        )

    @classmethod
    def degraded(
        cls,
        component: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
        duration_seconds: float = 0.0,
    ) -> "HealthResult":
        return cls(
            component=component,
            status=HealthStatus.DEGRADED,
            message=message,
            details=details or {},
            duration_seconds=duration_seconds,
        )

    @classmethod
    def unhealthy(
        cls,
        component: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
        duration_seconds: float = 0.0,
    ) -> "HealthResult":
        return cls(
            component=component,
            status=HealthStatus.UNHEALTHY,
            message=message,
            details=details or {},
            duration_seconds=duration_seconds,
        )

    def to_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "component": self.component,
            "status": self.status.value,
            "message": self.message,
            "duration_seconds": self.duration_seconds,
        }
        if self.details:
            record["details"] = redact_secrets(dict(self.details))
        return record


@dataclass(frozen=True)
class HealthReport:
    status: HealthStatus
    results: tuple[HealthResult, ...]

    def to_record(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "results": [result.to_record() for result in self.results],
        }


class CallableHealthCheck:
    """Wraps a callable in consistent timing and exception handling."""

    def __init__(
        self,
        component: str,
        check: Callable[[], HealthResult],
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.component = component
        self._check = check
        self._clock = clock

    def check(self) -> HealthResult:
        started_at = self._clock()
        try:
            result = self._check()
        except Exception as exc:
            return HealthResult.unhealthy(
                self.component,
                f"Health check failed: {exc}",
                duration_seconds=max(0.0, self._clock() - started_at),
            )

        duration_seconds = max(0.0, self._clock() - started_at)
        return HealthResult(
            component=result.component,
            status=result.status,
            message=result.message,
            details=result.details,
            duration_seconds=duration_seconds,
        )


class RequiredValueHealthCheck:
    """Checks that a required config or environment value is present."""

    def __init__(self, component: str, name: str, value: object) -> None:
        self.component = component
        self.name = name
        self.value = value

    def check(self) -> HealthResult:
        value = "" if self.value is None else str(self.value).strip()
        if value:
            return HealthResult.healthy(
                self.component,
                f"{self.name} is configured.",
                details={"name": self.name},
            )
        return HealthResult.unhealthy(
            self.component,
            f"{self.name} is not configured.",
            details={"name": self.name},
        )


class HttpEndpointHealthCheck:
    """Checks a simple HTTP endpoint with injectable transport."""

    def __init__(
        self,
        component: str,
        url: str,
        *,
        timeout_seconds: float = 2.0,
        opener: Callable[..., object] = urllib.request.urlopen,
    ) -> None:
        self.component = component
        self.url = url
        self.timeout_seconds = timeout_seconds
        self._opener = opener

    def check(self) -> HealthResult:
        if not self.url.strip():
            return HealthResult.unhealthy(self.component, "Endpoint URL is blank.")

        response: object | None = None
        try:
            response = self._opener(self.url, timeout=self.timeout_seconds)
            status_code = int(getattr(response, "status", 200))
        except urllib.error.HTTPError as exc:
            status_code = int(exc.code)
        except (OSError, urllib.error.URLError, ValueError) as exc:
            return HealthResult.unhealthy(
                self.component,
                f"Endpoint check failed: {exc}",
                details={"url": self.url},
            )
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

        if 200 <= status_code < 300:
            return HealthResult.healthy(
                self.component,
                "Endpoint responded successfully.",
                details={"url": self.url, "status_code": status_code},
            )
        if 300 <= status_code < 500:
            return HealthResult.degraded(
                self.component,
                f"Endpoint returned status {status_code}.",
                details={"url": self.url, "status_code": status_code},
            )
        return HealthResult.unhealthy(
            self.component,
            f"Endpoint returned status {status_code}.",
            details={"url": self.url, "status_code": status_code},
        )


class ExecutableHealthCheck:
    """Checks that a configured executable can be resolved."""

    def __init__(
        self,
        component: str,
        name: str,
        executable: str,
        *,
        resolver: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self.component = component
        self.name = name
        self.executable = executable
        self._resolver = resolver

    def check(self) -> HealthResult:
        executable = self.executable.strip()
        if not executable:
            return HealthResult.unhealthy(
                self.component,
                f"{self.name} is not configured.",
                details={"name": self.name},
            )

        try:
            resolved_path = self._resolver(executable)
        except OSError as exc:
            return HealthResult.unhealthy(
                self.component,
                f"{self.name} lookup failed: {exc}",
                details={"name": self.name, "executable": executable},
            )

        if resolved_path is None:
            return HealthResult.unhealthy(
                self.component,
                f"{self.name} not found: {executable}",
                details={"name": self.name, "executable": executable},
            )

        return HealthResult.healthy(
            self.component,
            f"{self.name} is available.",
            details={
                "name": self.name,
                "executable": executable,
                "resolved_path": resolved_path,
            },
        )


class WritableDirectoryHealthCheck:
    """Checks that a runtime directory exists and accepts a bounded write probe."""

    def __init__(
        self,
        component: str,
        name: str,
        directory: str | Path,
        *,
        exists: Callable[[Path], bool] | None = None,
        is_dir: Callable[[Path], bool] | None = None,
        probe_writer: Callable[[Path], None] | None = None,
    ) -> None:
        self.component = component
        self.name = name
        self.directory_value = str(directory).strip()
        self.directory = Path(directory)
        self._exists = exists or (lambda path: path.exists())
        self._is_dir = is_dir or (lambda path: path.is_dir())
        self._probe_writer = probe_writer or _write_directory_probe

    def check(self) -> HealthResult:
        if not self.directory_value:
            return HealthResult.unhealthy(
                self.component,
                f"{self.name} is not configured.",
                details={"name": self.name},
            )

        try:
            if not self._exists(self.directory):
                return HealthResult.unhealthy(
                    self.component,
                    f"{self.name} does not exist: {self.directory}",
                    details={"name": self.name, "path": str(self.directory)},
                )
            if not self._is_dir(self.directory):
                return HealthResult.unhealthy(
                    self.component,
                    f"{self.name} is not a directory: {self.directory}",
                    details={"name": self.name, "path": str(self.directory)},
                )

            self._probe_writer(self.directory)
        except OSError as exc:
            return HealthResult.unhealthy(
                self.component,
                f"{self.name} is not writable: {exc}",
                details={"name": self.name, "path": str(self.directory)},
            )

        return HealthResult.healthy(
            self.component,
            f"{self.name} is writable.",
            details={"name": self.name, "path": str(self.directory)},
        )


class ConfiguredStreamInputsHealthCheck:
    """Checks that every configured runtime stream has a non-empty input URL."""

    def __init__(
        self,
        component: str,
        stream_input_urls: Mapping[str, str],
    ) -> None:
        self.component = component
        self.stream_input_urls = stream_input_urls

    def check(self) -> HealthResult:
        input_urls = {
            str(stream_id): str(url).strip()
            for stream_id, url in self.stream_input_urls.items()
        }
        if not input_urls:
            return HealthResult.unhealthy(
                self.component,
                "No stream input URLs are configured.",
            )

        missing_stream_ids = [
            stream_id for stream_id, url in sorted(input_urls.items()) if not url
        ]
        if missing_stream_ids:
            return HealthResult.unhealthy(
                self.component,
                "Missing input URLs for stream IDs: "
                + ", ".join(missing_stream_ids),
                details={"missing_stream_ids": missing_stream_ids},
            )

        return HealthResult.healthy(
            self.component,
            "Stream input URLs are configured.",
            details={"stream_ids": sorted(input_urls)},
        )


def run_health_checks(checks: Sequence[HealthCheck]) -> HealthReport:
    results = tuple(check.check() for check in checks)
    if any(result.status == HealthStatus.UNHEALTHY for result in results):
        status = HealthStatus.UNHEALTHY
    elif any(result.status == HealthStatus.DEGRADED for result in results):
        status = HealthStatus.DEGRADED
    else:
        status = HealthStatus.HEALTHY

    return HealthReport(status=status, results=results)


def build_runtime_health_checks(
    target: str,
    *,
    app_config: AppConfig | None = None,
    env: Mapping[str, str] | None = None,
    opener: Callable[..., object] = urllib.request.urlopen,
    ffmpeg_resolver: Callable[[str], str | None] = shutil.which,
    directory_exists: Callable[[Path], bool] | None = None,
    directory_is_dir: Callable[[Path], bool] | None = None,
    directory_probe_writer: Callable[[Path], None] | None = None,
) -> tuple[HealthCheck, ...]:
    """Build health checks for one runtime target without starting the target."""

    normalized_target = _normalize_target(target)
    if normalized_target == "media-server":
        return build_media_server_health_checks(env=env, opener=opener)
    if normalized_target == "buffer-worker":
        return build_buffer_worker_health_checks(
            app_config=app_config,
            ffmpeg_resolver=ffmpeg_resolver,
            directory_exists=directory_exists,
            directory_is_dir=directory_is_dir,
            directory_probe_writer=directory_probe_writer,
        )
    if normalized_target == "transcription-worker":
        return build_transcription_worker_health_checks(
            app_config=app_config,
            env=env,
            opener=opener,
            ffmpeg_resolver=ffmpeg_resolver,
            directory_exists=directory_exists,
            directory_is_dir=directory_is_dir,
            directory_probe_writer=directory_probe_writer,
        )
    if normalized_target == "ai-endpoint":
        return build_ai_endpoint_health_checks(
            app_config=app_config,
            env=env,
            opener=opener,
        )
    if normalized_target == "orchestrator":
        return build_orchestrator_health_checks(
            app_config=app_config,
            env=env,
            opener=opener,
            directory_exists=directory_exists,
            directory_is_dir=directory_is_dir,
            directory_probe_writer=directory_probe_writer,
        )

    expected = ", ".join(RUNTIME_HEALTH_TARGETS)
    raise ValueError(
        f"Unknown health target {target!r}. Expected one of: {expected}."
    )


def build_media_server_health_checks(
    *,
    env: Mapping[str, str] | None = None,
    opener: Callable[..., object] = urllib.request.urlopen,
) -> tuple[HealthCheck, ...]:
    env = _runtime_env(env)
    return (
        HttpEndpointHealthCheck(
            "media-server",
            _media_server_health_url(env),
            timeout_seconds=_health_timeout_seconds(env),
            opener=opener,
        ),
    )


def build_buffer_worker_health_checks(
    *,
    app_config: AppConfig | None = None,
    ffmpeg_resolver: Callable[[str], str | None] = shutil.which,
    directory_exists: Callable[[Path], bool] | None = None,
    directory_is_dir: Callable[[Path], bool] | None = None,
    directory_probe_writer: Callable[[Path], None] | None = None,
) -> tuple[HealthCheck, ...]:
    app_config = app_config or get_config()
    return (
        ConfiguredStreamInputsHealthCheck(
            "buffer-worker",
            app_config.lookback_input_urls,
        ),
        ExecutableHealthCheck(
            "buffer-worker",
            "FFMPEG_EXECUTABLE",
            app_config.ffmpeg_executable,
            resolver=ffmpeg_resolver,
        ),
        WritableDirectoryHealthCheck(
            "buffer-worker",
            "LOOKBACK_BUFFER_DIR",
            app_config.lookback_buffer_dir,
            exists=directory_exists,
            is_dir=directory_is_dir,
            probe_writer=directory_probe_writer,
        ),
    )


def build_transcription_worker_health_checks(
    *,
    app_config: AppConfig | None = None,
    env: Mapping[str, str] | None = None,
    opener: Callable[..., object] = urllib.request.urlopen,
    ffmpeg_resolver: Callable[[str], str | None] = shutil.which,
    directory_exists: Callable[[Path], bool] | None = None,
    directory_is_dir: Callable[[Path], bool] | None = None,
    directory_probe_writer: Callable[[Path], None] | None = None,
) -> tuple[HealthCheck, ...]:
    env = _runtime_env(env)
    app_config = app_config or get_config()
    return (
        ConfiguredStreamInputsHealthCheck(
            "transcription-worker",
            app_config.audio_input_urls,
        ),
        ExecutableHealthCheck(
            "transcription-worker",
            "FFMPEG_EXECUTABLE",
            app_config.ffmpeg_executable,
            resolver=ffmpeg_resolver,
        ),
        WritableDirectoryHealthCheck(
            "transcription-worker",
            "AUDIO_EXTRACT_DIR",
            app_config.audio_extract_dir,
            exists=directory_exists,
            is_dir=directory_is_dir,
            probe_writer=directory_probe_writer,
        ),
        HttpEndpointHealthCheck(
            "transcription-endpoint",
            _transcription_health_url(app_config, env),
            timeout_seconds=_health_timeout_seconds(env),
            opener=opener,
        ),
    )


def build_ai_endpoint_health_checks(
    *,
    app_config: AppConfig | None = None,
    env: Mapping[str, str] | None = None,
    opener: Callable[..., object] = urllib.request.urlopen,
) -> tuple[HealthCheck, ...]:
    env = _runtime_env(env)
    app_config = app_config or get_config()
    return (
        RequiredValueHealthCheck(
            "ai-endpoint",
            "GEMMA_API_URL",
            app_config.gemma_api_url,
        ),
        RequiredValueHealthCheck(
            "ai-endpoint",
            "GEMMA_MODEL",
            app_config.gemma_model,
        ),
        HttpEndpointHealthCheck(
            "ai-endpoint",
            _ai_health_url(app_config, env),
            timeout_seconds=_health_timeout_seconds(env),
            opener=opener,
        ),
    )


def build_orchestrator_health_checks(
    *,
    app_config: AppConfig | None = None,
    env: Mapping[str, str] | None = None,
    opener: Callable[..., object] = urllib.request.urlopen,
    directory_exists: Callable[[Path], bool] | None = None,
    directory_is_dir: Callable[[Path], bool] | None = None,
    directory_probe_writer: Callable[[Path], None] | None = None,
) -> tuple[HealthCheck, ...]:
    app_config = app_config or get_config()
    ai_checks = build_ai_endpoint_health_checks(
        app_config=app_config,
        env=env,
        opener=opener,
    )
    return (
        RequiredValueHealthCheck("orchestrator", "OBS_HOST", app_config.obs_host),
        CallableHealthCheck(
            "orchestrator",
            lambda: _port_health_result("orchestrator", "OBS_PORT", app_config.obs_port),
        ),
        WritableDirectoryHealthCheck(
            "orchestrator",
            "LOOKBACK_BUFFER_DIR",
            app_config.lookback_buffer_dir,
            exists=directory_exists,
            is_dir=directory_is_dir,
            probe_writer=directory_probe_writer,
        ),
        WritableDirectoryHealthCheck(
            "orchestrator",
            "AUDIO_EXTRACT_DIR",
            app_config.audio_extract_dir,
            exists=directory_exists,
            is_dir=directory_is_dir,
            probe_writer=directory_probe_writer,
        ),
        *ai_checks,
    )


def runtime_health_report(
    target: str,
    *,
    app_config: AppConfig | None = None,
    env: Mapping[str, str] | None = None,
    opener: Callable[..., object] = urllib.request.urlopen,
    ffmpeg_resolver: Callable[[str], str | None] = shutil.which,
    directory_exists: Callable[[Path], bool] | None = None,
    directory_is_dir: Callable[[Path], bool] | None = None,
    directory_probe_writer: Callable[[Path], None] | None = None,
) -> HealthReport:
    """Evaluate one runtime health target and convert setup errors into results."""

    component = _normalize_target(target) or "runtime-health"
    try:
        checks = build_runtime_health_checks(
            target,
            app_config=app_config,
            env=env,
            opener=opener,
            ffmpeg_resolver=ffmpeg_resolver,
            directory_exists=directory_exists,
            directory_is_dir=directory_is_dir,
            directory_probe_writer=directory_probe_writer,
        )
        return run_health_checks(checks)
    except Exception as exc:
        return HealthReport(
            status=HealthStatus.UNHEALTHY,
            results=(
                HealthResult.unhealthy(
                    component,
                    f"Health check setup failed: {exc}",
                ),
            ),
        )


def write_health_report(report: HealthReport, stream: TextIO) -> None:
    print(json.dumps(report.to_record(), sort_keys=True), file=stream, flush=True)


def health_report_exit_code(report: HealthReport) -> int:
    return 0 if report.status == HealthStatus.HEALTHY else 1


def run_runtime_healthcheck(
    target: str,
    *,
    app_config: AppConfig | None = None,
    env: Mapping[str, str] | None = None,
    opener: Callable[..., object] = urllib.request.urlopen,
    ffmpeg_resolver: Callable[[str], str | None] = shutil.which,
    directory_exists: Callable[[Path], bool] | None = None,
    directory_is_dir: Callable[[Path], bool] | None = None,
    directory_probe_writer: Callable[[Path], None] | None = None,
    stream: TextIO | None = None,
) -> int:
    report = runtime_health_report(
        target,
        app_config=app_config,
        env=env,
        opener=opener,
        ffmpeg_resolver=ffmpeg_resolver,
        directory_exists=directory_exists,
        directory_is_dir=directory_is_dir,
        directory_probe_writer=directory_probe_writer,
    )
    write_health_report(report, stream or sys.stdout)
    return health_report_exit_code(report)


def main(argv: Sequence[str] | None = None) -> int:
    args = tuple(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or args[0] in {"-h", "--help"}:
        targets = ", ".join(RUNTIME_HEALTH_TARGETS)
        print(
            f"Usage: python -m services.health <target>\nTargets: {targets}",
            file=sys.stderr,
        )
        return 0 if args and args[0] in {"-h", "--help"} else 2

    return run_runtime_healthcheck(args[0])


def _normalize_target(target: str) -> str:
    return target.strip().lower().replace("_", "-")


def _runtime_env(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if env is None else env


def _env_value(env: Mapping[str, str], name: str) -> str:
    return str(env.get(name, "")).strip()


def _health_timeout_seconds(env: Mapping[str, str]) -> float:
    configured_value = _env_value(env, "RUNTIME_HEALTH_TIMEOUT_SECONDS")
    if not configured_value:
        return DEFAULT_HEALTH_TIMEOUT_SECONDS

    try:
        timeout_seconds = float(configured_value)
    except ValueError:
        return DEFAULT_HEALTH_TIMEOUT_SECONDS

    if timeout_seconds <= 0:
        return DEFAULT_HEALTH_TIMEOUT_SECONDS
    return timeout_seconds


def _media_server_health_url(env: Mapping[str, str]) -> str:
    configured_url = _env_value(env, "MEDIA_SERVER_HEALTH_URL")
    if configured_url:
        return configured_url

    host = _env_value(env, "MEDIA_SERVER_HEALTH_HOST") or "127.0.0.1"
    port = _env_value(env, "SRS_HTTP_API_PORT") or "1985"
    return f"http://{host}:{port}/api/v1/summaries"


def _transcription_health_url(
    app_config: AppConfig,
    env: Mapping[str, str],
) -> str:
    configured_url = _env_value(env, "TRANSCRIPTION_HEALTH_URL")
    if configured_url:
        return configured_url
    return _join_url(app_config.transcription_api_url, "/health")


def _ai_health_url(app_config: AppConfig, env: Mapping[str, str]) -> str:
    configured_url = _env_value(env, "AI_HEALTH_URL")
    if configured_url:
        return configured_url

    base_url = app_config.gemma_api_url.strip().rstrip("/")
    if not base_url:
        return ""
    if app_config.ai_provider == AI_PROVIDER_OLLAMA:
        return _join_url(base_url, "/api/tags")
    if app_config.ai_provider == AI_PROVIDER_OPENAI_COMPATIBLE:
        return _base_readiness_url(base_url)
    return base_url


def _join_url(base_url: str, path: str) -> str:
    stripped_base = base_url.strip().rstrip("/")
    if not stripped_base:
        return ""
    return f"{stripped_base}/{path.lstrip('/')}"


def _base_readiness_url(api_url: str) -> str:
    stripped_url = api_url.strip().rstrip("/")
    parsed = urlparse(stripped_url)
    if parsed.scheme and parsed.netloc:
        return urlunparse(
            parsed._replace(path="", params="", query="", fragment="")
        ).rstrip("/")
    return stripped_url


def _port_health_result(component: str, name: str, port: int) -> HealthResult:
    if 0 < int(port) <= 65535:
        return HealthResult.healthy(
            component,
            f"{name} is in range.",
            details={"name": name, "port": port},
        )
    return HealthResult.unhealthy(
        component,
        f"{name} is outside the valid TCP port range.",
        details={"name": name, "port": port},
    )


def _write_directory_probe(directory: Path) -> None:
    probe_path = directory / f".clutchcam-healthcheck-{os.getpid()}"
    probe_path.write_text("", encoding="utf-8")
    probe_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
