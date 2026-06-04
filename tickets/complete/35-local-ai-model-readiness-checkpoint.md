description: Completed local AI model readiness checkpoint diagnostics
prereq: local-ai-dev-quickstart, openai-compatible-gemma-client
files: ai-stream-director/scripts/smoke_ai_endpoint.py, ai-stream-director/tests/test_smoke_entrypoints.py, ai-stream-director/.env.example, ai-stream-director/README.md, docs/runbooks/terminal-dry-run.md
----
The AI endpoint smoke now gives operators clearer diagnostics before media
testing starts.

Built:

- `scripts/smoke_ai_endpoint.py` now reports provider, configured endpoint URL,
  readiness probe URL, model, timeout, and compatibility fields.
- Ollama readiness parses `/api/tags`, reports detected models/count on success,
  and explains malformed model-list responses.
- Missing Ollama model failures include the configured endpoint, probe, model,
  detected models, and exact `ollama pull <model>` recovery command.
- OpenAI-compatible readiness stays provider-neutral, sends bearer auth only
  when `GEMMA_API_KEY` is configured, and reports whether an API key was present.
- `.env.example`, `ai-stream-director/README.md`, and the terminal dry-run
  runbook now describe the readiness output and keep future multimodal model
  selection separate from the current transcript-only checkpoint.

Validation:

```powershell
cd ai-stream-director
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest tests.test_smoke_entrypoints tests.test_ingestion_config -v
```

Result:

- Focused AI smoke/ingestion suite: 25 tests passed.

The final full repo validation also passed:

```powershell
cd ai-stream-director
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest discover -s tests -v
```

Result:

- Full Python suite: 184 tests passed.
