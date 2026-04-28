import queue
import sys
import threading
import time

from ai_director import AIDirector
from config import get_config
from obs_controller import DryRunOBSController, OBSController
from scheduler import MANUAL_COMMAND_SCENES, SceneScheduler
from transcript_router import TranscriptRouter


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


def main() -> int:
    config = get_config()

    if config.dry_run_obs:
        obs_controller = DryRunOBSController(initial_scene=config.default_scene)
    else:
        obs_controller = OBSController(
            host=config.obs_host,
            port=config.obs_port,
            password=config.obs_password,
        )
    ai_director = AIDirector(
        ollama_base_url=config.ollama_base_url,
        model=config.ollama_model,
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
    )

    print("AI Stream Director MVP")
    print("======================")
    print(HELP_TEXT)
    print()

    try:
        obs_controller.connect()
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

            if process_line(line, transcript_router, ai_director, scheduler):
                return 0
    except KeyboardInterrupt:
        print()
        print("Exiting.")
        return 0

    return 0


def read_terminal_input(input_queue: queue.Queue[str | None]) -> None:
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            input_queue.put(INPUT_CLOSED)
            return

        input_queue.put(line)


def process_line(
    line: str,
    transcript_router: TranscriptRouter,
    ai_director: AIDirector,
    scheduler: SceneScheduler,
) -> bool:
    if not line:
        return False

    if line.startswith("/"):
        return handle_command(line, scheduler)

    message = transcript_router.parse_line(line)
    if message is None:
        print("Could not parse line. Use format: player_1: transcript text")
        return False

    print(f"Transcript accepted from {message.speaker}. Asking AI director...")
    try:
        context = transcript_router.get_recent_context_text()
        decision = ai_director.decide(context)
    except Exception as exc:
        print(f"AI decision failed: {exc}")
        return False

    print(
        "AI decision: "
        f"{decision.target_scene}, confidence={decision.confidence:.2f}, "
        f"duration={decision.duration_seconds}s"
    )
    scheduler.apply_ai_decision(decision)
    return False


def handle_command(command: str, scheduler: SceneScheduler) -> bool:
    normalized = command.strip().lower()

    if normalized in MANUAL_COMMAND_SCENES:
        scheduler.force_scene(MANUAL_COMMAND_SCENES[normalized])
        print("Manual command applied.")
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

        print(f"Current scene: {status.current_scene}")
        print(f"AI enabled: {status.ai_enabled}")
        print(f"Focus timer: {focused_until}")
        return False

    if normalized == "/quit":
        print("Exiting.")
        return True

    print("Unknown command. Try /status or /quit.")
    return False


if __name__ == "__main__":
    sys.exit(main())
