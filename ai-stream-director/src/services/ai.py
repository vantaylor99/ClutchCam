"""AI hype-classification boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from contracts import HypeSignal, TranscriptEvent


class HypeClassifierError(RuntimeError):
    """Raised when a classifier adapter cannot evaluate hype context."""


@dataclass(frozen=True)
class HypeContext:
    """Transcript and optional hybrid context for a hype decision."""

    transcripts: Sequence[TranscriptEvent] = ()
    visual_context: Mapping[str, str] = field(default_factory=dict)
    reference_time_seconds: float | None = None


class HypeClassifier(Protocol):
    """Classifies transcript or hybrid context into an optional hype signal."""

    def classify(self, context: HypeContext) -> HypeSignal | None:
        """Return a hype signal when the context is actionable."""
