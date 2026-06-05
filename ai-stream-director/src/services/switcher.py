"""Output switching boundary."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from enum import Enum
from typing import Protocol

from config import SCENES, STREAM_IDS
from contracts import HypeSignal, LookbackClipRequest, SwitcherTarget
from services.buffer import ClipResolutionStatus, LookbackBuffer, LookbackBufferError


DEFAULT_POST_ROLL_SECONDS = 5
DEFAULT_STREAM_SCENE_MAP = {stream_id: SCENES[stream_id] for stream_id in STREAM_IDS}


class SwitchStatus(str, Enum):
    APPLIED = "applied"
    PENDING = "pending"
    REJECTED = "rejected"


class OutputSwitchError(RuntimeError):
    """Raised when an output switch adapter cannot apply a target."""


@dataclass(frozen=True)
class SwitchResult:
    """Implementation-neutral result of an output switch request."""

    target: SwitcherTarget
    status: SwitchStatus
    switched_at_seconds: float | None = None
    reason: str = ""
    segment_uris: tuple[str, ...] = ()


class OutputSwitcher(Protocol):
    """Applies immediate or buffered output targets behind one boundary."""

    def switch(self, target: SwitcherTarget) -> SwitchResult:
        """Apply the requested output target and return its result."""


def build_buffered_target(
    *,
    stream_id: str,
    scene_name: str,
    trigger_time_seconds: float,
    pre_roll_seconds: int,
    post_roll_seconds: int = DEFAULT_POST_ROLL_SECONDS,
) -> SwitcherTarget:
    """Build a target that requests buffered media around a trigger."""

    if not stream_id:
        raise OutputSwitchError("Buffered switch target requires a stream ID.")
    if not scene_name:
        raise OutputSwitchError("Buffered switch target requires a scene name.")

    return SwitcherTarget(
        stream_id=stream_id,
        scene_name=scene_name,
        clip_request=LookbackClipRequest(
            stream_id=stream_id,
            trigger_time_seconds=trigger_time_seconds,
            pre_roll_seconds=int(pre_roll_seconds),
            post_roll_seconds=int(post_roll_seconds),
        ),
    )


def buffered_target_from_signal(
    signal: HypeSignal,
    *,
    scene_name: str | None = None,
    scene_map: Mapping[str, str] = DEFAULT_STREAM_SCENE_MAP,
    pre_roll_seconds: int,
    post_roll_seconds: int = DEFAULT_POST_ROLL_SECONDS,
) -> SwitcherTarget:
    """Convert a stream-focused signal into a buffered switch target."""

    resolved_scene_name = scene_name or scene_map.get(signal.stream_id)
    if not resolved_scene_name:
        raise OutputSwitchError(f"No scene is configured for {signal.stream_id}.")

    return build_buffered_target(
        stream_id=signal.stream_id,
        scene_name=resolved_scene_name,
        trigger_time_seconds=signal.trigger_time_seconds,
        pre_roll_seconds=pre_roll_seconds,
        post_roll_seconds=post_roll_seconds,
    )


class SceneOutputSwitcher:
    """Generic scene switcher for OBS/PyVMIX-like scene controllers."""

    def __init__(
        self,
        scene_controller,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.scene_controller = scene_controller
        self.clock = clock

    def switch(self, target: SwitcherTarget) -> SwitchResult:
        try:
            self.scene_controller.set_scene(target.scene_name)
        except Exception as exc:
            raise OutputSwitchError(
                f"Scene switch failed for {target.scene_name}: {exc}"
            ) from exc

        return SwitchResult(
            target=target,
            status=SwitchStatus.APPLIED,
            switched_at_seconds=self.clock(),
            reason=f"Scene switched to {target.scene_name}.",
        )


class MediaSourceOutputSwitcher:
    """Update a media source with a ready target before switching scenes."""

    def __init__(
        self,
        scene_controller,
        *,
        media_source_name: str,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not media_source_name:
            raise OutputSwitchError("Media source switcher requires a source name.")
        self.scene_controller = scene_controller
        self.media_source_name = media_source_name
        self.clock = clock

    def switch(self, target: SwitcherTarget) -> SwitchResult:
        if not target.media_uri:
            return SwitchResult(
                target=target,
                status=SwitchStatus.REJECTED,
                reason="Media-source switch target requires a media URI.",
            )

        try:
            self.scene_controller.set_media_source(
                self.media_source_name,
                target.media_uri,
            )
            self.scene_controller.set_scene(target.scene_name)
        except Exception as exc:
            raise OutputSwitchError(
                "Media-source switch failed for "
                f"{target.scene_name} via {self.media_source_name}: {exc}"
            ) from exc

        return SwitchResult(
            target=target,
            status=SwitchStatus.APPLIED,
            switched_at_seconds=self.clock(),
            reason=(
                f"Media source {self.media_source_name} set and scene switched "
                f"to {target.scene_name}."
            ),
        )


class BufferBackedSwitcher:
    """Resolve buffered clips before applying an output switch target."""

    def __init__(
        self,
        buffer: LookbackBuffer,
        *,
        downstream: OutputSwitcher | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.buffer = buffer
        self.downstream = downstream
        self.clock = clock

    def switch(self, target: SwitcherTarget) -> SwitchResult:
        request = target.clip_request
        if request is None:
            return SwitchResult(
                target=target,
                status=SwitchStatus.REJECTED,
                reason="Buffered switch target requires a clip request.",
            )

        try:
            resolution = self.buffer.resolve_clip(request)
        except LookbackBufferError as exc:
            return SwitchResult(
                target=target,
                status=SwitchStatus.REJECTED,
                reason=str(exc),
            )

        if resolution.status == ClipResolutionStatus.PENDING:
            return SwitchResult(
                target=target,
                status=SwitchStatus.PENDING,
                reason=resolution.reason or "Buffered clip is not ready yet.",
            )

        if resolution.status != ClipResolutionStatus.READY:
            return SwitchResult(
                target=target,
                status=SwitchStatus.REJECTED,
                reason=resolution.reason or "Buffered clip is unavailable.",
            )

        if not resolution.media_uri:
            return SwitchResult(
                target=target,
                status=SwitchStatus.REJECTED,
                reason="Ready buffered clip did not include a media URI.",
            )

        ready_target = replace(target, media_uri=resolution.media_uri)
        if self.downstream is not None:
            return self._switch_downstream(ready_target, resolution.segment_uris)

        return SwitchResult(
            target=ready_target,
            status=SwitchStatus.APPLIED,
            switched_at_seconds=self.clock(),
            reason=resolution.reason or "Buffered clip resolved.",
            segment_uris=resolution.segment_uris,
        )

    def _switch_downstream(
        self,
        ready_target: SwitcherTarget,
        segment_uris: tuple[str, ...],
    ) -> SwitchResult:
        try:
            result = self.downstream.switch(ready_target)
        except OutputSwitchError as exc:
            return SwitchResult(
                target=ready_target,
                status=SwitchStatus.REJECTED,
                reason=str(exc),
                segment_uris=segment_uris,
            )

        return replace(
            result,
            target=ready_target,
            segment_uris=segment_uris,
        )
