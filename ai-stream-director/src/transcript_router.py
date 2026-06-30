import time
from dataclasses import dataclass
from typing import List, Optional

from contracts import TranscriptEvent


VALID_SPEAKERS = {"player_1", "player_2", "player_3", "player_4"}
TRANSCRIPT_UTTERANCE_MAX_GAP_SECONDS = 2.0
TRANSCRIPT_UTTERANCE_MAX_DURATION_SECONDS = 8.0
TRANSCRIPT_UTTERANCE_MAX_CHARACTERS = 240
TRANSCRIPT_UTTERANCE_MAX_EVENTS = 8
STRONG_SENTENCE_PUNCTUATION = (".", "!", "?")


@dataclass
class TranscriptMessage:
    speaker: str
    text: str
    start_time_seconds: float
    end_time_seconds: float
    received_at: Optional[float] = None

    @property
    def timestamp(self) -> float:
        return self.end_time_seconds

    def to_event(self) -> TranscriptEvent:
        return TranscriptEvent(
            stream_id=self.speaker,
            text=self.text,
            start_time_seconds=self.start_time_seconds,
            end_time_seconds=self.end_time_seconds,
            is_final=True,
        )


@dataclass(frozen=True)
class TranscriptUtteranceCandidate:
    stream_id: str
    text: str
    start_time_seconds: float
    end_time_seconds: float
    source_event_count: int
    source_start_index: int
    source_end_index: int

    def to_event(self) -> TranscriptEvent:
        return TranscriptEvent(
            stream_id=self.stream_id,
            text=self.text,
            start_time_seconds=self.start_time_seconds,
            end_time_seconds=self.end_time_seconds,
            is_final=True,
        )


class TranscriptRouter:
    def __init__(
        self,
        history_seconds: int = 30,
        max_messages: int = 20,
        *,
        utterance_max_gap_seconds: float = TRANSCRIPT_UTTERANCE_MAX_GAP_SECONDS,
        utterance_max_duration_seconds: float = (
            TRANSCRIPT_UTTERANCE_MAX_DURATION_SECONDS
        ),
        utterance_max_characters: int = TRANSCRIPT_UTTERANCE_MAX_CHARACTERS,
        utterance_max_events: int = TRANSCRIPT_UTTERANCE_MAX_EVENTS,
    ):
        self.history_seconds = history_seconds
        self.max_messages = max_messages
        self.utterance_max_gap_seconds = utterance_max_gap_seconds
        self.utterance_max_duration_seconds = utterance_max_duration_seconds
        self.utterance_max_characters = utterance_max_characters
        self.utterance_max_events = utterance_max_events
        self._messages: List[TranscriptMessage] = []

    def parse_line(self, line: str) -> Optional[TranscriptMessage]:
        if ":" not in line:
            return None

        speaker, text = line.split(":", 1)
        speaker = speaker.strip().lower()
        text = text.strip()

        if speaker not in VALID_SPEAKERS or not text:
            return None

        timestamp = time.time()
        message = TranscriptMessage(
            speaker=speaker,
            text=text,
            start_time_seconds=timestamp,
            end_time_seconds=timestamp,
        )
        self._messages.append(message)
        self._trim_history()
        return message

    def add_event(self, event: TranscriptEvent) -> Optional[TranscriptMessage]:
        speaker = event.stream_id.strip().lower()
        text = event.text.strip()

        if (
            speaker not in VALID_SPEAKERS
            or not text
            or event.end_time_seconds < event.start_time_seconds
        ):
            return None

        message = TranscriptMessage(
            speaker=speaker,
            text=text,
            start_time_seconds=event.start_time_seconds,
            end_time_seconds=event.end_time_seconds,
            received_at=time.time(),
        )
        self._messages.append(message)
        self._trim_history()
        return message

    def get_recent_messages(self) -> List[TranscriptMessage]:
        self._trim_history()
        return list(self._messages)

    def get_recent_events(self) -> tuple[TranscriptEvent, ...]:
        return tuple(message.to_event() for message in self.get_recent_messages())

    def get_recent_utterance_candidates(self) -> tuple[TranscriptUtteranceCandidate, ...]:
        return self._assemble_utterance_candidates(self.get_recent_messages())

    def get_recent_candidate_events(self) -> tuple[TranscriptEvent, ...]:
        return tuple(
            candidate.to_event()
            for candidate in self.get_recent_utterance_candidates()
        )

    def get_recent_context_text(self) -> str:
        candidates = self.get_recent_utterance_candidates()
        if not candidates:
            return "No transcript messages yet."

        lines = []
        for candidate in candidates:
            lines.append(f"{candidate.stream_id}: {candidate.text}")
        return "\n".join(lines)

    def _trim_history(self) -> None:
        cutoff = time.time() - self.history_seconds
        self._messages = [
            message
            for message in self._messages
            if (message.received_at or message.end_time_seconds) >= cutoff
        ]

        if len(self._messages) > self.max_messages:
            self._messages = self._messages[-self.max_messages :]

    def _assemble_utterance_candidates(
        self,
        messages: list[TranscriptMessage],
    ) -> tuple[TranscriptUtteranceCandidate, ...]:
        candidates: list[TranscriptUtteranceCandidate] = []
        current_messages: list[TranscriptMessage] = []
        current_start_index = 0

        for index, message in enumerate(messages):
            if current_messages and self._should_start_new_candidate(
                current_messages,
                message,
            ):
                candidates.append(
                    self._build_candidate(current_messages, current_start_index)
                )
                current_messages = []

            if not current_messages:
                current_start_index = index
            current_messages.append(message)

        if current_messages:
            candidates.append(self._build_candidate(current_messages, current_start_index))

        return tuple(candidates)

    def _should_start_new_candidate(
        self,
        current_messages: list[TranscriptMessage],
        next_message: TranscriptMessage,
    ) -> bool:
        current_first = current_messages[0]
        current_last = current_messages[-1]
        current_text = _join_message_text(current_messages)
        next_text = next_message.text.strip()

        if current_last.speaker != next_message.speaker:
            return True
        if (
            next_message.start_time_seconds - current_last.end_time_seconds
            > self.utterance_max_gap_seconds
        ):
            return True
        if (
            next_message.end_time_seconds - current_first.start_time_seconds
            > self.utterance_max_duration_seconds
        ):
            return True
        if current_text.endswith(STRONG_SENTENCE_PUNCTUATION):
            return True
        if len(_join_text_parts((current_text, next_text))) > self.utterance_max_characters:
            return True
        if len(current_messages) >= self.utterance_max_events:
            return True
        return False

    def _build_candidate(
        self,
        messages: list[TranscriptMessage],
        source_start_index: int,
    ) -> TranscriptUtteranceCandidate:
        return TranscriptUtteranceCandidate(
            stream_id=messages[0].speaker,
            text=_join_message_text(messages),
            start_time_seconds=messages[0].start_time_seconds,
            end_time_seconds=messages[-1].end_time_seconds,
            source_event_count=len(messages),
            source_start_index=source_start_index,
            source_end_index=source_start_index + len(messages) - 1,
        )


def _join_message_text(messages: list[TranscriptMessage]) -> str:
    return _join_text_parts(message.text for message in messages)


def _join_text_parts(parts) -> str:
    return " ".join(part.strip() for part in parts if part.strip())
