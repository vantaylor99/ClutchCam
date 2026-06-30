"""Deterministic offline latency and soak harness for live orchestration."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import tracemalloc
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any, Mapping, Sequence, TextIO


PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
for path in (PROJECT_DIR, SRC_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from ai_director import AIDirector, DirectorDecision  # noqa: E402
from config import SCENES  # noqa: E402
from contracts import HypeSignal, TranscriptEvent  # noqa: E402
from main import build_runtime_switch_target  # noqa: E402
from obs_controller import DryRunOBSController  # noqa: E402
from scheduler import SceneScheduler  # noqa: E402
from services.ai import (  # noqa: E402
    HypeContext,
    TranscriptTriggerPrefilter,
    TranscriptTriggerPrefilterConfig,
)
from services.buffer import ClipResolution, LookbackBufferError  # noqa: E402
from services.switcher import BufferBackedSwitcher, SwitchStatus  # noqa: E402
from transcript_router import TranscriptRouter  # noqa: E402


SCHEMA_VERSION = 1
DEFAULT_EVENT_COUNT = 48
DEFAULT_SYNTHETIC_INTERVAL_SECONDS = 1.0
DEFAULT_SWITCH_LOOKBACK_SECONDS = 15
DEFAULT_LATENCY_BUDGETS_MS: dict[str, float] = {
    "ingest_buffer_available": 250.0,
    "transcript_event_handling": 25.0,
    "local_prefilter": 20.0,
    "model_decision": 450.0,
    "clip_resolution": 150.0,
    "switch_action": 75.0,
    "end_to_end": 1000.0,
}
STAGE_NAMES = tuple(DEFAULT_LATENCY_BUDGETS_MS)
STREAM_IDS = ("player_1", "player_2", "player_3", "player_4")


@dataclass(frozen=True)
class HarnessOptions:
    event_count: int = DEFAULT_EVENT_COUNT
    synthetic_interval_seconds: float = DEFAULT_SYNTHETIC_INTERVAL_SECONDS
    switch_lookback_seconds: int = DEFAULT_SWITCH_LOOKBACK_SECONDS
    budgets_ms: Mapping[str, float] = field(
        default_factory=lambda: dict(DEFAULT_LATENCY_BUDGETS_MS)
    )


@dataclass(frozen=True)
class SyntheticEvent:
    event: TranscriptEvent
    should_drop: bool = False


class VirtualClock:
    def __init__(self) -> None:
        self.now_ms = 0.0

    def advance(self, milliseconds: float) -> None:
        if milliseconds < 0:
            raise ValueError("Virtual latency cannot be negative.")
        self.now_ms += milliseconds


class StageTimer:
    def __init__(self, clock: VirtualClock, samples: dict[str, list[float]]) -> None:
        self.clock = clock
        self.samples = samples

    def record(self, stage: str, milliseconds: float) -> None:
        if stage not in self.samples:
            raise ValueError(f"Unknown latency stage: {stage}")
        self.clock.advance(milliseconds)
        self.samples[stage].append(round(milliseconds, 6))


class DeterministicDirectorProvider:
    """AI provider fixture that returns scene decisions without network calls."""

    def __init__(self, timer: StageTimer) -> None:
        self.timer = timer
        self.calls = 0

    def check_readiness(self) -> None:
        return None

    def generate(self, prompt: str) -> dict[str, object]:
        self.calls += 1
        self.timer.record("model_decision", _deterministic_latency(180.0, self.calls, 23.0))
        stream_id = _stream_id_from_prompt(prompt)
        return {
            "target_scene": SCENES.get(stream_id, SCENES["quad"]),
            "confidence": 0.91,
            "duration_seconds": 9,
            "reason": "Deterministic soak fixture accepted local trigger.",
        }


class DeterministicLookbackBuffer:
    """Lookback buffer fixture that resolves clips through the production protocol."""

    def __init__(self, timer: StageTimer) -> None:
        self.timer = timer
        self.calls = 0

    def resolve_clip(self, request):
        self.calls += 1
        self.timer.record("clip_resolution", _deterministic_latency(40.0, self.calls, 11.0))
        if request.stream_id not in STREAM_IDS:
            raise LookbackBufferError(f"Unknown stream ID: {request.stream_id}")
        return ClipResolution.ready(
            request,
            media_uri=f"file:///synthetic/{request.stream_id}/{self.calls:04d}.m3u8",
            start_time_seconds=request.start_time_seconds,
            end_time_seconds=request.end_time_seconds,
            reason="Synthetic clip resolved.",
            segment_uris=(
                f"file:///synthetic/{request.stream_id}/{self.calls:04d}_0.ts",
                f"file:///synthetic/{request.stream_id}/{self.calls:04d}_1.ts",
            ),
        )


class DeterministicDownstreamSwitcher:
    def __init__(self, timer: StageTimer, clock: VirtualClock) -> None:
        self.timer = timer
        self.clock = clock
        self.calls = 0

    def switch(self, target):
        self.calls += 1
        self.timer.record("switch_action", _deterministic_latency(18.0, self.calls, 7.0))
        return {
            "target": target,
            "status": SwitchStatus.APPLIED,
            "switched_at_seconds": round(self.clock.now_ms / 1000.0, 6),
            "reason": "Synthetic downstream switch applied.",
        }


def run_latency_soak(options: HarnessOptions | None = None) -> dict[str, object]:
    selected_options = _validate_options(options or HarnessOptions())
    tracemalloc.start()
    wall_started = time.perf_counter()
    process_started = _process_info()

    clock = VirtualClock()
    samples = {stage: [] for stage in STAGE_NAMES}
    timer = StageTimer(clock, samples)
    provider = DeterministicDirectorProvider(timer)
    ai_director = AIDirector(
        ollama_base_url="http://offline.invalid",
        model="deterministic-soak",
        provider=provider,
        ai_provider="openai-compatible",
    )
    trigger_prefilter = TranscriptTriggerPrefilter(
        TranscriptTriggerPrefilterConfig(duplicate_window_seconds=0.0)
    )
    router = TranscriptRouter(history_seconds=3600, max_messages=selected_options.event_count)
    scheduler = _started_scheduler()
    buffer = DeterministicLookbackBuffer(timer)
    switcher = BufferBackedSwitcher(
        buffer,
        downstream=_DownstreamAdapter(DeterministicDownstreamSwitcher(timer, clock)),
        clock=lambda: round(clock.now_ms / 1000.0, 6),
    )

    counts = {
        "total_events": 0,
        "accepted_events": 0,
        "rejected_events": 0,
        "prefilter_accepted_events": 0,
        "prefilter_rejected_events": 0,
        "model_calls": 0,
        "switch_applied_events": 0,
        "switch_pending_events": 0,
        "switch_rejected_events": 0,
        "dropped_events": 0,
        "late_events": 0,
    }
    event_reports: list[dict[str, object]] = []

    for index, synthetic in enumerate(_synthetic_events(selected_options), start=1):
        counts["total_events"] += 1
        event_started_ms = clock.now_ms
        timer.record("ingest_buffer_available", _deterministic_latency(65.0, index, 17.0))

        if synthetic.should_drop:
            counts["dropped_events"] += 1
            _record_end_to_end(samples, counts, selected_options, clock.now_ms - event_started_ms)
            event_reports.append(
                _event_report(index, synthetic.event, "dropped", clock.now_ms - event_started_ms)
            )
            continue

        timer.record("transcript_event_handling", _deterministic_latency(5.0, index, 3.0))
        message = router.add_event(synthetic.event)
        if message is None:
            counts["rejected_events"] += 1
            counts["dropped_events"] += 1
            _record_end_to_end(samples, counts, selected_options, clock.now_ms - event_started_ms)
            event_reports.append(
                _event_report(index, synthetic.event, "router_rejected", clock.now_ms - event_started_ms)
            )
            continue

        counts["accepted_events"] += 1
        timer.record("local_prefilter", _deterministic_latency(4.0, index, 2.0))
        candidate_events = router.get_recent_candidate_events()
        signal = trigger_prefilter.classify(
            HypeContext(
                transcripts=candidate_events,
                reference_time_seconds=candidate_events[-1].end_time_seconds,
            )
        )
        if signal is None:
            counts["prefilter_rejected_events"] += 1
            _record_end_to_end(samples, counts, selected_options, clock.now_ms - event_started_ms)
            event_reports.append(
                _event_report(index, synthetic.event, "prefilter_rejected", clock.now_ms - event_started_ms)
            )
            continue

        counts["prefilter_accepted_events"] += 1
        decision = ai_director.decide(router.get_recent_context_text(), candidate_signal=signal)
        counts["model_calls"] = provider.calls
        switch_target = build_runtime_switch_target(
            decision=decision,
            candidate_signal=signal,
            scheduler=scheduler,
            switch_lookback_seconds=selected_options.switch_lookback_seconds,
        )
        switch_result = switcher.switch(switch_target) if switch_target is not None else None
        scheduler.apply_ai_decision(decision)
        status = _switch_status_name(switch_result)
        if status == "applied":
            counts["switch_applied_events"] += 1
        elif status == "pending":
            counts["switch_pending_events"] += 1
        elif status == "rejected":
            counts["switch_rejected_events"] += 1
            counts["dropped_events"] += 1

        elapsed_ms = clock.now_ms - event_started_ms
        _record_end_to_end(samples, counts, selected_options, elapsed_ms)
        event_reports.append(_event_report(index, synthetic.event, status, elapsed_ms, signal, decision))

    current_memory, peak_memory = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    wall_duration = round(time.perf_counter() - wall_started, 6)
    budgets = _budget_report(samples, selected_options.budgets_ms)

    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "offline-deterministic",
        "status": "passed" if budgets["overall_passed"] else "failed",
        "options": {
            "event_count": selected_options.event_count,
            "synthetic_interval_seconds": selected_options.synthetic_interval_seconds,
            "switch_lookback_seconds": selected_options.switch_lookback_seconds,
        },
        "counts": counts,
        "timing": {
            "synthetic_elapsed_ms": round(clock.now_ms, 6),
            "wall_duration_seconds": wall_duration,
            "stages": {
                stage: _distribution(values)
                for stage, values in samples.items()
            },
        },
        "budgets": budgets,
        "process": {
            **process_started,
            "memory_current_bytes": current_memory,
            "memory_peak_bytes": peak_memory,
        },
        "events": event_reports,
    }


def main(argv: Sequence[str] | None = None, stdout: TextIO | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    budgets = dict(DEFAULT_LATENCY_BUDGETS_MS)
    for override in args.budget or ():
        name, value = _parse_budget_override(override)
        budgets[name] = value

    report = run_latency_soak(
        HarnessOptions(
            event_count=args.events,
            synthetic_interval_seconds=args.interval_seconds,
            switch_lookback_seconds=args.switch_lookback_seconds,
            budgets_ms=budgets,
        )
    )
    print(
        json.dumps(report, indent=args.indent, sort_keys=True, allow_nan=False),
        file=stdout or sys.stdout,
    )
    return 0 if report["status"] == "passed" else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=int, default=DEFAULT_EVENT_COUNT)
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=DEFAULT_SYNTHETIC_INTERVAL_SECONDS,
    )
    parser.add_argument(
        "--switch-lookback-seconds",
        type=int,
        default=DEFAULT_SWITCH_LOOKBACK_SECONDS,
    )
    parser.add_argument(
        "--budget",
        action="append",
        metavar="STAGE=MS",
        help="Override a latency budget in milliseconds.",
    )
    parser.add_argument("--indent", type=int, default=2)
    return parser


def _validate_options(options: HarnessOptions) -> HarnessOptions:
    if options.event_count < 1:
        raise ValueError("event_count must be positive.")
    if options.synthetic_interval_seconds <= 0:
        raise ValueError("synthetic_interval_seconds must be positive.")
    if options.switch_lookback_seconds < 0:
        raise ValueError("switch_lookback_seconds cannot be negative.")
    budgets = dict(DEFAULT_LATENCY_BUDGETS_MS)
    budgets.update(options.budgets_ms)
    unknown = sorted(set(budgets).difference(DEFAULT_LATENCY_BUDGETS_MS))
    if unknown:
        raise ValueError("Unknown latency budget stages: " + ", ".join(unknown))
    for name, value in budgets.items():
        if value < 0:
            raise ValueError(f"Latency budget {name} cannot be negative.")
    return HarnessOptions(
        event_count=options.event_count,
        synthetic_interval_seconds=options.synthetic_interval_seconds,
        switch_lookback_seconds=options.switch_lookback_seconds,
        budgets_ms=budgets,
    )


def _synthetic_events(options: HarnessOptions) -> tuple[SyntheticEvent, ...]:
    events = []
    for index in range(options.event_count):
        stream_id = STREAM_IDS[index % len(STREAM_IDS)]
        start = index * options.synthetic_interval_seconds
        is_hype = index % 3 == 0
        text = (
            f"holy cow player {index % 4 + 1} found the rare boss"
            if is_hype
            else f"routine comms rotation {index}"
        )
        if index % 17 == 16:
            stream_id = "unknown_stream"
        events.append(
            SyntheticEvent(
                event=TranscriptEvent(
                    stream_id=stream_id,
                    text=text,
                    start_time_seconds=start,
                    end_time_seconds=start + 0.75,
                    is_final=True,
                ),
                should_drop=(index % 23 == 22),
            )
        )
    return tuple(events)


def _started_scheduler() -> SceneScheduler:
    controller = DryRunOBSController(initial_scene=SCENES["quad"], log=lambda message: None)
    scheduler = SceneScheduler(
        obs_controller=controller,
        default_scene=SCENES["quad"],
        confidence_threshold=0.75,
        min_switch_interval_seconds=0,
        max_focus_duration_seconds=20,
        log=lambda message: None,
    )
    controller.connect()
    scheduler.start()
    return scheduler


class _DownstreamAdapter:
    def __init__(self, downstream: DeterministicDownstreamSwitcher) -> None:
        self.downstream = downstream

    def switch(self, target):
        raw = self.downstream.switch(target)
        from services.switcher import SwitchResult

        return SwitchResult(**raw)


def _parse_budget_override(value: str) -> tuple[str, float]:
    if "=" not in value:
        raise ValueError("Budget overrides must use STAGE=MS.")
    name, raw_amount = value.split("=", 1)
    name = name.strip()
    if name not in DEFAULT_LATENCY_BUDGETS_MS:
        raise ValueError(f"Unknown latency budget stage: {name}")
    return name, float(raw_amount)


def _deterministic_latency(base_ms: float, index: int, step_ms: float) -> float:
    return base_ms + ((index * step_ms) % (step_ms * 5))


def _stream_id_from_prompt(prompt: str) -> str:
    for stream_id in STREAM_IDS:
        if f"stream_id: {stream_id}" in prompt:
            return stream_id
    for stream_id in STREAM_IDS:
        if f"{stream_id}:" in prompt:
            return stream_id
    return "player_1"


def _switch_status_name(result: Any) -> str:
    if result is None:
        return "not_requested"
    return result.status.value


def _record_end_to_end(
    samples: dict[str, list[float]],
    counts: dict[str, int],
    options: HarnessOptions,
    elapsed_ms: float,
) -> None:
    samples["end_to_end"].append(round(elapsed_ms, 6))
    if elapsed_ms > options.budgets_ms["end_to_end"]:
        counts["late_events"] += 1


def _event_report(
    index: int,
    event: TranscriptEvent,
    status: str,
    elapsed_ms: float,
    signal: HypeSignal | None = None,
    decision: DirectorDecision | None = None,
) -> dict[str, object]:
    return {
        "index": index,
        "stream_id": event.stream_id,
        "status": status,
        "elapsed_ms": round(elapsed_ms, 6),
        "triggered": signal is not None,
        "target_scene": None if decision is None else decision.target_scene,
    }


def _budget_report(
    samples: Mapping[str, Sequence[float]],
    budgets_ms: Mapping[str, float],
) -> dict[str, object]:
    stages = {}
    for stage in STAGE_NAMES:
        distribution = _distribution(samples[stage])
        max_ms = distribution["max_ms"]
        budget_ms = budgets_ms[stage]
        passed = max_ms is None or max_ms <= budget_ms
        stages[stage] = {
            "budget_ms": budget_ms,
            "passed": passed,
            "observed_max_ms": max_ms,
        }
    return {
        "overall_passed": all(stage["passed"] for stage in stages.values()),
        "stages": stages,
    }


def _distribution(values: Sequence[float]) -> dict[str, float | int | None]:
    ordered = sorted(values)
    if not ordered:
        return {
            "count": 0,
            "min_ms": None,
            "max_ms": None,
            "avg_ms": None,
            "p50_ms": None,
            "p95_ms": None,
        }
    return {
        "count": len(ordered),
        "min_ms": round(ordered[0], 6),
        "max_ms": round(ordered[-1], 6),
        "avg_ms": round(mean(ordered), 6),
        "p50_ms": round(_percentile(ordered, 0.50), 6),
        "p95_ms": round(_percentile(ordered, 0.95), 6),
    }


def _percentile(ordered: Sequence[float], percentile: float) -> float:
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * percentile
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _process_info() -> dict[str, object]:
    return {
        "pid": os.getpid(),
        "python": sys.version.split()[0],
        "platform": sys.platform,
    }


if __name__ == "__main__":
    raise SystemExit(main())
