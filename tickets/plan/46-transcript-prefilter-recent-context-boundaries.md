description: Make transcript detection consider recent fragments from the same stream so split phrases are not missed.
prereq: prefilter-live-eval-gaming-callouts
files: ai-stream-director/src/services/ai.py, ai-stream-director/src/transcript_router.py, ai-stream-director/src/main.py, ai-stream-director/tests/test_runtime_event_pipeline.py, ai-stream-director/tests/test_service_boundaries.py
----
The current transcript prefilter decides whether to escalate a transcript event
by looking only at the newest transcript text. That is fragile when speech
recognition or fixed audio chunks split a natural phrase across adjacent events,
such as `holy` in one event and `cow` in the next. In that case the AI director
never sees the broader transcript context because the local prefilter rejects
the newest event first.

The desired behavior is for the local prefilter to evaluate a bounded recent
same-stream context ending at the newest event, while preserving the existing
cheap local gate before model escalation.

Expected behavior:
- Adjacent same-stream transcript fragments can trigger when their joined text
  contains a configured hype phrase.
- Old transcript fragments outside the configured prefilter context window do
  not contribute to a new trigger.
- Transcript events from other streams do not get joined into the newest
  stream's candidate phrase.
- Duplicate suppression still prevents repeated escalation for the same phrase
  inside the duplicate window.
- `HypeSignal.trigger_time_seconds` remains anchored to the newest relevant
  transcript event so buffered clips continue to use the existing lookback
  strategy.
- Routine filler and short non-signal text remain rejected without calling the
  AI director.
