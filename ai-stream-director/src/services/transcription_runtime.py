"""Runtime pump for turning audio refs into routed transcript events."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Callable, Protocol

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


class TranscriptEventSource(Protocol):
    """Long-lived producer of normalized transcript events."""

    def start(self) -> None:
        """Start owned extractors, streams, and worker loops."""

    def stop(self) -> None:
        """Stop owned extractors, streams, and worker loops."""


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
        final_events_only: bool = False,
        suppress_non_newer_final_events: bool = False,
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        self.transcriber = transcriber
        self.sink = sink
        self.fail_fast = fail_fast
        self.final_events_only = final_events_only
        self.suppress_non_newer_final_events = suppress_non_newer_final_events
        self.should_stop = should_stop or (lambda: False)
        self._last_final_end_by_stream: dict[str, float] = {}

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
            if self.should_stop():
                break
            processed_audio_refs += 1
            try:
                for event in self._transcript_events(audio_ref):
                    if self.should_stop():
                        break
                    emitted_transcript_events += 1
                    if self.final_events_only and not event.is_final:
                        rejected_events += 1
                        continue
                    if self._is_overlap_only_event(audio_ref, event):
                        rejected_events += 1
                        continue
                    if self._is_non_newer_final_event(event):
                        rejected_events += 1
                        continue
                    if self._emit(event):
                        accepted_events += 1
                        self._mark_emitted(event)
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

    def _is_overlap_only_event(
        self,
        audio_ref: AudioInputRef,
        event: TranscriptEvent,
    ) -> bool:
        if audio_ref.emit_from_seconds is None:
            return False
        if event.stream_id != audio_ref.stream_id:
            return False
        return event.end_time_seconds <= audio_ref.emit_from_seconds

    def _is_non_newer_final_event(self, event: TranscriptEvent) -> bool:
        if not self.suppress_non_newer_final_events or not event.is_final:
            return False
        last_end = self._last_final_end_by_stream.get(event.stream_id)
        return last_end is not None and event.end_time_seconds <= last_end

    def _mark_emitted(self, event: TranscriptEvent) -> None:
        if not event.is_final:
            return
        previous = self._last_final_end_by_stream.get(event.stream_id)
        if previous is None or event.end_time_seconds > previous:
            self._last_final_end_by_stream[event.stream_id] = event.end_time_seconds


def run_transcription_pump(
    audio_refs: Iterable[AudioInputRef],
    transcriber: Transcriber,
    sink: TranscriptEventSink,
    *,
    fail_fast: bool = False,
    final_events_only: bool = False,
    suppress_non_newer_final_events: bool = False,
) -> TranscriptionRuntimeSummary:
    """Process supplied audio refs through a fresh pump instance."""

    return TranscriptionRuntimePump(
        transcriber=transcriber,
        sink=sink,
        fail_fast=fail_fast,
        final_events_only=final_events_only,
        suppress_non_newer_final_events=suppress_non_newer_final_events,
    ).run_once(audio_refs)
