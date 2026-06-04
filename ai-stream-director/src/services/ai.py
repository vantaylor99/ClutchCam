"""AI hype-classification boundary."""

from __future__ import annotations

import re
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


@dataclass(frozen=True)
class TranscriptTriggerPrefilterConfig:
    """Runtime-tunable local transcript trigger rules."""

    enabled: bool = True
    min_text_characters: int = 6
    duplicate_window_seconds: float = 12.0
    context_window_seconds: float = 30.0
    min_confidence: float = 0.7
    hype_phrases: Sequence[str] = (
        "holy cow",
        "holy crap",
        "oh my god",
        "omg",
        "no way",
        "wait what",
        "what is going on",
        "what's going on",
        "look at this",
        "clip it",
        "let's go",
        "i found",
        "found something",
        "found the",
        "rare",
        "boss",
        "diamonds",
        "crazy",
        "insane",
        "huge",
        "unbelievable",
    )
    filler_phrases: Sequence[str] = (
        "ok",
        "okay",
        "yeah",
        "yep",
        "yes",
        "no",
        "hi",
        "hello",
        "cool",
        "nice",
        "thanks",
        "thank you",
        "got it",
        "copy",
    )

    def __post_init__(self) -> None:
        if self.min_text_characters < 1:
            raise ValueError("min_text_characters must be positive.")
        if self.duplicate_window_seconds < 0:
            raise ValueError("duplicate_window_seconds cannot be negative.")
        if self.context_window_seconds < 0:
            raise ValueError("context_window_seconds cannot be negative.")
        if not 0 <= self.min_confidence <= 1:
            raise ValueError("min_confidence must be between 0 and 1.")


class TranscriptTriggerPrefilter:
    """Cheap local transcript gate before model escalation."""

    def __init__(
        self,
        config: TranscriptTriggerPrefilterConfig | None = None,
    ) -> None:
        self.config = config or TranscriptTriggerPrefilterConfig()
        self._hype_phrases = tuple(
            _normalize_text(phrase) for phrase in self.config.hype_phrases
        )
        self._filler_phrases = {
            _normalize_text(phrase) for phrase in self.config.filler_phrases
        }

    def classify(self, context: HypeContext) -> HypeSignal | None:
        if not self.config.enabled or not context.transcripts:
            return None

        newest = context.transcripts[-1]
        normalized = _normalize_text(newest.text)
        if not self._is_signal_text(normalized):
            return None

        trigger_time = (
            context.reference_time_seconds
            if context.reference_time_seconds is not None
            else newest.end_time_seconds
        )
        if self._is_recent_duplicate(
            normalized_text=normalized,
            newest=newest,
            trigger_time_seconds=trigger_time,
            transcripts=self._recent_history(trigger_time, context.transcripts[:-1]),
        ):
            return None

        phrase = self._matched_hype_phrase(normalized)
        confidence = self._confidence_for_phrase(phrase, normalized)
        if confidence < self.config.min_confidence:
            return None

        return HypeSignal(
            stream_id=newest.stream_id,
            trigger_time_seconds=trigger_time,
            confidence=confidence,
            reason=_reason_for_phrase(phrase, normalized),
            source="transcript",
        )

    def _is_signal_text(self, normalized: str) -> bool:
        if len(normalized) < self.config.min_text_characters:
            return False
        if normalized in self._filler_phrases:
            return False
        if not re.search(r"[a-z0-9]", normalized):
            return False
        return self._matched_hype_phrase(normalized) is not None

    def _matched_hype_phrase(self, normalized: str) -> str | None:
        for phrase in self._hype_phrases:
            if phrase and phrase in normalized:
                return phrase
        return None

    def _confidence_for_phrase(self, phrase: str | None, normalized: str) -> float:
        if phrase is None:
            return 0.0
        if phrase in {"holy cow", "oh my god", "omg", "no way", "clip it"}:
            return 0.9
        if "!" in normalized:
            return 0.85
        return 0.8

    def _is_recent_duplicate(
        self,
        *,
        normalized_text: str,
        newest: TranscriptEvent,
        trigger_time_seconds: float,
        transcripts: Sequence[TranscriptEvent],
    ) -> bool:
        if self.config.duplicate_window_seconds <= 0:
            return False

        for event in reversed(transcripts):
            if trigger_time_seconds - event.end_time_seconds > self.config.duplicate_window_seconds:
                break
            if _normalize_text(event.text) == normalized_text:
                return True
            if self._same_hype_phrase(
                normalized_text,
                _normalize_text(event.text),
            ):
                return True

        return False

    def _same_hype_phrase(self, left: str, right: str) -> bool:
        left_phrase = self._matched_hype_phrase(left)
        return left_phrase is not None and left_phrase == self._matched_hype_phrase(right)

    def _recent_history(
        self,
        trigger_time_seconds: float,
        transcripts: Sequence[TranscriptEvent],
    ) -> tuple[TranscriptEvent, ...]:
        if self.config.context_window_seconds <= 0:
            return tuple(transcripts)

        cutoff = trigger_time_seconds - self.config.context_window_seconds
        return tuple(
            event for event in transcripts if event.end_time_seconds >= cutoff
        )


def _normalize_text(text: str) -> str:
    normalized = text.casefold()
    normalized = normalized.replace("’", "'")
    normalized = re.sub(r"[^a-z0-9']+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _reason_for_phrase(phrase: str | None, normalized: str) -> str:
    if phrase is None:
        return "Matched local transcript trigger."
    if phrase in {"i found", "found something", "found the"}:
        return f"Matched discovery phrase: {phrase}."
    if phrase in {"rare", "boss", "diamonds"}:
        return f"Matched gameplay phrase: {phrase}."
    if phrase in {"holy cow", "holy crap", "oh my god", "omg", "no way"}:
        return f"Matched excitement phrase: {phrase}."
    return f"Matched trigger phrase: {phrase}."
