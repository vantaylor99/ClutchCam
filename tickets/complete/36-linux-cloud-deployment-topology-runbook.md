description: Completed Linux server and cloud VM deployment topology docs
prereq: compose-generated-ingest-checkpoint, faster-whisper-compose-profile
files: docs/runbooks/linux-cloud-deployment-topology.md, docs/runbooks/README.md, docs/ARCHITECTURE.md, docs/STATUS.md
----
Added a docs-only deployment topology runbook for ClutchCam's local-first Linux
path and future remote endpoint options.

What changed:

- Added `docs/runbooks/linux-cloud-deployment-topology.md`.
- Documented one-host, two-Linux-host, and future cloud GPU/VM endpoint
  topologies.
- Clarified which services should stay near the event network and which may
  move behind HTTP endpoint contracts.
- Covered bind addresses, firewall ports, RAM-backed storage paths, GPU/runtime
  assumptions, and secrets handling.
- Updated runbook index, architecture, and status docs to link the topology
  guidance.

Validation:

- `rg -n "linux-cloud-deployment-topology|GEMMA_API_URL|TRANSCRIPTION_API_URL" docs ai-stream-director/.env.example`
- `rg -n "SRS_BIND_ADDR|FASTER_WHISPER_BIND_ADDR|LOOKBACK_BUFFER_HOST_DIR|GEMMA_API_KEY" docs/runbooks ai-stream-director/.env.example`

No live Docker, GPU, or cloud commands were required for this docs-only ticket.
