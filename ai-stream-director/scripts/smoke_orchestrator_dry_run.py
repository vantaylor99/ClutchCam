"""Run the terminal orchestrator in dry-run OBS mode with bounded input."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Iterator, Mapping, Sequence


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_LINES = (
    "/status",
    "/ai off",
    "player_3: no way, I just found something crazy",
    "/p2",
    "/quad",
    "/quit",
)


class SmokeFailure(RuntimeError):
    """Raised when the orchestrator dry-run smoke cannot complete."""


@dataclass(frozen=True)
class OrchestratorSmokeResult:
    command: tuple[str, ...]
    timeout_seconds: float
    returncode: int
    used_fake_ai: bool
    stdout: str
    stderr: str


def input_text_from_env(env: Mapping[str, str] = os.environ) -> str:
    configured = env.get("SMOKE_ORCHESTRATOR_INPUT")
    if configured:
        text = configured.replace("\\n", "\n")
    else:
        text = "\n".join(DEFAULT_INPUT_LINES)
    if not text.endswith("\n"):
        text += "\n"
    return text


def build_command(env: Mapping[str, str] = os.environ) -> list[str]:
    python = env.get("PYTHON_EXECUTABLE", sys.executable)
    return [python, "src/main.py"]


def build_subprocess_env(
    env: Mapping[str, str],
    *,
    fake_ai_url: str | None = None,
) -> dict[str, str]:
    runtime_env = dict(os.environ)
    runtime_env.update(env)
    runtime_env["DRY_RUN_OBS"] = "true"
    if fake_ai_url is not None:
        runtime_env["AI_PROVIDER"] = "openai-compatible"
        runtime_env["GEMMA_API_URL"] = fake_ai_url
        runtime_env["GEMMA_MODEL"] = "smoke-model"
        runtime_env["GEMMA_API_KEY"] = ""
    return runtime_env


def smoke_orchestrator_dry_run(
    env: Mapping[str, str] = os.environ,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> OrchestratorSmokeResult:
    timeout_seconds = _env_float(env, "SMOKE_ORCHESTRATOR_TIMEOUT_SECONDS", 20.0)
    use_fake_ai = _env_bool(env, "SMOKE_ORCHESTRATOR_FAKE_AI", True)
    command = build_command(env)
    input_text = input_text_from_env(env)

    with _fake_openai_server(use_fake_ai) as fake_ai_url:
        runtime_env = build_subprocess_env(env, fake_ai_url=fake_ai_url)
        try:
            result = run(
                command,
                cwd=str(PROJECT_DIR),
                env=runtime_env,
                input=input_text,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise SmokeFailure(
                "Timed out running orchestrator dry-run smoke after "
                f"{timeout_seconds:g}s."
            ) from exc

    if result.returncode != 0:
        raise SmokeFailure(
            "Orchestrator dry-run exited with code "
            f"{result.returncode}: {_completed_output(result)}"
        )

    _assert_expected_output(result.stdout or "")
    return OrchestratorSmokeResult(
        command=tuple(command),
        timeout_seconds=timeout_seconds,
        returncode=result.returncode,
        used_fake_ai=use_fake_ai,
        stdout=result.stdout or "",
        stderr=result.stderr or "",
    )


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    try:
        result = smoke_orchestrator_dry_run()
    except (SmokeFailure, OSError, ValueError) as exc:
        print(f"orchestrator dry-run smoke failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(asdict(result), indent=2, sort_keys=True))
    return 0


@contextmanager
def _fake_openai_server(enabled: bool) -> Iterator[str | None]:
    if not enabled:
        yield None
        return

    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOpenAIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class _FakeOpenAIHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self._send_json({"ok": True})

    def do_POST(self) -> None:
        payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "target_scene": "Quad View",
                                "confidence": 0.1,
                                "duration_seconds": 8,
                                "reason": "Smoke fixture keeps quad view.",
                            }
                        )
                    }
                }
            ]
        }
        self._send_json(payload)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_json(self, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _assert_expected_output(stdout: str) -> None:
    required_fragments = (
        "DRY_RUN_OBS enabled",
        "[DRY RUN OBS] Starting scene: Quad View",
        "Manual command applied.",
        "Exiting.",
    )
    missing = [fragment for fragment in required_fragments if fragment not in stdout]
    if missing:
        raise SmokeFailure(
            "Orchestrator dry-run output was missing expected text: "
            + ", ".join(missing)
        )


def _completed_output(result: subprocess.CompletedProcess[str]) -> str:
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    return output.strip() or f"exit code {result.returncode}"


def _env_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    value = env.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_float(env: Mapping[str, str], name: str, default: float) -> float:
    value = env.get(name)
    if value is None or not value.strip():
        return default
    return float(value)


if __name__ == "__main__":
    raise SystemExit(main())
