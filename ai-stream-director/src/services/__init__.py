"""Production service boundary interfaces.

The modules in this package define importable contracts for future services.
They intentionally do not start media servers, subprocesses, network clients, or
OBS connections.
"""

__all__ = [
    "ai",
    "buffer",
    "ingestion",
    "switcher",
    "telemetry",
    "transcription",
]
