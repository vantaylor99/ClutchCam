"""Ingestion boundary for discovering configured stream sources."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from config import SCENES, STREAM_IDS
from contracts import StreamSource


class StreamSourceError(RuntimeError):
    """Raised when configured stream source records cannot be described."""


class StreamSourceProvider(Protocol):
    """Provides stable stream records without owning media-server lifecycle."""

    def list_sources(self) -> Sequence[StreamSource]:
        """Return currently known stream sources."""

    def get_source(self, stream_id: str) -> StreamSource | None:
        """Return one stream source by stable stream ID, if known."""


@dataclass(frozen=True)
class StaticStreamSourceProvider:
    """In-memory source provider for configured or fixture stream records."""

    sources: Sequence[StreamSource]

    def list_sources(self) -> tuple[StreamSource, ...]:
        return tuple(self.sources)

    def get_source(self, stream_id: str) -> StreamSource | None:
        for source in self.sources:
            if source.stream_id == stream_id:
                return source
        return None


def build_configured_sources(
    ingest_base_url: str,
    stream_ids: Sequence[str] = STREAM_IDS,
    scenes: Mapping[str, str] = SCENES,
) -> tuple[StreamSource, ...]:
    """Build configured source records from environment-derived settings."""

    sources: list[StreamSource] = []
    for stream_id in stream_ids:
        scene_name = scenes.get(stream_id)
        if scene_name is None:
            raise StreamSourceError(f"No scene configured for stream ID {stream_id}.")

        sources.append(
            StreamSource(
                stream_id=stream_id,
                display_name=_display_name(stream_id),
                ingest_url=build_rtmp_stream_url(ingest_base_url, stream_id),
                scene_name=scene_name,
            )
        )

    return tuple(sources)


def build_rtmp_stream_url(base_url: str, stream_id: str) -> str:
    """Build an RTMP URL under the configured ingest app."""

    return f"{base_url.rstrip('/')}/{stream_id}"


def build_srt_publish_url(
    host: str,
    port: int | str,
    stream_id: str,
    app: str = "live",
) -> str:
    """Build an SRT publish URL using SRS streamid mode syntax."""

    return _build_srt_stream_url(host, port, app, stream_id, mode="publish")


def build_srt_request_url(
    host: str,
    port: int | str,
    stream_id: str,
    app: str = "live",
) -> str:
    """Build an SRT request/play URL using SRS streamid mode syntax."""

    return _build_srt_stream_url(host, port, app, stream_id, mode="request")


def _display_name(stream_id: str) -> str:
    return stream_id.replace("_", " ").title()


def _build_srt_stream_url(
    host: str,
    port: int | str,
    app: str,
    stream_id: str,
    mode: str,
) -> str:
    if mode not in {"publish", "request"}:
        raise StreamSourceError(f"Unsupported SRT stream mode {mode}.")

    streamid = f"#!::r={app}/{stream_id},m={mode}"
    return f"srt://{_format_srt_host(host)}:{port}?streamid={streamid}"


def _format_srt_host(host: str) -> str:
    if ":" in host and not (host.startswith("[") and host.endswith("]")):
        return f"[{host}]"
    return host
