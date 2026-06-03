"""Output switching boundary."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from contracts import SwitcherTarget


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


class OutputSwitcher(Protocol):
    """Applies immediate or buffered output targets behind one boundary."""

    def switch(self, target: SwitcherTarget) -> SwitchResult:
        """Apply the requested output target and return its result."""
