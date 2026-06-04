import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from services.health import (  # noqa: E402
    CallableHealthCheck,
    HealthResult,
    HealthStatus,
    HttpEndpointHealthCheck,
    RequiredValueHealthCheck,
    run_health_checks,
)


class FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status


class HealthCheckTests(unittest.TestCase):
    def test_required_value_health_check_reports_configured_value(self) -> None:
        result = RequiredValueHealthCheck(
            "ai",
            "GEMMA_API_URL",
            "http://ollama:11434",
        ).check()

        self.assertEqual(result.status, HealthStatus.HEALTHY)
        self.assertEqual(result.details["name"], "GEMMA_API_URL")

    def test_required_value_health_check_reports_missing_value(self) -> None:
        result = RequiredValueHealthCheck("obs", "OBS_PASSWORD", "  ").check()

        self.assertEqual(result.status, HealthStatus.UNHEALTHY)
        self.assertIn("not configured", result.message)

    def test_http_endpoint_health_check_reports_success(self) -> None:
        calls = []

        def opener(url, **kwargs):
            calls.append((url, kwargs))
            return FakeResponse(204)

        result = HttpEndpointHealthCheck(
            "media-server",
            "http://127.0.0.1:1985/api/v1/summaries",
            timeout_seconds=1.5,
            opener=opener,
        ).check()

        self.assertEqual(result.status, HealthStatus.HEALTHY)
        self.assertEqual(calls[0][0], "http://127.0.0.1:1985/api/v1/summaries")
        self.assertEqual(calls[0][1]["timeout"], 1.5)
        self.assertEqual(result.details["status_code"], 204)

    def test_http_endpoint_health_check_reports_degraded_client_status(self) -> None:
        result = HttpEndpointHealthCheck(
            "transcription",
            "http://whisper:8000/health",
            opener=lambda *args, **kwargs: FakeResponse(404),
        ).check()

        self.assertEqual(result.status, HealthStatus.DEGRADED)
        self.assertEqual(result.details["status_code"], 404)

    def test_http_endpoint_health_check_reports_transport_failure(self) -> None:
        result = HttpEndpointHealthCheck(
            "ai",
            "http://gemma:8000/v1/models",
            opener=lambda *args, **kwargs: (_ for _ in ()).throw(OSError("down")),
        ).check()

        self.assertEqual(result.status, HealthStatus.UNHEALTHY)
        self.assertIn("down", result.message)

    def test_callable_health_check_catches_exceptions_and_records_duration(self) -> None:
        ticks = iter((10.0, 10.25))
        check = CallableHealthCheck(
            "buffer",
            lambda: (_ for _ in ()).throw(RuntimeError("segments missing")),
            clock=lambda: next(ticks),
        )

        result = check.check()

        self.assertEqual(result.status, HealthStatus.UNHEALTHY)
        self.assertEqual(result.duration_seconds, 0.25)
        self.assertIn("segments missing", result.message)

    def test_aggregate_health_prefers_worst_status(self) -> None:
        report = run_health_checks(
            [
                _StaticCheck(HealthResult.healthy("media-server")),
                _StaticCheck(HealthResult.degraded("ai", "model list unavailable")),
                _StaticCheck(HealthResult.unhealthy("obs", "not connected")),
            ]
        )

        self.assertEqual(report.status, HealthStatus.UNHEALTHY)
        self.assertEqual(len(report.results), 3)
        self.assertEqual(report.to_record()["status"], "unhealthy")

    def test_aggregate_health_reports_degraded_when_no_failures(self) -> None:
        report = run_health_checks(
            [
                _StaticCheck(HealthResult.healthy("media-server")),
                _StaticCheck(HealthResult.degraded("ai", "readiness skipped")),
            ]
        )

        self.assertEqual(report.status, HealthStatus.DEGRADED)


class _StaticCheck:
    def __init__(self, result: HealthResult) -> None:
        self.result = result

    def check(self) -> HealthResult:
        return self.result


if __name__ == "__main__":
    unittest.main()
