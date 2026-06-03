"""Speech-to-text boundary for stream audio references."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from contracts import TranscriptEvent


class TranscriptionError(RuntimeError):
    """Raised when a transcription adapter cannot emit transcript events."""


@dataclass(frozen=True)
class AudioInputRef:
    """Implementation-neutral reference to stream audio."""

    stream_id: str
    uri: str
    starts_at_seconds: float | None = None
    codec: str | None = None


class Transcriber(Protocol):
    """Turns audio references into transcript events."""

    def transcribe(self, audio: AudioInputRef) -> Iterable[TranscriptEvent]:
        """Yield transcript events for the supplied audio reference."""
