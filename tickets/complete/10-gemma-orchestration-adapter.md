description: Completed provider boundary for Gemma orchestration
prereq: transcript-trigger-prefilter
files: ai-stream-director/src/ai_director.py, ai-stream-director/tests/test_ai_director.py, docs/ARCHITECTURE.md
----
The AI director now has a small provider/client boundary while preserving the
stable `AIDirector.check_readiness()` and `AIDirector.decide(...)` runtime
interface.

Built:

- Added a `DirectorProvider` protocol and default `OllamaDirectorProvider`.
- Moved Ollama-native `/api/tags` readiness checks behind the provider.
- Moved Ollama-native `/api/generate` request payload and response-field
  extraction behind the provider.
- Kept prompt construction, strict JSON decision parsing, scene validation, and
  `DirectorDecision` normalization in `AIDirector`.
- Preserved the existing constructor shape used by `main.py`, including
  `ollama_base_url`, `model`, and `timeout_seconds`; provider injection is
  optional.
- Preserved candidate-signal prompt context.
- Updated architecture docs to note that the MVP now has a provider adapter and
  still defaults to Ollama-native endpoints.

Validation:

```powershell
cd ai-stream-director
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest tests.test_ai_director tests.test_dry_run_obs -v
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest tests.test_ai_director tests.test_dry_run_obs tests.test_buffer_worker_entrypoint tests.test_rolling_buffer tests.test_transcription_worker_entrypoint tests.test_transcription_runtime tests.test_transcription_event_api tests.test_telemetry tests.test_service_boundaries -v
```

Result:

- Focused AI/dry-run suite: 35 tests passed.
- Combined review suite: 93 tests passed.
