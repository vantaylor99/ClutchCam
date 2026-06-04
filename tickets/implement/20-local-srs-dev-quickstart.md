description: Document the local SRS media-server quickstart smoke path
prereq: local-media-server-ingest
files: ai-stream-director/README.md, ai-stream-director/docker-compose.yml, ai-stream-director/.env.example, docs/STATUS.md, docs/ROADMAP.md
----
The local SRS media-server ingest layer is already implemented and reviewed in
`local-media-server-ingest`. The docs now need a concise first-run quickstart
that distinguishes "SRS is not started or not listening" from "the SRS HTTP API
started but returned an unexpected response."

Relevant current state:

- `ai-stream-director/docker-compose.yml` defines `media-server` using
  `${SRS_IMAGE:-ossrs/srs:6}` and binds the SRS HTTP API with
  `${SRS_BIND_ADDR:-127.0.0.1}:${SRS_HTTP_API_PORT:-1985}:1985/tcp`.
- `ai-stream-director/.env.example` keeps `SRS_BIND_ADDR=127.0.0.1` by default
  and documents `0.0.0.0` as an intentional LAN/firewall choice.
- `ai-stream-director/README.md` already has a `Local Media Server` section with
  the `docker compose up -d media-server` command, RTMP/SRT URL shapes,
  generated-source examples, and the `/api/v1/summaries` request.
- The README does not yet make the Docker-on-PATH prerequisite or the port-1985
  listener check prominent enough for the first smoke test.

Keep this ticket scoped to documentation. Do not change SRS config, Compose
ports, service names, stream IDs, or application runtime behavior for this pass.

TODO:

- Add or tighten a first-run quickstart under the README's local media-server
  docs, starting from the `ai-stream-director/` directory.
- State that Docker or Docker Desktop must be installed and that the `docker`
  command must be available on `PATH`; the quickstart uses Docker Compose.
- Show the exact SRS-only startup command:
  `docker compose up -d media-server`.
- Show how to verify that something is listening on host port `1985` before
  calling the API. Prefer a Windows PowerShell-friendly command because the
  README examples are PowerShell-first, and include a Linux equivalent if it
  keeps the quickstart clear.
- Show the SRS HTTP API smoke call:
  `Invoke-RestMethod http://127.0.0.1:1985/api/v1/summaries`.
- Explain the expected failure split: browser or client connection refused
  means SRS is not started, Docker is unavailable, or the host port is not
  listening; a response from `/api/v1/summaries` means the SRS API is reachable
  even if no player streams are currently publishing.
- Explain host selection for smoke tests: use `127.0.0.1` when testing from the
  same machine, use the Linux server LAN IP when publishers or operators are on
  another machine, and set `SRS_BIND_ADDR=0.0.0.0` only when that LAN exposure
  and firewall boundary are intentional.
- Preserve the existing note that the upstream `ossrs/srs:6` image should not
  be assumed to contain `curl` or `wget`, so host-side validation is the
  supported quickstart path.
- Update `docs/STATUS.md` or `docs/ROADMAP.md` only if the README changes make
  their current SRS quickstart/status wording stale.
