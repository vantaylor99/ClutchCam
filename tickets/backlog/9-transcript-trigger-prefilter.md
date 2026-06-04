description: Add local transcript trigger prefiltering before model escalation
prereq: transcription-event-api
files: docs/ARCHITECTURE.md, docs/ROADMAP.md, ai-stream-director/src/contracts.py, ai-stream-director/src/ai_director.py
----
Not every transcript event should call Gemma. A local prefilter should identify
obvious low-signal speech, candidate hype phrases, repeated noise, and cooldown
conditions before invoking the heavier AI layer.

The local Gemma dry-run smoke test showed one important edge case: after recent
multi-player transcript history builds up, the model can select a different
player than the newest accepted line. The prefilter should preserve the
candidate stream and trigger time so model escalation is grounded in the event
that caused the escalation rather than the whole rolling context alone.

Expected behavior:
- Score recent transcript events by stream and time window.
- Emit candidate `HypeSignal` values for likely trigger moments.
- Preserve the stream and timestamp of the candidate event that triggered model
  escalation.
- Suppress low-signal or repeated phrases that would cause noisy switching.
- Avoid model calls entirely when AI is disabled or scheduler cooldown makes a
  switch impossible.
- Keep thresholds configurable and testable with transcript fixtures.
