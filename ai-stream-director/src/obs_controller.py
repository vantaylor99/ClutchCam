import importlib
from typing import Any, Optional


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

    def get_current_scene(self) -> str:
        self._require_connection()
        return self.current_scene

    def _require_connection(self) -> None:
        if not self.connected:
            raise RuntimeError("Dry-run OBS controller is not connected.")
