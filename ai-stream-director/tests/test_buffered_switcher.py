import tempfile
import unittest
from pathlib import Path

import sys


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from config import SCENES  # noqa: E402
from contracts import HypeSignal, LookbackClipRequest, SwitcherTarget  # noqa: E402
from services.buffer import FixtureLookbackBuffer, SegmentRecord  # noqa: E402
from services.switcher import (  # noqa: E402
    BufferBackedSwitcher,
    MediaSourceOutputSwitcher,
    OutputSwitchError,
    SceneOutputSwitcher,
    SwitchStatus,
    buffered_target_from_signal,
    build_buffered_target,
)


class BufferBackedSwitcherTests(unittest.TestCase):
    def test_buffered_target_from_signal_uses_preroll_and_stream_scene(self) -> None:
        signal = HypeSignal(
            stream_id="player_3",
            trigger_time_seconds=42.0,
            confidence=0.91,
            reason="excited transcript",
        )

        target = buffered_target_from_signal(signal, pre_roll_seconds=15)

        self.assertEqual(target.stream_id, "player_3")
        self.assertEqual(target.scene_name, SCENES["player_3"])
        self.assertIsNotNone(target.clip_request)
        self.assertEqual(target.clip_request.start_time_seconds, 27.0)
        self.assertEqual(target.clip_request.end_time_seconds, 47.0)

    def test_buffered_target_from_signal_rejects_unknown_scene_mapping(self) -> None:
        signal = HypeSignal(
            stream_id="player_9",
            trigger_time_seconds=42.0,
            confidence=0.91,
            reason="excited transcript",
        )

        with self.assertRaisesRegex(OutputSwitchError, "No scene is configured"):
            buffered_target_from_signal(
                signal,
                scene_map={},
                pre_roll_seconds=15,
            )

    def test_ready_buffered_clip_returns_applied_media_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            buffer = _fixture_buffer(
                temp_dir,
                [
                    ("player_2", "000.ts", 0.0, 2.0),
                    ("player_2", "001.ts", 2.0, 4.0),
                    ("player_2", "002.ts", 4.0, 6.0),
                ],
            )
            target = build_buffered_target(
                stream_id="player_2",
                scene_name=SCENES["player_2"],
                trigger_time_seconds=4.0,
                pre_roll_seconds=4,
                post_roll_seconds=1,
            )

            result = BufferBackedSwitcher(buffer, clock=lambda: 123.4).switch(target)

        self.assertEqual(result.status, SwitchStatus.APPLIED)
        self.assertEqual(result.switched_at_seconds, 123.4)
        self.assertEqual(result.target.stream_id, "player_2")
        self.assertEqual(result.target.scene_name, SCENES["player_2"])
        self.assertIsNotNone(result.target.media_uri)
        self.assertTrue(result.target.media_uri.endswith(".m3u8"))
        self.assertEqual(len(result.segment_uris), 3)

    def test_ready_clip_can_be_passed_to_downstream_scene_switcher(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            buffer = _fixture_buffer(
                temp_dir,
                [
                    ("player_1", "000.ts", 0.0, 2.0),
                    ("player_1", "001.ts", 2.0, 4.0),
                ],
            )
            controller = RecordingSceneController()
            target = build_buffered_target(
                stream_id="player_1",
                scene_name=SCENES["player_1"],
                trigger_time_seconds=3.0,
                pre_roll_seconds=3,
                post_roll_seconds=1,
            )

            result = BufferBackedSwitcher(
                buffer,
                downstream=SceneOutputSwitcher(controller, clock=lambda: 200.0),
            ).switch(target)

        self.assertEqual(result.status, SwitchStatus.APPLIED)
        self.assertEqual(result.switched_at_seconds, 200.0)
        self.assertEqual(controller.scenes, [SCENES["player_1"]])
        self.assertIsNotNone(result.target.media_uri)

    def test_ready_clip_can_update_media_source_before_scene_cut(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            buffer = _fixture_buffer(
                temp_dir,
                [
                    ("player_2", "000.ts", 0.0, 2.0),
                    ("player_2", "001.ts", 2.0, 4.0),
                ],
            )
            controller = RecordingMediaSceneController()
            target = build_buffered_target(
                stream_id="player_2",
                scene_name=SCENES["player_2"],
                trigger_time_seconds=3.0,
                pre_roll_seconds=3,
                post_roll_seconds=1,
            )

            result = BufferBackedSwitcher(
                buffer,
                downstream=MediaSourceOutputSwitcher(
                    controller,
                    media_source_name="ClutchCam Buffered Playback",
                    clock=lambda: 201.0,
                ),
            ).switch(target)

        self.assertEqual(result.status, SwitchStatus.APPLIED)
        self.assertEqual(result.switched_at_seconds, 201.0)
        self.assertIsNotNone(result.target.media_uri)
        self.assertEqual(
            controller.calls,
            [
                (
                    "media",
                    "ClutchCam Buffered Playback",
                    result.target.media_uri,
                ),
                ("scene", SCENES["player_2"]),
            ],
        )

    def test_media_source_switcher_rejects_target_without_media_uri(self) -> None:
        controller = RecordingMediaSceneController()
        switcher = MediaSourceOutputSwitcher(
            controller,
            media_source_name="ClutchCam Buffered Playback",
        )

        result = switcher.switch(
            SwitcherTarget(stream_id="player_1", scene_name=SCENES["player_1"])
        )

        self.assertEqual(result.status, SwitchStatus.REJECTED)
        self.assertIn("requires a media URI", result.reason)
        self.assertEqual(controller.calls, [])

    def test_pending_clip_returns_pending_without_downstream_switch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            buffer = _fixture_buffer(
                temp_dir,
                [
                    ("player_4", "000.ts", 0.0, 2.0),
                    ("player_4", "001.ts", 2.0, 4.0),
                ],
            )
            controller = RecordingSceneController()
            target = build_buffered_target(
                stream_id="player_4",
                scene_name=SCENES["player_4"],
                trigger_time_seconds=4.0,
                pre_roll_seconds=2,
                post_roll_seconds=2,
            )

            result = BufferBackedSwitcher(
                buffer,
                downstream=SceneOutputSwitcher(controller),
            ).switch(target)

        self.assertEqual(result.status, SwitchStatus.PENDING)
        self.assertIn("newer than the latest segment", result.reason)
        self.assertEqual(controller.scenes, [])
        self.assertIsNone(result.target.media_uri)

    def test_unavailable_clip_returns_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            buffer = _fixture_buffer(
                temp_dir,
                [("player_2", "000.ts", 20.0, 22.0)],
            )
            target = build_buffered_target(
                stream_id="player_2",
                scene_name=SCENES["player_2"],
                trigger_time_seconds=4.0,
                pre_roll_seconds=2,
                post_roll_seconds=1,
            )

            result = BufferBackedSwitcher(buffer).switch(target)

        self.assertEqual(result.status, SwitchStatus.REJECTED)
        self.assertIn("outside retained segments", result.reason)

    def test_unknown_stream_returns_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            buffer = _fixture_buffer(temp_dir, [])
            target = build_buffered_target(
                stream_id="player_9",
                scene_name="Player 9 Fullscreen",
                trigger_time_seconds=4.0,
                pre_roll_seconds=2,
            )

            result = BufferBackedSwitcher(buffer).switch(target)

        self.assertEqual(result.status, SwitchStatus.REJECTED)
        self.assertIn("Unknown stream ID", result.reason)

    def test_missing_clip_request_returns_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            buffer = _fixture_buffer(temp_dir, [])
            target = SwitcherTarget(
                stream_id="player_1",
                scene_name=SCENES["player_1"],
            )

            result = BufferBackedSwitcher(buffer).switch(target)

        self.assertEqual(result.status, SwitchStatus.REJECTED)
        self.assertIn("requires a clip request", result.reason)

    def test_scene_output_switcher_surfaces_controller_failures(self) -> None:
        switcher = SceneOutputSwitcher(FailingSceneController())

        with self.assertRaisesRegex(OutputSwitchError, "Scene switch failed"):
            switcher.switch(
                SwitcherTarget(stream_id="player_1", scene_name=SCENES["player_1"])
            )


class ImmediateSceneSwitchRegressionTests(unittest.TestCase):
    def test_immediate_switch_target_still_does_not_require_clip_request(self) -> None:
        controller = RecordingSceneController()
        target = SwitcherTarget(stream_id="player_3", scene_name=SCENES["player_3"])

        result = SceneOutputSwitcher(controller, clock=lambda: 5.0).switch(target)

        self.assertEqual(result.status, SwitchStatus.APPLIED)
        self.assertEqual(result.switched_at_seconds, 5.0)
        self.assertEqual(controller.scenes, [SCENES["player_3"]])
        self.assertIsNone(result.target.clip_request)
        self.assertIsNone(result.target.media_uri)


class RecordingSceneController:
    def __init__(self) -> None:
        self.scenes: list[str] = []

    def set_scene(self, scene_name: str) -> None:
        self.scenes.append(scene_name)


class RecordingMediaSceneController:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def set_media_source(self, source_name: str, media_uri: str) -> None:
        self.calls.append(("media", source_name, media_uri))

    def set_scene(self, scene_name: str) -> None:
        self.calls.append(("scene", scene_name))


class FailingSceneController:
    def set_scene(self, scene_name: str) -> None:
        raise RuntimeError("offline")


def _fixture_buffer(
    temp_dir: str,
    segment_specs: list[tuple[str, str, float, float]],
) -> FixtureLookbackBuffer:
    records = []
    for stream_id, file_name, start, end in segment_specs:
        stream_dir = Path(temp_dir) / stream_id
        stream_dir.mkdir(parents=True, exist_ok=True)
        segment_path = stream_dir / file_name
        segment_path.write_bytes(b"segment")
        records.append(
            SegmentRecord(
                stream_id=stream_id,
                path=segment_path,
                start_time_seconds=start,
                end_time_seconds=end,
            )
        )

    return FixtureLookbackBuffer(records=records, buffer_root=temp_dir)


if __name__ == "__main__":
    unittest.main()
