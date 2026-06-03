description: Configure the local SRS RTMP/SRT media ingest service
prereq: production-service-boundaries
files: docs/ARCHITECTURE.md, docs/ROADMAP.md, docs/STATUS.md, ai-stream-director/README.md, ai-stream-director/docker-compose.yml, ai-stream-director/.env.example, ai-stream-director/src/config.py, ai-stream-director/src/services/ingestion.py, ai-stream-director/tests/test_ingestion_config.py, ai-stream-director/infra/srs.conf
----
Add the first concrete local media-server layer behind the existing ingestion
boundary. Use SRS (Simple Realtime Server) as the selected open-source server:
it supports RTMP and SRT in one Docker service, has official Docker images, and
can expose RTMP, SRT, HTTP-FLV/HLS, and HTTP API endpoints while raw player
feeds remain on the local network.

References:

- Current boundary docs: `docs/ARCHITECTURE.md`,
  `ai-stream-director/src/services/ingestion.py`, and
  `ai-stream-director/src/config.py`.
- SRS upstream README: https://github.com/ossrs/srs
- SRS Docker/live-streaming guide:
  https://ossrs.io/lts/en-us/docs/v7/doc/getting-started
- SRS SRT guide:
  https://ossrs.net/lts/en-us/docs/v7/doc/srt
- SRS HTTP API guide:
  https://ossrs.io/lts/en-us/docs/v5/doc/http-api

Runtime shape:

- Add a `media-server` service to `ai-stream-director/docker-compose.yml` using
  a pinned, environment-overridable SRS image such as
  `${SRS_IMAGE:-ossrs/srs:6}`. Avoid `latest`.
- Mount a repo-owned SRS config file, for example
  `ai-stream-director/infra/srs.conf`, and run SRS with that config rather than
  relying on opaque image defaults.
- Expose these ports through environment-driven Compose bindings:
  - RTMP: `${SRS_RTMP_PORT:-1935}:1935/tcp`
  - HTTP API: `${SRS_HTTP_API_PORT:-1985}:1985/tcp`
  - HTTP stream server: `${SRS_HTTP_STREAM_PORT:-8080}:8080/tcp`
  - SRT: `${SRS_SRT_PORT:-10080}:10080/udp`
- Allow a host bind address such as `${SRS_BIND_ADDR:-127.0.0.1}` in the port
  mappings. Document that `127.0.0.1` is host-local and operators can set
  `SRS_BIND_ADDR=0.0.0.0` only when the LAN firewall boundary is intentional.
- Add a Compose health check against the SRS HTTP API if the chosen image has a
  usable `curl` or `wget`; otherwise document the checked fallback and keep the
  API endpoint available for manual validation.

SRS configuration:

- Enable RTMP on container port `1935`.
- Enable the HTTP API on container port `1985`.
- Enable the HTTP stream server on container port `8080` so smoke tests and
  future tooling can inspect HTTP-FLV/HLS output if useful.
- Enable SRT on container UDP port `10080`.
- Prefer a publisher-friendly SRT configuration (`default_mode publish`) only if
  it does not make FFmpeg/OBS request URLs ambiguous. Full streamid URLs with
  explicit `m=publish` and `m=request` must remain documented and supported.
- Do not add cloud relay, external authentication, DVR persistence, or public
  egress in this ticket.

Stable stream mapping:

- Preserve the project stream IDs from `config.STREAM_IDS`:
  `player_1`, `player_2`, `player_3`, and `player_4`.
- Player or capture-machine RTMP publish URLs should be documented as:
  `rtmp://<media-server-host>:<SRS_RTMP_PORT>/live/player_1` through
  `player_4`.
- Player or capture-machine SRT publish URLs should be documented as:
  `srt://<media-server-host>:<SRS_SRT_PORT>?streamid=#!::r=live/player_1,m=publish`
  through `player_4`.
- FFmpeg buffer workers running in the Compose network should be able to consume
  stable local URLs such as:
  `rtmp://media-server:1935/live/player_1` through `player_4`.
- If SRT request URLs are exposed for buffer workers, use explicit request mode:
  `srt://media-server:10080?streamid=#!::r=live/player_1,m=request`.
- Update `INGEST_API_URL` defaults/examples so `build_configured_sources(...)`
  can generate the worker-facing stream URLs without hardcoding host ports in
  Python. For the Docker Compose stack, prefer
  `INGEST_API_URL=rtmp://media-server:1935/live`.

Import and boundary rules:

- The SRS lifecycle belongs to Docker Compose. Importing
  `services.ingestion`, `config`, or any boundary module must not start SRS,
  open sockets, inspect Docker, run FFmpeg, or require non-standard Python
  packages.
- Keep `build_configured_sources(...)` compatible with arbitrary base URLs. If
  additional helpers are added for publish/play URL construction, they should be
  deterministic pure functions with clear tests.
- Do not wire the terminal MVP directly to media ingestion yet. This ticket is
  configuration plus source description for the follow-up buffer/transcription
  workers.

Smoke-test path:

- Document a no-player smoke test using generated FFmpeg sources. Include at
  least one RTMP publish example:
  `ffmpeg -re -f lavfi -i testsrc=size=1280x720:rate=30 -f lavfi -i sine=frequency=440 -c:v libx264 -preset veryfast -tune zerolatency -pix_fmt yuv420p -c:a aac -f flv rtmp://127.0.0.1:1935/live/player_1`
- Include an SRT publish example using MPEG-TS and explicit publish mode:
  `ffmpeg -re -f lavfi -i testsrc=size=1280x720:rate=30 -f lavfi -i sine=frequency=440 -c:v libx264 -preset veryfast -tune zerolatency -pix_fmt yuv420p -c:a aac -pes_payload_size 0 -f mpegts "srt://127.0.0.1:10080?streamid=#!::r=live/player_1,m=publish"`
- Include validation commands using local tools, such as `ffprobe` or `ffplay`,
  and the SRS HTTP API endpoint `http://127.0.0.1:1985/api/v1/summaries`.
- Make it clear how to repeat the command for `player_2`, `player_3`, and
  `player_4`, preferably with different test patterns or audio frequencies so
  streams are visually/audibly distinguishable.

Documentation updates:

- Update `docs/ARCHITECTURE.md` to say the first local ingest implementation
  uses SRS through Docker Compose and publishes stable stream IDs under the
  `live` app.
- Update `docs/ROADMAP.md` and `docs/STATUS.md` so the repo no longer says the
  local RTMP/SRT media-server configuration is missing after implementation.
- Add an `ai-stream-director/README.md` section for starting the media server,
  publishing from OBS/vMix/FFmpeg, generated-source smoke testing, and consuming
  worker URLs from inside Compose.
- Update `ai-stream-director/.env.example` with SRS image/port/bind variables
  and a Compose-appropriate `INGEST_API_URL`.

Tests:

- Add focused tests in `ai-stream-director/tests/test_ingestion_config.py` that
  do not require Docker, FFmpeg, or network sockets.
- Cover `build_configured_sources("rtmp://media-server:1935/live")` producing
  the four expected worker-facing URLs.
- Cover any new pure URL helper for RTMP and SRT publish/request URLs, including
  escaping or preserving the SRT streamid string.
- Add a lightweight config-file/Compose assertion if practical with the standard
  library, for example checking that `docker-compose.yml` defines
  `media-server`, RTMP/TCP and SRT/UDP port mappings, the SRS config mount, and
  the worker-facing `INGEST_API_URL` example.
- Keep the existing clean-process import test passing; no new import should pull
  in Docker, FFmpeg, requests, OBS, or media-server runtime dependencies.

TODO:

- Add the SRS config file under `ai-stream-director/infra/`.
- Add the `media-server` service, environment-driven ports, config mount, and
  health/manual validation endpoint to `ai-stream-director/docker-compose.yml`.
- Update `ai-stream-director/.env.example` and any pure ingestion URL helpers
  needed for stable `player_1` through `player_4` records.
- Add ingestion config tests that require only the Python standard library.
- Update architecture/status/README documentation with publish, consume, and
  generated-source smoke-test instructions.
- Run `python -m unittest discover -s tests -v` from `ai-stream-director/`.
