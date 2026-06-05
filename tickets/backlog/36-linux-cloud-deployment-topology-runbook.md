description: Document Linux server and cloud VM deployment topology
prereq: compose-generated-ingest-checkpoint, faster-whisper-compose-profile
files: docs/ARCHITECTURE.md, docs/STATUS.md, docs/runbooks/local-linux-compose.md, ai-stream-director/.env.example
----
The project is local-first but should remain ready to run across a couple of
Linux hosts and later cloud GPU VMs. Once local generated-ingest and optional
local transcription profiles are stable, document the deployment topology so the
same service contracts can move between host-local, LAN, and cloud endpoints.

Expected behavior:

- Describe a two-Linux-host deployment split for ingest/buffer/orchestrator and
  optional AI/STT GPU services.
- Describe the cloud VM variant where AI or transcription endpoints move to GPU
  instances while media ingest stays local.
- Preserve environment-variable endpoint contracts such as `GEMMA_API_URL` and
  `TRANSCRIPTION_API_URL`.
- Identify firewall ports, bind-address defaults, RAM-backed storage
  expectations, GPU/runtime assumptions, and secrets handling.
- Keep this as documentation and configuration guidance; do not require cloud
  resources or live Docker validation in unit tests.
