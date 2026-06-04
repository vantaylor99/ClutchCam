"""Runtime pump for turning audio refs into routed transcript events."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from contracts import TranscriptEvent
from services.transcription import AudioInputRef, Transcriber, TranscriptionError


class TranscriptEventSink(Protocol):
    """Consumes a normalized transcript event.

    A return value of ``None`` means the event was rejected. This matches
    ``TranscriptRouter.add_event`` while still allowing tests to use simple
    callback sinks.
    """

    def __call__(self, event: TranscriptEvent) -> object | None:
        """Handle one transcript event."""


@dataclass(frozen=True)
class TranscriptionRuntimeFailure:
    """One isolated audio-ref processing failure."""

    audio_ref: AudioInputRef
    error: TranscriptionError

    @property
    def message(self) -> str:
        return str(self.error)


@dataclass(frozen=True)
class TranscriptionRuntimeSummary:
    """Counters from one transcription pump pass."""

    processed_audio_refs: int
    emitted_transcript_events: int
    accepted_events: int
    rejected_events: int
    failures: tuple[TranscriptionRuntimeFailure, ...] = ()

    @property
    def failed_audio_refs(self) -> int:
        return len(self.failures)


class TranscriptionRuntimePump:
    """One-shot transcription runtime pump.

    The pump accepts already-discovered ``AudioInputRef`` values so it can be
    unit-tested without FFmpeg, Docker, or a live Faster-Whisper service. Later
    runtime wiring can feed it refs from an extractor watcher.
    """

    def __init__(
        self,
        transcriber: Transcriber,
        sink: TranscriptEventSink,
        *,
        fail_fast: bool = False,
    ) -> None:
        self.transcriber = transcriber
        self.sink = sink
        self.fail_fast = fail_fast

    def run_once(
        self,
        audio_refs: Iterable[AudioInputRef],
    ) -> TranscriptionRuntimeSummary:
        processed_audio_refs = 0
        emitted_transcript_events = 0
        accepted_events = 0
        rejected_events = 0
        failures: list[TranscriptionRuntimeFailure] = []

        for audio_ref in audio_refs:
            processed_audio_refs += 1
            try:
                for event in self._transcript_events(audio_ref):
                    emitted_transcript_events += 1
                    if self._emit(event):
                        accepted_events += 1
                    else:
                        rejected_events += 1
            except TranscriptionError as exc:
                failures.append(
                    TranscriptionRuntimeFailure(audio_ref=audio_ref, error=exc)
                )
                if self.fail_fast:
                    raise

        return TranscriptionRuntimeSummary(
            processed_audio_refs=processed_audio_refs,
            emitted_transcript_events=emitted_transcript_events,
            accepted_events=accepted_events,
            rejected_events=rejected_events,
            failures=tuple(failures),
        )

    def _transcript_events(
        self,
        audio_ref: AudioInputRef,
    ) -> Iterable[TranscriptEvent]:
        try:
            events = self.transcriber.transcribe(audio_ref)
        except TranscriptionError:
            raise
        except Exception as exc:
            raise TranscriptionError(
                f"Transcription failed for {audio_ref.stream_id}: {exc}"
            ) from exc

        if events is None:
            raise TranscriptionError(
                "Transcriber returned None instead of transcript events."
            )

        try:
            iterator = iter(events)
        except TypeError as exc:
            raise TranscriptionError(
                "Transcriber output must be an iterable of TranscriptEvent values."
            ) from exc

        index = 0
        while True:
            try:
                event = next(iterator)
            except StopIteration:
                return
            except TranscriptionError:
                raise
            except Exception as exc:
                raise TranscriptionError(
                    f"Transcriber failed while yielding events for "
                    f"{audio_ref.stream_id}: {exc}"
                ) from exc

            if not isinstance(event, TranscriptEvent):
                raise TranscriptionError(
                    f"Transcriber emitted non-TranscriptEvent at index {index} "
                    f"for {audio_ref.stream_id}."
                )

            index += 1
            yield event

    def _emit(self, event: TranscriptEvent) -> bool:
        try:
            return self.sink(event) is not None
        except TranscriptionError:
            raise
        except Exception as exc:
            raise TranscriptionError(
                f"Transcript sink failed for {event.stream_id}: {exc}"
            ) from exc


def run_transcription_pump(
    audio_refs: Iterable[AudioInputRef],
    transcriber: Transcriber,
    sink: TranscriptEventSink,
    *,
    fail_fast: bool = False,
) -> TranscriptionRuntimeSummary:
    """Process supplied audio refs through a fresh pump instance."""

    return TranscriptionRuntimePump(
        transcriber=transcriber,
        sink=sink,
        fail_fast=fail_fast,
    ).run_once(audio_refs)
