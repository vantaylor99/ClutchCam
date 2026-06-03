description: Completed review of OBS connection and required scene-name validation at startup
prereq: local-smoke-test-mode
files: ai-stream-director/src/obs_controller.py, ai-stream-director/src/main.py, ai-stream-director/tests/test_dry_run_obs.py, ai-stream-director/README.md, ai-stream-director/src/config.py
----
## Summary

Startup connects to OBS (when `DRY_RUN_OBS` is false), calls `OBSController.list_scenes()` (`GetSceneList` via `obsws-python`), compares names to `config.SCENES.values()`, prints each missing required scene, and exits with status 1 before `SceneScheduler.start()`. Dry-run mode uses `DryRunOBSController` and never calls `list_scenes()`.

## Review findings

- **`list_scenes()` vs obsws-python 1.7.2:** `ReqClient.get_scene_list()` returns `as_dataclass("GetSceneList", responseData)`, so the response has a `.scenes` attribute (top-level keys are snake_cased; nested scene entries stay as OBS JSON shapes, typically dicts with `sceneName`). `_scene_name()` supports dict `sceneName`, attribute `sceneName`, and fallback `scene_name`.
- **Error messaging:** Missing scenes print under `OBS is missing required scenes:` with bullet lines and a short fix hint (`Create or rename the OBS scenes so they match exactly.`). Connection failures keep the separate WebSocket / `.env` guidance.
- **Dry-run:** `main.py` only runs `find_missing_scenes` when `not config.dry_run_obs`; `DryRunOBSController` has no `list_scenes` method and is never asked to list scenes.
- **Tests:** `test_dry_run_obs.py` covers dict-shaped `get_scene_list` results, `find_missing_scenes` order (missing `player_1` and `player_3` when only those are absent), and the all-present empty list case.

## Validation

- Installed `ai-stream-director/requirements.txt` and ran:

```powershell
py -3 -m unittest discover -s C:\ClutchCam\ai-stream-director\tests -v
```

- Result: **17 tests**, all **OK** (including `test_dry_run_obs` and `test_ai_director`).

## Usage

Ensure OBS defines the five scene names documented in `ai-stream-director/README.md` (exact strings). For local runs without OBS, set `DRY_RUN_OBS=true` to skip WebSocket connection and scene validation.
