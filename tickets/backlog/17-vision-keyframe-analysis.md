description: Add visual hype confirmation from buffered keyframes
prereq: buffered-switcher-playback
files: docs/ARCHITECTURE.md, docs/ROADMAP.md, ai-stream-director/src/contracts.py
----
After transcript-triggered switching works, the system should support visual or
multimodal confirmation. The first pass should extract keyframes from the
rolling buffer and submit them to a multimodal model only for candidate moments.

Expected behavior:
- Extract keyframes around a candidate `HypeSignal`.
- Keep visual analysis asynchronous from the critical live switching path.
- Combine transcript and vision evidence without increasing false positives.
- Use fixtures for known visual moments before depending on live gameplay.
