from typing import Optional

import obsws_python as obs


class OBSController:
    def __init__(self, host: str, port: int, password: str):
        self.host = host
        self.port = port
        self.password = password
        self.client: Optional[obs.ReqClient] = None

    def connect(self) -> None:
        self.client = obs.ReqClient(
            host=self.host,
            port=self.port,
            password=self.password,
            timeout=3,
        )
        version = self.client.get_version()
        print(f"Connected to OBS WebSocket. OBS version: {version.obs_version}")

    def set_scene(self, scene_name: str) -> None:
        self._require_client().set_current_program_scene(scene_name)
        print(f"OBS scene switched to: {scene_name}")

    def get_current_scene(self) -> str:
        result = self._require_client().get_current_program_scene()
        return result.current_program_scene_name

    def _require_client(self) -> obs.ReqClient:
        if self.client is None:
            raise RuntimeError("OBS client is not connected.")
        return self.client
