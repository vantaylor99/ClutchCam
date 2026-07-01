# Real OBS Connection Checkpoint

Use this runbook for the first real-OBS checkpoint: prove that ClutchCam can
reach an actual OBS WebSocket endpoint, see the expected scenes, and avoid any
unexpected scene change before live switching is allowed.

This checkpoint is connection-only. Keep these out of scope for the pass:

- real stream ingest;
- live transcription;
- AI-driven scene switching.

## When To Use It

Use this runbook when you need a repeatable operator checklist for one of
these shapes:

- direct local Python talking to OBS on the same machine;
- Docker or Compose talking to OBS on the host machine;
- a Linux server talking to OBS on a separate LAN machine.

Run the same preflight from the same runtime shape that will later run the
orchestrator:

```bash
python scripts/smoke_obs_connection.py
```

The preflight must be non-destructive. It should report reachability, the OBS
version, the current program scene, the visible scene list, and any missing
required scenes without switching scenes or mutating media sources.

## Safe Settings

Set the OBS WebSocket values directly in `.env` or the environment that will
launch the app:

```text
OBS_HOST=<reachable-obs-host>
OBS_PORT=4455
OBS_PASSWORD=<obs-websocket-password>
DRY_RUN_OBS=false
```

Choose the host value that the runtime can actually reach:

- `127.0.0.1` when the app runs directly on the same machine as OBS;
- `host.docker.internal` when Docker Desktop on Windows or macOS needs to
  reach OBS on the host machine;
- a host LAN IP or DNS name when a Linux container or Linux server needs to
  reach OBS on the host or another machine.

Do not use `127.0.0.1` from inside a container unless OBS is also inside that
same container namespace. From a container, `127.0.0.1` points back to the
container itself.

Keep the OBS WebSocket password in a local secret store or uncommitted `.env`
file. The password should be redacted from tickets, runbook evidence, and
screen recordings.

## Required OBS Scene Set

Create these scenes manually in OBS, with exact names:

- `Quad View`
- `Player 1 Fullscreen`
- `Player 2 Fullscreen`
- `Player 3 Fullscreen`
- `Player 4 Fullscreen`

The preflight should treat missing or misspelled names as a failure. The scene
set is the same for every deployment shape.

## Deployment Shapes

### Direct Local Python

Use this when Python runs on the same machine as OBS.

```text
OBS_HOST=127.0.0.1
OBS_PORT=4455
OBS_PASSWORD=<local-password>
```

Check that the port is listening before you run the preflight:

```powershell
Test-NetConnection 127.0.0.1 -Port 4455
```

On Linux, an equivalent check is:

```bash
ss -ltn '( sport = :4455 )'
```

### Docker Or Compose To Host OBS

Use this when the app runs in a container but OBS runs on the host machine.
On Docker Desktop, `host.docker.internal` is the preferred host name. On Linux,
use a host address that the container can actually reach, such as the host LAN
IP or an explicit host-gateway alias.

```text
OBS_HOST=host.docker.internal
OBS_PORT=4455
OBS_PASSWORD=<host-password>
```

If the host firewall blocks the port, the preflight should fail before any
scene logic runs. Keep the port open only to the machines that need OBS access.

### Linux Server To LAN OBS

Use this when the app runs on a Linux host and OBS runs on a different machine
on the same LAN.

```text
OBS_HOST=<lan-ip-or-dns-name>
OBS_PORT=4455
OBS_PASSWORD=<lan-password>
```

Open TCP `4455` only on the network path between the runtime machine and the
OBS machine. Do not expose the WebSocket port broadly unless the event network
design explicitly calls for it.

## Repeatable Checklist

Use the same steps each time so the evidence stays comparable:

1. Record the branch or commit under test.
2. Record the runtime shape: direct Python, Docker or Compose, or Linux-to-LAN.
3. Confirm OBS is open on the target machine and note the OBS version.
4. Record the current scene before the check.
5. Run `python scripts/smoke_obs_connection.py` from `ai-stream-director/`.
6. Save the preflight output exactly as printed, with the password redacted.
7. Confirm the scene did not change during the preflight.
8. If you run the full orchestrator afterward, keep real ingest, live
   transcription, and AI switching disabled for this checkpoint and note
   whether startup or shutdown changed the scene unexpectedly. If the
   orchestrator is allowed to start with real OBS, a switch to the configured
   default scene on startup is expected; any extra scene change is not.
9. Record the current scene after the check.

### Acceptance Evidence

Capture the following in the ticket or handoff:

- branch or commit under test;
- machine name and runtime shape;
- OBS WebSocket host and port, with the password redacted;
- OBS version reported by WebSocket;
- current scene before and after the check;
- full required scene list and whether each one was found;
- non-destructive preflight output;
- optional app startup, status, and quit output if you exercised the full
  orchestrator after the preflight, including whether startup landed on the
  configured default scene.

## Pass Or Fail

Pass when OBS is reachable, credentials work, all required scenes exist, and no
unexpected OBS state changes occurred.

Fail when OBS is unreachable, the password is wrong, the host value cannot be
reached from the runtime shape, the firewall blocks the port, or one or more
required scenes are missing.

## Related Docs

- [Operator runbooks](README.md)
- [Local Linux Compose runbook](local-linux-compose.md)
- [AI Stream Director README](../../ai-stream-director/README.md)
