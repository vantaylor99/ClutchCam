description: Add a real-time transcription adapter that emits TranscriptEvent objects
prereq: transcription-audio-extraction
files: docs/ARCHITECTURE.md, ai-stream-director/src/contracts.py, ai-stream-director/src/transcript_router.py
----
The transcription adapter extracts or receives audio for each stream and sends
it to a Faster-Whisper-compatible service over `TRANSCRIPTION_API_URL`. Its
output must be normalized into `TranscriptEvent` objects with stream ID, text,
start timestamp, end timestamp, and final/partial status.

The adapter must not depend on the physical container location of Faster-Whisper.
Local Docker and remote GPU-hosted inference should both be selected through the
API URL.

Expected behavior:
- Preserve stream identity across audio extraction, transcription, and routing.
- Emit timestamped final transcript events suitable for lookback trigger
  alignment.
- Keep partial transcript support possible without forcing the MVP terminal path
  to change immediately.
- Surface transcription service failures as recoverable orchestration errors.
