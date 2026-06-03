description: Add OpenAI-compatible Gemma or vLLM client support
prereq: gemma-orchestration-adapter
files: docs/ARCHITECTURE.md, docs/ROADMAP.md, ai-stream-director/src/ai_director.py, ai-stream-director/src/config.py, ai-stream-director/tests/test_ai_director.py
----
The MVP currently calls Ollama's native `/api/generate` and `/api/tags`
endpoints. Production should also support OpenAI-compatible chat completion
servers such as vLLM without changing scheduler or transcript routing code.

Expected behavior:
- Select provider behavior through configuration.
- Support OpenAI-compatible chat completions for Gemma.
- Preserve strict JSON decision validation.
- Keep Ollama compatibility tests passing.
- Document provider configuration examples for local and remote inference.
