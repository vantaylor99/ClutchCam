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
        "that was nasty",
        "behind you",
        "good work",
        "triple",
        "legend",
    )
    short_hype_phrases: Sequence[str] = (
        "help",
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
        self._short_hype_phrases = {
            _normalize_text(phrase) for phrase in self.config.short_hype_phrases
        }
        self._filler_phrases = {
            _normalize_text(phrase) for phrase in self.config.filler_phrases
        }

    def classify(self, context: HypeContext) -> HypeSignal | None:
        if not self.config.enabled or not context.transcripts:
            return None

        newest = context.transcripts[-1]
        trigger_time = (
            context.reference_time_seconds
            if context.reference_time_seconds is not None
            else newest.end_time_seconds
        )
        candidate_text = self._candidate_text(
            transcripts=context.transcripts,
            target_index=len(context.transcripts) - 1,
            trigger_time_seconds=newest.end_time_seconds,
        )
        phrase = self._matched_target_hype_phrase(
            transcripts=context.transcripts,
            target_index=len(context.transcripts) - 1,
            trigger_time_seconds=newest.end_time_seconds,
        )
        if not self._is_signal_text(candidate_text, phrase=phrase):
            return None

        if self._is_recent_duplicate(
            candidate_text=candidate_text,
            phrase=phrase,
            newest_index=len(context.transcripts) - 1,
            trigger_time_seconds=trigger_time,
            transcripts=context.transcripts,
        ):
            return None

        confidence = self._confidence_for_phrase(phrase, candidate_text)
        if confidence < self.config.min_confidence:
            return None

        return HypeSignal(
            stream_id=newest.stream_id,
            trigger_time_seconds=trigger_time,
            confidence=confidence,
            reason=_reason_for_phrase(phrase, candidate_text),
            source="transcript",
        )

    def _is_signal_text(self, normalized: str, *, phrase: str | None = None) -> bool:
        if normalized in self._filler_phrases:
            return False
        if not re.search(r"[a-z0-9]", normalized):
            return False
        if phrase in self._short_hype_phrases:
            return True
        if len(normalized) < self.config.min_text_characters:
            return False
        return phrase is not None

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
        candidate_text: str,
        phrase: str | None,
        newest_index: int,
        trigger_time_seconds: float,
        transcripts: Sequence[TranscriptEvent],
    ) -> bool:
        if self.config.duplicate_window_seconds <= 0:
            return False

        for index in range(newest_index - 1, -1, -1):
            event = transcripts[index]
            if trigger_time_seconds - event.end_time_seconds > self.config.duplicate_window_seconds:
                break
            prior_candidate_text = self._candidate_text(
                transcripts=transcripts,
                target_index=index,
                trigger_time_seconds=event.end_time_seconds,
            )
            if prior_candidate_text == candidate_text:
                return True
            prior_phrase = self._matched_target_hype_phrase(
                transcripts=transcripts,
                target_index=index,
                trigger_time_seconds=event.end_time_seconds,
            )
            if phrase is not None and phrase == prior_phrase:
                return True

        return False

    def _candidate_text(
        self,
        *,
        transcripts: Sequence[TranscriptEvent],
        target_index: int,
        trigger_time_seconds: float,
    ) -> str:
        return " ".join(
            part
            for _, part in self._candidate_parts(
                transcripts=transcripts,
                target_index=target_index,
                trigger_time_seconds=trigger_time_seconds,
            )
        )

    def _matched_target_hype_phrase(
        self,
        *,
        transcripts: Sequence[TranscriptEvent],
        target_index: int,
        trigger_time_seconds: float,
    ) -> str | None:
        text = ""
        target_span: tuple[int, int] | None = None
        for index, part in self._candidate_parts(
            transcripts=transcripts,
            target_index=target_index,
            trigger_time_seconds=trigger_time_seconds,
        ):
            if text:
                text += " "
            start = len(text)
            text += part
            end = len(text)
            if index == target_index:
                target_span = (start, end)

        if target_span is None:
            return None

        target_text = text[target_span[0] : target_span[1]]
        if target_text in self._short_hype_phrases:
            return target_text

        for phrase in self._hype_phrases:
            if not phrase:
                continue
            start = text.find(phrase)
            while start != -1:
                end = start + len(phrase)
                if start < target_span[1] and end > target_span[0]:
                    return phrase
                start = text.find(phrase, start + 1)
        return None

    def _candidate_parts(
        self,
        *,
        transcripts: Sequence[TranscriptEvent],
        target_index: int,
        trigger_time_seconds: float,
    ) -> tuple[tuple[int, str], ...]:
        target = transcripts[target_index]
        if self.config.context_window_seconds <= 0:
            cutoff = None
        else:
            cutoff = trigger_time_seconds - self.config.context_window_seconds

        parts = []
        for index, event in enumerate(transcripts[: target_index + 1]):
            if event.stream_id != target.stream_id:
                continue
            if cutoff is not None and event.end_time_seconds < cutoff:
                continue
            part = _normalize_text(event.text)
            if part:
                parts.append((index, part))
        return tuple(parts)


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
    if phrase in {
        "that was nasty",
        "behind you",
        "good work",
        "triple",
        "legend",
        "help",
    }:
        return f"Matched gaming callout phrase: {phrase}."
    if phrase in {"holy cow", "holy crap", "oh my god", "omg", "no way"}:
        return f"Matched excitement phrase: {phrase}."
    return f"Matched trigger phrase: {phrase}."
