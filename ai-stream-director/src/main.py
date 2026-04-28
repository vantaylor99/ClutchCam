import sys
import time

from ai_director import AIDirector
from config import get_config
from obs_controller import OBSController
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


def main() -> int:
    config = get_config()

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
        print(f"Could not connect to OBS WebSocket: {exc}")
        print("Check OBS WebSocket settings and your .env values.")
        return 1

    while True:
        scheduler.tick()
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            print("Exiting.")
            return 0

        scheduler.tick()
        if not line:
            continue

        if line.startswith("/"):
            if handle_command(line, scheduler):
                return 0
            continue

        message = transcript_router.parse_line(line)
        if message is None:
            print("Could not parse line. Use format: player_1: transcript text")
            continue

        print(f"Transcript accepted from {message.speaker}. Asking AI director...")
        try:
            context = transcript_router.get_recent_context_text()
            decision = ai_director.decide(context)
        except Exception as exc:
            print(f"AI decision failed: {exc}")
            continue

        print(
            "AI decision: "
            f"{decision.target_scene}, confidence={decision.confidence:.2f}, "
            f"duration={decision.duration_seconds}s"
        )
        scheduler.apply_ai_decision(decision)

    return 0


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
