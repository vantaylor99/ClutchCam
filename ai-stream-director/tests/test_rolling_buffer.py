import os
import shutil
import subprocess
import sys
import textwrap
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
import unittest
from pathlib import Path
from urllib.parse import unquote, urlparse
from unittest.mock import patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
PROJECT_DIR = Path(__file__).resolve().parents[1]
TEST_TMP_ROOT = PROJECT_DIR / ".test-tmp"
sys.path.insert(0, str(SRC_DIR))

from config import STREAM_IDS, get_config  # noqa: E402
from contracts import LookbackClipRequest  # noqa: E402
from services.buffer import (  # noqa: E402
    ClipResolutionStatus,
    FFmpegRollingLookbackBuffer,
    FixtureLookbackBuffer,
    LookbackBufferError,
    RollingBufferConfig,
    SegmentRecord,
)


class RollingBufferFixtureTests(unittest.TestCase):
    def test_valid_stream_ids_are_accepted_and_unknown_ids_fail_clearly(self) -> None:
        with _temp_dir() as temp_dir:
            buffer = FixtureLookbackBuffer(buffer_root=temp_dir)

            for index, stream_id in enumerate(STREAM_IDS):
                record = _write_segment(temp_dir, stream_id, index, 0.0, 2.0)
                buffer.add_segment(record)

            request = LookbackClipRequest(
                stream_id="player_9",
                trigger_time_seconds=10.0,
            )
            result = buffer.resolve_clip(request)

            self.assertEqual(result.status, ClipResolutionStatus.UNAVAILABLE)
            self.assertIn("Unknown stream ID", result.reason)
            with self.assertRaisesRegex(LookbackBufferError, "Unknown stream ID"):
                buffer.add_segment(
                    _write_segment(temp_dir, "player_9", 0, 0.0, 2.0)
                )

    def test_retention_pruning_removes_expired_segments(self) -> None:
        with _temp_dir() as temp_dir:
            records = (
                _write_segment(temp_dir, "player_1", 0, 0.0, 2.0),
                _write_segment(temp_dir, "player_1", 1, 10.0, 12.0),
                _write_segment(temp_dir, "player_1", 2, 20.0, 22.0),
            )
            buffer = FixtureLookbackBuffer(
                records=records,
                buffer_root=temp_dir,
                retention_window_seconds=10.0,
                retention_slack_seconds=2.0,
            )

            removed = buffer.prune_retention("player_1", delete_files=True)

            self.assertEqual([record.path for record in removed], [records[0].path])
            self.assertFalse(records[0].path.exists())
            self.assertTrue(records[1].path.exists())
            self.assertTrue(records[2].path.exists())
            self.assertEqual(buffer.list_segments("player_1"), records[1:])

    def test_trigger_lookback_resolves_to_ordered_segment_files(self) -> None:
        with _temp_dir() as temp_dir:
            records = (
                _write_segment(temp_dir, "player_2", 0, 4.0, 8.0),
                _write_segment(temp_dir, "player_2", 1, 8.0, 12.0),
                _write_segment(temp_dir, "player_2", 2, 12.0, 16.0),
                _write_segment(temp_dir, "player_2", 3, 16.0, 20.0),
                _write_segment(temp_dir, "player_2", 4, 20.0, 24.0),
            )
            buffer = FixtureLookbackBuffer(records=records, buffer_root=temp_dir)
            request = LookbackClipRequest(
                stream_id="player_2",
                trigger_time_seconds=20.0,
                pre_roll_seconds=15,
                post_roll_seconds=1,
            )

            result = buffer.resolve_clip(request)

            self.assertEqual(result.status, ClipResolutionStatus.READY)
            self.assertEqual(result.start_time_seconds, 4.0)
            self.assertEqual(result.end_time_seconds, 24.0)
            self.assertEqual(
                result.segment_uris,
                tuple(record.media_uri for record in records),
            )
            self.assertIsNotNone(result.media_uri)
            self.assertTrue(_path_from_file_uri(result.media_uri).exists())

    def test_gaps_and_outside_retention_ranges_return_unavailable(self) -> None:
        with _temp_dir() as temp_dir:
            gap_buffer = FixtureLookbackBuffer(
                records=(
                    _write_segment(temp_dir, "player_3", 0, 0.0, 5.0),
                    _write_segment(temp_dir, "player_3", 1, 10.0, 15.0),
                ),
                buffer_root=temp_dir,
            )
            gap_request = LookbackClipRequest(
                stream_id="player_3",
                trigger_time_seconds=12.0,
                pre_roll_seconds=8,
                post_roll_seconds=0,
            )

            gap_result = gap_buffer.resolve_clip(gap_request)

            self.assertEqual(gap_result.status, ClipResolutionStatus.UNAVAILABLE)
            self.assertIn("Segment gap", gap_result.reason)

            old_segment = _write_segment(temp_dir, "player_4", 0, 0.0, 2.0)
            new_segment = _write_segment(temp_dir, "player_4", 1, 40.0, 42.0)
            old_buffer = FixtureLookbackBuffer(
                records=(old_segment, new_segment),
                buffer_root=temp_dir,
                retention_window_seconds=10.0,
                retention_slack_seconds=2.0,
            )
            old_request = LookbackClipRequest(
                stream_id="player_4",
                trigger_time_seconds=1.0,
                pre_roll_seconds=1,
                post_roll_seconds=1,
            )

            old_result = old_buffer.resolve_clip(old_request)

            self.assertEqual(old_result.status, ClipResolutionStatus.UNAVAILABLE)
            self.assertIn("outside retained", old_result.reason)

    def test_request_ending_just_beyond_latest_segment_returns_pending(self) -> None:
        with _temp_dir() as temp_dir:
            buffer = FixtureLookbackBuffer(
                records=(
                    _write_segment(temp_dir, "player_1", 0, 0.0, 5.0),
                    _write_segment(temp_dir, "player_1", 1, 5.0, 10.0),
                ),
                buffer_root=temp_dir,
                segment_duration_seconds=2.0,
            )
            request = LookbackClipRequest(
                stream_id="player_1",
                trigger_time_seconds=8.0,
                pre_roll_seconds=2,
                post_roll_seconds=3,
            )

            result = buffer.resolve_clip(request)

            self.assertEqual(result.status, ClipResolutionStatus.PENDING)
            self.assertIn("newer than the latest segment", result.reason)

    def test_far_future_trigger_with_large_preroll_is_unavailable(self) -> None:
        with _temp_dir() as temp_dir:
            buffer = FixtureLookbackBuffer(
                records=(
                    _write_segment(temp_dir, "player_1", 0, 0.0, 5.0),
                    _write_segment(temp_dir, "player_1", 1, 5.0, 10.0),
                ),
                buffer_root=temp_dir,
                segment_duration_seconds=2.0,
            )
            request = LookbackClipRequest(
                stream_id="player_1",
                trigger_time_seconds=100.0,
                pre_roll_seconds=100,
                post_roll_seconds=3,
            )

            result = buffer.resolve_clip(request)

            self.assertEqual(result.status, ClipResolutionStatus.UNAVAILABLE)
            self.assertIn("ends after retained media", result.reason)

    def test_overlapping_segments_are_merged_for_gap_detection(self) -> None:
        with _temp_dir() as temp_dir:
            records = (
                _write_segment(temp_dir, "player_2", 0, 0.0, 10.0),
                _write_segment(temp_dir, "player_2", 1, 2.0, 3.0),
                _write_segment(temp_dir, "player_2", 2, 10.1, 12.0),
            )
            buffer = FixtureLookbackBuffer(records=records, buffer_root=temp_dir)
            request = LookbackClipRequest(
                stream_id="player_2",
                trigger_time_seconds=11.0,
                pre_roll_seconds=11,
                post_roll_seconds=1,
            )

            result = buffer.resolve_clip(request)

            self.assertEqual(result.status, ClipResolutionStatus.READY)
            self.assertEqual(
                result.segment_uris,
                tuple(record.media_uri for record in records),
            )


class FFmpegRollingBufferTests(unittest.TestCase):
    def test_ffmpeg_command_uses_configured_runtime_values(self) -> None:
        with _temp_dir() as temp_dir:
            config = RollingBufferConfig(
                buffer_root=temp_dir,
                stream_input_urls={"player_1": "srt://127.0.0.1:9001"},
                stream_ids=("player_1",),
                ffmpeg_executable="custom-ffmpeg",
                segment_duration_seconds=3.5,
                retention_window_seconds=21.0,
            )
            buffer = FFmpegRollingLookbackBuffer(config)

            command = buffer.build_ffmpeg_command("player_1")

            self.assertEqual(command[0], "custom-ffmpeg")
            self.assertIn("srt://127.0.0.1:9001", command)
            self.assertIn("3.5", command)
            self.assertIn(str(Path(temp_dir) / "player_1" / "segments.csv"), command)
            self.assertIn(str(Path(temp_dir) / "player_1" / "%09d.ts"), command)

    def test_start_rejects_missing_input_urls_before_subprocess_launch(self) -> None:
        with _temp_dir() as temp_dir:
            config = RollingBufferConfig(
                buffer_root=temp_dir,
                stream_input_urls={},
                stream_ids=("player_1",),
            )
            buffer = FFmpegRollingLookbackBuffer(config)

            with patch("services.buffer.subprocess.Popen") as popen:
                with self.assertRaisesRegex(LookbackBufferError, "Missing input URLs"):
                    buffer.start()

            popen.assert_not_called()

    def test_refresh_metadata_ignores_segment_paths_outside_stream_dir(self) -> None:
        with _temp_dir() as temp_dir:
            stream_dir = Path(temp_dir) / "player_1"
            stream_dir.mkdir(parents=True)
            outside_segment = Path(temp_dir) / "outside.ts"
            outside_segment.write_bytes(b"outside media")
            (stream_dir / "segments.csv").write_text(
                f"{outside_segment},0.0,2.0\n",
                encoding="utf-8",
            )
            config = RollingBufferConfig(
                buffer_root=temp_dir,
                stream_input_urls={"player_1": "rtmp://localhost/live/player_1"},
                stream_ids=("player_1",),
            )
            buffer = FFmpegRollingLookbackBuffer(config)

            buffer.refresh_metadata("player_1")

            self.assertEqual(buffer.list_segments("player_1"), ())


class RollingBufferEnvironmentConfigTests(unittest.TestCase):
    def test_app_config_exposes_buffer_runtime_defaults(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = get_config()

        self.assertEqual(config.lookback_segment_seconds, 2.0)
        self.assertEqual(config.ffmpeg_executable, "ffmpeg")
        self.assertEqual(
            config.lookback_input_urls["player_1"],
            "rtmp://localhost/live/player_1",
        )

    def test_app_config_accepts_per_stream_buffer_input_override(self) -> None:
        with patch.dict(
            os.environ,
            {
                "INGEST_API_URL": "srt://media-router/live",
                "LOOKBACK_INPUT_URL_PLAYER_3": "srt://player-three:9000",
            },
            clear=True,
        ):
            config = get_config()

        self.assertEqual(
            config.lookback_input_urls["player_1"],
            "srt://media-router/live/player_1",
        )
        self.assertEqual(
            config.lookback_input_urls["player_3"],
            "srt://player-three:9000",
        )

    def test_env_example_documents_buffer_runtime_settings(self) -> None:
        env_example = (PROJECT_DIR / ".env.example").read_text()

        self.assertIn("LOOKBACK_SEGMENT_SECONDS=2", env_example)
        self.assertIn("FFMPEG_EXECUTABLE=ffmpeg", env_example)
        self.assertIn(
            "LOOKBACK_INPUT_URL_PLAYER_1=rtmp://media-server:1935/live/player_1",
            env_example,
        )


class RollingBufferImportTests(unittest.TestCase):
    def test_buffer_import_does_not_create_configured_buffer_directory(self) -> None:
        with _temp_dir() as temp_dir:
            buffer_dir = Path(temp_dir) / "lookback"
            script = textwrap.dedent(
                f"""
                import importlib
                import os
                import sys
                from pathlib import Path

                sys.path.insert(0, {str(SRC_DIR)!r})
                os.environ["LOOKBACK_BUFFER_DIR"] = {str(buffer_dir)!r}
                importlib.import_module("services.buffer")
                if Path(os.environ["LOOKBACK_BUFFER_DIR"]).exists():
                    raise SystemExit("buffer import created LOOKBACK_BUFFER_DIR")
                """
            )

            result = subprocess.run(
                [sys.executable, "-c", script],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)


def _write_segment(
    root: str,
    stream_id: str,
    sequence: int,
    start_time_seconds: float,
    end_time_seconds: float,
) -> SegmentRecord:
    path = Path(root) / stream_id / f"{sequence:09d}.ts"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fixture media")
    return SegmentRecord(
        stream_id=stream_id,
        path=path,
        start_time_seconds=start_time_seconds,
        end_time_seconds=end_time_seconds,
        sequence=sequence,
    )


@contextmanager
def _temp_dir() -> Iterator[str]:
    TEST_TMP_ROOT.mkdir(exist_ok=True)
    path = TEST_TMP_ROOT / uuid.uuid4().hex
    path.mkdir()
    try:
        yield str(path)
    finally:
        shutil.rmtree(path, ignore_errors=True)
        try:
            TEST_TMP_ROOT.rmdir()
        except OSError:
            pass


def _path_from_file_uri(uri: str) -> Path:
    parsed = urlparse(uri)
    path = unquote(parsed.path)
    if os.name == "nt" and path.startswith("/") and path[2:3] == ":":
        path = path[1:]
    return Path(path)


if __name__ == "__main__":
    unittest.main()
