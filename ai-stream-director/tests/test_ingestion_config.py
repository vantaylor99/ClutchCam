import sys
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"
sys.path.insert(0, str(SRC_DIR))

from config import STREAM_IDS  # noqa: E402
from services.ingestion import (  # noqa: E402
    build_configured_sources,
    build_rtmp_stream_url,
    build_srt_publish_url,
    build_srt_request_url,
)


class IngestionSourceConfigTests(unittest.TestCase):
    def test_builds_worker_facing_rtmp_sources_for_compose_media_server(self) -> None:
        sources = build_configured_sources("rtmp://media-server:1935/live")

        self.assertEqual([source.stream_id for source in sources], list(STREAM_IDS))
        self.assertEqual(
            [source.ingest_url for source in sources],
            [
                "rtmp://media-server:1935/live/player_1",
                "rtmp://media-server:1935/live/player_2",
                "rtmp://media-server:1935/live/player_3",
                "rtmp://media-server:1935/live/player_4",
            ],
        )

    def test_rtmp_helper_trims_trailing_base_slash(self) -> None:
        self.assertEqual(
            build_rtmp_stream_url("rtmp://media-server:1935/live/", "player_1"),
            "rtmp://media-server:1935/live/player_1",
        )

    def test_srt_helpers_preserve_explicit_streamid_modes(self) -> None:
        self.assertEqual(
            build_srt_publish_url("127.0.0.1", 10080, "player_1"),
            "srt://127.0.0.1:10080?streamid=#!::r=live/player_1,m=publish",
        )
        self.assertEqual(
            build_srt_request_url("media-server", "10080", "player_1"),
            "srt://media-server:10080?streamid=#!::r=live/player_1,m=request",
        )

    def test_srt_helper_brackets_ipv6_hosts(self) -> None:
        self.assertEqual(
            build_srt_publish_url("::1", 10080, "player_2"),
            "srt://[::1]:10080?streamid=#!::r=live/player_2,m=publish",
        )


class IngestionComposeConfigTests(unittest.TestCase):
    def test_compose_defines_srs_media_server_surface(self) -> None:
        compose = (PROJECT_DIR / "docker-compose.yml").read_text()

        self.assertIn("media-server:", compose)
        self.assertIn("image: ${SRS_IMAGE:-ossrs/srs:6}", compose)
        self.assertIn(
            "${SRS_BIND_ADDR:-127.0.0.1}:${SRS_RTMP_PORT:-1935}:1935/tcp",
            compose,
        )
        self.assertIn(
            "${SRS_BIND_ADDR:-127.0.0.1}:${SRS_SRT_PORT:-10080}:10080/udp",
            compose,
        )
        self.assertIn(
            "./infra/srs.conf:/usr/local/srs/conf/clutchcam.conf:ro",
            compose,
        )
        self.assertIn(
            "INGEST_API_URL: ${INGEST_API_URL:-rtmp://media-server:1935/live}",
            compose,
        )

    def test_srs_config_enables_rtmp_srt_api_and_http_streaming(self) -> None:
        config = (PROJECT_DIR / "infra" / "srs.conf").read_text()

        self.assertIn("listen 1935;", config)
        self.assertIn("http_api", config)
        self.assertIn("listen 1985;", config)
        self.assertIn("http_server", config)
        self.assertIn("listen 8080;", config)
        self.assertIn("srt_server", config)
        self.assertIn("listen 10080;", config)
        self.assertIn("srt_to_rtmp on;", config)
        self.assertIn("http_remux", config)

    def test_env_example_documents_local_srs_bind_and_ports(self) -> None:
        env_example = (PROJECT_DIR / ".env.example").read_text()

        self.assertIn("INGEST_API_URL=rtmp://media-server:1935/live", env_example)
        self.assertIn("SRS_IMAGE=ossrs/srs:6", env_example)
        self.assertIn("SRS_BIND_ADDR=127.0.0.1", env_example)
        self.assertIn("SRS_RTMP_PORT=1935", env_example)
        self.assertIn("SRS_SRT_PORT=10080", env_example)

    def test_ollama_pull_prefers_configured_gemma_model(self) -> None:
        compose = (PROJECT_DIR / "docker-compose.yml").read_text()

        self.assertIn("GEMMA_MODEL: ${GEMMA_MODEL:-}", compose)
        self.assertIn("OLLAMA_MODEL: ${OLLAMA_MODEL:-gemma3:4b}", compose)
        self.assertIn(
            'ollama pull \\"$${GEMMA_MODEL:-$${OLLAMA_MODEL:-gemma3:4b}}\\"',
            compose,
        )


if __name__ == "__main__":
    unittest.main()
