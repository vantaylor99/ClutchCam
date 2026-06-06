description: Completed FFmpeg installation in the shared Python runtime image
prereq: local-linux-compose-profiles
files: ai-stream-director/Dockerfile, ai-stream-director/tests/test_linux_compose_stack.py
----
The shared `python:3.12-slim` runtime image now installs Debian's `ffmpeg`
package before Python dependencies. The noninteractive installation excludes
recommended packages and removes apt lists in the same image layer, so the
Compose workers' default `FFMPEG_EXECUTABLE=ffmpeg` resolves in clean images
without retaining apt metadata.

Automated coverage reads only the Dockerfile and protects the package-layer
contract: `apt-get update`, noninteractive `--no-install-recommends`
installation of `ffmpeg`, and `/var/lib/apt/lists/*` cleanup in one `RUN`
instruction.

Review found no implementation issues. The package command is valid for the
Debian-based `python:3.12-slim` image, cleanup remains in the installation
layer, and the assertion is scoped to the runtime image rather than unrelated
Compose behavior.

Validation:

- `python -B -m unittest tests.test_linux_compose_stack.LinuxComposeStackTests.test_runtime_image_installs_ffmpeg_without_apt_metadata -v`
  passed: 1 test.
- `python -B -m unittest tests.test_linux_compose_stack -v` passed: 9 tests.
- `python -B -m unittest tests.test_runtime_healthcheck_entrypoints -v`
  passed: 11 tests.
- `git diff --check -- ai-stream-director/Dockerfile ai-stream-director/tests/test_linux_compose_stack.py tickets/review/40-docker-runtime-ffmpeg.md`
  passed before the stage transition.
- Runtime image build and in-container `command -v ffmpeg` verification were not
  run because the `docker` command is not installed in the validation
  environment.

Documentation changes were intentionally excluded for parent integration.
