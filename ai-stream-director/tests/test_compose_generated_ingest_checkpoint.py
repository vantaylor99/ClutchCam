import io
import json
import subprocess
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from scripts import compose_generated_ingest_checkpoint as checkpoint  # noqa: E402


@dataclass(frozen=True)
class FakeSummaries:
    url: str
    status_code: int
    payload_keys: tuple[str, ...]


@dataclass(frozen=True)
class FakePublish:
    stream_id: str
    url: str
    command: tuple[str, ...]
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class FakeMediaResult:
    summaries: FakeSummaries
    publish_results: tuple[FakePublish, ...]
    compose_command: tuple[str, ...] | None = None


@dataclass(frozen=True)
class FakeLatestSegment:
    path: str
    start_time_seconds: float
    end_time_seconds: float
    sequence: int
    exists: bool


@dataclass(frozen=True)
class FakeStream:
    stream_id: str
    segment_count: int
    clip_status: str
    clip_media_uri: str | None
    clip_reason: str
    segment_uris: tuple[str, ...]
    latest_segment: FakeLatestSegment | None = None


@dataclass(frozen=True)
class FakeBufferResult:
    buffer_root: str
    streams: tuple[FakeStream, ...]

    @property
    def ready_streams(self) -> tuple[str, ...]:
        return tuple(
            stream.stream_id
            for stream in self.streams
            if stream.clip_status == "ready"
        )


def compose_ps_output(
    *,
    media_state: str = "running",
    media_health: str = "healthy",
    buffer_state: str = "running",
    buffer_health: str = "healthy",
) -> str:
    return json.dumps(
        [
            {
                "Service": "media-server",
                "Name": "ai-stream-director-media-server",
                "State": media_state,
                "Health": media_health,
                "Status": media_state,
                "ExitCode": 0,
            },
            {
                "Service": "buffer-worker",
                "Name": "ai-stream-director-buffer-worker",
                "State": buffer_state,
                "Health": buffer_health,
                "Status": buffer_state,
                "ExitCode": 0,
            },
        ]
    )


class FakeCommandRunner:
    def __init__(
        self,
        *,
        ps_outputs: tuple[str, ...] = (),
        fail_preflight: str | None = None,
        compose_up_timeout: bool = False,
        log_output: str = "",
    ) -> None:
        self.calls: list[tuple[list[str], dict[str, object]]] = []
        self.ps_outputs = list(ps_outputs or (compose_ps_output(),))
        self.fail_preflight = fail_preflight
        self.compose_up_timeout = compose_up_timeout
        self.log_output = log_output

    def __call__(self, command, **kwargs):
        command = list(command)
        self.calls.append((command, kwargs))
        if len(command) > 1 and command[1] == "info":
            return self._preflight_result(command, "docker_engine", "27.0")
        if "compose" in command and "version" in command:
            return self._preflight_result(command, "docker_compose", "2.29.0")
        if command[-1:] == ["-version"]:
            return self._preflight_result(command, "host_ffmpeg", "ffmpeg version test")
        if "up" in command:
            if self.compose_up_timeout:
                raise subprocess.TimeoutExpired(command, timeout=kwargs["timeout"])
            return subprocess.CompletedProcess(command, 0, stdout="started", stderr="")
        if "ps" in command:
            output = self.ps_outputs.pop(0) if len(self.ps_outputs) > 1 else self.ps_outputs[0]
            return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")
        if "logs" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=self.log_output,
                stderr="",
            )
        raise AssertionError(f"unexpected command: {command}")

    def _preflight_result(self, command, requirement: str, stdout: str):
        returncode = 1 if self.fail_preflight == requirement else 0
        stderr = f"{requirement} unavailable" if returncode else ""
        return subprocess.CompletedProcess(
            command,
            returncode,
            stdout=stdout if not returncode else "",
            stderr=stderr,
        )


def fake_media_result(*stream_ids: str) -> FakeMediaResult:
    return FakeMediaResult(
        summaries=FakeSummaries(
            url="http://127.0.0.1:1985/api/v1/summaries",
            status_code=200,
            payload_keys=("code", "data"),
        ),
        publish_results=tuple(
            FakePublish(
                stream_id=stream_id,
                url=f"rtmp://127.0.0.1:1935/live/{stream_id}",
                command=("ffmpeg", "-t", "8", f"rtmp://127.0.0.1/live/{stream_id}"),
            )
            for stream_id in stream_ids
        ),
    )


def ready_buffer_result(buffer_root: str = "/dev/shm/clutchcam") -> FakeBufferResult:
    return FakeBufferResult(
        buffer_root=buffer_root,
        streams=(
            FakeStream(
                stream_id="player_1",
                segment_count=2,
                latest_segment=FakeLatestSegment(
                    path=f"{buffer_root}/player_1/000000001.ts",
                    start_time_seconds=2.0,
                    end_time_seconds=4.0,
                    sequence=1,
                    exists=True,
                ),
                clip_status="ready",
                clip_media_uri=f"file://{buffer_root}/player_1/clips/clip.m3u8",
                clip_reason="",
                segment_uris=(f"file://{buffer_root}/player_1/000000001.ts",),
            ),
        ),
    )


class ComposeGeneratedIngestCheckpointTests(unittest.TestCase):
    def test_default_report_is_skipped_without_touching_live_boundaries(self) -> None:
        calls = []

        report = checkpoint.run_generated_ingest_checkpoint(
            {},
            options=checkpoint.GeneratedIngestOptions(run=False),
            run=lambda *args, **kwargs: calls.append(("compose", args, kwargs)),
            probe_writable_path=lambda path: calls.append(("path", path)),
            media_smoke=lambda *args, **kwargs: calls.append(("media", args, kwargs)),
            buffer_inspect=lambda *args, **kwargs: calls.append(("buffer", args, kwargs)),
            buffer_assert_ready=lambda result: None,
        )

        self.assertEqual(report["status"], "skipped")
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["checkpoint"], "compose-generated-ingest")
        self.assertEqual(report["stream_ids"], ["player_1"])
        self.assertEqual(report["preflight"]["status"], "not_run")
        self.assertEqual(report["compose"]["status"], "not_run")
        self.assertEqual(report["publish"]["status"], "not_run")
        self.assertEqual(report["buffer"]["status"], "not_run")
        self.assertEqual(report["diagnostics"]["status"], "not_run")
        self.assertTrue(
            {
                "schema_version",
                "checkpoint",
                "status",
                "duration_seconds",
                "stream_ids",
                "compose",
                "publish",
                "buffer",
                "failure_reason",
                "operator_hints",
            }.issubset(report)
        )
        self.assertEqual(calls, [])
        self.assertIn("--run", report["operator_hints"][0])

    def test_preflight_failures_name_requirement_and_prevent_publish(self) -> None:
        for requirement in ("docker_engine", "docker_compose", "host_ffmpeg"):
            with self.subTest(requirement=requirement):
                runner = FakeCommandRunner(fail_preflight=requirement)
                report = checkpoint.run_generated_ingest_checkpoint(
                    {},
                    options=checkpoint.GeneratedIngestOptions(run=True),
                    run=runner,
                    probe_writable_path=lambda path: None,
                    media_smoke=lambda *args, **kwargs: self.fail(
                        "media should not run"
                    ),
                )

                self.assertEqual(report["status"], "failed")
                self.assertEqual(
                    report["preflight"]["failed_requirements"],
                    [requirement],
                )
                self.assertIn(requirement, report["failure_reason"])
                self.assertEqual(report["publish"]["status"], "not_run")
                self.assertEqual(report["diagnostics"]["log_tail"], 100)

        runner = FakeCommandRunner()
        report = checkpoint.run_generated_ingest_checkpoint(
            {"LOOKBACK_BUFFER_HOST_DIR": "/host/buffer"},
            options=checkpoint.GeneratedIngestOptions(run=True),
            run=runner,
            probe_writable_path=lambda path: (_ for _ in ()).throw(
                PermissionError(f"denied: {path}")
            ),
            media_smoke=lambda *args, **kwargs: self.fail("media should not run"),
        )

        self.assertEqual(
            report["preflight"]["failed_requirements"],
            ["host_buffer_path"],
        )
        self.assertIn("Host buffer path is not writable", report["failure_reason"])

    def test_run_starts_compose_publishes_and_reports_ready_buffer(self) -> None:
        calls = []
        runner = FakeCommandRunner()

        def media_smoke(env, *, stream_ids):
            calls.append(("media", dict(env), tuple(stream_ids)))
            return fake_media_result("player_1", "player_2")

        def inspect_buffer(env, *, stream_ids):
            calls.append(("buffer", dict(env), tuple(stream_ids)))
            return ready_buffer_result()

        def assert_ready(result):
            if not result.ready_streams:
                raise RuntimeError("not ready")

        report = checkpoint.run_generated_ingest_checkpoint(
            {"DOCKER_EXECUTABLE": "docker-test"},
            options=checkpoint.GeneratedIngestOptions(
                run=True,
                stream_ids=("player_1", "player_2"),
                compose_timeout_seconds=12,
                buffer_ready_timeout_seconds=0,
            ),
            run=runner,
            probe_writable_path=lambda path: calls.append(("path", path.as_posix())),
            media_smoke=media_smoke,
            buffer_inspect=inspect_buffer,
            buffer_assert_ready=assert_ready,
            sleep=lambda seconds: None,
        )

        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["failure_reason"], None)
        self.assertEqual(report["stream_ids"], ["player_1", "player_2"])
        self.assertEqual(report["preflight"]["status"], "passed")
        self.assertEqual(
            [item["name"] for item in report["preflight"]["requirements"]],
            ["docker_engine", "docker_compose", "host_ffmpeg", "host_buffer_path"],
        )
        compose_up = next(call for call in runner.calls if "up" in call[0])
        self.assertEqual(compose_up[0][:6], ["docker-test", "compose", "--profile", "media-server", "--profile", "buffer-worker"])
        self.assertIn("--build", compose_up[0])
        self.assertEqual(compose_up[1]["timeout"], 12)
        self.assertEqual(compose_up[1]["cwd"], str(PROJECT_DIR))
        self.assertEqual(calls[0], ("path", "/dev/shm/clutchcam"))
        self.assertEqual(calls[1][0], "media")
        self.assertEqual(calls[1][1]["SMOKE_SKIP_COMPOSE"], "true")
        self.assertEqual(calls[1][1]["SMOKE_SKIP_PUBLISH"], "false")
        self.assertEqual(calls[1][1]["SMOKE_PUBLISH_STREAMS"], "player_1,player_2")
        self.assertEqual(calls[2][0], "buffer")
        self.assertEqual(report["publish"]["published_stream_ids"], ["player_1", "player_2"])
        self.assertEqual(report["compose"]["service_state"]["status"], "passed")
        self.assertEqual(report["buffer"]["status"], "ready")
        self.assertEqual(report["buffer"]["ready_streams"], ["player_1"])
        self.assertEqual(report["buffer"]["streams"][0]["clip_status"], "ready")
        self.assertEqual(report["diagnostics"]["status"], "not_run")

    def test_multi_stream_run_requires_every_requested_stream_ready(self) -> None:
        runner = FakeCommandRunner()

        def media_smoke(env, *, stream_ids):
            return fake_media_result("player_1", "player_2")

        def inspect_buffer(env, *, stream_ids):
            return FakeBufferResult(
                buffer_root="/dev/shm/clutchcam",
                streams=(
                    ready_buffer_result().streams[0],
                    FakeStream(
                        stream_id="player_2",
                        segment_count=0,
                        latest_segment=None,
                        clip_status="unavailable",
                        clip_media_uri=None,
                        clip_reason="No segment metadata for stream.",
                        segment_uris=(),
                    ),
                ),
            )

        report = checkpoint.run_generated_ingest_checkpoint(
            {},
            options=checkpoint.GeneratedIngestOptions(
                run=True,
                stream_ids=("player_1", "player_2"),
                buffer_ready_timeout_seconds=0,
            ),
            run=runner,
            probe_writable_path=lambda path: None,
            media_smoke=media_smoke,
            buffer_inspect=inspect_buffer,
            sleep=lambda seconds: None,
        )

        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["buffer"]["status"], "failed")
        self.assertEqual(report["buffer"]["ready_streams"], ["player_1"])
        self.assertIn("Not all requested streams", report["failure_reason"])
        self.assertIn("player_2=unavailable", report["failure_reason"])

    def test_compose_timeout_reports_failure_without_publishing(self) -> None:
        runner = FakeCommandRunner(compose_up_timeout=True)

        report = checkpoint.run_generated_ingest_checkpoint(
            {},
            options=checkpoint.GeneratedIngestOptions(
                run=True,
                compose_timeout_seconds=3,
            ),
            run=runner,
            probe_writable_path=lambda path: None,
            media_smoke=lambda *args, **kwargs: self.fail("media should not run"),
            buffer_inspect=lambda *args, **kwargs: self.fail("buffer should not run"),
            buffer_assert_ready=lambda result: None,
        )

        self.assertEqual(report["status"], "failed")
        self.assertIn("timed out after 3s", report["failure_reason"])
        self.assertEqual(report["compose"]["status"], "failed")
        self.assertEqual(report["publish"]["status"], "not_run")
        self.assertEqual(report["buffer"]["status"], "not_run")
        self.assertEqual(report["diagnostics"]["status"], "passed")
        self.assertTrue(any("logs" in command for command, _ in runner.calls))
        self.assertTrue(any("Docker" in hint for hint in report["operator_hints"]))

    def test_buffer_timeout_reports_last_inspection_details(self) -> None:
        runner = FakeCommandRunner()

        def media_smoke(env, *, stream_ids):
            return fake_media_result("player_1")

        def inspect_buffer(env, *, stream_ids):
            return FakeBufferResult(
                buffer_root="/dev/shm/clutchcam",
                streams=(
                    FakeStream(
                        stream_id="player_1",
                        segment_count=0,
                        latest_segment=None,
                        clip_status="unavailable",
                        clip_media_uri=None,
                        clip_reason="No segment metadata for stream.",
                        segment_uris=(),
                    ),
                ),
            )

        report = checkpoint.run_generated_ingest_checkpoint(
            {},
            options=checkpoint.GeneratedIngestOptions(
                run=True,
                skip_compose=True,
                buffer_ready_timeout_seconds=0,
            ),
            run=runner,
            probe_writable_path=lambda path: None,
            media_smoke=media_smoke,
            buffer_inspect=inspect_buffer,
            buffer_assert_ready=lambda result: (_ for _ in ()).throw(
                RuntimeError("No resolvable clips were found")
            ),
            sleep=lambda seconds: None,
        )

        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["compose"]["status"], "passed")
        self.assertEqual(report["compose"]["startup_status"], "skipped")
        self.assertEqual(report["buffer"]["status"], "failed")
        self.assertEqual(report["buffer"]["attempts"], 1)
        self.assertEqual(report["buffer"]["streams"][0]["clip_reason"], "No segment metadata for stream.")
        self.assertIn("Buffer metadata did not become ready", report["failure_reason"])
        self.assertEqual(report["diagnostics"]["status"], "passed")
        self.assertTrue(any("SMOKE_PUBLISH_SECONDS" in hint for hint in report["operator_hints"]))

    def test_compose_state_polls_starting_health_until_ready(self) -> None:
        runner = FakeCommandRunner(
            ps_outputs=(
                compose_ps_output(buffer_health="starting"),
                compose_ps_output(),
            )
        )

        report = checkpoint.run_generated_ingest_checkpoint(
            {},
            options=checkpoint.GeneratedIngestOptions(
                run=True,
                skip_compose=True,
                compose_ready_timeout_seconds=5,
                compose_poll_interval_seconds=0.1,
                buffer_ready_timeout_seconds=0,
            ),
            run=runner,
            probe_writable_path=lambda path: None,
            media_smoke=lambda env, *, stream_ids: fake_media_result(*stream_ids),
            buffer_inspect=lambda env, *, stream_ids: ready_buffer_result(),
            buffer_assert_ready=lambda result: None,
            sleep=lambda seconds: None,
        )

        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["compose"]["service_state"]["attempts"], 2)
        self.assertEqual(report["compose"]["startup_status"], "skipped")
        self.assertFalse(any("up" in command for command, _ in runner.calls))

    def test_compose_state_parser_accepts_array_and_json_lines(self) -> None:
        array_output = compose_ps_output()
        json_lines_output = "\n".join(
            json.dumps(record) for record in json.loads(array_output)
        )

        for output in (array_output, json_lines_output):
            with self.subTest(output=output[:1]):
                services = checkpoint._parse_compose_service_state(output)

                self.assertEqual(
                    set(services),
                    {"media-server", "buffer-worker"},
                )
                self.assertEqual(
                    checkpoint._compose_readiness(services),
                    ("ready", ""),
                )

        with self.assertRaisesRegex(ValueError, "JSON object"):
            checkpoint._parse_compose_service_state('"not a service record"')

    def test_compose_health_classification_is_strict_but_compatible(self) -> None:
        empty_health = checkpoint._parse_compose_service_state(
            compose_ps_output(media_health="", buffer_health="")
        )
        unknown_health = checkpoint._parse_compose_service_state(
            compose_ps_output(buffer_health="degraded")
        )
        terminal_status = checkpoint._parse_compose_service_state(
            compose_ps_output()
        )
        terminal_status["buffer-worker"]["state"] = ""
        terminal_status["buffer-worker"]["status"] = "Exited (1) 2 seconds ago"

        self.assertEqual(
            checkpoint._compose_readiness(empty_health),
            ("ready", ""),
        )
        self.assertEqual(
            checkpoint._compose_readiness(unknown_health),
            ("pending", "buffer-worker health=degraded"),
        )
        readiness, reason = checkpoint._compose_readiness(terminal_status)
        self.assertEqual(readiness, "failed")
        self.assertIn("exited", reason)

    def test_compose_terminal_states_fail_before_publish(self) -> None:
        cases = {
            "exited": compose_ps_output(buffer_state="exited", buffer_health=""),
            "restarting": compose_ps_output(
                buffer_state="restarting",
                buffer_health="",
            ),
            "unhealthy": compose_ps_output(buffer_health="unhealthy"),
        }
        for expected, state_output in cases.items():
            with self.subTest(expected=expected):
                runner = FakeCommandRunner(
                    ps_outputs=(state_output, compose_ps_output())
                )
                report = checkpoint.run_generated_ingest_checkpoint(
                    {},
                    options=checkpoint.GeneratedIngestOptions(
                        run=True,
                        skip_compose=True,
                    ),
                    run=runner,
                    probe_writable_path=lambda path: None,
                    media_smoke=lambda *args, **kwargs: self.fail(
                        "media should not run"
                    ),
                )

                self.assertEqual(report["status"], "failed")
                self.assertIn(expected, report["failure_reason"])
                self.assertEqual(report["publish"]["status"], "not_run")
                self.assertEqual(report["diagnostics"]["status"], "passed")

    def test_failure_diagnostics_are_bounded_and_redacted(self) -> None:
        secret = "env-secret-value"
        log_output = (
            ("x" * 5000)
            + f"\nGEMMA_API_KEY={secret}"
            + "\nPASSWORD=hunter2"
            + "\nAuthorization: Bearer token-value"
            + "\nrtmp://user:pass@example.test/live"
        )
        runner = FakeCommandRunner(log_output=log_output)

        report = checkpoint.run_generated_ingest_checkpoint(
            {"GEMMA_API_KEY": secret},
            options=checkpoint.GeneratedIngestOptions(
                run=True,
                skip_compose=True,
                diagnostic_timeout_seconds=7,
            ),
            run=runner,
            probe_writable_path=lambda path: None,
            media_smoke=lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("publish failed")
            ),
        )

        logs = report["diagnostics"]["recent_logs"]
        self.assertEqual(report["status"], "failed")
        self.assertEqual(logs["timeout_seconds"], 7)
        self.assertLessEqual(len(logs["stdout"]), checkpoint.OUTPUT_LIMIT)
        self.assertNotIn(secret, logs["stdout"])
        self.assertNotIn("hunter2", logs["stdout"])
        self.assertNotIn("token-value", logs["stdout"])
        self.assertNotIn("user:pass", logs["stdout"])
        self.assertIn("[REDACTED]", logs["stdout"])
        log_call = next(command for command, _ in runner.calls if "logs" in command)
        self.assertIn("--tail=100", log_call)

    def test_json_secret_assignments_are_redacted(self) -> None:
        output = checkpoint._redact_output(
            '{"PASSWORD": "hunter2", "access_token":"abc123"}',
            {},
        )

        self.assertNotIn("hunter2", output)
        self.assertNotIn("abc123", output)
        self.assertEqual(output.count("[REDACTED]"), 2)

    def test_media_summary_redacts_urls_commands_and_output(self) -> None:
        result = FakeMediaResult(
            summaries=FakeSummaries(
                url="http://user:pass@example.test/summaries",
                status_code=200,
                payload_keys=("code",),
            ),
            publish_results=(
                FakePublish(
                    stream_id="player_1",
                    url="rtmp://user:pass@example.test/live/player_1",
                    command=(
                        "ffmpeg",
                        "rtmp://user:pass@example.test/live/player_1",
                    ),
                    stdout='{"access_token":"abc123"}',
                    stderr="PASSWORD=hunter2",
                ),
            ),
        )

        summary = checkpoint._summarize_media_smoke(result, {})
        serialized = json.dumps(summary)

        for secret in ("user:pass", "abc123", "hunter2"):
            self.assertNotIn(secret, serialized)
        self.assertIn("[REDACTED]", serialized)

    def test_diagnostic_exceptions_do_not_replace_primary_failure(self) -> None:
        ps_calls = 0
        secret = "diagnostic-secret"

        def run(command, **kwargs):
            nonlocal ps_calls
            command = list(command)
            if len(command) > 1 and command[1] == "info":
                return subprocess.CompletedProcess(command, 0, stdout="27.0", stderr="")
            if "compose" in command and "version" in command:
                return subprocess.CompletedProcess(command, 0, stdout="2.29.0", stderr="")
            if command[-1:] == ["-version"]:
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout="ffmpeg version test",
                    stderr="",
                )
            if "ps" in command:
                ps_calls += 1
                if ps_calls == 1:
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout=compose_ps_output(),
                        stderr="",
                    )
                raise RuntimeError(f"diagnostic failed with {secret}")
            if "logs" in command:
                raise RuntimeError(f"logs failed with {secret}")
            raise AssertionError(f"unexpected command: {command}")

        report = checkpoint.run_generated_ingest_checkpoint(
            {"DIAGNOSTIC_TOKEN": secret},
            options=checkpoint.GeneratedIngestOptions(
                run=True,
                skip_compose=True,
            ),
            run=run,
            probe_writable_path=lambda path: None,
            media_smoke=lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("primary publish failure")
            ),
        )

        self.assertEqual(
            report["failure_reason"],
            "Generated RTMP publish or SRS readiness failed: primary publish failure",
        )
        self.assertEqual(report["diagnostics"]["status"], "failed")
        diagnostics_json = json.dumps(report["diagnostics"])
        self.assertNotIn(secret, diagnostics_json)
        self.assertIn("[REDACTED]", diagnostics_json)

    def test_readiness_query_timeout_is_clamped_to_readiness_budget(self) -> None:
        observed_timeouts = []

        def run(command, **kwargs):
            observed_timeouts.append(kwargs["timeout"])
            raise subprocess.TimeoutExpired(command, timeout=kwargs["timeout"])

        result = checkpoint._wait_for_compose_ready(
            {},
            timeout_seconds=0.25,
            poll_interval_seconds=1,
            command_timeout_seconds=10,
            run=run,
            sleep=lambda seconds: None,
            clock=__import__("time").monotonic,
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(observed_timeouts), 1)
        self.assertGreaterEqual(observed_timeouts[0], 0.1)
        self.assertLessEqual(observed_timeouts[0], 0.25)

    def test_main_emits_json_and_honors_env_opt_in(self) -> None:
        stdout = io.StringIO()

        exit_code = checkpoint.main(
            ["--indent", "0"],
            env={"GENERATED_INGEST_CHECKPOINT_RUN": "false"},
            stdout=stdout,
        )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "skipped")

    def test_skipped_report_honors_configured_docker_executable(self) -> None:
        report = checkpoint.run_generated_ingest_checkpoint(
            {"DOCKER_EXECUTABLE": "docker-test"},
            options=checkpoint.GeneratedIngestOptions(run=False),
        )

        self.assertEqual(report["compose"]["command"][0], "docker-test")

    def test_host_buffer_dir_is_used_for_local_buffer_inspection(self) -> None:
        captured_env = {}
        probed_paths = []
        runner = FakeCommandRunner()

        def media_smoke(env, *, stream_ids):
            return fake_media_result("player_1")

        def inspect_buffer(env, *, stream_ids):
            captured_env.update(env)
            return FakeBufferResult(
                buffer_root="/mnt/ram/clutchcam",
                streams=(
                    FakeStream(
                        stream_id="player_1",
                        segment_count=1,
                        latest_segment=None,
                        clip_status="ready",
                        clip_media_uri="file:///mnt/ram/clutchcam/player_1/clip.m3u8",
                        clip_reason="",
                        segment_uris=(),
                    ),
                ),
            )

        report = checkpoint.run_generated_ingest_checkpoint(
            {
                "LOOKBACK_BUFFER_HOST_DIR": "/mnt/ram/clutchcam-host",
                "LOOKBACK_BUFFER_DIR": "/dev/shm/clutchcam",
            },
            options=checkpoint.GeneratedIngestOptions(
                run=True,
                skip_compose=True,
                buffer_ready_timeout_seconds=0,
            ),
            run=runner,
            probe_writable_path=lambda path: probed_paths.append(path.as_posix()),
            media_smoke=media_smoke,
            buffer_inspect=inspect_buffer,
            buffer_assert_ready=lambda result: None,
        )

        self.assertEqual(report["status"], "passed")
        self.assertEqual(probed_paths, ["/mnt/ram/clutchcam-host"])
        self.assertEqual(
            captured_env["LOOKBACK_BUFFER_DIR"],
            "/mnt/ram/clutchcam-host",
        )
        compose_ps_call = next(
            kwargs for command, kwargs in runner.calls if "ps" in command
        )
        self.assertEqual(
            compose_ps_call["env"]["LOOKBACK_BUFFER_DIR"],
            "/dev/shm/clutchcam",
        )

    def test_relative_host_buffer_path_is_anchored_to_project(self) -> None:
        relative_path = "runtime-buffer"

        host_path = checkpoint._host_buffer_path(
            {"LOOKBACK_BUFFER_HOST_DIR": relative_path}
        )
        compose_env = checkpoint._compose_env(
            {
                "LOOKBACK_BUFFER_HOST_DIR": relative_path,
                "LOOKBACK_BUFFER_DIR": "/dev/shm/clutchcam",
            }
        )
        runtime_env = checkpoint._runtime_env(
            {"LOOKBACK_BUFFER_HOST_DIR": relative_path},
            ("player_1",),
        )

        expected = (PROJECT_DIR / relative_path).as_posix()
        self.assertEqual(host_path.as_posix(), expected)
        self.assertEqual(compose_env["LOOKBACK_BUFFER_HOST_DIR"], expected)
        self.assertEqual(
            compose_env["LOOKBACK_BUFFER_DIR"],
            "/dev/shm/clutchcam",
        )
        self.assertEqual(runtime_env["LOOKBACK_BUFFER_DIR"], expected)

    def test_windows_rejects_posix_root_buffer_path_before_writing(self) -> None:
        with self.assertRaisesRegex(
            OSError,
            "POSIX-root buffer paths are not host paths on Windows",
        ):
            checkpoint._probe_writable_path(
                Path("/dev/shm/clutchcam"),
                platform_name="nt",
            )

    def test_importing_script_does_not_import_live_smoke_helpers(self) -> None:
        script = f"""
import importlib
import sys
sys.path.insert(0, {str(PROJECT_DIR)!r})
importlib.import_module("scripts.compose_generated_ingest_checkpoint")
for name in (
    "scripts.smoke_media_server",
    "scripts.smoke_buffer_worker",
):
    if name in sys.modules:
        raise SystemExit(f"imported live helper {{name}}")
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
