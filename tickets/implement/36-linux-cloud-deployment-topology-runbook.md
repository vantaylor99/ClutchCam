description: Document Linux server and cloud VM deployment topology
prereq: compose-generated-ingest-checkpoint, faster-whisper-compose-profile
files: docs/ARCHITECTURE.md, docs/STATUS.md, docs/runbooks/local-linux-compose.md, ai-stream-director/.env.example
----
The project is local-first but should remain ready to run across a couple of
Linux hosts and later cloud GPU VMs. Now that local generated-ingest and
optional local transcription profiles exist, document the deployment topology so
the same service contracts can move between host-local, LAN, and cloud
endpoints.

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

TODO:

- Add a runbook section or standalone runbook for host-local, two-Linux-host,
  and cloud-GPU endpoint topologies.
- Update architecture/status docs to name which services are local-only and
  which may move behind HTTP endpoint contracts.
- Add or update endpoint examples in `.env.example` only if needed.
- Keep the guidance concrete about bind addresses, firewalls, RAM-backed
  storage, GPU assumptions, and secret placement.
