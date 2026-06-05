import io
import json
import sys
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from scripts import latency_soak_harness  # noqa: E402


class LatencySoakHarnessTests(unittest.TestCase):
    def test_default_report_shape_includes_counts_timing_budgets_and_process(self) -> None:
        report = latency_soak_harness.run_latency_soak(
            latency_soak_harness.HarnessOptions(event_count=6)
        )

        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["mode"], "offline-deterministic")
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["counts"]["total_events"], 6)
        self.assertEqual(len(report["events"]), 6)
        self.assertIn("memory_peak_bytes", report["process"])
        self.assertGreaterEqual(report["process"]["memory_peak_bytes"], 0)
        self.assertIn("wall_duration_seconds", report["timing"])

        stages = report["timing"]["stages"]
        for stage_name in latency_soak_harness.DEFAULT_LATENCY_BUDGETS_MS:
            self.assertIn(stage_name, stages)
            self.assertIn(stage_name, report["budgets"]["stages"])
            self.assertIn("max_ms", stages[stage_name])
            self.assertIn("p95_ms", stages[stage_name])

    def test_fake_components_are_deterministic_for_stable_workload(self) -> None:
        first = latency_soak_harness.run_latency_soak(
            latency_soak_harness.HarnessOptions(event_count=9)
        )
        second = latency_soak_harness.run_latency_soak(
            latency_soak_harness.HarnessOptions(event_count=9)
        )

        self.assertEqual(first["counts"], second["counts"])
        self.assertEqual(first["timing"]["stages"], second["timing"]["stages"])
        self.assertEqual(first["events"], second["events"])

    def test_budget_failure_marks_report_and_cli_as_failed(self) -> None:
        options = latency_soak_harness.HarnessOptions(
            event_count=3,
            budgets_ms={
                **latency_soak_harness.DEFAULT_LATENCY_BUDGETS_MS,
                "model_decision": 1.0,
            },
        )

        report = latency_soak_harness.run_latency_soak(options)

        self.assertEqual(report["status"], "failed")
        self.assertFalse(report["budgets"]["overall_passed"])
        self.assertFalse(report["budgets"]["stages"]["model_decision"]["passed"])

        stdout = io.StringIO()
        exit_code = latency_soak_harness.main(
            ["--events", "3", "--budget", "model_decision=1", "--indent", "0"],
            stdout=stdout,
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(json.loads(stdout.getvalue())["status"], "failed")

    def test_bounded_duration_and_event_count_are_reflected_in_output(self) -> None:
        report = latency_soak_harness.run_latency_soak(
            latency_soak_harness.HarnessOptions(
                event_count=24,
                synthetic_interval_seconds=0.5,
            )
        )

        self.assertEqual(report["options"]["event_count"], 24)
        self.assertEqual(report["counts"]["total_events"], 24)
        self.assertEqual(report["counts"]["dropped_events"], 2)
        self.assertEqual(report["counts"]["rejected_events"], 1)
        self.assertEqual(report["counts"]["switch_applied_events"], 8)
        self.assertGreater(report["timing"]["synthetic_elapsed_ms"], 0)

    def test_invalid_options_fail_clearly(self) -> None:
        with self.assertRaisesRegex(ValueError, "event_count"):
            latency_soak_harness.run_latency_soak(
                latency_soak_harness.HarnessOptions(event_count=0)
            )

        with self.assertRaisesRegex(ValueError, "Unknown latency budget"):
            latency_soak_harness.run_latency_soak(
                latency_soak_harness.HarnessOptions(
                    event_count=1,
                    budgets_ms={"not_a_stage": 1},
                )
            )


if __name__ == "__main__":
    unittest.main()
