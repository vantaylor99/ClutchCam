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


class ComposeGeneratedIngestCheckpointTests(unittest.TestCase):
    def test_default_report_is_skipped_without_touching_live_boundaries(self) -> None:
        calls = []

        report = checkpoint.run_generated_ingest_checkpoint(
            {},
            options=checkpoint.GeneratedIngestOptions(run=False),
            run=lambda *args, **kwargs: calls.append(("compose", args, kwargs)),
            media_smoke=lambda *args, **kwargs: calls.append(("media", args, kwargs)),
            buffer_inspect=lambda *args, **kwargs: calls.append(("buffer", args, kwargs)),
            buffer_assert_ready=lambda result: None,
        )

        self.assertEqual(report["status"], "skipped")
        self.assertEqual(report["checkpoint"], "compose-generated-ingest")
        self.assertEqual(report["stream_ids"], ["player_1"])
        self.assertEqual(report["compose"]["status"], "not_run")
        self.assertEqual(report["publish"]["status"], "not_run")
        self.assertEqual(report["buffer"]["status"], "not_run")
        self.assertEqual(calls, [])
        self.assertIn("--run", report["operator_hints"][0])

    def test_run_starts_compose_publishes_and_reports_ready_buffer(self) -> None:
        calls = []

        def run(command, **kwargs):
            calls.append(("compose", command, kwargs))
            return subprocess.CompletedProcess(command, 0, stdout="started", stderr="")

        def media_smoke(env, *, stream_ids):
            calls.append(("media", dict(env), tuple(stream_ids)))
            return FakeMediaResult(
                summaries=FakeSummaries(
                    url="http://127.0.0.1:1985/api/v1/summaries",
                    status_code=200,
                    payload_keys=("code", "data"),
                ),
                publish_results=(
                    FakePublish(
                        stream_id="player_1",
                        url="rtmp://127.0.0.1:1935/live/player_1",
                        command=("ffmpeg", "-t", "8", "rtmp://127.0.0.1/live/player_1"),
                    ),
                    FakePublish(
                        stream_id="player_2",
                        url="rtmp://127.0.0.1:1935/live/player_2",
                        command=("ffmpeg", "-t", "8", "rtmp://127.0.0.1/live/player_2"),
                    ),
                ),
            )

        def inspect_buffer(env, *, stream_ids):
            calls.append(("buffer", dict(env), tuple(stream_ids)))
            return FakeBufferResult(
                buffer_root="/dev/shm/clutchcam",
                streams=(
                    FakeStream(
                        stream_id="player_1",
                        segment_count=2,
                        latest_segment=FakeLatestSegment(
                            path="/dev/shm/clutchcam/player_1/000000001.ts",
                            start_time_seconds=2.0,
                            end_time_seconds=4.0,
                            sequence=1,
                            exists=True,
                        ),
                        clip_status="ready",
                        clip_media_uri="file:///dev/shm/clutchcam/player_1/clips/clip.m3u8",
                        clip_reason="",
                        segment_uris=("file:///dev/shm/clutchcam/player_1/000000001.ts",),
                    ),
                ),
            )

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
            run=run,
            media_smoke=media_smoke,
            buffer_inspect=inspect_buffer,
            buffer_assert_ready=assert_ready,
            sleep=lambda seconds: None,
        )

        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["failure_reason"], None)
        self.assertEqual(report["stream_ids"], ["player_1", "player_2"])
        self.assertEqual(calls[0][0], "compose")
        self.assertEqual(calls[0][1][:6], ["docker-test", "compose", "--profile", "media-server", "--profile", "buffer-worker"])
        self.assertIn("--build", calls[0][1])
        self.assertEqual(calls[0][2]["timeout"], 12)
        self.assertEqual(calls[0][2]["cwd"], str(PROJECT_DIR))
        self.assertEqual(calls[1][0], "media")
        self.assertEqual(calls[1][1]["SMOKE_SKIP_COMPOSE"], "true")
        self.assertEqual(calls[1][1]["SMOKE_SKIP_PUBLISH"], "false")
        self.assertEqual(calls[1][1]["SMOKE_PUBLISH_STREAMS"], "player_1,player_2")
        self.assertEqual(calls[2][0], "buffer")
        self.assertEqual(report["publish"]["published_stream_ids"], ["player_1", "player_2"])
        self.assertEqual(report["buffer"]["status"], "ready")
        self.assertEqual(report["buffer"]["ready_streams"], ["player_1"])
        self.assertEqual(report["buffer"]["streams"][0]["clip_status"], "ready")

    def test_compose_timeout_reports_failure_without_publishing(self) -> None:
        calls = []

        def run(command, **kwargs):
            calls.append((command, kwargs))
            raise subprocess.TimeoutExpired(command, timeout=3)

        report = checkpoint.run_generated_ingest_checkpoint(
            {},
            options=checkpoint.GeneratedIngestOptions(
                run=True,
                compose_timeout_seconds=3,
            ),
            run=run,
            media_smoke=lambda *args, **kwargs: self.fail("media should not run"),
            buffer_inspect=lambda *args, **kwargs: self.fail("buffer should not run"),
            buffer_assert_ready=lambda result: None,
        )

        self.assertEqual(report["status"], "failed")
        self.assertIn("Timed out starting Docker Compose", report["failure_reason"])
        self.assertEqual(report["compose"]["status"], "failed")
        self.assertEqual(report["publish"]["status"], "not_run")
        self.assertEqual(report["buffer"]["status"], "not_run")
        self.assertEqual(len(calls), 1)
        self.assertTrue(any("Docker" in hint for hint in report["operator_hints"]))

    def test_buffer_timeout_reports_last_inspection_details(self) -> None:
        def media_smoke(env, *, stream_ids):
            return FakeMediaResult(
                summaries=FakeSummaries(url="http://srs", status_code=200, payload_keys=()),
                publish_results=(
                    FakePublish(
                        stream_id="player_1",
                        url="rtmp://127.0.0.1:1935/live/player_1",
                        command=("ffmpeg", "rtmp://127.0.0.1:1935/live/player_1"),
                    ),
                ),
            )

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
            run=lambda *args, **kwargs: self.fail("compose should be skipped"),
            media_smoke=media_smoke,
            buffer_inspect=inspect_buffer,
            buffer_assert_ready=lambda result: (_ for _ in ()).throw(
                RuntimeError("No resolvable clips were found")
            ),
            sleep=lambda seconds: None,
        )

        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["compose"]["status"], "skipped")
        self.assertEqual(report["buffer"]["status"], "failed")
        self.assertEqual(report["buffer"]["attempts"], 1)
        self.assertEqual(report["buffer"]["streams"][0]["clip_reason"], "No segment metadata for stream.")
        self.assertIn("Buffer metadata did not become ready", report["failure_reason"])
        self.assertTrue(any("SMOKE_PUBLISH_SECONDS" in hint for hint in report["operator_hints"]))

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

        def media_smoke(env, *, stream_ids):
            return FakeMediaResult(
                summaries=FakeSummaries(url="http://srs", status_code=200, payload_keys=()),
                publish_results=(
                    FakePublish(
                        stream_id="player_1",
                        url="rtmp://127.0.0.1:1935/live/player_1",
                        command=("ffmpeg", "rtmp://127.0.0.1:1935/live/player_1"),
                    ),
                ),
            )

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
            {"LOOKBACK_BUFFER_HOST_DIR": "/mnt/ram/clutchcam"},
            options=checkpoint.GeneratedIngestOptions(
                run=True,
                skip_compose=True,
                buffer_ready_timeout_seconds=0,
            ),
            media_smoke=media_smoke,
            buffer_inspect=inspect_buffer,
            buffer_assert_ready=lambda result: None,
        )

        self.assertEqual(report["status"], "passed")
        self.assertEqual(captured_env["LOOKBACK_BUFFER_DIR"], "/mnt/ram/clutchcam")

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
