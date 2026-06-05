import importlib
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlparse


class OBSController:
    def __init__(self, host: str, port: int, password: str, log=print):
        self.host = host
        self.port = port
        self.password = password
        self.client: Optional[Any] = None
        self._log = log

    def connect(self) -> None:
        obs = _load_obs_module()
        self.client = obs.ReqClient(
            host=self.host,
            port=self.port,
            password=self.password,
            timeout=3,
        )
        version = self.client.get_version()
        self._log(f"Connected to OBS WebSocket. OBS version: {version.obs_version}")

    def set_scene(self, scene_name: str) -> None:
        self._require_client().set_current_program_scene(scene_name)
        self._log(f"OBS scene switched to: {scene_name}")

    def set_media_source(self, source_name: str, media_uri: str) -> None:
        settings = _media_source_settings(media_uri)
        client = self._require_client()
        client.set_input_settings(
            input_name=source_name,
            input_settings=settings,
            overlay=True,
        )
        response = client.get_input_settings(input_name=source_name)
        applied_settings = _input_settings(response)
        if applied_settings is None:
            raise RuntimeError("OBS media source settings could not be read back.")
        _verify_media_source_settings(applied_settings, media_uri)
        self._log(f"OBS media source {source_name} set to: {media_uri}")

    def list_scenes(self) -> list[str]:
        result = self._require_client().get_scene_list()
        return [_scene_name(scene) for scene in result.scenes]

    def get_current_scene(self) -> str:
        result = self._require_client().get_current_program_scene()
        return result.current_program_scene_name

    def _require_client(self) -> Any:
        if self.client is None:
            raise RuntimeError("OBS client is not connected.")
        return self.client


def _load_obs_module() -> Any:
    try:
        return importlib.import_module("obsws_python")
    except ModuleNotFoundError as exc:
        if exc.name == "obsws_python":
            raise RuntimeError(
                "obsws-python is required for real OBS mode. "
                "Install ai-stream-director requirements, or set "
                "DRY_RUN_OBS=true to run without OBS WebSocket."
            ) from exc
        raise


def _scene_name(scene) -> str:
    if isinstance(scene, dict):
        return str(scene.get("sceneName", ""))

    scene_name = getattr(scene, "sceneName", None)
    if scene_name is not None:
        return str(scene_name)

    return str(getattr(scene, "scene_name", ""))


def _media_source_settings(media_uri: str) -> dict[str, Any]:
    parsed = urlparse(media_uri)
    if parsed.scheme == "file":
        return {
            "is_local_file": True,
            "local_file": _local_path_from_file_uri(media_uri),
            "restart_on_activate": True,
        }

    return {
        "is_local_file": False,
        "input": media_uri,
        "restart_on_activate": True,
    }


def _local_path_from_file_uri(media_uri: str) -> str:
    parsed = urlparse(media_uri)
    path = unquote(parsed.path)
    if parsed.netloc:
        path = f"//{parsed.netloc}{path}"
    if len(path) >= 3 and path[0] == "/" and path[2] == ":":
        path = path[1:]
    return str(Path(path))


def _input_settings(response: Any) -> dict[str, Any] | None:
    if response is None:
        return None
    if isinstance(response, dict):
        settings = response.get("inputSettings") or response.get("input_settings")
        return settings if isinstance(settings, dict) else None

    settings = getattr(response, "inputSettings", None)
    if isinstance(settings, dict):
        return settings

    settings = getattr(response, "input_settings", None)
    return settings if isinstance(settings, dict) else None


def _verify_media_source_settings(
    applied_settings: dict[str, Any],
    media_uri: str,
) -> None:
    expected_settings = _media_source_settings(media_uri)
    for key in ("is_local_file", "local_file", "input"):
        if key in expected_settings and applied_settings.get(key) != expected_settings[key]:
            raise RuntimeError(
                "OBS media source settings did not match the requested media URI."
            )


class DryRunOBSController:
    def __init__(self, initial_scene: str, log=print):
        self.current_scene = initial_scene
        self.connected = False
        self._log = log

    def connect(self) -> None:
        self.connected = True
        self._log("DRY_RUN_OBS enabled. Skipping OBS WebSocket connection.")
        self._log(f"[DRY RUN OBS] Starting scene: {self.current_scene}")

    def set_scene(self, scene_name: str) -> None:
        self._require_connection()
        self.current_scene = scene_name
        self._log(f"[DRY RUN OBS] Scene switch: {scene_name}")

    def set_media_source(self, source_name: str, media_uri: str) -> None:
        self._require_connection()
        self._log(f"[DRY RUN OBS] Media source {source_name} set to: {media_uri}")

    def get_current_scene(self) -> str:
        self._require_connection()
        return self.current_scene

    def _require_connection(self) -> None:
        if not self.connected:
            raise RuntimeError("Dry-run OBS controller is not connected.")
