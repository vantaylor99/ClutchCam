description: Optional Gemma 4 visual confirmation from buffered keyframes
prereq: runtime-event-pipeline-wiring, obs-buffered-media-source-adapter
files: docs/ARCHITECTURE.md, docs/ROADMAP.md, ai-stream-director/src/contracts.py
----
Gemma 4 can support image-based visual confirmation, but this is intentionally
not part of the next testing checkpoint. Keep it parked until transcript-driven
lookback switching and OBS buffered playback are stable.

Expected behavior when this eventually becomes active:
- Extract a small number of keyframes around a candidate `HypeSignal`.
- Send keyframes to a Gemma 4 multimodal endpoint only after transcript/local
  rules produce a candidate moment.
- Keep visual analysis asynchronous from the critical live switching path.
- Use the vision result as confirmation or confidence adjustment, not as the
  only switching trigger in the first pass.
- Use fixtures for known visual moments before depending on live gameplay.
