description: Completed OpenAI-compatible Gemma client support
prereq: gemma-orchestration-adapter
files: ai-stream-director/src/ai_director.py, ai-stream-director/src/config.py, ai-stream-director/src/main.py, ai-stream-director/.env.example, ai-stream-director/tests/test_ai_director.py, ai-stream-director/tests/test_dry_run_obs.py, docs/ARCHITECTURE.md
----
OpenAI-compatible Gemma/vLLM chat-completion endpoints are now supported behind
the existing AI director provider boundary.

Built:

- Added explicit `AI_PROVIDER` config with `ollama` default and aliases for
  `openai-compatible`, `openai`, and `vllm`.
- Added optional `GEMMA_API_KEY` support.
- Added `OpenAICompatibleDirectorProvider` behind the existing
  `DirectorProvider` protocol.
- Preserved the Ollama-native `/api/tags` and `/api/generate` provider path.
- Kept prompt construction, strict JSON decision parsing, scene validation, and
  `DirectorDecision` normalization owned by `AIDirector`.
- Added OpenAI-compatible chat-completion request payloads with model, messages,
  temperature, `stream=false`, and JSON-object response intent.
- Added endpoint handling for host-only URLs, `/v1` base URLs, and full
  configured chat-completions paths.
- Extracted the first assistant message content and passed it through the
  existing strict director parser.
- Wired `main.py` to pass provider/key values from parsed `AppConfig`.
- Documented provider examples in architecture docs and `.env.example`.

Validation:

```powershell
cd ai-stream-director
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest tests.test_ai_director tests.test_dry_run_obs -v
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest tests.test_ai_director tests.test_dry_run_obs tests.test_linux_compose_stack tests.test_ingestion_config -v
```

Result:

- Focused AI/dry-run suite: 45 tests passed before review polish.
- Post-review AI/dry-run/Compose/ingestion suite: 58 tests passed.
