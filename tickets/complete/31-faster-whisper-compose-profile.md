description: Completed optional local Faster-Whisper service profile
prereq: transcription-event-api, linux-compose-profiles
files: ai-stream-director/docker-compose.yml, ai-stream-director/.env.example, ai-stream-director/README.md, ai-stream-director/tests/test_linux_compose_stack.py, docs/ARCHITECTURE.md, docs/runbooks/local-linux-compose.md
----
Docker Compose now includes an opt-in local transcription server profile.

Built:

- Added a `faster-whisper` service behind the `local-transcription` profile.
- Kept the default local Linux runtime unchanged; `local-transcription` is not
  part of the default `COMPOSE_PROFILES` value.
- Defaulted the service to the CPU-safe
  `fedirz/faster-whisper-server:latest-cpu` image with env overrides for CUDA
  image, model, device, device index, compute type, CPU threads, worker count,
  TTL, preloaded models, host bind, port, logging, UI, and Hugging Face cache.
- Added a bounded container healthcheck and a cache volume.
- Preserved `TRANSCRIPTION_API_URL` as the app-facing endpoint contract.
- Documented the current ClutchCam JSON `/transcribe` adapter separately from
  the stock server's OpenAI-compatible `/v1/audio/transcriptions` upload API.
- Added Docker-free tests for the optional profile, endpoint examples, and docs.

Validation:

```powershell
cd ai-stream-director
& 'C:\Users\jacob\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -B -m unittest tests.test_linux_compose_stack -v
```

Result:

- Local Linux Compose suite: 8 tests passed.

Follow-up:

- The stock Faster-Whisper server profile is useful for direct operator
  validation today, but the runtime adapter still posts JSON audio references to
  `/transcribe`. A follow-up should add an OpenAI-compatible multipart
  transcription adapter mode before pointing `transcription-worker` directly at
  this stock service in production.
