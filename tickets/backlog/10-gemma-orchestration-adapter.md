description: Generalize AI orchestration for Gemma REST endpoints
prereq: transcript-trigger-prefilter
files: docs/ARCHITECTURE.md, ai-stream-director/src/ai_director.py, ai-stream-director/src/config.py
----
The AI director should evolve from an Ollama-native MVP client into a provider
adapter that can target local Ollama, local vLLM, or cloud-hosted Gemma through
environment-configured REST endpoints.

`GEMMA_API_URL` and `GEMMA_MODEL` are the preferred configuration names.
`OLLAMA_BASE_URL` and `OLLAMA_MODEL` remain compatibility aliases while the MVP
still uses Ollama's native `/api/generate` shape.

Expected behavior:
- Support a provider boundary that can add OpenAI-compatible chat completion
  calls without changing scheduler or switcher code.
- Keep strict JSON decision parsing and validation.
- Continue accepting the current MVP prompt and scene names.
- Return decisions that can later be mapped to `HypeSignal` and
  `LookbackClipRequest`.
