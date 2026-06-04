"""Structured telemetry primitives for orchestration decisions."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol, TextIO


TRANSCRIPT_RECEIVED_EVENT = "transcript.received"
PREFILTER_DECISION_EVENT = "prefilter.decision"
MODEL_ESCALATION_EVENT = "model.escalation"
MODEL_DECISION_EVENT = "model.decision"
CLIP_REQUESTED_EVENT = "clip.requested"
SWITCH_ACTION_EVENT = "switch.action"

ORCHESTRATION_EVENT_NAMES = (
    TRANSCRIPT_RECEIVED_EVENT,
    PREFILTER_DECISION_EVENT,
    MODEL_ESCALATION_EVENT,
    MODEL_DECISION_EVENT,
    CLIP_REQUESTED_EVENT,
    SWITCH_ACTION_EVENT,
)

LineSink = Callable[[str], None] | TextIO


class TelemetryEmitter(Protocol):
    """Emits a structured telemetry event."""

    def emit(self, event: "TelemetryEvent") -> None:
        """Emit one event record."""


@dataclass(frozen=True)
class TelemetryEvent:
    """One machine-readable orchestration telemetry record."""

    name: str
    timestamp: str
    stream_id: str | None = None
    correlation_id: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Telemetry event name is required.")
        if not self.timestamp.strip():
            raise ValueError("Telemetry event timestamp is required.")
        if self.stream_id is not None and not self.stream_id.strip():
            raise ValueError("Telemetry stream_id cannot be blank.")
        if self.correlation_id is not None and not self.correlation_id.strip():
            raise ValueError("Telemetry correlation_id cannot be blank.")

        normalized_details = dict(self.details)
        for key in normalized_details:
            if not isinstance(key, str) or not key:
                raise ValueError("Telemetry detail keys must be non-empty strings.")
        object.__setattr__(self, "details", normalized_details)

    def to_record(self) -> dict[str, Any]:
        """Return the JSON-serializable event record."""

        record: dict[str, Any] = {
            "timestamp": self.timestamp,
            "event": self.name,
        }
        if self.stream_id is not None:
            record["stream_id"] = self.stream_id
        if self.correlation_id is not None:
            record["correlation_id"] = self.correlation_id
        if self.details:
            record["details"] = dict(self.details)
        return record

    def to_json_line(self) -> str:
        """Serialize the event as one deterministic JSON-lines record."""

        return (
            json.dumps(
                self.to_record(),
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        )


class JsonLinesTelemetryEmitter:
    """Writes telemetry events as JSON Lines to a file-like or callable sink."""

    def __init__(self, sink: LineSink | None = None) -> None:
        self._sink = sink or sys.stdout

    def emit(self, event: TelemetryEvent) -> None:
        line = event.to_json_line()
        write = getattr(self._sink, "write", None)
        if callable(write):
            write(line)
            flush = getattr(self._sink, "flush", None)
            if callable(flush):
                flush()
            return

        self._sink(line)


class TelemetryLogger:
    """Creates timestamped telemetry events and delegates emission."""

    def __init__(
        self,
        emitter: TelemetryEmitter | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._emitter = emitter or JsonLinesTelemetryEmitter()
        self._clock = clock or _utc_now

    def emit(
        self,
        name: str,
        *,
        stream_id: str | None = None,
        correlation_id: str | None = None,
        details: Mapping[str, Any] | None = None,
        **detail_fields: Any,
    ) -> TelemetryEvent:
        """Create and emit one timestamped telemetry event."""

        merged_details: dict[str, Any] = {}
        if details is not None:
            merged_details.update(details)
        merged_details.update(detail_fields)

        event = TelemetryEvent(
            name=name,
            timestamp=_format_timestamp(self._clock()),
            stream_id=stream_id,
            correlation_id=correlation_id,
            details=merged_details,
        )
        self._emitter.emit(event)
        return event


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
