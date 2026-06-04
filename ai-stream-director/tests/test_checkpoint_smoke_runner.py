import io
import json
import subprocess
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from scripts import checkpoint_smoke_runner  # noqa: E402


@dataclass(frozen=True)
class FakeSmokeResult:
    boundary: str
    values: tuple[str, ...] = ()


def _registry(calls, *, failing=()):
    failing_names = set(failing)

    def make_runner(name):
        def run(env):
            calls.append((name, dict(env)))
            if name in failing_names:
                raise RuntimeError(f"{name} unavailable")
            return FakeSmokeResult(boundary=name, values=(env.get("MARKER", ""),))

        return run

    return tuple(
        checkpoint_smoke_runner.CheckDefinition(
            name=name,
            command=("python", f"scripts/{name}.py"),
            runner=make_runner(name),
            enabled_by_default=(name == "orchestrator"),
            default_skip_reason=f"{name} opt-in",
        )
        for name in (
            "media-server",
            "buffer",
            "transcription",
            "ai",
            "orchestrator",
        )
    )


class CheckpointSmokeRunnerTests(unittest.TestCase):
    def test_default_skips_live_boundaries_and_runs_orchestrator(self) -> None:
        calls = []

        report = checkpoint_smoke_runner.run_checkpoint_smokes(
            {"MARKER": "safe"},
            registry=_registry(calls),
        )

        self.assertEqual(report["status"], "passed")
        self.assertEqual([name for name, _env in calls], ["orchestrator"])
        checks = {check["name"]: check for check in report["checks"]}
        self.assertEqual(checks["media-server"]["status"], "skipped")
        self.assertEqual(checks["media-server"]["skip_reason"], "media-server opt-in")
        self.assertEqual(checks["orchestrator"]["status"], "passed")
        self.assertEqual(
            checks["orchestrator"]["result"],
            {"boundary": "orchestrator", "values": ["safe"]},
        )

    def test_run_all_executes_every_boundary_and_reports_failures(self) -> None:
        calls = []

        report = checkpoint_smoke_runner.run_checkpoint_smokes(
            {},
            registry=_registry(calls, failing={"ai"}),
            options=checkpoint_smoke_runner.RunnerOptions(run_all=True),
        )

        self.assertEqual(report["status"], "failed")
        self.assertEqual(
            [name for name, _env in calls],
            ["media-server", "buffer", "transcription", "ai", "orchestrator"],
        )
        checks = {check["name"]: check for check in report["checks"]}
        self.assertEqual(checks["ai"]["status"], "failed")
        self.assertEqual(checks["ai"]["error_reason"], "ai unavailable")
        self.assertEqual(checks["orchestrator"]["status"], "passed")

    def test_env_can_run_and_skip_individual_boundaries(self) -> None:
        calls = []

        report = checkpoint_smoke_runner.run_checkpoint_smokes(
            {
                "CHECKPOINT_SMOKE_RUN_AI": "true",
                "CHECKPOINT_SMOKE_SKIP_ORCHESTRATOR": "true",
            },
            registry=_registry(calls),
        )

        self.assertEqual(report["status"], "passed")
        self.assertEqual([name for name, _env in calls], ["ai"])
        checks = {check["name"]: check for check in report["checks"]}
        self.assertEqual(checks["ai"]["context"]["selection"], "enabled by CHECKPOINT_SMOKE_RUN_AI")
        self.assertEqual(checks["orchestrator"]["status"], "skipped")
        self.assertEqual(
            checks["orchestrator"]["skip_reason"],
            "disabled by CHECKPOINT_SMOKE_SKIP_ORCHESTRATOR",
        )

    def test_cli_flags_override_env_and_return_failure_code(self) -> None:
        calls = []
        stdout = io.StringIO()

        exit_code = checkpoint_smoke_runner.main(
            ["--run-ai", "--skip-orchestrator"],
            registry=_registry(calls, failing={"ai"}),
            env={
                "CHECKPOINT_SMOKE_SKIP_AI": "true",
                "CHECKPOINT_SMOKE_RUN_ORCHESTRATOR": "true",
            },
            stdout=stdout,
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual([name for name, _env in calls], ["ai"])
        payload = json.loads(stdout.getvalue())
        checks = {check["name"]: check for check in payload["checks"]}
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(checks["ai"]["context"]["selection"], "enabled by --run-ai")
        self.assertEqual(checks["orchestrator"]["status"], "skipped")

    def test_skip_all_returns_skipped_report_and_zero_exit(self) -> None:
        calls = []
        stdout = io.StringIO()

        exit_code = checkpoint_smoke_runner.main(
            ["--skip-all"],
            registry=_registry(calls),
            stdout=stdout,
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls, [])
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "skipped")
        self.assertTrue(all(check["status"] == "skipped" for check in payload["checks"]))

    def test_importing_runner_does_not_import_smoke_boundaries(self) -> None:
        script = f"""
import importlib
import sys
sys.path.insert(0, {str(PROJECT_DIR)!r})
importlib.import_module("scripts.checkpoint_smoke_runner")
for name in (
    "scripts.smoke_media_server",
    "scripts.smoke_buffer_worker",
    "scripts.smoke_transcription_api",
    "scripts.smoke_ai_endpoint",
    "scripts.smoke_orchestrator_dry_run",
):
    if name in sys.modules:
        raise SystemExit(f"imported boundary {{name}}")
"""

        result = subprocess.run(
            [sys.executable, "-B", "-c", script],
            check=False,
            capture_output=True,
            text=True,
            cwd=str(PROJECT_DIR),
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
