import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = PROJECT_DIR.parent
COMPOSE_FILE = PROJECT_DIR / "docker-compose.yml"
DOCKERFILE = PROJECT_DIR / "Dockerfile"
ENV_EXAMPLE_FILE = PROJECT_DIR / ".env.example"
README_FILE = PROJECT_DIR / "README.md"
ARCHITECTURE_FILE = REPO_DIR / "docs" / "ARCHITECTURE.md"
LOCAL_LINUX_RUNBOOK_FILE = REPO_DIR / "docs" / "runbooks" / "local-linux-compose.md"


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
    def test_runtime_image_installs_ffmpeg_without_apt_metadata(self) -> None:
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        normalized = " ".join(dockerfile.replace("\\\n", " ").split())

        self.assertIn(
            "RUN apt-get update && DEBIAN_FRONTEND=noninteractive "
            "apt-get install -y --no-install-recommends ffmpeg "
            "&& rm -rf /var/lib/apt/lists/*",
            normalized,
        )

    def test_runtime_services_have_profile_scoped_entrypoints(self) -> None:
        expected_services = {
            "media-server": 'profiles: ["media-server", "local-linux"]',
            "buffer-worker": 'profiles: ["buffer-worker", "local-linux"]',
            "transcription-worker": 'profiles: ["transcription-worker"]',
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
        self.assertNotIn(
            'profiles: ["transcription-worker", "local-linux"]',
            service_block("transcription-worker"),
        )

    def test_runtime_services_define_bounded_healthchecks(self) -> None:
        media_server = service_block("media-server")
        buffer_worker = service_block("buffer-worker")
        transcription_worker = service_block("transcription-worker")
        orchestrator = service_block("orchestrator")

        self.assertIn("healthcheck:", media_server)
        self.assertIn("test -s ./objs/srs.pid", media_server)
        self.assertIn("kill -0", media_server)
        self.assertIn("cat ./objs/srs.pid", media_server)
        self.assertIn(
            'test: ["CMD", "python", "-m", "buffer_worker", "--healthcheck"]',
            buffer_worker,
        )
        self.assertIn(
            'test: ["CMD", "python", "-m", "transcription_worker", "--healthcheck"]',
            transcription_worker,
        )
        self.assertIn(
            'test: ["CMD", "python", "src/main.py", "--healthcheck"]',
            orchestrator,
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
            "TRANSCRIPTION_REQUEST_MODE: ${TRANSCRIPTION_REQUEST_MODE:-json}",
            transcription_worker,
        )
        self.assertIn(
            "TRANSCRIPTION_MODEL: "
            "${TRANSCRIPTION_MODEL:-Systran/faster-whisper-small}",
            transcription_worker,
        )
        self.assertIn(
            "AUDIO_INPUT_URL_PLAYER_1: "
            "${AUDIO_INPUT_URL_PLAYER_1:-rtmp://media-server:1935/live/player_1}",
            transcription_worker,
        )
        self.assertIn(
            "GEMMA_API_URL: ${GEMMA_API_URL:-http://ollama:11434}",
            orchestrator,
        )
        self.assertIn("AI_PROVIDER: ${AI_PROVIDER:-ollama}", orchestrator)
        self.assertIn("GEMMA_API_KEY: ${GEMMA_API_KEY:-}", orchestrator)
        self.assertIn(
            "TRANSCRIPTION_API_URL: "
            "${TRANSCRIPTION_API_URL:-http://host.docker.internal:8000}",
            orchestrator,
        )
        self.assertIn(
            "LIVE_TRANSCRIPTION_ENABLED: ${LIVE_TRANSCRIPTION_ENABLED:-false}",
            orchestrator,
        )
        self.assertIn(
            "LIVE_TRANSCRIPTION_QUEUE_SIZE: ${LIVE_TRANSCRIPTION_QUEUE_SIZE:-16}",
            orchestrator,
        )
        self.assertIn(
            "AUDIO_INPUT_URL_PLAYER_1: "
            "${AUDIO_INPUT_URL_PLAYER_1:-rtmp://media-server:1935/live/player_1}",
            orchestrator,
        )
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

    def test_local_transcription_profile_is_optional_faster_whisper_server(self) -> None:
        compose = read_compose()
        faster_whisper = service_block("faster-whisper")
        transcription_worker = service_block("transcription-worker")

        self.assertIn('profiles: ["local-transcription"]', faster_whisper)
        self.assertNotIn("local-linux", faster_whisper)
        self.assertNotIn("depends_on:", faster_whisper)
        self.assertNotIn("faster-whisper:", transcription_worker)
        self.assertIn(
            "image: ${FASTER_WHISPER_IMAGE:-fedirz/faster-whisper-server:latest-cpu}",
            faster_whisper,
        )
        self.assertIn(
            "${FASTER_WHISPER_BIND_ADDR:-127.0.0.1}:"
            "${FASTER_WHISPER_PORT:-8000}:8000/tcp",
            faster_whisper,
        )
        self.assertIn("UVICORN_HOST: 0.0.0.0", faster_whisper)
        self.assertIn("UVICORN_PORT: 8000", faster_whisper)
        self.assertIn(
            "WHISPER__MODEL: "
            "${FASTER_WHISPER_MODEL:-Systran/faster-whisper-small}",
            faster_whisper,
        )
        self.assertIn(
            "WHISPER__INFERENCE_DEVICE: ${FASTER_WHISPER_DEVICE:-cpu}",
            faster_whisper,
        )
        self.assertIn(
            "WHISPER__COMPUTE_TYPE: ${FASTER_WHISPER_COMPUTE_TYPE:-int8}",
            faster_whisper,
        )
        self.assertIn(
            "${FASTER_WHISPER_CACHE_HOST_DIR:-faster-whisper-cache}:"
            "/root/.cache/huggingface",
            faster_whisper,
        )
        self.assertIn("python3 -c", faster_whisper)
        self.assertIn("socket.create_connection", faster_whisper)
        self.assertIn("faster-whisper-cache:", compose)

    def test_env_example_documents_profiles_and_portable_endpoints(self) -> None:
        env_example = ENV_EXAMPLE_FILE.read_text(encoding="utf-8")
        profiles_line = next(
            line for line in env_example.splitlines() if line.startswith("COMPOSE_PROFILES=")
        )

        self.assertIn("COMPOSE_PROFILES=local-linux,local-ai", env_example)
        self.assertNotIn("local-transcription", profiles_line)
        self.assertNotIn("transcription-worker", profiles_line)
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
        self.assertIn("LIVE_TRANSCRIPTION_ENABLED=false", env_example)
        self.assertIn("LIVE_TRANSCRIPTION_QUEUE_SIZE=16", env_example)
        self.assertIn(
            "# TRANSCRIPTION_API_URL=http://faster-whisper:8000",
            env_example,
        )
        self.assertIn("# TRANSCRIPTION_API_URL=https://stt-gpu.example.internal", env_example)
        self.assertIn(
            "FASTER_WHISPER_IMAGE=fedirz/faster-whisper-server:latest-cpu",
            env_example,
        )
        self.assertIn(
            "# FASTER_WHISPER_IMAGE=fedirz/faster-whisper-server:latest-cuda",
            env_example,
        )
        self.assertIn("FASTER_WHISPER_DEVICE=cpu", env_example)
        self.assertIn("# FASTER_WHISPER_DEVICE=cuda", env_example)
        self.assertIn("FASTER_WHISPER_MODEL=Systran/faster-whisper-small", env_example)
        self.assertIn("FASTER_WHISPER_CACHE_HOST_DIR=faster-whisper-cache", env_example)

    def test_docs_document_transcription_profile_and_endpoint_contracts(self) -> None:
        docs = "\n\n".join(
            path.read_text(encoding="utf-8")
            for path in (README_FILE, ARCHITECTURE_FILE, LOCAL_LINUX_RUNBOOK_FILE)
        )

        self.assertIn("local-transcription", docs)
        self.assertIn("fedirz/faster-whisper-server", docs)
        self.assertIn("<TRANSCRIPTION_API_URL>/transcribe", docs)
        self.assertIn("/v1/audio/transcriptions", docs)


if __name__ == "__main__":
    unittest.main()
