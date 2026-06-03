import time
from dataclasses import dataclass
from typing import List, Optional

from contracts import TranscriptEvent


VALID_SPEAKERS = {"player_1", "player_2", "player_3", "player_4"}


@dataclass
class TranscriptMessage:
    speaker: str
    text: str
    timestamp: float

    def to_event(self) -> TranscriptEvent:
        return TranscriptEvent(
            stream_id=self.speaker,
            text=self.text,
            start_time_seconds=self.timestamp,
            end_time_seconds=self.timestamp,
            is_final=True,
        )


class TranscriptRouter:
    def __init__(self, history_seconds: int = 30, max_messages: int = 20):
        self.history_seconds = history_seconds
        self.max_messages = max_messages
        self._messages: List[TranscriptMessage] = []

    def parse_line(self, line: str) -> Optional[TranscriptMessage]:
        if ":" not in line:
            return None

        speaker, text = line.split(":", 1)
        speaker = speaker.strip().lower()
        text = text.strip()

        if speaker not in VALID_SPEAKERS or not text:
            return None

        message = TranscriptMessage(
            speaker=speaker,
            text=text,
            timestamp=time.time(),
        )
        self._messages.append(message)
        self._trim_history()
        return message

    def get_recent_messages(self) -> List[TranscriptMessage]:
        self._trim_history()
        return list(self._messages)

    def get_recent_context_text(self) -> str:
        messages = self.get_recent_messages()
        if not messages:
            return "No transcript messages yet."

        lines = []
        for message in messages:
            lines.append(f"{message.speaker}: {message.text}")
        return "\n".join(lines)

    def _trim_history(self) -> None:
        cutoff = time.time() - self.history_seconds
        self._messages = [
            message for message in self._messages if message.timestamp >= cutoff
        ]

        if len(self._messages) > self.max_messages:
            self._messages = self._messages[-self.max_messages :]
