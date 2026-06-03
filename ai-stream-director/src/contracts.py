from dataclasses import dataclass


@dataclass(frozen=True)
class StreamSource:
    stream_id: str
    display_name: str
    ingest_url: str
    scene_name: str


@dataclass(frozen=True)
class TranscriptEvent:
    stream_id: str
    text: str
    start_time_seconds: float
    end_time_seconds: float
    is_final: bool = True


@dataclass(frozen=True)
class HypeSignal:
    stream_id: str
    trigger_time_seconds: float
    confidence: float
    reason: str
    source: str = "transcript"


@dataclass(frozen=True)
class LookbackClipRequest:
    stream_id: str
    trigger_time_seconds: float
    pre_roll_seconds: int = 15
    post_roll_seconds: int = 5

    @property
    def start_time_seconds(self) -> float:
        return max(0.0, self.trigger_time_seconds - self.pre_roll_seconds)

    @property
    def end_time_seconds(self) -> float:
        return self.trigger_time_seconds + self.post_roll_seconds


@dataclass(frozen=True)
class SwitcherTarget:
    stream_id: str
    scene_name: str
    clip_request: LookbackClipRequest | None = None
