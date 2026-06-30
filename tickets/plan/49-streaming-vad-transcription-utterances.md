description: Design a transcription path that can finish speech around natural pauses instead of arbitrary audio chunk boundaries.
prereq: runtime-transcription-event-source
files: ai-stream-director/src/services/transcription.py, ai-stream-director/src/services/transcription_runtime.py, ai-stream-director/src/transcription_worker.py, ai-stream-director/src/contracts.py, ai-stream-director/src/transcript_router.py, ai-stream-director/src/main.py, docs/ARCHITECTURE.md, docs/ROADMAP.md
difficulty: hard
----
The current live transcription path extracts fixed-duration audio chunks with FFmpeg, optionally prepends a previous WAV tail for overlap, sends each request to a Faster-Whisper-compatible HTTP adapter, and normalizes the response into `TranscriptEvent` values. The orchestrator only consumes final transcript events; partial events are accepted by the contract but ignored by the live queue and runtime event handler. `TranscriptRouter` then builds bounded same-stream utterance candidates from final events so trigger checks are less sensitive to chunk breaks.

This planning pass should design the next transcription boundary: a streaming or voice-activity-detection-aware path that finalizes speech around pauses or provider finalization signals while preserving the existing fail-soft fixed-chunk mode.

The design should keep provider details behind the transcription service boundary. The orchestrator should continue to receive normalized `TranscriptEvent` values and should not need to know whether an event came from fixed chunks, overlapped chunks, local voice activity detection, or a provider streaming API.

Expected behavior:

- Final speech events represent utterance-level spans when the source can provide them, using speech pauses, provider finalization signals, or both.
- Partial transcript events may be emitted for diagnostics or a future user interface, but switching decisions continue to use final events unless a later ticket explicitly changes that behavior.
- Media timestamps remain reliable. Word-level or segment-level timestamps should be preserved or mapped into `TranscriptEvent` start and end times when the provider exposes them.
- Existing fixed-chunk transcription remains the default or fallback path when streaming or voice activity detection is unavailable, misconfigured, slow, or unsupported by the selected provider.
- The design should make clear whether voice activity detection runs before provider requests, inside a provider stream, or as a post-processing/finalization layer over provider segments.
- The standalone JSONL worker path and the in-process live transcription source should either share the new boundary or have an explicit reason not to.
- Live validation should compare missed trigger phrases, duplicate triggers, trigger latency, CPU/GPU use, request volume, and backend cost against the current fixed-chunk plus optional-overlap path.

Important existing constraints:

- `Transcriber.transcribe(AudioInputRef)` is request/response-shaped today, so a streaming source may need a separate protocol or runtime source boundary rather than forcing streaming into one audio-ref call.
- `TranscriptionRuntimePump` is a one-shot pump over discovered `AudioInputRef` values and currently handles failures per audio reference.
- `CompletedAudioChunkDiscovery` owns stable chunk discovery and `_infer_chunk_start_seconds(...)` maps numeric segment filenames to media timestamps.
- `OverlappedAudioWindowDiscovery` and `AudioInputRef.emit_from_seconds` already provide a deduplication mechanism for overlapped WAV requests, but that mechanism assumes local files and timestamped response segments.
- `LiveTranscriptQueueSink` and `process_transcript_event(...)` intentionally reject partial events from switching decisions today.
- `TranscriptRouter` assembles final events into candidate utterances for trigger detection, so the plan should say whether provider-level utterance finalization replaces, complements, or feeds that router assembly.

Edge cases and interactions to resolve during planning:

- Speech that starts before a reconnect, extraction restart, or provider stream reset and ends after it.
- Silence-only spans, background game audio, crosstalk, and false voice activity starts.
- Long monologues that exceed existing utterance duration, event count, or character limits.
- Providers that emit only text, only segment timestamps, word timestamps, unstable partial text revisions, or final events without a clear utterance end.
- Duplicate text across provider reconnects, overlap windows, or voice activity detection padding.
- Backpressure when a streaming provider emits partials faster than the orchestrator queue can drain.
- Shutdown and cleanup for long-lived provider streams, FFmpeg subprocesses, local voice activity detection state, and diagnostic worker output.
- Cost and latency tradeoffs between continuous streaming, local voice activity detection-gated requests, and the current chunked request mode.
- Configuration and healthcheck behavior when streaming is enabled but the selected provider or local runtime cannot support it.

The output of this planning ticket should be one or more implementation tickets that are small enough for one agent run each, with clear tests and validation expectations.
