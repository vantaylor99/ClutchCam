import subprocess
import sys
import textwrap
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from config import STREAM_IDS  # noqa: E402
from contracts import (  # noqa: E402
    HypeSignal,
    LookbackClipRequest,
    SwitcherTarget,
    TranscriptEvent,
)
from services.ai import (  # noqa: E402
    HypeContext,
    TranscriptTriggerPrefilter,
    TranscriptTriggerPrefilterConfig,
)
from services.buffer import ClipResolution, ClipResolutionStatus  # noqa: E402
from services.ingestion import (  # noqa: E402
    StaticStreamSourceProvider,
    build_configured_sources,
)
from services.switcher import SwitchResult, SwitchStatus  # noqa: E402
from services.transcription import AudioInputRef  # noqa: E402


class ServiceBoundaryImportTests(unittest.TestCase):
    def test_services_import_without_runtime_client_dependencies(self) -> None:
        script = textwrap.dedent(
            f"""
            import importlib
            import sys

            sys.path.insert(0, {str(SRC_DIR)!r})
            modules = [
                "services.ingestion",
                "services.buffer",
                "services.transcription",
                "services.ai",
                "services.switcher",
            ]
            for module in modules:
                importlib.import_module(module)

            blocked = {{
                "ai_director",
                "main",
                "obs_controller",
                "obswebsocket",
                "requests",
                "scheduler",
                "transcript_router",
            }}
            imported = blocked.intersection(sys.modules)
            if imported:
                raise SystemExit(f"Unexpected runtime imports: {{sorted(imported)}}")
            """
        )

        result = subprocess.run(
            [sys.executable, "-c", script],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)


class IngestionBoundaryTests(unittest.TestCase):
    def test_builds_configured_sources_for_stable_stream_ids(self) -> None:
        sources = build_configured_sources("rtmp://localhost/live")

        self.assertEqual([source.stream_id for source in sources], list(STREAM_IDS))
        self.assertEqual(sources[0].display_name, "Player 1")
        self.assertEqual(sources[0].ingest_url, "rtmp://localhost/live/player_1")
        self.assertEqual(sources[0].scene_name, "Player 1 Fullscreen")

    def test_static_source_provider_lists_and_finds_sources(self) -> None:
        sources = build_configured_sources("rtmp://localhost/live")
        provider = StaticStreamSourceProvider(sources=sources)

        self.assertEqual(provider.list_sources(), sources)
        self.assertEqual(provider.get_source("player_3"), sources[2])
        self.assertIsNone(provider.get_source("player_9"))


class BufferBoundaryTests(unittest.TestCase):
    def test_clip_resolution_describes_ready_and_unavailable_states(self) -> None:
        request = LookbackClipRequest(stream_id="player_2", trigger_time_seconds=50.0)

        ready = ClipResolution.ready(request, media_uri="file:///buffer/player_2.m3u8")
        unavailable = ClipResolution.unavailable(request, reason="outside retention")

        self.assertEqual(ready.status, ClipResolutionStatus.READY)
        self.assertEqual(ready.start_time_seconds, 35.0)
        self.assertEqual(ready.end_time_seconds, 55.0)
        self.assertEqual(unavailable.status, ClipResolutionStatus.UNAVAILABLE)
        self.assertEqual(unavailable.reason, "outside retention")


class TranscriptionBoundaryTests(unittest.TestCase):
    def test_audio_input_refs_can_emit_transcript_events(self) -> None:
        audio = AudioInputRef(
            stream_id="player_1",
            uri="rtmp://localhost/live/player_1",
            starts_at_seconds=12.0,
        )
        event = TranscriptEvent(
            stream_id=audio.stream_id,
            text="I found the boss room",
            start_time_seconds=12.5,
            end_time_seconds=13.2,
        )

        self.assertEqual(audio.stream_id, event.stream_id)
        self.assertTrue(event.is_final)


class AIBoundaryTests(unittest.TestCase):
    def test_hype_context_accepts_transcripts_and_returns_optional_signal(self) -> None:
        event = TranscriptEvent(
            stream_id="player_4",
            text="huge moment",
            start_time_seconds=20.0,
            end_time_seconds=21.0,
        )
        context = HypeContext(transcripts=(event,), reference_time_seconds=21.0)
        signal = HypeSignal(
            stream_id=event.stream_id,
            trigger_time_seconds=context.reference_time_seconds or event.end_time_seconds,
            confidence=0.9,
            reason="Excited transcript",
        )

        self.assertEqual(signal.stream_id, "player_4")
        self.assertEqual(signal.source, "transcript")

    def test_transcript_prefilter_accepts_clear_hype_phrase(self) -> None:
        event = TranscriptEvent(
            stream_id="player_2",
            text="holy cow, look at this",
            start_time_seconds=11.0,
            end_time_seconds=12.0,
        )

        signal = TranscriptTriggerPrefilter().classify(
            HypeContext(transcripts=(event,))
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.stream_id, "player_2")
        self.assertEqual(signal.trigger_time_seconds, 12.0)
        self.assertGreaterEqual(signal.confidence, 0.7)
        self.assertEqual(signal.source, "transcript")
        self.assertIn("excitement phrase", signal.reason)

    def test_transcript_prefilter_rejects_filler_and_short_noise(self) -> None:
        classifier = TranscriptTriggerPrefilter()
        filler = TranscriptEvent("player_1", "yeah", 1.0, 1.5)
        noise = TranscriptEvent("player_1", "!!!", 2.0, 2.5)

        self.assertIsNone(classifier.classify(HypeContext(transcripts=(filler,))))
        self.assertIsNone(classifier.classify(HypeContext(transcripts=(noise,))))

    def test_transcript_prefilter_rejects_recent_duplicates_across_streams(self) -> None:
        previous = TranscriptEvent("player_1", "holy cow, this is huge", 10.0, 11.0)
        newest = TranscriptEvent("player_3", "Holy cow, look here", 12.0, 13.0)

        signal = TranscriptTriggerPrefilter().classify(
            HypeContext(transcripts=(previous, newest))
        )

        self.assertIsNone(signal)

    def test_transcript_prefilter_uses_reference_time_for_candidate(self) -> None:
        event = TranscriptEvent("player_4", "no way, rare drop", 10.0, 12.0)

        signal = TranscriptTriggerPrefilter().classify(
            HypeContext(transcripts=(event,), reference_time_seconds=99.0)
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.trigger_time_seconds, 99.0)

    def test_transcript_prefilter_can_be_disabled_by_config(self) -> None:
        event = TranscriptEvent("player_4", "no way, rare drop", 10.0, 12.0)
        classifier = TranscriptTriggerPrefilter(
            TranscriptTriggerPrefilterConfig(enabled=False)
        )

        self.assertIsNone(classifier.classify(HypeContext(transcripts=(event,))))


class SwitcherBoundaryTests(unittest.TestCase):
    def test_switch_result_wraps_immediate_or_buffered_targets(self) -> None:
        request = LookbackClipRequest(stream_id="player_3", trigger_time_seconds=100.0)
        target = SwitcherTarget(
            stream_id="player_3",
            scene_name="Player 3 Fullscreen",
            clip_request=request,
        )
        result = SwitchResult(target=target, status=SwitchStatus.APPLIED)

        self.assertEqual(result.target.clip_request, request)
        self.assertEqual(result.status, SwitchStatus.APPLIED)


if __name__ == "__main__":
    unittest.main()
