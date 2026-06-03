description: Add local transcript trigger prefiltering before model escalation
prereq: transcription-event-api
files: docs/ARCHITECTURE.md, docs/ROADMAP.md, ai-stream-director/src/contracts.py, ai-stream-director/src/ai_director.py
----
Not every transcript event should call Gemma. A local prefilter should identify
obvious low-signal speech, candidate hype phrases, repeated noise, and cooldown
conditions before invoking the heavier AI layer.

Expected behavior:
- Score recent transcript events by stream and time window.
- Emit candidate `HypeSignal` values for likely trigger moments.
- Suppress low-signal or repeated phrases that would cause noisy switching.
- Keep thresholds configurable and testable with transcript fixtures.
