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
from services.switcher import (  # noqa: E402
    BufferBackedSwitcher,
    SwitchResult,
    SwitchStatus,
    buffered_target_from_signal,
)
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
                "services.telemetry",
                "services.health",
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

    def test_transcript_prefilter_accepts_split_same_stream_hype_phrase(self) -> None:
        previous = TranscriptEvent("player_2", "holy", 10.0, 11.0)
        newest = TranscriptEvent("player_2", "cow", 11.5, 12.0)

        signal = TranscriptTriggerPrefilter().classify(
            HypeContext(
                transcripts=(previous, newest),
                reference_time_seconds=21.0,
            )
        )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.stream_id, "player_2")
        self.assertEqual(signal.trigger_time_seconds, 21.0)
        self.assertIn("excitement phrase: holy cow", signal.reason)

    def test_transcript_prefilter_rejects_split_phrase_outside_context_window(self) -> None:
        classifier = TranscriptTriggerPrefilter(
            TranscriptTriggerPrefilterConfig(context_window_seconds=2.0)
        )
        previous = TranscriptEvent("player_2", "holy", 9.0, 10.0)
        newest = TranscriptEvent("player_2", "cow", 12.5, 13.0)

        signal = classifier.classify(HypeContext(transcripts=(previous, newest)))

        self.assertIsNone(signal)

    def test_transcript_prefilter_does_not_join_other_stream_fragments(self) -> None:
        previous = TranscriptEvent("player_1", "holy", 10.0, 11.0)
        newest = TranscriptEvent("player_2", "cow", 11.5, 12.0)

        signal = TranscriptTriggerPrefilter().classify(
            HypeContext(transcripts=(previous, newest))
        )

        self.assertIsNone(signal)

    def test_transcript_prefilter_rejects_filler_and_short_noise(self) -> None:
        classifier = TranscriptTriggerPrefilter()
        filler = TranscriptEvent("player_1", "yeah", 1.0, 1.5)
        noise = TranscriptEvent("player_1", "!!!", 2.0, 2.5)

        self.assertIsNone(classifier.classify(HypeContext(transcripts=(filler,))))
        self.assertIsNone(classifier.classify(HypeContext(transcripts=(noise,))))

    def test_transcript_prefilter_accepts_live_gaming_callouts(self) -> None:
        classifier = TranscriptTriggerPrefilter()

        for text in (
            "that was nasty",
            "behind you",
            "good work",
            "triple",
            "legend",
        ):
            with self.subTest(text=text):
                event = TranscriptEvent("player_1", text, 3.0, 4.0)
                signal = classifier.classify(HypeContext(transcripts=(event,)))

                self.assertIsNotNone(signal)
                self.assertGreaterEqual(signal.confidence, 0.7)
                self.assertIn("gaming callout phrase", signal.reason)

    def test_transcript_prefilter_accepts_exact_short_help_callout_only(self) -> None:
        classifier = TranscriptTriggerPrefilter()
        help_event = TranscriptEvent("player_1", "help", 3.0, 4.0)
        short_filler = TranscriptEvent("player_1", "ok", 5.0, 6.0)

        signal = classifier.classify(HypeContext(transcripts=(help_event,)))

        self.assertIsNotNone(signal)
        self.assertIn("gaming callout phrase: help", signal.reason)
        self.assertIsNone(classifier.classify(HypeContext(transcripts=(short_filler,))))

    def test_transcript_prefilter_accepts_short_help_after_prior_context(self) -> None:
        previous = TranscriptEvent("player_1", "checking stairs", 3.0, 4.0)
        help_event = TranscriptEvent("player_1", "help", 5.0, 6.0)

        signal = TranscriptTriggerPrefilter().classify(
            HypeContext(transcripts=(previous, help_event))
        )

        self.assertIsNotNone(signal)
        self.assertIn("gaming callout phrase: help", signal.reason)

    def test_transcript_prefilter_rejects_recent_duplicates_across_streams(self) -> None:
        previous = TranscriptEvent("player_1", "holy cow, this is huge", 10.0, 11.0)
        newest = TranscriptEvent("player_3", "Holy cow, look here", 12.0, 13.0)

        signal = TranscriptTriggerPrefilter().classify(
            HypeContext(transcripts=(previous, newest))
        )

        self.assertIsNone(signal)

    def test_transcript_prefilter_rejects_repeated_split_phrase_inside_duplicate_window(self) -> None:
        classifier = TranscriptTriggerPrefilter()
        first_holy = TranscriptEvent("player_2", "holy", 10.0, 11.0)
        first_cow = TranscriptEvent("player_2", "cow", 11.5, 12.0)
        second_holy = TranscriptEvent("player_2", "holy", 14.0, 15.0)
        second_cow = TranscriptEvent("player_2", "cow", 15.5, 16.0)

        first_signal = classifier.classify(
            HypeContext(transcripts=(first_holy, first_cow))
        )
        second_signal = classifier.classify(
            HypeContext(
                transcripts=(first_holy, first_cow, second_holy, second_cow)
            )
        )

        self.assertIsNotNone(first_signal)
        self.assertIsNone(second_signal)

    def test_transcript_prefilter_rejects_cross_stream_repeated_split_phrase_inside_duplicate_window(self) -> None:
        first_holy = TranscriptEvent("player_1", "holy", 10.0, 11.0)
        first_cow = TranscriptEvent("player_1", "cow", 11.5, 12.0)
        second_holy = TranscriptEvent("player_3", "holy", 14.0, 15.0)
        second_cow = TranscriptEvent("player_3", "cow", 15.5, 16.0)

        signal = TranscriptTriggerPrefilter().classify(
            HypeContext(
                transcripts=(first_holy, first_cow, second_holy, second_cow)
            )
        )

        self.assertIsNone(signal)

    def test_transcript_prefilter_does_not_retrigger_stale_context_phrase(self) -> None:
        old_signal = TranscriptEvent("player_2", "holy cow", 10.0, 11.0)
        newest_filler = TranscriptEvent("player_2", "okay", 29.0, 30.0)

        signal = TranscriptTriggerPrefilter().classify(
            HypeContext(transcripts=(old_signal, newest_filler))
        )

        self.assertIsNone(signal)

    def test_transcript_prefilter_accepts_newer_same_stream_phrase_after_old_signal(self) -> None:
        old_signal = TranscriptEvent("player_2", "holy cow", 10.0, 11.0)
        newest_signal = TranscriptEvent("player_2", "look at this", 14.0, 15.0)

        signal = TranscriptTriggerPrefilter().classify(
            HypeContext(transcripts=(old_signal, newest_signal))
        )

        self.assertIsNotNone(signal)
        self.assertIn("trigger phrase: look at this", signal.reason)

    def test_transcript_prefilter_rejects_repeated_gaming_callout_across_streams(self) -> None:
        previous = TranscriptEvent("player_1", "behind you on the stairs", 10.0, 11.0)
        newest = TranscriptEvent("player_3", "Behind you, behind you", 12.0, 13.0)

        signal = TranscriptTriggerPrefilter().classify(
            HypeContext(transcripts=(previous, newest))
        )

        self.assertIsNone(signal)

    def test_transcript_prefilter_rejects_repeated_short_help_across_streams(self) -> None:
        previous = TranscriptEvent("player_1", "help", 10.0, 11.0)
        newest = TranscriptEvent("player_3", "Help!", 12.0, 13.0)

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
            media_uri="file:///buffer/player_3/clip.m3u8",
        )
        result = SwitchResult(
            target=target,
            status=SwitchStatus.APPLIED,
            segment_uris=("file:///buffer/player_3/000.ts",),
        )

        self.assertEqual(result.target.clip_request, request)
        self.assertEqual(result.target.media_uri, "file:///buffer/player_3/clip.m3u8")
        self.assertEqual(result.status, SwitchStatus.APPLIED)
        self.assertEqual(result.segment_uris, ("file:///buffer/player_3/000.ts",))

    def test_buffered_target_helper_uses_hype_signal_trigger_time(self) -> None:
        signal = HypeSignal(
            stream_id="player_4",
            trigger_time_seconds=90.0,
            confidence=0.95,
            reason="rare drop",
        )

        target = buffered_target_from_signal(signal, pre_roll_seconds=15)

        self.assertEqual(target.stream_id, "player_4")
        self.assertEqual(target.scene_name, "Player 4 Fullscreen")
        self.assertIsNotNone(target.clip_request)
        self.assertEqual(target.clip_request.start_time_seconds, 75.0)
        self.assertEqual(target.clip_request.trigger_time_seconds, 90.0)

    def test_buffered_switcher_boundary_rejects_targets_without_clip_requests(self) -> None:
        class EmptyBuffer:
            def resolve_clip(self, request):
                raise AssertionError("resolve_clip should not be called")

        result = BufferBackedSwitcher(EmptyBuffer()).switch(
            SwitcherTarget(stream_id="player_1", scene_name="Player 1 Fullscreen")
        )

        self.assertEqual(result.status, SwitchStatus.REJECTED)
        self.assertIn("clip request", result.reason)


if __name__ == "__main__":
    unittest.main()
