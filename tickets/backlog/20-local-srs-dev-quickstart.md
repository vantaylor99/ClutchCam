description: Document first local SRS media-server smoke test path
prereq: local-media-server-ingest
files: ai-stream-director/README.md, docs/STATUS.md, docs/ROADMAP.md, ai-stream-director/docker-compose.yml
----
Opening `http://127.0.0.1:1985/api/v1/summaries` before SRS is running shows a
browser connection-refused page. This is expected, but the local testing path
should make the difference between "service not started" and "SRS API failed"
obvious.

Expected behavior:

- The docs should show the exact command to start only the SRS media server with
  Docker Compose.
- The docs should show how to verify that something is listening on port `1985`
  and how to call `/api/v1/summaries`.
- The docs should explain that Docker must be installed and available on PATH
  for this smoke test.
- The docs should explain when to use `127.0.0.1` versus a Linux server LAN IP
  and when `SRS_BIND_ADDR=0.0.0.0` is needed.
