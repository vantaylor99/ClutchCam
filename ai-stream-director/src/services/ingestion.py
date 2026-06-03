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

    base_url = ingest_base_url.rstrip("/")
    sources: list[StreamSource] = []
    for stream_id in stream_ids:
        scene_name = scenes.get(stream_id)
        if scene_name is None:
            raise StreamSourceError(f"No scene configured for stream ID {stream_id}.")

        sources.append(
            StreamSource(
                stream_id=stream_id,
                display_name=_display_name(stream_id),
                ingest_url=f"{base_url}/{stream_id}",
                scene_name=scene_name,
            )
        )

    return tuple(sources)


def _display_name(stream_id: str) -> str:
    return stream_id.replace("_", " ").title()
