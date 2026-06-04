import os
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname
from unittest.mock import patch

import sys


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from config import SCENES, get_config  # noqa: E402
from contracts import TranscriptEvent  # noqa: E402
from services.ai import HypeContext, TranscriptTriggerPrefilter  # noqa: E402
from services.buffer import FixtureLookbackBuffer, SegmentRecord  # noqa: E402
from services.switcher import (  # noqa: E402
    BufferBackedSwitcher,
    SwitchStatus,
    buffered_target_from_signal,
)
from transcript_router import TranscriptRouter  # noqa: E402


class SampleMediaIntegrationHarnessTests(unittest.TestCase):
    def test_triggered_transcript_resolves_buffered_sample_clip(self) -> None:
        config = _test_config()
        self.assertGreater(config.switch_lookback_seconds, 0)

        clip_start_seconds = 27.0
        trigger_time_seconds = clip_start_seconds + config.switch_lookback_seconds
        stream_id = "player_2"
        clip_end_seconds = trigger_time_seconds + 5
        first_cut = clip_start_seconds + (config.switch_lookback_seconds / 3)
        second_cut = clip_start_seconds + (config.switch_lookback_seconds * 2 / 3)

        with tempfile.TemporaryDirectory() as temp_dir:
            buffer = _fixture_buffer(
                temp_dir,
                [
                    (stream_id, "000.ts", clip_start_seconds, first_cut),
                    (stream_id, "001.ts", first_cut, second_cut),
                    (stream_id, "002.ts", second_cut, trigger_time_seconds),
                    (stream_id, "003.ts", trigger_time_seconds, clip_end_seconds),
                ],
            )
            routed_event = _route_event(
                TranscriptEvent(
                    stream_id=stream_id,
                    text="holy cow, look at this clutch play",
                    start_time_seconds=41.5,
                    end_time_seconds=trigger_time_seconds,
                )
            )
            signal = TranscriptTriggerPrefilter().classify(
                HypeContext(transcripts=(routed_event,))
            )

            self.assertIsNotNone(signal)
            target = buffered_target_from_signal(
                signal,
                pre_roll_seconds=config.switch_lookback_seconds,
            )
            result = BufferBackedSwitcher(buffer, clock=lambda: 1000.0).switch(target)

            playlist_path = _path_from_file_uri(result.target.media_uri)

            self.assertEqual(result.status, SwitchStatus.APPLIED)
            self.assertEqual(result.target.stream_id, stream_id)
            self.assertEqual(result.target.scene_name, SCENES[stream_id])
            self.assertEqual(
                result.target.clip_request.start_time_seconds,
                clip_start_seconds,
            )
            self.assertEqual(
                result.target.clip_request.end_time_seconds,
                clip_end_seconds,
            )
            self.assertEqual(result.target.media_uri, playlist_path.as_uri())
            self.assertEqual(result.switched_at_seconds, 1000.0)
            self.assertEqual(len(result.segment_uris), 4)
            self.assertTrue(
                all(uri.startswith("file://") for uri in result.segment_uris)
            )
            self.assertTrue(playlist_path.exists())
            self.assertTrue(playlist_path.name.startswith("clip_"))
            self.assertEqual(playlist_path.suffix, ".m3u8")
            self.assertLess(
                result.target.clip_request.start_time_seconds,
                trigger_time_seconds,
            )

    def test_non_trigger_transcript_does_not_build_switch_target(self) -> None:
        routed_event = _route_event(
            TranscriptEvent(
                stream_id="player_1",
                text="rotating back to mid lane",
                start_time_seconds=10.0,
                end_time_seconds=10.5,
            )
        )

        signal = TranscriptTriggerPrefilter().classify(
            HypeContext(transcripts=(routed_event,))
        )

        self.assertIsNone(signal)

    def test_trigger_with_insufficient_media_rejects_buffered_switch(self) -> None:
        config = _test_config()
        requested_start_seconds = 42.0
        trigger_time_seconds = requested_start_seconds + config.switch_lookback_seconds
        stream_id = "player_3"

        with tempfile.TemporaryDirectory() as temp_dir:
            buffer = _fixture_buffer(
                temp_dir,
                [
                    (
                        stream_id,
                        "000.ts",
                        requested_start_seconds + 1,
                        trigger_time_seconds + 5,
                    ),
                ],
            )
            signal = TranscriptTriggerPrefilter().classify(
                HypeContext(
                    transcripts=(
                        TranscriptEvent(
                            stream_id=stream_id,
                            text="no way, rare drop right here",
                            start_time_seconds=41.0,
                            end_time_seconds=trigger_time_seconds,
                        ),
                    )
                )
            )

            self.assertIsNotNone(signal)
            target = buffered_target_from_signal(
                signal,
                pre_roll_seconds=config.switch_lookback_seconds,
            )
            result = BufferBackedSwitcher(buffer).switch(target)

        self.assertEqual(result.status, SwitchStatus.REJECTED)
        self.assertIn("starts before retained media", result.reason)
        self.assertIsNone(result.target.media_uri)
        self.assertEqual(result.segment_uris, ())


def _route_event(event: TranscriptEvent) -> TranscriptEvent:
    router = TranscriptRouter()
    message = router.add_event(event)

    if message is None:
        raise AssertionError("Fixture transcript event should be accepted.")

    recent_events = router.get_recent_events()
    if len(recent_events) != 1:
        raise AssertionError("Expected one routed transcript event.")

    return recent_events[0]


def _test_config():
    with patch.dict(os.environ, {"SWITCH_LOOKBACK_SECONDS": "15"}, clear=False):
        return get_config()


def _fixture_buffer(
    temp_dir: str,
    segment_specs: list[tuple[str, str, float, float]],
) -> FixtureLookbackBuffer:
    records = []
    for stream_id, file_name, start, end in segment_specs:
        stream_dir = Path(temp_dir) / stream_id
        stream_dir.mkdir(parents=True, exist_ok=True)
        segment_path = stream_dir / file_name
        segment_path.write_bytes(b"deterministic segment fixture")
        records.append(
            SegmentRecord(
                stream_id=stream_id,
                path=segment_path,
                start_time_seconds=start,
                end_time_seconds=end,
            )
        )

    return FixtureLookbackBuffer(records=records, buffer_root=temp_dir)


def _path_from_file_uri(media_uri: str | None) -> Path:
    if media_uri is None:
        raise AssertionError("Expected buffered switch result to include media URI.")

    parsed = urlparse(media_uri)
    if parsed.scheme != "file":
        raise AssertionError(f"Expected file URI, got {media_uri!r}.")

    return Path(url2pathname(parsed.path))


if __name__ == "__main__":
    unittest.main()
