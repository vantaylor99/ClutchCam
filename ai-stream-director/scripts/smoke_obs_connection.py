"""Check that the configured OBS WebSocket endpoint is reachable and ready."""

from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import asdict, dataclass
from io import StringIO
from pathlib import Path
from typing import Callable, Iterator, Mapping, Sequence


PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from config import SCENES, get_config, redact_secrets  # noqa: E402
from obs_controller import OBSController, collect_obs_preflight  # noqa: E402


class SmokeFailure(RuntimeError):
    """Raised when the OBS connection smoke cannot complete."""


@dataclass(frozen=True)
class OBSSmokeResult:
    host: str
    port: int
    dry_run_obs: bool
    password_configured: bool
    obs_version: str
    current_program_scene: str
    scenes: tuple[str, ...]
    missing_required_scenes: tuple[str, ...]


def smoke_obs_connection(
    env: Mapping[str, str] | None = None,
    *,
    controller_factory: Callable[..., OBSController] = OBSController,
) -> OBSSmokeResult:
    runtime_env = dict(os.environ if env is None else env)
    with _applied_env(runtime_env):
        config = get_config()

    if config.dry_run_obs:
        raise SmokeFailure(
            "OBS connection smoke requires DRY_RUN_OBS=false so it can verify a real "
            "OBS WebSocket session."
        )

    controller = controller_factory(
        host=config.obs_host,
        port=config.obs_port,
        password=config.obs_password,
        log=lambda message: None,
    )
    try:
        with _suppress_obs_client_output():
            controller.connect()
            preflight = collect_obs_preflight(
                controller,
                required_scenes=SCENES.values(),
            )
    except Exception as exc:
        raise SmokeFailure(
            "OBS connection preflight failed "
            f"(host={config.obs_host}, port={config.obs_port}, "
            f"password_configured={str(bool(config.obs_password)).lower()}): {exc}"
        ) from exc

    if preflight.missing_required_scenes:
        raise SmokeFailure(
            "OBS connection preflight found missing required scenes "
            f"(host={config.obs_host}, port={config.obs_port}, "
            f"current_program_scene={preflight.current_program_scene!r}, "
            f"missing={', '.join(preflight.missing_required_scenes)})."
        )

    return OBSSmokeResult(
        host=config.obs_host,
        port=config.obs_port,
        dry_run_obs=config.dry_run_obs,
        password_configured=bool(config.obs_password),
        obs_version=preflight.obs_version,
        current_program_scene=preflight.current_program_scene,
        scenes=preflight.scenes,
        missing_required_scenes=preflight.missing_required_scenes,
    )


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    try:
        result = smoke_obs_connection()
    except (SmokeFailure, ValueError) as exc:
        print(f"obs connection smoke failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(redact_secrets(asdict(result)), indent=2, sort_keys=True))
    return 0


@contextmanager
def _applied_env(env: Mapping[str, str]) -> Iterator[None]:
    previous_env = dict(os.environ)
    os.environ.clear()
    os.environ.update(env)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous_env)


@contextmanager
def _suppress_obs_client_output() -> Iterator[None]:
    with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
        yield


if __name__ == "__main__":
    raise SystemExit(main())
