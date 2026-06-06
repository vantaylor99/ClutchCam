description: Blocked pending a real Linux Docker host for generated RTMP ingest acceptance
prereq: docker-runtime-ffmpeg, buffer-worker-ffmpeg-supervision, generated-ingest-preflight-diagnostics
files: ai-stream-director/scripts/compose_generated_ingest_checkpoint.py, ai-stream-director/scripts/smoke_media_server.py, ai-stream-director/scripts/smoke_buffer_worker.py, ai-stream-director/docker-compose.yml, docs/STATUS.md, docs/ROADMAP.md, docs/runbooks/local-linux-compose.md
----
Planning is complete, but live acceptance cannot be performed in the current
Windows environment because the Docker command is absent and `/dev/shm` is not
a Linux tmpfs mount. Windows or mocked results are not acceptance evidence.

External blocker: provide an x86_64 Linux host with Docker Engine, the Docker
Compose v2 plugin, host FFmpeg with `libx264` and AAC encoding, Python 3, Git,
and a checkout containing completed tickets `docker-runtime-ffmpeg`,
`buffer-worker-ffmpeg-supervision`, and
`generated-ingest-preflight-diagnostics`. The operator must be able to create
and remove `/dev/shm/clutchcam`, bind ports 1935 and 1985 on loopback, build
images, and run Docker without an interactive privilege prompt.

The generated-ingest checkpoint has one important acceptance limitation:
`assert_any_ready` permits a multi-stream report to pass when only one stream
has a resolvable clip. The four-stream procedure below therefore applies a
stricter post-check assertion requiring every requested stream to be ready.

## Resume command sequence

On the Linux host, set `REPO` to the checkout and `EVIDENCE_ROOT` to a durable
absolute directory outside the checkout. Run the following from Bash. It
isolates the Compose project, records the exact source state, streams long
commands, captures bounded diagnostics on failure, and tears the stack down.

```bash
set -Eeuo pipefail

export REPO=/absolute/path/to/ClutchCam
export EVIDENCE_ROOT="$HOME/clutchcam-acceptance-$(date -u +%Y%m%dT%H%M%SZ)"
cd "$REPO/ai-stream-director"
mkdir -p "$EVIDENCE_ROOT"

export COMPOSE_PROJECT_NAME=clutchcam-acceptance
export SRS_BIND_ADDR=127.0.0.1
export SRS_RTMP_PORT=1935
export SRS_HTTP_API_PORT=1985
export LOOKBACK_BUFFER_HOST_DIR=/dev/shm/clutchcam
export LOOKBACK_BUFFER_DIR=/dev/shm/clutchcam
export INGEST_API_URL=rtmp://media-server:1935/live
export FFMPEG_EXECUTABLE=ffmpeg
export LOOKBACK_INPUT_URL_PLAYER_1=rtmp://media-server:1935/live/player_1
export LOOKBACK_INPUT_URL_PLAYER_2=rtmp://media-server:1935/live/player_2
export LOOKBACK_INPUT_URL_PLAYER_3=rtmp://media-server:1935/live/player_3
export LOOKBACK_INPUT_URL_PLAYER_4=rtmp://media-server:1935/live/player_4
compose=(docker compose --profile media-server --profile buffer-worker)

on_exit() {
  rc=$?
  trap - EXIT
  set +e
  "${compose[@]}" ps --all --format json \
    >"$EVIDENCE_ROOT/failure-compose-ps.json" 2>&1
  timeout 15s "${compose[@]}" logs --no-color --tail=100 \
    media-server buffer-worker \
    >"$EVIDENCE_ROOT/failure-compose-logs.txt" 2>&1
  "${compose[@]}" down --remove-orphans --timeout 30 \
    >"$EVIDENCE_ROOT/failure-compose-down.txt" 2>&1
  printf 'FAIL exit_code=%s\n' "$rc" >"$EVIDENCE_ROOT/RESULT.txt"
  exit "$rc"
}
trap on_exit EXIT

test "$(uname -s)" = Linux
command -v docker python3 ffmpeg findmnt timeout sha256sum git
{
  date -u --iso-8601=seconds
  cat /etc/os-release
  uname -a
  git rev-parse HEAD
  git status --short
} | tee "$EVIDENCE_ROOT/host-and-source.txt"
timeout 20s docker version | tee "$EVIDENCE_ROOT/docker-version.txt"
timeout 20s docker compose version | tee "$EVIDENCE_ROOT/compose-version.txt"
ffmpeg -hide_banner -version | tee "$EVIDENCE_ROOT/host-ffmpeg-version.txt"
ffmpeg -hide_banner -encoders 2>/dev/null |
  grep -E '(^| )libx264( |$)|(^| )aac( |$)' |
  tee "$EVIDENCE_ROOT/host-ffmpeg-encoders.txt"
grep -q libx264 "$EVIDENCE_ROOT/host-ffmpeg-encoders.txt"
grep -qE '(^| )aac( |$)' "$EVIDENCE_ROOT/host-ffmpeg-encoders.txt"

test "$LOOKBACK_BUFFER_HOST_DIR" = /dev/shm/clutchcam
mkdir -p "$LOOKBACK_BUFFER_HOST_DIR"
findmnt -T "$LOOKBACK_BUFFER_HOST_DIR" -o TARGET,SOURCE,FSTYPE,OPTIONS |
  tee "$EVIDENCE_ROOT/ram-findmnt.txt"
test "$(findmnt -n -o FSTYPE -T "$LOOKBACK_BUFFER_HOST_DIR")" = tmpfs

"${compose[@]}" down --remove-orphans --timeout 30 |
  tee "$EVIDENCE_ROOT/initial-down.txt"
test -z "$("${compose[@]}" ps -q)"
for name in ai-stream-director-media-server ai-stream-director-buffer-worker; do
  ! docker inspect "$name" >/dev/null 2>&1
done
rm -rf -- "$LOOKBACK_BUFFER_HOST_DIR"/player_{1,2,3,4}

docker compose --profile buffer-worker build --pull --no-cache buffer-worker \
  2>&1 | tee "$EVIDENCE_ROOT/worker-build.txt"
IMAGE_ID="$(docker compose --profile buffer-worker images -q buffer-worker | head -n 1)"
test -n "$IMAGE_ID"
printf '%s\n' "$IMAGE_ID" | tee "$EVIDENCE_ROOT/worker-image-id.txt"
docker run --rm --entrypoint sh "$IMAGE_ID" -c \
  'command -v ffmpeg && ffmpeg -hide_banner -version | head -n 1' |
  tee "$EVIDENCE_ROOT/worker-image-ffmpeg.txt"

SMOKE_PUBLISH_SECONDS=12 \
SMOKE_PUBLISH_TIMEOUT_SECONDS=30 \
GENERATED_INGEST_COMPOSE_READY_TIMEOUT_SECONDS=60 \
GENERATED_INGEST_BUFFER_READY_TIMEOUT_SECONDS=60 \
python3 scripts/compose_generated_ingest_checkpoint.py \
  --run --no-build --streams player_1 \
  2>&1 | tee "$EVIDENCE_ROOT/one-stream-report.json"

python3 - "$EVIDENCE_ROOT/one-stream-report.json" <<'PY'
import json, sys
r = json.load(open(sys.argv[1], encoding="utf-8"))
assert r["schema_version"] == 1
assert r["checkpoint"] == "compose-generated-ingest"
assert r["status"] == "passed" and r["failure_reason"] is None
assert r["stream_ids"] == ["player_1"]
assert r["preflight"]["status"] == "passed"
assert all(x["status"] == "passed" for x in r["preflight"]["requirements"])
assert r["compose"]["status"] == "passed"
assert r["compose"]["service_state"]["status"] == "passed"
assert r["publish"]["published_stream_ids"] == ["player_1"]
assert all(x["returncode"] == 0 for x in r["publish"]["streams"])
assert r["buffer"]["status"] == "ready"
assert r["buffer"]["buffer_root"] == "/dev/shm/clutchcam"
s = {x["stream_id"]: x for x in r["buffer"]["streams"]}["player_1"]
assert s["segment_count"] > 0
assert s["clip_status"] == "ready"
assert s["clip_media_uri"]
assert s["latest_segment"]["exists"] is True
PY
test -s /dev/shm/clutchcam/player_1/segments.csv
find /dev/shm/clutchcam/player_1 -maxdepth 1 -type f -name '*.ts' -size +0c \
  -print -quit | grep -q .
"${compose[@]}" ps --all --format json \
  >"$EVIDENCE_ROOT/one-stream-compose-ps.json"
"${compose[@]}" logs --no-color --tail=100 media-server buffer-worker \
  >"$EVIDENCE_ROOT/one-stream-compose-logs.txt"

"${compose[@]}" down --remove-orphans --timeout 30 |
  tee "$EVIDENCE_ROOT/between-runs-down.txt"
test -z "$("${compose[@]}" ps -q)"
rm -rf -- "$LOOKBACK_BUFFER_HOST_DIR"/player_{1,2,3,4}

SMOKE_PUBLISH_SECONDS=12 \
SMOKE_PUBLISH_TIMEOUT_SECONDS=30 \
GENERATED_INGEST_COMPOSE_READY_TIMEOUT_SECONDS=60 \
GENERATED_INGEST_BUFFER_READY_TIMEOUT_SECONDS=60 \
python3 scripts/compose_generated_ingest_checkpoint.py \
  --run --no-build --streams player_1,player_2,player_3,player_4 \
  2>&1 | tee "$EVIDENCE_ROOT/four-stream-report.json"

python3 - "$EVIDENCE_ROOT/four-stream-report.json" <<'PY'
import json, pathlib, sys
r = json.load(open(sys.argv[1], encoding="utf-8"))
expected = ["player_1", "player_2", "player_3", "player_4"]
assert r["status"] == "passed" and r["failure_reason"] is None
assert r["stream_ids"] == expected
assert r["preflight"]["status"] == "passed"
assert r["compose"]["status"] == "passed"
assert r["compose"]["service_state"]["status"] == "passed"
assert r["publish"]["published_stream_ids"] == expected
assert all(x["returncode"] == 0 for x in r["publish"]["streams"])
assert r["buffer"]["status"] == "ready"
assert r["buffer"]["buffer_root"] == "/dev/shm/clutchcam"
streams = {x["stream_id"]: x for x in r["buffer"]["streams"]}
assert sorted(streams) == expected
for stream_id in expected:
    s = streams[stream_id]
    root = pathlib.Path("/dev/shm/clutchcam", stream_id).resolve()
    assert s["segment_count"] > 0
    assert s["clip_status"] == "ready"
    assert s["clip_media_uri"]
    assert s["latest_segment"]["exists"] is True
    assert pathlib.Path(s["latest_segment"]["path"]).resolve().is_relative_to(root)
    assert all(uri.startswith(f"file://{root}/") for uri in s["segment_uris"])
PY
for stream_id in player_1 player_2 player_3 player_4; do
  test -s "$LOOKBACK_BUFFER_HOST_DIR/$stream_id/segments.csv"
  find "$LOOKBACK_BUFFER_HOST_DIR/$stream_id" -maxdepth 1 \
    -type f -name '*.ts' -size +0c -print -quit | grep -q .
done
"${compose[@]}" ps --all --format json \
  >"$EVIDENCE_ROOT/four-stream-compose-ps.json"
"${compose[@]}" logs --no-color --tail=100 media-server buffer-worker \
  >"$EVIDENCE_ROOT/four-stream-compose-logs.txt"

WORKER_ID_BEFORE="$("${compose[@]}" ps -q buffer-worker)"
test -n "$WORKER_ID_BEFORE"
docker inspect "$WORKER_ID_BEFORE" >"$EVIDENCE_ROOT/worker-inspect.json"
printf '%s\n' "$WORKER_ID_BEFORE" >"$EVIDENCE_ROOT/reconnect-worker-id-before.txt"
RECONNECT_SINCE="$(date -u --iso-8601=seconds)"

SMOKE_PUBLISH_SECONDS=45 SMOKE_PUBLISH_TIMEOUT_SECONDS=60 \
SMOKE_PUBLISH_STREAMS=player_1 \
python3 scripts/smoke_media_server.py --no-compose --streams player_1 \
  2>&1 | tee "$EVIDENCE_ROOT/reconnect-publish-1.json"
LOOKBACK_BUFFER_DIR=/dev/shm/clutchcam \
SMOKE_BUFFER_STREAM_IDS=player_1 \
python3 scripts/smoke_buffer_worker.py |
  tee "$EVIDENCE_ROOT/reconnect-buffer-before.json"
BEFORE_SEQ="$(python3 -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["streams"][0]["latest_segment"]["sequence"])' \
  "$EVIDENCE_ROOT/reconnect-buffer-before.json")"
sleep 5

SECOND_PUBLISH_SINCE="$(date -u --iso-8601=seconds)"
SMOKE_PUBLISH_SECONDS=45 SMOKE_PUBLISH_TIMEOUT_SECONDS=60 \
SMOKE_PUBLISH_STREAMS=player_1 \
python3 scripts/smoke_media_server.py --no-compose --streams player_1 \
  2>&1 | tee "$EVIDENCE_ROOT/reconnect-publish-2.json"

advanced=false
for attempt in $(seq 1 30); do
  LOOKBACK_BUFFER_DIR=/dev/shm/clutchcam \
  SMOKE_BUFFER_STREAM_IDS=player_1 \
  python3 scripts/smoke_buffer_worker.py \
    >"$EVIDENCE_ROOT/reconnect-buffer-after.json"
  AFTER_SEQ="$(python3 -c \
    'import json,sys; print(json.load(open(sys.argv[1]))["streams"][0]["latest_segment"]["sequence"])' \
    "$EVIDENCE_ROOT/reconnect-buffer-after.json")"
  if (( AFTER_SEQ > BEFORE_SEQ )); then advanced=true; break; fi
  sleep 2
done
test "$advanced" = true

WORKER_ID_AFTER="$("${compose[@]}" ps -q buffer-worker)"
printf '%s\n' "$WORKER_ID_AFTER" >"$EVIDENCE_ROOT/reconnect-worker-id-after.txt"
test "$WORKER_ID_AFTER" = "$WORKER_ID_BEFORE"
timeout 15s "${compose[@]}" logs --since "$RECONNECT_SINCE" \
  --timestamps --no-color --tail=100 buffer-worker \
  >"$EVIDENCE_ROOT/reconnect-worker-logs.txt"
timeout 15s "${compose[@]}" logs --since "$SECOND_PUBLISH_SINCE" \
  --timestamps --no-color --tail=100 buffer-worker \
  >"$EVIDENCE_ROOT/reconnect-second-publish-logs.txt"
grep -q 'buffer_ffmpeg_exited stream=player_1' \
  "$EVIDENCE_ROOT/reconnect-worker-logs.txt"
grep -q 'buffer_ffmpeg_started stream=player_1' \
  "$EVIDENCE_ROOT/reconnect-second-publish-logs.txt"

findmnt -T "$LOOKBACK_BUFFER_HOST_DIR" -o TARGET,SOURCE,FSTYPE,OPTIONS \
  >"$EVIDENCE_ROOT/ram-findmnt-after.txt"
test "$(findmnt -n -o FSTYPE -T "$LOOKBACK_BUFFER_HOST_DIR")" = tmpfs
python3 - "$EVIDENCE_ROOT/worker-inspect.json" <<'PY'
import json, pathlib, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))[0]
mounts = [
    m for m in data["Mounts"]
    if m["Destination"] == "/dev/shm/clutchcam"
]
assert len(mounts) == 1
mount = mounts[0]
assert mount["Type"] == "bind"
assert pathlib.Path(mount["Source"]).resolve() == pathlib.Path("/dev/shm/clutchcam").resolve()
assert "LOOKBACK_BUFFER_DIR=/dev/shm/clutchcam" in data["Config"]["Env"]
PY
find "$LOOKBACK_BUFFER_HOST_DIR" -maxdepth 2 -type f -printf '%p %s\n' |
  sort >"$EVIDENCE_ROOT/ram-buffer-files.txt"
test -s "$EVIDENCE_ROOT/ram-buffer-files.txt"

"${compose[@]}" ps --all --format json \
  >"$EVIDENCE_ROOT/pre-cleanup-compose-ps.json"
"${compose[@]}" logs --no-color --tail=100 media-server buffer-worker \
  >"$EVIDENCE_ROOT/pre-cleanup-compose-logs.txt"
"${compose[@]}" down --remove-orphans --timeout 30 \
  2>&1 | tee "$EVIDENCE_ROOT/cleanup-down.txt"
"${compose[@]}" ps --all --format json \
  >"$EVIDENCE_ROOT/post-cleanup-compose-ps.json"
test -z "$("${compose[@]}" ps -q)"
test -z "$(docker ps -q --filter "label=com.docker.compose.project=$COMPOSE_PROJECT_NAME")"
for name in ai-stream-director-media-server ai-stream-director-buffer-worker; do
  ! docker inspect "$name" >/dev/null 2>&1
done
rm -rf -- "$LOOKBACK_BUFFER_HOST_DIR"/player_{1,2,3,4}
for stream_id in player_1 player_2 player_3 player_4; do
  test ! -e "$LOOKBACK_BUFFER_HOST_DIR/$stream_id"
done

printf 'PASS\n' >"$EVIDENCE_ROOT/RESULT.txt"
find "$EVIDENCE_ROOT" -type f ! -name SHA256SUMS -print0 |
  sort -z | xargs -0 sha256sum >"$EVIDENCE_ROOT/SHA256SUMS"
trap - EXIT
printf 'Acceptance evidence: %s\n' "$EVIDENCE_ROOT"
```

The 45-second reconnect publishers intentionally exceed the worker
supervisor's 30-second maximum restart backoff. Do not shorten them unless the
worker logs prove the publisher was connected and new segments were produced.

## Evidence to retain

Retain the entire `EVIDENCE_ROOT` directory unchanged:

- Host/source identity: `host-and-source.txt`, Docker/Compose versions, host
  FFmpeg version and encoder list.
- Image provenance: streamed no-cache build log, image ID, and in-image FFmpeg
  path/version.
- One-stream and four-stream structured reports plus their post-run Compose
  state and bounded 100-line service logs.
- Reconnect publisher outputs, before/after buffer JSON, unchanged worker
  container IDs, worker inspect JSON, and bounded timestamped recovery logs.
- RAM-backed storage proof: both `findmnt` captures, Docker bind-mount inspect,
  and the retained file/size listing made before media cleanup.
- Cleanup proof: pre/post Compose state, bounded final logs, `down` output,
  `RESULT.txt`, and `SHA256SUMS`.

If any command fails, retain the partial directory including
`failure-compose-ps.json`, `failure-compose-logs.txt`,
`failure-compose-down.txt`, and the failing report. Do not replace a failed
run with prose or manually edit structured evidence.

## Pass/fail criteria

One stream passes only when the checkpoint exits zero, reports top-level
`passed`, all preflight requirements and both Compose services pass, the
publisher returns zero for exactly `player_1`, and `player_1` has non-empty
metadata, a non-empty segment, an existing latest segment, and a ready clip.

Four streams pass only when the checkpoint exits zero for exactly all four
stable IDs and the stricter assertion proves every stream independently has a
directory, non-empty `segments.csv`, non-empty transport-stream media, a ready
clip, and segment paths rooted in that stream's own directory. One ready
stream is not sufficient.

Publisher reconnect passes only when two bounded `player_1` publishers
complete with a gap between them, the worker container ID is identical before
and after, the latest segment sequence increases after the second publisher,
and bounded logs show both a `buffer_ffmpeg_exited` event and a later
`buffer_ffmpeg_started` event for `player_1`. Restarting `buffer-worker`
invalidates this case.

RAM-backed storage passes only when `findmnt` reports `tmpfs` for
`/dev/shm/clutchcam`, Docker inspection reports a bind mount from that exact
host path to the same container path, the worker environment uses that path,
and actual segment files are listed below it.

Cleanup passes only when `docker compose down --remove-orphans` succeeds, no
running container remains with the isolated Compose project label, neither
named media/buffer container remains, and the four acceptance stream
directories are removed after their evidence listing is retained.

Any failed assertion, missing evidence file, nonzero publisher/checkpoint
exit, service restart during reconnect, non-tmpfs backing, cross-stream path,
or remaining running project container fails acceptance. After a genuine pass,
record the evidence directory and tested Git revision in the next Tess stage;
the parent integration pass may then update `docs/STATUS.md`,
`docs/ROADMAP.md`, and `docs/runbooks/local-linux-compose.md` with the exact
validated scope and remaining limitations.

## TODO

- Resume only on the external Linux Docker host and run the sequence above.
- Preserve the complete evidence directory and report its absolute retained
  location or durable artifact URL.
- On failure, keep the ticket blocked with the failing criterion and evidence.
- On pass, advance the ticket with the tested revision, evidence location,
  concise results for all five acceptance areas, and documentation changes
  left explicitly to parent integration.
