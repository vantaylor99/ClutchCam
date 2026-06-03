description: Completed review of the SRS local media-server ingest configuration
prereq: production-service-boundaries
files: docs/ARCHITECTURE.md, docs/ROADMAP.md, docs/STATUS.md, ai-stream-director/README.md, ai-stream-director/docker-compose.yml, ai-stream-director/.env.example, ai-stream-director/src/services/ingestion.py, ai-stream-director/tests/test_ingestion_config.py, ai-stream-director/infra/srs.conf
----
The local media-server ingest review is complete. The implementation provides a
configuration-only SRS ingest layer behind the existing import-safe ingestion
boundary without wiring the terminal MVP directly to live media feeds.

What was reviewed:

- `ai-stream-director/docker-compose.yml` defines a `media-server` service using
  `${SRS_IMAGE:-ossrs/srs:6}`, mounts the repo-owned SRS config read-only, and
  publishes RTMP, HTTP API, HTTP stream output, and SRT through environment
  driven host bindings.
- `ai-stream-director/infra/srs.conf` enables RTMP on `1935`, SRS HTTP API on
  `1985`, HTTP streaming on `8080`, SRT on UDP `10080`, SRT-to-RTMP bridging,
  HLS output, and HTTP-FLV remux for the default vhost.
- `services.ingestion` remains deterministic and import-safe. It only builds
  stable `StreamSource` records plus RTMP and SRT URL strings; it does not start
  SRS, inspect Docker, open sockets, or connect the MVP runtime to media feeds.
- README and shared docs describe publisher-facing RTMP/SRT URLs, worker-facing
  Compose URLs, generated-source smoke tests, and the safe
  `SRS_BIND_ADDR=127.0.0.1` default with an explicit `0.0.0.0` LAN option.

Review notes:

- Checked the SRS 6 documentation for RTMP, SRT, HTTP-FLV, HLS, and Docker live
  streaming examples. The configured blocks and documented URL shapes match the
  documented SRS patterns for RTMP publish/play, SRT publish/request via
  `streamid=#!::r=live/<stream>,m=<mode>`, HTTP-FLV, and HLS inspection.
- The lack of a Compose healthcheck is acceptable for this pass because the
  selected upstream image should not be assumed to contain `curl` or `wget`.
  Documentation uses the host SRS HTTP API endpoint for manual validation.
- The localhost-only default bind address is the right safety posture for local
  raw player feeds. Operators who need LAN publishers are told to opt into
  `SRS_BIND_ADDR=0.0.0.0` only when the firewall boundary is intentional.
- The SRT helper tests confirm SRS streamid syntax is preserved literally rather
  than URL-encoded.
- `docs/ROADMAP.md` was updated during review to remove this ticket from the
  active review list.

Validation:

- PASS: `python -m unittest tests.test_ingestion_config -v`
- PASS: `python -m unittest tests.test_service_boundaries tests.test_rolling_buffer -v`
- PASS: in-memory compile check over 13 Python files under `src`
- ATTEMPTED: `python -m unittest discover -s tests -v`
  - New ingestion, service-boundary, contract, and rolling-buffer tests passed.
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
    `src/services/__pycache__`; an in-memory compile check was used instead and
    passed.

Usage notes:

- Start SRS only: `docker compose up -d media-server`.
- RTMP publish example: `rtmp://127.0.0.1:1935/live/player_1`.
- SRT publish example:
  `srt://127.0.0.1:10080?streamid=#!::r=live/player_1,m=publish`.
- Worker RTMP consume example: `rtmp://media-server:1935/live/player_1`.
- Worker SRT request example:
  `srt://media-server:10080?streamid=#!::r=live/player_1,m=request`.
