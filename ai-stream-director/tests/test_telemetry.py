import io
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from services.telemetry import (  # noqa: E402
    MODEL_DECISION_EVENT,
    PREFILTER_DECISION_EVENT,
    SWITCH_ACTION_EVENT,
    JsonLinesTelemetryEmitter,
    TelemetryEvent,
    TelemetryLogger,
)


class TelemetryEventTests(unittest.TestCase):
    def test_json_line_emitter_writes_deterministic_event(self) -> None:
        lines: list[str] = []
        emitter = JsonLinesTelemetryEmitter(lines.append)
        event = TelemetryEvent(
            name=MODEL_DECISION_EVENT,
            timestamp="2026-06-04T18:00:00Z",
            stream_id="player_2",
            correlation_id="corr-123",
            details={
                "confidence": 0.87,
                "target_scene": "Player 2 Fullscreen",
            },
        )

        emitter.emit(event)

        self.assertEqual(
            lines,
            [
                (
                    '{"correlation_id":"corr-123",'
                    '"details":{"confidence":0.87,'
                    '"target_scene":"Player 2 Fullscreen"},'
                    '"event":"model.decision","stream_id":"player_2",'
                    '"timestamp":"2026-06-04T18:00:00Z"}\n'
                )
            ],
        )

    def test_optional_fields_are_omitted_when_absent(self) -> None:
        event = TelemetryEvent(
            name=SWITCH_ACTION_EVENT,
            timestamp="2026-06-04T18:05:00Z",
        )

        self.assertEqual(
            event.to_record(),
            {
                "timestamp": "2026-06-04T18:05:00Z",
                "event": "switch.action",
            },
        )

    def test_emitter_can_write_to_file_like_sink(self) -> None:
        sink = io.StringIO()
        emitter = JsonLinesTelemetryEmitter(sink)

        emitter.emit(
            TelemetryEvent(
                name=SWITCH_ACTION_EVENT,
                timestamp="2026-06-04T18:07:00Z",
                details={"status": "applied"},
            )
        )

        self.assertEqual(
            json.loads(sink.getvalue()),
            {
                "details": {"status": "applied"},
                "event": "switch.action",
                "timestamp": "2026-06-04T18:07:00Z",
            },
        )

    def test_logger_generates_timestamp_and_propagates_correlation_id(self) -> None:
        lines: list[str] = []
        logger = TelemetryLogger(
            emitter=JsonLinesTelemetryEmitter(lines.append),
            clock=lambda: datetime(2026, 6, 4, 18, 30, 1, tzinfo=timezone.utc),
        )

        event = logger.emit(
            PREFILTER_DECISION_EVENT,
            stream_id="player_3",
            correlation_id="turn-7",
            accepted=False,
            reason="no local trigger",
        )

        self.assertEqual(event.timestamp, "2026-06-04T18:30:01Z")
        self.assertEqual(event.correlation_id, "turn-7")
        self.assertEqual(event.details["accepted"], False)
        self.assertEqual(
            json.loads(lines[0]),
            {
                "correlation_id": "turn-7",
                "details": {
                    "accepted": False,
                    "reason": "no local trigger",
                },
                "event": "prefilter.decision",
                "stream_id": "player_3",
                "timestamp": "2026-06-04T18:30:01Z",
            },
        )


if __name__ == "__main__":
    unittest.main()
