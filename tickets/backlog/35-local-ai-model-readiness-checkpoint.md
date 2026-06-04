description: Tighten local Gemma/Ollama readiness for checkpoint testing
prereq: local-ai-dev-quickstart, openai-compatible-gemma-client
files: ai-stream-director/scripts/smoke_ai_endpoint.py, ai-stream-director/.env.example, ai-stream-director/README.md, docs/runbooks/terminal-dry-run.md, docs/runbooks/local-linux-compose.md
----
The AI smoke script verifies endpoint reachability and model presence, but the
next checkpoint should make local Gemma/Ollama setup easier to diagnose before
operators start media tests.

Expected behavior:
- Report the configured provider, endpoint, model, and detected installed models
  in a concise operator-friendly shape.
- Make missing-model guidance explicit for Ollama, including the exact pull
  command.
- Keep OpenAI-compatible endpoint checks provider-neutral and API-key aware.
- Document how to use Gemma 4 text/image-capable tags later without making
  vision analysis part of the near-term checkpoint.
