"""Rolling lookback buffer boundary."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from contracts import LookbackClipRequest


class ClipResolutionStatus(str, Enum):
    READY = "ready"
    PENDING = "pending"
    UNAVAILABLE = "unavailable"


class LookbackBufferError(RuntimeError):
    """Raised when a buffer adapter cannot resolve a clip request."""


@dataclass(frozen=True)
class ClipResolution:
    """Implementation-neutral result for a lookback clip lookup."""

    request: LookbackClipRequest
    status: ClipResolutionStatus
    media_uri: str | None = None
    start_time_seconds: float | None = None
    end_time_seconds: float | None = None
    reason: str = ""

    @classmethod
    def ready(
        cls,
        request: LookbackClipRequest,
        media_uri: str,
        start_time_seconds: float | None = None,
        end_time_seconds: float | None = None,
        reason: str = "",
    ) -> "ClipResolution":
        return cls(
            request=request,
            status=ClipResolutionStatus.READY,
            media_uri=media_uri,
            start_time_seconds=(
                request.start_time_seconds
                if start_time_seconds is None
                else start_time_seconds
            ),
            end_time_seconds=(
                request.end_time_seconds if end_time_seconds is None else end_time_seconds
            ),
            reason=reason,
        )

    @classmethod
    def pending(
        cls,
        request: LookbackClipRequest,
        reason: str = "",
    ) -> "ClipResolution":
        return cls(
            request=request,
            status=ClipResolutionStatus.PENDING,
            reason=reason,
        )

    @classmethod
    def unavailable(
        cls,
        request: LookbackClipRequest,
        reason: str = "",
    ) -> "ClipResolution":
        return cls(
            request=request,
            status=ClipResolutionStatus.UNAVAILABLE,
            reason=reason,
        )


class LookbackBuffer(Protocol):
    """Resolves lookback media requests without prescribing FFmpeg details."""

    def resolve_clip(self, request: LookbackClipRequest) -> ClipResolution:
        """Return ready, pending, or unavailable media for the requested range."""
