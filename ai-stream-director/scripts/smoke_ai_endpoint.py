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
    endpoint_url: str
    probe_url: str
    model: str
    timeout_seconds: float
    available_models: tuple[str, ...] = ()
    detected_model_count: int | None = None
    api_key_configured: bool | None = None


def smoke_ai_endpoint(
    env: Mapping[str, str] = os.environ,
    *,
    get: Callable[..., Any] = requests.get,
) -> AISmokeResult:
    provider = normalize_ai_provider(env.get("AI_PROVIDER", AI_PROVIDER_OLLAMA))
    api_url = (
        _env_string(env, "GEMMA_API_URL")
        or _env_string(env, "OLLAMA_BASE_URL")
        or "http://127.0.0.1:11434"
    )
    model = (
        _env_string(env, "GEMMA_MODEL")
        or _env_string(env, "OLLAMA_MODEL")
        or "gemma3:4b"
    )
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
    endpoint_url = api_url.rstrip("/")
    tags_url = f"{endpoint_url}/api/tags"
    try:
        response = get(tags_url, timeout=timeout_seconds)
    except Exception as exc:
        raise _ollama_failure(
            endpoint_url=endpoint_url,
            probe_url=tags_url,
            model=model,
            detail=f"endpoint is not reachable within {timeout_seconds:g}s: {exc}",
        ) from exc

    try:
        response.raise_for_status()
    except Exception as exc:
        raise _ollama_failure(
            endpoint_url=endpoint_url,
            probe_url=tags_url,
            model=model,
            detail=f"readiness request failed within {timeout_seconds:g}s: {exc}",
        ) from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise _ollama_failure(
            endpoint_url=endpoint_url,
            probe_url=tags_url,
            model=model,
            detail="Ollama /api/tags response was not valid JSON.",
        ) from exc

    if not isinstance(payload, dict):
        raise _ollama_failure(
            endpoint_url=endpoint_url,
            probe_url=tags_url,
            model=model,
            detail=(
                "Ollama /api/tags response did not include a model list "
                f"(expected object, got {_type_name(payload)})."
            ),
        )

    model_list = payload.get("models")
    if not isinstance(model_list, list):
        raise _ollama_failure(
            endpoint_url=endpoint_url,
            probe_url=tags_url,
            model=model,
            detail=(
                "Ollama /api/tags response did not include a model list "
                f"(expected list at models, got {_type_name(model_list)})."
            ),
        )

    available_models = tuple(sorted(_model_names(model_list)))
    if model_list and not available_models:
        raise _ollama_failure(
            endpoint_url=endpoint_url,
            probe_url=tags_url,
            model=model,
            detail=(
                "Ollama /api/tags model list did not contain any parseable "
                'model names. Expected each entry to expose a string "name" '
                'or "model" field.'
            ),
        )
    if model not in available_models:
        raise _ollama_failure(
            endpoint_url=endpoint_url,
            probe_url=tags_url,
            model=model,
            detail=(
                f'Ollama model "{model}" is not installed. '
                f"Detected models: {_format_models(available_models)}. "
                f"Run: {_ollama_pull_command(model)}"
            ),
        )

    return AISmokeResult(
        provider=AI_PROVIDER_OLLAMA,
        url=tags_url,
        endpoint_url=endpoint_url,
        probe_url=tags_url,
        model=model,
        timeout_seconds=timeout_seconds,
        available_models=available_models,
        detected_model_count=len(available_models),
    )


def _smoke_openai_compatible(
    *,
    api_url: str,
    model: str,
    timeout_seconds: float,
    api_key: str,
    get: Callable[..., Any],
) -> AISmokeResult:
    endpoint_url = api_url.strip().rstrip("/")
    readiness_url = _readiness_probe_url(api_url)
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = get(readiness_url, timeout=timeout_seconds, headers=headers)
    except Exception as exc:
        raise _openai_compatible_failure(
            endpoint_url=endpoint_url,
            probe_url=readiness_url,
            model=model,
            api_key_configured=bool(api_key),
            detail=f"provider is not reachable within {timeout_seconds:g}s: {exc}",
        ) from exc

    try:
        response.raise_for_status()
    except Exception as exc:
        raise _openai_compatible_failure(
            endpoint_url=endpoint_url,
            probe_url=readiness_url,
            model=model,
            api_key_configured=bool(api_key),
            detail=f"readiness request failed within {timeout_seconds:g}s: {exc}",
        ) from exc

    return AISmokeResult(
        provider=AI_PROVIDER_OPENAI_COMPATIBLE,
        url=readiness_url,
        endpoint_url=endpoint_url,
        probe_url=readiness_url,
        model=model,
        timeout_seconds=timeout_seconds,
        api_key_configured=bool(api_key),
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


def _ollama_failure(
    *,
    endpoint_url: str,
    probe_url: str,
    model: str,
    detail: str,
) -> SmokeFailure:
    return SmokeFailure(
        "Ollama readiness failed "
        f"(provider={AI_PROVIDER_OLLAMA}, endpoint={endpoint_url}, "
        f"probe={probe_url}, model={model}): {detail}"
    )


def _openai_compatible_failure(
    *,
    endpoint_url: str,
    probe_url: str,
    model: str,
    api_key_configured: bool,
    detail: str,
) -> SmokeFailure:
    return SmokeFailure(
        "OpenAI-compatible readiness failed "
        f"(provider={AI_PROVIDER_OPENAI_COMPATIBLE}, endpoint={endpoint_url}, "
        f"probe={probe_url}, model={model}, "
        f"api_key_configured={str(api_key_configured).lower()}): {detail}"
    )


def _ollama_pull_command(model: str) -> str:
    return f"ollama pull {model}"


def _format_models(models: Sequence[str]) -> str:
    if not models:
        return "none"
    return ", ".join(models)


def _readiness_probe_url(api_url: str) -> str:
    stripped_url = api_url.strip().rstrip("/")
    parsed = urlparse(stripped_url)
    if parsed.scheme and parsed.netloc:
        return urlunparse(
            parsed._replace(path="", params="", query="", fragment="")
        ).rstrip("/")
    return stripped_url


def _env_string(env: Mapping[str, str], name: str) -> str:
    value = env.get(name)
    if value is None:
        return ""
    return value.strip()


def _env_float(env: Mapping[str, str], name: str, default: float) -> float:
    value = env.get(name)
    if value is None or not value.strip():
        return default
    return float(value)


def _type_name(value: object) -> str:
    return type(value).__name__


if __name__ == "__main__":
    raise SystemExit(main())
