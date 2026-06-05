description: Add OBS adapter for resolved buffered media playback
prereq: buffered-switcher-playback
files: ai-stream-director/src/obs_controller.py, ai-stream-director/src/services/switcher.py, ai-stream-director/tests/test_dry_run_obs.py, ai-stream-director/tests/test_buffered_switcher.py, docs/ARCHITECTURE.md, ai-stream-director/README.md
----
The buffer-backed switcher can now resolve a ready media URI, but OBS still only
receives immediate scene changes. Production buffered playback needs an
OBS-specific adapter that consumes a ready `SwitcherTarget.media_uri`.

Expected behavior:

- Configure or update a known OBS media source with the resolved clip URI.
- Preload or verify the media source is playable before cutting program output.
- Preserve manual override, cooldown, focus duration, and return-to-quad rules.
- Keep dry-run behavior available without OBS WebSocket.
- Cover OBS WebSocket calls with mocks; do not require live OBS in unit tests.

TODO:

- Add an OBS media-source switcher/adapter that accepts ready `SwitcherTarget`
  values with `media_uri`.
- Keep the existing scene-only controller behavior intact for manual and dry-run
  paths.
- Add dry-run or mock-controller coverage for media-source update calls.
- Reject buffered targets without `media_uri` clearly.
- Document the OBS source names/settings an operator must create for buffered
  playback.
