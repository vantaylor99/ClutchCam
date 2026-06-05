import queue
import sys
import threading
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TextIO

from ai_director import AIDirector, AIDirectorError, DirectorDecision
from config import SCENES, get_config
from contracts import HypeSignal, SwitcherTarget, TranscriptEvent
from obs_controller import DryRunOBSController, OBSController
from scheduler import MANUAL_COMMAND_SCENES, SceneScheduler
from services.ai import (
    HypeContext,
    TranscriptTriggerPrefilter,
    TranscriptTriggerPrefilterConfig,
)
from services.health import run_runtime_healthcheck
from services.switcher import (
    OutputSwitchError,
    OutputSwitcher,
    SwitchResult,
    buffered_target_from_signal,
)
from transcript_router import TranscriptMessage, TranscriptRouter


HELP_TEXT = """
Type transcript lines like:
  player_3: no way, I just found something crazy

Manual commands:
  /quad   Switch to Quad View
  /p1     Switch to Player 1 Fullscreen
  /p2     Switch to Player 2 Fullscreen
  /p3     Switch to Player 3 Fullscreen
  /p4     Switch to Player 4 Fullscreen
  /ai on  Enable AI decisions
  /ai off Disable AI decisions
  /status Show current app state
  /quit   Exit
""".strip()


TICK_INTERVAL_SECONDS = 0.25
INPUT_CLOSED = None
PROMPT_TEXT = "> "


@dataclass(frozen=True)
class RuntimeTranscriptEventResult:
    accepted: bool
    message: TranscriptMessage | None = None
    candidate_signal: HypeSignal | None = None
    decision: DirectorDecision | None = None
    switch_target: SwitcherTarget | None = None
    switch_result: SwitchResult | None = None
    ai_evaluation_attempted: bool = False
    reason: str = ""


class RuntimeTranscriptEventHandler:
    """Callable sink that routes normalized runtime transcript events."""

    def __init__(
        self,
        *,
        transcript_router: TranscriptRouter,
        ai_director: AIDirector,
        scheduler: SceneScheduler,
        trigger_prefilter: TranscriptTriggerPrefilter | None = None,
        output_switcher: OutputSwitcher | None = None,
        switch_lookback_seconds: int = 15,
        log=print,
    ) -> None:
        self.transcript_router = transcript_router
        self.ai_director = ai_director
        self.scheduler = scheduler
        self.trigger_prefilter = trigger_prefilter
        self.output_switcher = output_switcher
        self.switch_lookback_seconds = switch_lookback_seconds
        self.log = log

    def __call__(self, event: TranscriptEvent) -> RuntimeTranscriptEventResult | None:
        result = process_transcript_event(
            event,
            self.transcript_router,
            self.ai_director,
            self.scheduler,
            trigger_prefilter=self.trigger_prefilter,
            output_switcher=self.output_switcher,
            switch_lookback_seconds=self.switch_lookback_seconds,
            log=self.log,
        )
        if not result.accepted:
            return None
        return result


class TerminalOutput:
    def __init__(self, stream: TextIO | None = None, prompt: str = PROMPT_TEXT):
        self.stream = stream or sys.stdout
        self.prompt = prompt
        self.refresh_prompt = False
        self._lock = threading.Lock()

    def enable_prompt_refresh(self) -> None:
        self.refresh_prompt = True

    def log(self, message: str) -> None:
        with self._lock:
            if not self.refresh_prompt:
                print(message, file=self.stream)
                return

            self.stream.write(f"\n{message}\n{self.prompt}")
            self.stream.flush()


def main(argv: Sequence[str] | None = None) -> int:
    args = tuple(sys.argv[1:] if argv is None else argv)
    if args == ("--healthcheck",):
        return run_runtime_healthcheck("orchestrator")
    if args:
        print("Unknown orchestrator arguments: " + " ".join(args))
        return 2

    config = get_config()
    terminal_output = TerminalOutput()

    if config.dry_run_obs:
        obs_controller = DryRunOBSController(
            initial_scene=config.default_scene,
            log=terminal_output.log,
        )
    else:
        obs_controller = OBSController(
            host=config.obs_host,
            port=config.obs_port,
            password=config.obs_password,
            log=terminal_output.log,
        )
    ai_director = AIDirector(
        ollama_base_url=config.gemma_api_url,
        model=config.gemma_model,
        ai_provider=config.ai_provider,
        api_key=config.gemma_api_key,
    )
    trigger_prefilter = TranscriptTriggerPrefilter(
        TranscriptTriggerPrefilterConfig(
            enabled=config.transcript_prefilter_enabled,
            min_text_characters=config.transcript_prefilter_min_text_characters,
            duplicate_window_seconds=(
                config.transcript_prefilter_duplicate_window_seconds
            ),
            context_window_seconds=config.transcript_prefilter_context_seconds,
            min_confidence=config.transcript_prefilter_min_confidence,
        )
    )
    transcript_router = TranscriptRouter(
        history_seconds=config.transcript_history_seconds,
        max_messages=config.transcript_history_messages,
    )
    scheduler = SceneScheduler(
        obs_controller=obs_controller,
        default_scene=config.default_scene,
        confidence_threshold=config.confidence_threshold,
        min_switch_interval_seconds=config.min_switch_interval_seconds,
        max_focus_duration_seconds=config.max_focus_duration_seconds,
        log=terminal_output.log,
    )

    print("AI Stream Director MVP")
    print("======================")
    print(HELP_TEXT)
    print()

    try:
        ai_director.check_readiness()
    except AIDirectorError as exc:
        print(f"AI director is not ready: {exc}")
        return 1

    try:
        obs_controller.connect()
        if not config.dry_run_obs:
            missing_scenes = find_missing_scenes(
                available_scenes=obs_controller.list_scenes(),
                required_scenes=SCENES.values(),
            )
            if missing_scenes:
                print("OBS is missing required scenes:")
                for scene_name in missing_scenes:
                    print(f"  - {scene_name}")
                print("Create or rename the OBS scenes so they match exactly.")
                return 1
        scheduler.start()
    except Exception as exc:
        if config.dry_run_obs:
            print(f"Could not start dry-run OBS controller: {exc}")
        else:
            print(f"Could not connect to OBS WebSocket: {exc}")
            print("Check OBS WebSocket settings and your .env values.")
        return 1

    input_queue: queue.Queue[str | None] = queue.Queue()
    input_thread = threading.Thread(
        target=read_terminal_input,
        args=(input_queue,),
        daemon=True,
    )
    input_thread.start()
    terminal_output.enable_prompt_refresh()

    try:
        while True:
            scheduler.tick()

            try:
                line = input_queue.get(timeout=TICK_INTERVAL_SECONDS)
            except queue.Empty:
                continue

            if line is INPUT_CLOSED:
                print()
                print("Exiting.")
                return 0

            if process_line(
                line,
                transcript_router,
                ai_director,
                scheduler,
                trigger_prefilter=trigger_prefilter,
                log=terminal_output.log,
            ):
                return 0
    except KeyboardInterrupt:
        print()
        print("Exiting.")
        return 0

    return 0


def find_missing_scenes(
    available_scenes: Iterable[str],
    required_scenes: Iterable[str],
) -> list[str]:
    available = set(available_scenes)
    return [scene_name for scene_name in required_scenes if scene_name not in available]


def read_terminal_input(input_queue: queue.Queue[str | None]) -> None:
    while True:
        try:
            line = input(PROMPT_TEXT).strip()
        except (EOFError, KeyboardInterrupt):
            input_queue.put(INPUT_CLOSED)
            return

        input_queue.put(line)


def process_line(
    line: str,
    transcript_router: TranscriptRouter,
    ai_director: AIDirector,
    scheduler: SceneScheduler,
    trigger_prefilter: TranscriptTriggerPrefilter | None = None,
    log=print,
) -> bool:
    if not line:
        return False

    if line.startswith("/"):
        return handle_command(line, scheduler, log=log)

    message = transcript_router.parse_line(line)
    if message is None:
        log("Could not parse line. Use format: player_1: transcript text")
        return False

    evaluate_accepted_transcript(
        message=message,
        transcript_router=transcript_router,
        ai_director=ai_director,
        scheduler=scheduler,
        trigger_prefilter=trigger_prefilter,
        log=log,
    )
    return False


def process_transcript_event(
    event: TranscriptEvent,
    transcript_router: TranscriptRouter,
    ai_director: AIDirector,
    scheduler: SceneScheduler,
    trigger_prefilter: TranscriptTriggerPrefilter | None = None,
    output_switcher: OutputSwitcher | None = None,
    switch_lookback_seconds: int = 15,
    log=print,
) -> RuntimeTranscriptEventResult:
    message = transcript_router.add_event(event)
    if message is None:
        log(f"Transcript event rejected from {event.stream_id}.")
        return RuntimeTranscriptEventResult(
            accepted=False,
            reason="router_rejected",
        )

    return evaluate_accepted_transcript(
        message=message,
        transcript_router=transcript_router,
        ai_director=ai_director,
        scheduler=scheduler,
        trigger_prefilter=trigger_prefilter,
        output_switcher=output_switcher,
        switch_lookback_seconds=switch_lookback_seconds,
        log=log,
    )


def evaluate_accepted_transcript(
    *,
    message: TranscriptMessage,
    transcript_router: TranscriptRouter,
    ai_director: AIDirector,
    scheduler: SceneScheduler,
    trigger_prefilter: TranscriptTriggerPrefilter | None = None,
    output_switcher: OutputSwitcher | None = None,
    switch_lookback_seconds: int = 15,
    log=print,
) -> RuntimeTranscriptEventResult:
    if not scheduler.status().ai_enabled:
        log(
            f"Transcript accepted from {message.speaker}. "
            "AI evaluation skipped because AI mode is off."
        )
        return RuntimeTranscriptEventResult(
            accepted=True,
            message=message,
            reason="ai_disabled",
        )

    gate = scheduler.ai_evaluation_gate()
    if not gate.allowed:
        if gate.cooldown_remaining_seconds > 0:
            log(
                f"Transcript accepted from {message.speaker}. "
                "AI evaluation skipped because switch cooldown has "
                f"{gate.cooldown_remaining_seconds:.1f}s left."
            )
        else:
            log(
                f"Transcript accepted from {message.speaker}. "
                f"AI evaluation skipped because {gate.reason}"
            )
        return RuntimeTranscriptEventResult(
            accepted=True,
            message=message,
            reason="scheduler_gate_blocked",
        )

    trigger_prefilter = trigger_prefilter or TranscriptTriggerPrefilter()
    candidate_signal = trigger_prefilter.classify(
        HypeContext(
            transcripts=transcript_router.get_recent_events(),
            reference_time_seconds=message.timestamp,
        )
    )
    if candidate_signal is None:
        log(
            f"Transcript accepted from {message.speaker}. "
            "Local prefilter found no trigger; AI evaluation skipped."
        )
        return RuntimeTranscriptEventResult(
            accepted=True,
            message=message,
            reason="prefilter_rejected",
        )

    log(
        f"Transcript accepted from {message.speaker}. "
        "Local trigger found; Asking AI director..."
    )
    try:
        context = transcript_router.get_recent_context_text()
        decision = ai_director.decide(context, candidate_signal=candidate_signal)
    except AIDirectorError as exc:
        log(f"AI decision failed: {exc}")
        return RuntimeTranscriptEventResult(
            accepted=True,
            message=message,
            candidate_signal=candidate_signal,
            ai_evaluation_attempted=True,
            reason="ai_error",
        )
    except Exception as exc:
        log(f"AI decision failed unexpectedly: {exc}")
        return RuntimeTranscriptEventResult(
            accepted=True,
            message=message,
            candidate_signal=candidate_signal,
            ai_evaluation_attempted=True,
            reason="ai_error",
        )

    log(
        "AI decision: "
        f"{decision.target_scene}, confidence={decision.confidence:.2f}, "
        f"duration={decision.duration_seconds}s"
    )
    switch_target = build_runtime_switch_target(
        decision=decision,
        candidate_signal=candidate_signal,
        scheduler=scheduler,
        switch_lookback_seconds=switch_lookback_seconds,
    )
    switch_result = apply_runtime_switch_target(
        switch_target,
        output_switcher=output_switcher,
        log=log,
    )
    scheduler.apply_ai_decision(decision)
    return RuntimeTranscriptEventResult(
        accepted=True,
        message=message,
        candidate_signal=candidate_signal,
        decision=decision,
        switch_target=switch_target,
        switch_result=switch_result,
        ai_evaluation_attempted=True,
        reason="decision_evaluated",
    )


def build_runtime_switch_target(
    *,
    decision: DirectorDecision,
    candidate_signal: HypeSignal,
    scheduler: SceneScheduler,
    switch_lookback_seconds: int,
) -> SwitcherTarget | None:
    if decision.target_scene == scheduler.default_scene:
        return None
    if decision.confidence < scheduler.confidence_threshold:
        return None
    if decision.target_scene != SCENES.get(candidate_signal.stream_id):
        return None

    return buffered_target_from_signal(
        candidate_signal,
        scene_name=decision.target_scene,
        pre_roll_seconds=switch_lookback_seconds,
    )


def apply_runtime_switch_target(
    switch_target: SwitcherTarget | None,
    *,
    output_switcher: OutputSwitcher | None = None,
    log=print,
) -> SwitchResult | None:
    if switch_target is None or output_switcher is None:
        return None

    try:
        result = output_switcher.switch(switch_target)
    except OutputSwitchError as exc:
        log(f"Buffered switch failed: {exc}")
        return None

    log(f"Buffered switch target {result.status.value}: {result.reason}")
    return result


def handle_command(command: str, scheduler: SceneScheduler, log=print) -> bool:
    normalized = command.strip().lower()

    if normalized in MANUAL_COMMAND_SCENES:
        scheduler.force_scene(MANUAL_COMMAND_SCENES[normalized])
        log("Manual command applied.")
        return False

    if normalized == "/ai on":
        scheduler.set_ai_enabled(True)
        return False

    if normalized == "/ai off":
        scheduler.set_ai_enabled(False)
        return False

    if normalized == "/status":
        status = scheduler.status()
        focused_until = "none"
        if status.focused_until is not None:
            remaining = max(0.0, status.focused_until - time.time())
            focused_until = f"{remaining:.1f}s remaining"

        log(
            f"Current scene: {status.current_scene}\n"
            f"AI enabled: {status.ai_enabled}\n"
            f"Focus timer: {focused_until}"
        )
        return False

    if normalized == "/quit":
        log("Exiting.")
        return True

    log("Unknown command. Try /status or /quit.")
    return False


if __name__ == "__main__":
    sys.exit(main())
