import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from config import get_config  # noqa: E402
from services.transcription import (  # noqa: E402
    AudioExtractionConfig,
    FFmpegAudioExtractor,
    FixtureAudioExtractor,
    TranscriptionError,
)


class AudioExtractionConfigTests(unittest.TestCase):
    def test_app_config_exposes_audio_extraction_defaults(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = get_config()

        self.assertEqual(config.audio_extract_dir, "/dev/shm/clutchcam-audio")
        self.assertEqual(config.audio_extract_sample_rate, 16000)
        self.assertEqual(config.audio_extract_channels, 1)
        self.assertEqual(config.audio_extract_chunk_seconds, 5.0)
        self.assertEqual(config.audio_extract_codec, "pcm_s16le")
        self.assertEqual(config.audio_extract_container, "wav")
        self.assertEqual(
            config.audio_input_urls["player_1"],
            "rtmp://localhost/live/player_1",
        )

    def test_audio_input_urls_fall_back_through_lookback_inputs(self) -> None:
        with patch.dict(
            os.environ,
            {
                "INGEST_API_URL": "rtmp://media-server:1935/live",
                "LOOKBACK_INPUT_URL_PLAYER_2": "srt://lookback-player-two:10080",
                "AUDIO_INPUT_URL_PLAYER_3": "rtmp://audio-player-three/live",
            },
            clear=True,
        ):
            config = get_config()

        self.assertEqual(
            config.audio_input_urls["player_1"],
            "rtmp://media-server:1935/live/player_1",
        )
        self.assertEqual(
            config.audio_input_urls["player_2"],
            "srt://lookback-player-two:10080",
        )
        self.assertEqual(
            config.audio_input_urls["player_3"],
            "rtmp://audio-player-three/live",
        )

    def test_audio_extraction_config_rejects_unknown_input_ids(self) -> None:
        with self.assertRaisesRegex(TranscriptionError, "unknown stream IDs"):
            AudioExtractionConfig(
                output_dir="audio",
                stream_input_urls={"player_9": "rtmp://example/live/player_9"},
            )


class FFmpegAudioExtractorTests(unittest.TestCase):
    def test_ffmpeg_command_uses_configured_audio_values(self) -> None:
        config = AudioExtractionConfig(
            output_dir="audio-cache",
            stream_input_urls={"player_1": "rtmp://media/live/player_1"},
            stream_ids=("player_1",),
            ffmpeg_executable="ffmpeg-test",
            sample_rate_hz=24000,
            channels=2,
            chunk_duration_seconds=3,
            codec="pcm_s16le",
            container="wav",
        )

        command = FFmpegAudioExtractor(config).build_ffmpeg_command("player_1")

        self.assertEqual(command[0], "ffmpeg-test")
        self.assertIn("rtmp://media/live/player_1", command)
        self.assertIn("-vn", command)
        self.assertIn("2", command)
        self.assertIn("24000", command)
        self.assertIn("3", command)
        self.assertTrue(str(command[-1]).endswith("player_1\\%09d.wav") or str(command[-1]).endswith("player_1/%09d.wav"))

    def test_missing_input_url_fails_before_subprocess_launch(self) -> None:
        config = AudioExtractionConfig(
            output_dir="audio-cache",
            stream_input_urls={},
            stream_ids=("player_1",),
        )

        with self.assertRaisesRegex(TranscriptionError, "Missing audio input URL"):
            FFmpegAudioExtractor(config).build_ffmpeg_command("player_1")

    def test_sessions_preserve_stream_identity_before_start(self) -> None:
        config = AudioExtractionConfig(
            output_dir="audio-cache",
            stream_input_urls={"player_1": "rtmp://media/live/player_1"},
            stream_ids=("player_1",),
        )

        sessions = FFmpegAudioExtractor(config).sessions()

        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].stream_id, "player_1")
        self.assertFalse(sessions[0].running)


class FixtureAudioExtractorTests(unittest.TestCase):
    def test_fixture_audio_ref_preserves_timestamp_and_stream_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            chunk_path = Path(tmpdir) / "chunk.wav"
            chunk_path.write_bytes(b"fixture")
            config = AudioExtractionConfig(
                output_dir=tmpdir,
                stream_input_urls={"player_2": "rtmp://media/live/player_2"},
                stream_ids=("player_2",),
                chunk_duration_seconds=4,
            )

            audio_ref = FixtureAudioExtractor(config).build_audio_ref(
                "player_2",
                chunk_path,
                starts_at_seconds=12.5,
            )

        self.assertEqual(audio_ref.stream_id, "player_2")
        self.assertEqual(audio_ref.starts_at_seconds, 12.5)
        self.assertEqual(audio_ref.duration_seconds, 4.0)
        self.assertEqual(audio_ref.codec, "pcm_s16le")
        self.assertEqual(audio_ref.sample_rate_hz, 16000)
        self.assertEqual(audio_ref.channels, 1)

    def test_unknown_fixture_stream_id_fails_clearly(self) -> None:
        config = AudioExtractionConfig(
            output_dir="audio-cache",
            stream_input_urls={"player_1": "rtmp://media/live/player_1"},
            stream_ids=("player_1",),
        )

        with self.assertRaisesRegex(TranscriptionError, "Unknown stream ID"):
            FixtureAudioExtractor(config).build_audio_ref(
                "player_4",
                "missing.wav",
            )


if __name__ == "__main__":
    unittest.main()
