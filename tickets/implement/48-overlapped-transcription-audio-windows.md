description: Add an opt-in transcription overlap mode so words at audio chunk boundaries keep enough context without sending duplicate transcript events downstream.
prereq: per-stream-transcript-utterance-assembler
files: ai-stream-director/src/config.py, ai-stream-director/src/services/transcription.py, ai-stream-director/src/services/transcription_runtime.py, ai-stream-director/src/transcription_worker.py, ai-stream-director/docker-compose.yml, ai-stream-director/README.md, docs/ARCHITECTURE.md, ai-stream-director/tests/test_transcription_audio_extraction.py, ai-stream-director/tests/test_transcription_worker_entrypoint.py, ai-stream-director/tests/test_transcription_runtime.py, ai-stream-director/tests/test_transcription_event_api.py, ai-stream-director/tests/test_linux_compose_stack.py
difficulty: medium
----
Live transcription currently sends each extracted audio chunk to the speech-to-text backend independently. That keeps latency low, but speech that crosses a chunk boundary can lose context. Add an opt-in request-window layer that includes a short tail from the previous chunk while preserving monotonic `TranscriptEvent` output on the stream media timeline.

Keep FFmpeg extraction as-is. `FFmpegAudioExtractor.build_ffmpeg_command(...)` should continue to segment at `AUDIO_EXTRACT_CHUNK_SECONDS` and write stable numbered chunk files. The overlap feature belongs after chunk discovery and before transcription requests.

## Implementation shape

Add `TRANSCRIPTION_REQUEST_OVERLAP_SECONDS`, exposed as `AppConfig.transcription_request_overlap_seconds`, defaulting to `0`. Validate it at config load time:

- It must be non-negative.
- It must be strictly less than `AUDIO_EXTRACT_CHUNK_SECONDS`.
- If it is greater than `0`, `AUDIO_EXTRACT_CONTAINER` must be `wav`, because the first implementation composes local WAV windows with the Python standard library.

Extend `AudioInputRef` with a media-timeline threshold such as `emit_from_seconds: float | None = None`. This is not an audio offset. It means "events ending at or before this media timestamp came entirely from overlap context and must not be emitted." For non-overlapped refs the field stays `None`.

Add a small request-window builder in `services.transcription` that can build a local WAV file for the current request:

- Inputs: current `AudioInputRef`, current chunk path, previous chunk path if available, overlap seconds, and `AudioExtractionConfig`.
- If overlap is disabled, or the current chunk is the first chunk for that stream, return the original ref unchanged.
- If the previous chunk is missing, deleted, unreadable, not a WAV file, or incompatible with the current WAV parameters, log a warning and return the original current chunk ref unchanged.
- For the happy path, write `<AUDIO_EXTRACT_DIR>/_overlap/<stream_id>/<current_chunk_stem>.wav` containing the last `overlap_seconds` of the previous chunk followed by the full current chunk.
- The resulting `AudioInputRef.starts_at_seconds` must be `current_start - actual_overlap_duration`, clamped by the actual frames copied from the previous file.
- The resulting `AudioInputRef.duration_seconds` must be `actual_overlap_duration + current_duration`.
- The resulting `AudioInputRef.emit_from_seconds` must be the original current chunk start timestamp.
- Use `wave` from the standard library and copy frames; do not add a new audio dependency.
- Keep cleanup deterministic: overlap files from earlier discovery passes that are no longer referenced by the current pass should be deleted on a later discovery pass, but never delete a composed file before the pump has had a chance to transcribe the refs returned in that same pass.

Wire this after `CompletedAudioChunkDiscovery`, for example with an `OverlappedAudioWindowDiscovery` decorator. The existing discovery class should still own stable-file detection and one-time processing. The overlap decorator can infer the previous chunk path from the current chunk filename when stems are numeric, or track the last original chunk path per stream. If it cannot identify a previous chunk, it must fall back to the original current chunk ref.

Update `build_worker(...)` so overlap is enabled only when `app_config.transcription_request_overlap_seconds > 0`. Disabled mode must keep the existing `AudioInputRef` path and behavior unchanged.

## Runtime event filtering

Teach `TranscriptionRuntimePump` to honor `AudioInputRef.emit_from_seconds`:

- If the field is `None`, emit events exactly as today.
- If it is set, drop events whose `end_time_seconds <= emit_from_seconds`.
- Preserve events that start in the overlap and end in the new chunk, because those are the boundary phrases this feature is meant to recover.
- Filtering is per audio ref and per stream; do not use one stream's threshold to filter another stream.
- Dropped overlap-only events should count as rejected events, not failures. They should not call the sink.

Keep transcript timestamps on the media timeline. Do not shift events after transcription; the transcriber should continue to produce media-timeline `TranscriptEvent` objects using `AudioInputRef.starts_at_seconds`.

## Text-only response policy

Reject timestampless transcription responses when overlap is enabled for a request. The current transcriber maps text-only responses without segment timestamps to the full `AudioInputRef.duration_seconds`, which would duplicate the previous chunk tail in overlapped mode. If `audio.emit_from_seconds is not None` and a segment has no explicit `start`/`end` or `start_seconds`/`end_seconds`, raise `TranscriptionError` with a clear message explaining that overlap requires timestamped transcription segments.

Non-overlapped text-only responses must keep working as they do today.

## Edge cases & interactions

- First chunk for each stream has no overlap and should be sent unchanged.
- Missing or unreadable previous chunks must not stop the worker; fall back to the current chunk and continue.
- Overlap equal to or greater than the chunk stride must fail config validation before worker startup.
- Catch-up discovery may return multiple chunks in one poll. Any cleanup strategy must keep every composed file referenced by that returned batch available until the pump processes it.
- Duplicate filtering must not drop a phrase that begins in the overlap and ends after `emit_from_seconds`.
- OpenAI-compatible mode uploads local files, so composed windows must use local file URIs and be readable by `FasterWhisperTranscriber`.
- Fixture and unit tests must not require an installed FFmpeg binary.
- Existing chunk filenames, health checks, failure payload shape, and media timeline inference should remain understandable.

## Tests to add or update

- Config tests cover the default overlap value, a valid non-zero value, negative overlap rejection, overlap equal to chunk duration rejection, and non-WAV container rejection when overlap is enabled.
- Worker construction tests confirm disabled overlap uses plain `CompletedAudioChunkDiscovery`, while enabled overlap wraps the base discovery and passes the configured overlap.
- Discovery/window tests create tiny WAV fixtures and verify an overlapped request starts at `current_start - overlap`, has duration `overlap + chunk_duration`, uses a local `_overlap` URI, and sets `emit_from_seconds` to the current chunk start.
- Discovery/window tests cover first chunk fallback and missing/unreadable previous chunk fallback.
- Runtime pump tests verify overlap-only events are rejected without calling the sink, boundary-spanning events are emitted, and filtering does not cross streams.
- Transcriber tests verify timestampless text responses still work without overlap but raise `TranscriptionError` when `emit_from_seconds` is set.
- Documentation and compose tests cover the new environment variable where the project already asserts documented transcription settings.

## Validation

Run focused tests first:

```powershell
cd ai-stream-director
python -m unittest tests.test_transcription_audio_extraction tests.test_transcription_worker_entrypoint tests.test_transcription_runtime tests.test_transcription_event_api tests.test_linux_compose_stack -v
```

If those pass quickly, run the full Python test suite:

```powershell
cd ai-stream-director
python -m unittest discover -s tests -v
```

## TODO

- Add `TRANSCRIPTION_REQUEST_OVERLAP_SECONDS` to config, Compose, README, and architecture docs with validation and tests.
- Extend `AudioInputRef` with the overlap emission threshold and keep existing non-overlap behavior unchanged.
- Implement the WAV request-window builder and overlap discovery wrapper with deterministic delayed cleanup.
- Wire the wrapper into `build_worker(...)` only when overlap is enabled.
- Add runtime pump filtering for overlap-only events and count those drops as rejected events.
- Reject timestampless transcription responses for overlapped requests while preserving current text-only behavior for non-overlapped requests.
- Add the focused unit tests listed above and run the focused validation command.
