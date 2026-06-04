description: Completed local SRS media-server first smoke quickstart docs
prereq: local-media-server-ingest
files: ai-stream-director/README.md
----
The README now documents the first local SRS `media-server` smoke path.

Built:

- Added Docker/Docker Desktop and `docker` PATH prerequisites.
- Added `docker --version`, `docker compose version`, and
  `docker compose up -d media-server`.
- Added a host port `1985` listener check using PowerShell
  `Test-NetConnection`, plus a Linux `ss` equivalent.
- Added the SRS HTTP API smoke call:
  `Invoke-RestMethod http://127.0.0.1:1985/api/v1/summaries`.
- Explained that connection refused means SRS is not started, Docker is
  unavailable, or port `1985` is not listening.
- Clarified that an API response means SRS is reachable even when no player
  streams are publishing.
- Clarified `127.0.0.1` versus LAN IP testing and when
  `SRS_BIND_ADDR=0.0.0.0` is appropriate.

Validation:

- Verified commands align with the `media-server` service and default Compose
  port binding.
- Preserved the existing host-side validation note for `ossrs/srs:6`.
- `git diff --check` passed with only CRLF normalization warnings.
