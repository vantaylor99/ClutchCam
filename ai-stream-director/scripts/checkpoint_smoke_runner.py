"""Run a bounded local checkpoint across the smoke entrypoints."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, TextIO


PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

STATUS_PASSED = "passed"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

CHECK_NAMES = (
    "media-server",
    "buffer",
    "transcription",
    "ai",
    "orchestrator",
)

SmokeCallable = Callable[[Mapping[str, str]], object]


@dataclass(frozen=True)
class CheckDefinition:
    name: str
    command: tuple[str, ...]
    runner: SmokeCallable
    enabled_by_default: bool
    default_skip_reason: str


@dataclass(frozen=True)
class RunnerOptions:
    run_all: bool = False
    skip_all: bool = False
    run_checks: frozenset[str] = field(default_factory=frozenset)
    skip_checks: frozenset[str] = field(default_factory=frozenset)


def build_default_registry() -> tuple[CheckDefinition, ...]:
    return (
        CheckDefinition(
            name="media-server",
            command=("python", "scripts/smoke_media_server.py"),
            runner=_run_media_server,
            enabled_by_default=False,
            default_skip_reason=(
                "opt-in: pass --run-media-server or "
                "CHECKPOINT_SMOKE_RUN_MEDIA_SERVER=true; may start Docker, "
                "FFmpeg, and call SRS"
            ),
        ),
        CheckDefinition(
            name="buffer",
            command=("python", "scripts/smoke_buffer_worker.py"),
            runner=_run_buffer_worker,
            enabled_by_default=False,
            default_skip_reason=(
                "opt-in: pass --run-buffer or CHECKPOINT_SMOKE_RUN_BUFFER=true; "
                "requires existing rolling-buffer segment metadata"
            ),
        ),
        CheckDefinition(
            name="transcription",
            command=("python", "scripts/smoke_transcription_api.py"),
            runner=_run_transcription_api,
            enabled_by_default=False,
            default_skip_reason=(
                "opt-in: pass --run-transcription or "
                "CHECKPOINT_SMOKE_RUN_TRANSCRIPTION=true; calls "
                "TRANSCRIPTION_API_URL"
            ),
        ),
        CheckDefinition(
            name="ai",
            command=("python", "scripts/smoke_ai_endpoint.py"),
            runner=_run_ai_endpoint,
            enabled_by_default=False,
            default_skip_reason=(
                "opt-in: pass --run-ai or CHECKPOINT_SMOKE_RUN_AI=true; "
                "calls the configured AI endpoint"
            ),
        ),
        CheckDefinition(
            name="orchestrator",
            command=("python", "scripts/smoke_orchestrator_dry_run.py"),
            runner=_run_orchestrator_dry_run,
            enabled_by_default=True,
            default_skip_reason=(
                "disabled only when --skip-orchestrator or "
                "CHECKPOINT_SMOKE_SKIP_ORCHESTRATOR=true is set"
            ),
        ),
    )


def run_checkpoint_smokes(
    env: Mapping[str, str] = os.environ,
    *,
    registry: Sequence[CheckDefinition] | Mapping[str, CheckDefinition] | None = None,
    options: RunnerOptions | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, object]:
    selected_options = options or RunnerOptions()
    checks = _normalize_registry(registry or build_default_registry())
    _validate_options(selected_options, checks)

    runtime_env = dict(env)
    started_at = clock()
    check_reports = []
    for check in checks:
        enabled, selection_reason = _selection_for_check(
            check,
            runtime_env,
            selected_options,
        )
        if not enabled:
            check_reports.append(_skipped_report(check, selection_reason))
            continue

        check_reports.append(
            _run_check(
                check,
                runtime_env,
                selection_reason=selection_reason,
                clock=clock,
            )
        )

    return {
        "schema_version": 1,
        "status": _overall_status(check_reports),
        "duration_seconds": _duration_since(started_at, clock),
        "checks": check_reports,
    }


def main(
    argv: Sequence[str] | None = None,
    *,
    registry: Sequence[CheckDefinition] | Mapping[str, CheckDefinition] | None = None,
    env: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.run_all and args.skip_all:
        parser.error("--run-all cannot be combined with --skip-all")

    options = RunnerOptions(
        run_all=args.run_all,
        skip_all=args.skip_all,
        run_checks=frozenset(args.run_checks or ()),
        skip_checks=frozenset(args.skip_checks or ()),
    )
    report = run_checkpoint_smokes(
        os.environ if env is None else env,
        registry=registry,
        options=options,
    )
    stream = stdout or sys.stdout
    print(json.dumps(report, indent=args.indent, sort_keys=True), file=stream)
    return 1 if report["status"] == STATUS_FAILED else 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-all",
        action="store_true",
        help=(
            "Run every smoke boundary. This can start Docker/FFmpeg and call "
            "configured HTTP endpoints."
        ),
    )
    parser.add_argument(
        "--skip-all",
        action="store_true",
        help="Skip every boundary and emit a skipped report.",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indentation. Defaults to 2.",
    )
    for check_name in CHECK_NAMES:
        parser.add_argument(
            f"--run-{check_name}",
            action="append_const",
            const=check_name,
            dest="run_checks",
            help=f"Run the {check_name} smoke boundary.",
        )
        parser.add_argument(
            f"--skip-{check_name}",
            f"--no-{check_name}",
            action="append_const",
            const=check_name,
            dest="skip_checks",
            help=f"Skip the {check_name} smoke boundary.",
        )
    return parser


def _run_check(
    check: CheckDefinition,
    env: Mapping[str, str],
    *,
    selection_reason: str,
    clock: Callable[[], float],
) -> dict[str, object]:
    started_at = clock()
    try:
        result = check.runner(env)
    except Exception as exc:
        return _base_report(
            check,
            status=STATUS_FAILED,
            duration_seconds=_duration_since(started_at, clock),
            selection_reason=selection_reason,
            skip_reason=None,
            error_reason=str(exc) or exc.__class__.__name__,
            result=None,
        )

    return _base_report(
        check,
        status=STATUS_PASSED,
        duration_seconds=_duration_since(started_at, clock),
        selection_reason=selection_reason,
        skip_reason=None,
        error_reason=None,
        result=_jsonable(result),
    )


def _skipped_report(check: CheckDefinition, reason: str) -> dict[str, object]:
    return _base_report(
        check,
        status=STATUS_SKIPPED,
        duration_seconds=0.0,
        selection_reason=reason,
        skip_reason=reason,
        error_reason=None,
        result=None,
    )


def _base_report(
    check: CheckDefinition,
    *,
    status: str,
    duration_seconds: float,
    selection_reason: str,
    skip_reason: str | None,
    error_reason: str | None,
    result: object | None,
) -> dict[str, object]:
    return {
        "name": check.name,
        "status": status,
        "duration_seconds": duration_seconds,
        "command": list(check.command),
        "context": {
            "enabled_by_default": check.enabled_by_default,
            "selection": selection_reason,
        },
        "skip_reason": skip_reason,
        "error_reason": error_reason,
        "result": result,
    }


def _selection_for_check(
    check: CheckDefinition,
    env: Mapping[str, str],
    options: RunnerOptions,
) -> tuple[bool, str]:
    if check.name in options.skip_checks:
        return False, f"disabled by --skip-{check.name}"
    if check.name in options.run_checks:
        return True, f"enabled by --run-{check.name}"
    if options.skip_all:
        return False, "disabled by --skip-all"
    if options.run_all:
        return True, "enabled by --run-all"

    suffix = _env_suffix(check.name)
    if _env_bool(env, f"CHECKPOINT_SMOKE_SKIP_{suffix}", False):
        return False, f"disabled by CHECKPOINT_SMOKE_SKIP_{suffix}"
    if _env_bool(env, f"CHECKPOINT_SMOKE_RUN_{suffix}", False):
        return True, f"enabled by CHECKPOINT_SMOKE_RUN_{suffix}"
    if _env_bool(env, "CHECKPOINT_SMOKE_SKIP_ALL", False):
        return False, "disabled by CHECKPOINT_SMOKE_SKIP_ALL"
    if _env_bool(env, "CHECKPOINT_SMOKE_RUN_ALL", False):
        return True, "enabled by CHECKPOINT_SMOKE_RUN_ALL"

    if check.enabled_by_default:
        return True, "enabled by safe default"
    return False, check.default_skip_reason


def _normalize_registry(
    registry: Sequence[CheckDefinition] | Mapping[str, CheckDefinition],
) -> tuple[CheckDefinition, ...]:
    if isinstance(registry, Mapping):
        checks = tuple(registry.values())
    else:
        checks = tuple(registry)

    names = [check.name for check in checks]
    duplicates = sorted(name for name in set(names) if names.count(name) > 1)
    if duplicates:
        raise ValueError("Duplicate checkpoint smoke checks: " + ", ".join(duplicates))
    return checks


def _validate_options(options: RunnerOptions, checks: Sequence[CheckDefinition]) -> None:
    valid_names = {check.name for check in checks}
    unknown = sorted((options.run_checks | options.skip_checks).difference(valid_names))
    if unknown:
        raise ValueError("Unknown checkpoint smoke checks: " + ", ".join(unknown))


def _overall_status(check_reports: Sequence[Mapping[str, object]]) -> str:
    statuses = [str(report["status"]) for report in check_reports]
    if STATUS_FAILED in statuses:
        return STATUS_FAILED
    if STATUS_PASSED in statuses:
        return STATUS_PASSED
    return STATUS_SKIPPED


def _duration_since(started_at: float, clock: Callable[[], float]) -> float:
    return round(max(0.0, clock() - started_at), 6)


def _jsonable(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, set):
        return sorted(_jsonable(item) for item in value)
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def _env_suffix(check_name: str) -> str:
    return check_name.upper().replace("-", "_")


def _env_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    value = env.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _import_script_module(module_name: str) -> Any:
    try:
        return importlib.import_module(f"scripts.{module_name}")
    except ModuleNotFoundError as exc:
        if exc.name not in {"scripts", f"scripts.{module_name}"}:
            raise
        return importlib.import_module(module_name)


def _run_media_server(env: Mapping[str, str]) -> object:
    module = _import_script_module("smoke_media_server")
    return module.smoke_media_server(env)


def _run_buffer_worker(env: Mapping[str, str]) -> object:
    module = _import_script_module("smoke_buffer_worker")
    result = module.inspect_buffer(env)
    module.assert_any_ready(result)
    return result


def _run_transcription_api(env: Mapping[str, str]) -> object:
    module = _import_script_module("smoke_transcription_api")
    return module.smoke_transcription_api(env)


def _run_ai_endpoint(env: Mapping[str, str]) -> object:
    module = _import_script_module("smoke_ai_endpoint")
    return module.smoke_ai_endpoint(env)


def _run_orchestrator_dry_run(env: Mapping[str, str]) -> object:
    module = _import_script_module("smoke_orchestrator_dry_run")
    return module.smoke_orchestrator_dry_run(env)


if __name__ == "__main__":
    raise SystemExit(main())
