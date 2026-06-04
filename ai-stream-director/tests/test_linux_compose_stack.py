import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
COMPOSE_FILE = PROJECT_DIR / "docker-compose.yml"
ENV_EXAMPLE_FILE = PROJECT_DIR / ".env.example"


def read_compose() -> str:
    return COMPOSE_FILE.read_text(encoding="utf-8")


def service_block(service_name: str) -> str:
    lines = read_compose().splitlines()
    marker = f"  {service_name}:"
    try:
        start = lines.index(marker)
    except ValueError as exc:
        raise AssertionError(f"Missing Compose service: {service_name}") from exc

    block: list[str] = []
    for line in lines[start:]:
        if block and line.startswith("  ") and not line.startswith("    "):
            break
        if block and line and not line.startswith(" "):
            break
        block.append(line)

    return "\n".join(block)


class LinuxComposeStackTests(unittest.TestCase):
    def test_runtime_services_have_profile_scoped_entrypoints(self) -> None:
        expected_services = {
            "media-server": 'profiles: ["media-server", "local-linux"]',
            "buffer-worker": 'profiles: ["buffer-worker", "local-linux"]',
            "transcription-worker": (
                'profiles: ["transcription-worker", "local-linux"]'
            ),
            "orchestrator": 'profiles: ["orchestrator", "local-linux"]',
        }

        for service_name, profile_line in expected_services.items():
            with self.subTest(service_name=service_name):
                self.assertIn(profile_line, service_block(service_name))

        self.assertIn(
            'command: ["python", "-m", "buffer_worker"]',
            service_block("buffer-worker"),
        )
        self.assertIn(
            'command: ["python", "-m", "transcription_worker"]',
            service_block("transcription-worker"),
        )
        self.assertIn(
            'command: ["python", "src/main.py"]',
            service_block("orchestrator"),
        )

    def test_workers_default_to_compose_media_dns_and_not_local_ai(self) -> None:
        buffer_worker = service_block("buffer-worker")
        transcription_worker = service_block("transcription-worker")
        orchestrator = service_block("orchestrator")

        for block in (buffer_worker, transcription_worker):
            self.assertIn("depends_on:\n      media-server:", block)
            self.assertIn(
                "INGEST_API_URL: ${INGEST_API_URL:-rtmp://media-server:1935/live}",
                block,
            )
            self.assertNotIn("ollama", block)
            self.assertNotIn("ollama-pull", block)

        self.assertIn(
            "TRANSCRIPTION_API_URL: "
            "${TRANSCRIPTION_API_URL:-http://host.docker.internal:8000}",
            transcription_worker,
        )
        self.assertIn(
            "GEMMA_API_URL: ${GEMMA_API_URL:-http://ollama:11434}",
            orchestrator,
        )
        self.assertIn("AI_PROVIDER: ${AI_PROVIDER:-ollama}", orchestrator)
        self.assertIn("GEMMA_API_KEY: ${GEMMA_API_KEY:-}", orchestrator)
        self.assertNotIn("depends_on:", orchestrator)
        self.assertNotIn("ollama-pull", orchestrator)

    def test_linux_ram_backed_paths_are_bind_mounts_not_named_volumes(self) -> None:
        compose = read_compose()
        buffer_worker = service_block("buffer-worker")
        transcription_worker = service_block("transcription-worker")
        orchestrator = service_block("orchestrator")

        self.assertIn(
            "source: ${LOOKBACK_BUFFER_HOST_DIR:-/dev/shm/clutchcam}",
            buffer_worker,
        )
        self.assertIn("target: /dev/shm/clutchcam", buffer_worker)
        self.assertIn(
            "source: ${AUDIO_EXTRACT_HOST_DIR:-/dev/shm/clutchcam-audio}",
            transcription_worker,
        )
        self.assertIn("target: /dev/shm/clutchcam-audio", transcription_worker)
        self.assertIn("target: /dev/shm/clutchcam", orchestrator)
        self.assertIn("target: /dev/shm/clutchcam-audio", orchestrator)
        self.assertIn("ollama-data:/root/.ollama", service_block("ollama"))
        self.assertNotIn("clutchcam-data:", compose)
        self.assertNotIn("clutchcam-audio-data:", compose)

    def test_local_ai_profile_is_optional_ollama_only(self) -> None:
        compose = read_compose().lower()
        ollama = service_block("ollama")
        ollama_pull = service_block("ollama-pull")

        self.assertIn('profiles: ["local-ai"]', ollama)
        self.assertIn('profiles: ["local-ai"]', ollama_pull)
        self.assertIn("ollama-data:/root/.ollama", ollama)
        self.assertIn("condition: service_healthy", ollama_pull)
        self.assertIn("GEMMA_MODEL: ${GEMMA_MODEL:-}", ollama_pull)
        self.assertIn("OLLAMA_MODEL: ${OLLAMA_MODEL:-gemma3:4b}", ollama_pull)
        self.assertIn(
            'ollama pull \\"$${GEMMA_MODEL:-$${OLLAMA_MODEL:-gemma3:4b}}\\"',
            ollama_pull,
        )
        self.assertNotIn("faster-whisper:", compose)
        self.assertNotIn("image: faster", compose)

    def test_env_example_documents_profiles_and_portable_endpoints(self) -> None:
        env_example = ENV_EXAMPLE_FILE.read_text(encoding="utf-8")

        self.assertIn(
            "COMPOSE_PROFILES=media-server,buffer-worker,"
            "transcription-worker,orchestrator,local-ai",
            env_example,
        )
        self.assertIn("LOOKBACK_BUFFER_HOST_DIR=/dev/shm/clutchcam", env_example)
        self.assertIn("AUDIO_EXTRACT_HOST_DIR=/dev/shm/clutchcam-audio", env_example)
        self.assertIn("GEMMA_API_URL=http://ollama:11434", env_example)
        self.assertIn("AI_PROVIDER=ollama", env_example)
        self.assertIn("# AI_PROVIDER=openai-compatible", env_example)
        self.assertIn("GEMMA_API_KEY=", env_example)
        self.assertIn("# GEMMA_API_URL=http://host.docker.internal:11434", env_example)
        self.assertIn(
            "TRANSCRIPTION_API_URL=http://host.docker.internal:8000",
            env_example,
        )
        self.assertIn("# TRANSCRIPTION_API_URL=https://stt-gpu.example.internal", env_example)
        self.assertNotIn("TRANSCRIPTION_API_URL=http://faster-whisper:8000", env_example)


if __name__ == "__main__":
    unittest.main()
