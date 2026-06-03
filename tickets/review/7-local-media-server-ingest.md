description: Review the SRS local media-server ingest configuration
prereq: production-service-boundaries
files: docs/ARCHITECTURE.md, docs/ROADMAP.md, docs/STATUS.md, ai-stream-director/README.md, ai-stream-director/docker-compose.yml, ai-stream-director/.env.example, ai-stream-director/src/services/ingestion.py, ai-stream-director/tests/test_ingestion_config.py, ai-stream-director/infra/srs.conf
----
The first concrete local media-server ingest layer is implemented with SRS
behind the existing import-safe ingestion boundary.

Implemented behavior:

- `ai-stream-director/docker-compose.yml` now defines a `media-server` service
  using `${SRS_IMAGE:-ossrs/srs:6}` and a repo-owned config mount at
  `./infra/srs.conf:/usr/local/srs/conf/clutchcam.conf:ro`.
- Compose publishes RTMP, HTTP API, HTTP stream output, and SRT through
  environment-driven host bindings:
  `${SRS_BIND_ADDR:-127.0.0.1}`, `${SRS_RTMP_PORT:-1935}`,
  `${SRS_HTTP_API_PORT:-1985}`, `${SRS_HTTP_STREAM_PORT:-8080}`, and
  `${SRS_SRT_PORT:-10080}`.
- `ai-stream-director/infra/srs.conf` enables RTMP on `1935`, SRS HTTP API on
  `1985`, HTTP stream output on `8080`, SRT on UDP `10080`, SRT-to-RTMP
  bridging, HLS, and HTTP-FLV remux for the default vhost.
- The Compose app environment now defaults worker-facing ingestion to
  `INGEST_API_URL=rtmp://media-server:1935/live`; `.env.example` documents that
  value plus SRS image, bind, and port variables.
- `services.ingestion` remains deterministic and import-safe. It now exposes
  pure helpers for RTMP stream URLs plus explicit SRT publish and request URLs
  while keeping `build_configured_sources(...)` compatible with arbitrary RTMP
  base URLs.
- README and shared docs describe RTMP and SRT publish URLs for `player_1`
  through `player_4`, internal Compose worker URLs, the host-local
  `SRS_BIND_ADDR=127.0.0.1` default, the intentional `0.0.0.0` LAN option, and
  generated FFmpeg smoke tests.

Review focus:

- Confirm the SRS 6.x config syntax and enabled blocks are sufficient for RTMP
  publish/play, SRT publish/request with explicit `streamid`, and HTTP-FLV/HLS
  inspection.
- Confirm the lack of a Compose healthcheck is acceptable for the chosen image:
  the upstream image does not guarantee `curl` or `wget`, so docs use the SRS
  HTTP API endpoint `http://127.0.0.1:1985/api/v1/summaries` for manual
  validation instead.
- Confirm default `SRS_BIND_ADDR=127.0.0.1` is the right safety posture and that
  the docs are clear enough for operators who need LAN publishers.
- Confirm the URL helpers preserve SRS streamid syntax rather than URL-encoding
  `#!::r=live/<stream_id>,m=<mode>`.
- Confirm this ticket remains configuration plus source description only and
  does not wire the terminal MVP directly to live media ingest.

Validation:

- PASS: `python -m unittest tests.test_ingestion_config -v`
- PASS: `python -m unittest tests.test_service_boundaries tests.test_rolling_buffer -v`
- ATTEMPTED: `python -m unittest discover -s tests -v`
  - New ingestion tests and boundary/rolling-buffer tests passed.
  - Full discovery still fails in this local environment because `requests` is
    not installed, so existing `test_ai_director` and `test_dry_run_obs` fail
    during import before their tests run.
- CONFIRMED: `python -m pip show requests` reports `Package(s) not found:
  requests`.
- ATTEMPTED: `docker compose config`
  - Blocked in this local environment because `docker` is not installed on the
    PATH.
- ATTEMPTED: `python -m compileall src`
  - Blocked by a local filesystem permission error writing
    `src/services/__pycache__`; no tracked cache files were introduced.

Usage notes for review:

- Start SRS only: `docker compose up -d media-server`.
- RTMP publish example:
  `rtmp://127.0.0.1:1935/live/player_1`.
- SRT publish example:
  `srt://127.0.0.1:10080?streamid=#!::r=live/player_1,m=publish`.
- Worker RTMP consume example:
  `rtmp://media-server:1935/live/player_1`.
- Worker SRT request example:
  `srt://media-server:10080?streamid=#!::r=live/player_1,m=request`.
