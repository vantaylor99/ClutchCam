"""Smoke the configured Gemma AI endpoint."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlparse, urlunparse

import requests


PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from config import (  # noqa: E402
    AI_PROVIDER_OLLAMA,
    AI_PROVIDER_OPENAI_COMPATIBLE,
    normalize_ai_provider,
)


class SmokeFailure(RuntimeError):
    """Raised when the AI endpoint smoke cannot complete."""


@dataclass(frozen=True)
class AISmokeResult:
    provider: str
    url: str
    model: str
    timeout_seconds: float
    available_models: tuple[str, ...] = ()


def smoke_ai_endpoint(
    env: Mapping[str, str] = os.environ,
    *,
    get: Callable[..., Any] = requests.get,
) -> AISmokeResult:
    provider = normalize_ai_provider(env.get("AI_PROVIDER", AI_PROVIDER_OLLAMA))
    api_url = env.get("GEMMA_API_URL") or env.get("OLLAMA_BASE_URL") or "http://127.0.0.1:11434"
    model = env.get("GEMMA_MODEL") or env.get("OLLAMA_MODEL") or "gemma3:4b"
    timeout_seconds = _env_float(
        env,
        "SMOKE_AI_TIMEOUT_SECONDS",
        _env_float(env, "SMOKE_HTTP_TIMEOUT_SECONDS", 5.0),
    )

    if provider == AI_PROVIDER_OLLAMA:
        return _smoke_ollama(
            api_url=api_url,
            model=model,
            timeout_seconds=timeout_seconds,
            get=get,
        )
    if provider == AI_PROVIDER_OPENAI_COMPATIBLE:
        return _smoke_openai_compatible(
            api_url=api_url,
            model=model,
            timeout_seconds=timeout_seconds,
            api_key=env.get("GEMMA_API_KEY", ""),
            get=get,
        )

    raise SmokeFailure(f"Unsupported AI provider: {provider}")


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    try:
        result = smoke_ai_endpoint()
    except (SmokeFailure, ValueError) as exc:
        print(f"ai-endpoint smoke failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(asdict(result), indent=2, sort_keys=True))
    return 0


def _smoke_ollama(
    *,
    api_url: str,
    model: str,
    timeout_seconds: float,
    get: Callable[..., Any],
) -> AISmokeResult:
    tags_url = f"{api_url.rstrip('/')}/api/tags"
    try:
        response = get(tags_url, timeout=timeout_seconds)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        raise SmokeFailure(
            f"Ollama is not reachable at {tags_url} within {timeout_seconds:g}s: {exc}"
        ) from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        raise SmokeFailure("Ollama /api/tags response did not include a model list.")

    available_models = tuple(sorted(_model_names(payload["models"])))
    if model not in available_models:
        raise SmokeFailure(
            f'Ollama model "{model}" is not installed. Run: ollama pull {model}'
        )

    return AISmokeResult(
        provider=AI_PROVIDER_OLLAMA,
        url=tags_url,
        model=model,
        timeout_seconds=timeout_seconds,
        available_models=available_models,
    )


def _smoke_openai_compatible(
    *,
    api_url: str,
    model: str,
    timeout_seconds: float,
    api_key: str,
    get: Callable[..., Any],
) -> AISmokeResult:
    readiness_url = _readiness_probe_url(api_url)
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = get(readiness_url, timeout=timeout_seconds, headers=headers)
        response.raise_for_status()
    except Exception as exc:
        raise SmokeFailure(
            "OpenAI-compatible AI provider is not reachable at "
            f"{readiness_url} within {timeout_seconds:g}s: {exc}"
        ) from exc

    return AISmokeResult(
        provider=AI_PROVIDER_OPENAI_COMPATIBLE,
        url=readiness_url,
        model=model,
        timeout_seconds=timeout_seconds,
    )


def _model_names(models: list[object]) -> set[str]:
    names: set[str] = set()
    for model_info in models:
        if not isinstance(model_info, dict):
            continue
        for key in ("name", "model"):
            value = model_info.get(key)
            if isinstance(value, str):
                names.add(value)
    return names


def _readiness_probe_url(api_url: str) -> str:
    stripped_url = api_url.strip().rstrip("/")
    parsed = urlparse(stripped_url)
    if parsed.scheme and parsed.netloc:
        return urlunparse(
            parsed._replace(path="", params="", query="", fragment="")
        ).rstrip("/")
    return stripped_url


def _env_float(env: Mapping[str, str], name: str, default: float) -> float:
    value = env.get(name)
    if value is None or not value.strip():
        return default
    return float(value)


if __name__ == "__main__":
    raise SystemExit(main())
