"""Health-check primitives for production service diagnostics."""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class HealthCheckError(RuntimeError):
    """Raised when a health-check adapter cannot evaluate a component."""


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
            record["details"] = dict(self.details)
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

        try:
            response = self._opener(self.url, timeout=self.timeout_seconds)
            status_code = int(getattr(response, "status", 200))
        except (OSError, urllib.error.URLError, ValueError) as exc:
            return HealthResult.unhealthy(
                self.component,
                f"Endpoint check failed: {exc}",
                details={"url": self.url},
            )

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


def run_health_checks(checks: Sequence[HealthCheck]) -> HealthReport:
    results = tuple(check.check() for check in checks)
    if any(result.status == HealthStatus.UNHEALTHY for result in results):
        status = HealthStatus.UNHEALTHY
    elif any(result.status == HealthStatus.DEGRADED for result in results):
        status = HealthStatus.DEGRADED
    else:
        status = HealthStatus.HEALTHY

    return HealthReport(status=status, results=results)
