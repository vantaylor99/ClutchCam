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

TODO:

- Enhance `scripts/smoke_ai_endpoint.py` result/error detail without changing
  provider contracts used by app logic.
- Add or update tests for successful Ollama, missing model, unexpected model
  list, OpenAI-compatible reachability, and auth-header behavior.
- Update `.env.example` and runbooks with checkpoint-oriented guidance for
  Gemma 4/Ollama model selection.
- Keep visual analysis clearly optional and later.
- Run:
  `python -B -m unittest tests.test_smoke_entrypoints tests.test_ingestion_config -v`.
