import logging
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from services.buffer import FFmpegRollingLookbackBuffer, RollingBufferConfig  # noqa: E402


class _FakeProcess:
    _next_pid = 1000

    def __init__(
        self,
        poll_results: tuple[int | None, ...] = (None,),
        *,
        exit_after_seconds: float | None = None,
        exit_code: int = 1,
    ) -> None:
        self.pid = self._next_pid
        type(self)._next_pid += 1
        self._poll_results = list(poll_results)
        self._last_poll_result: int | None = None
        self._exit_after_seconds = exit_after_seconds
        self._exit_code = exit_code
        self._started_at: float | None = None
        self._lock = threading.Lock()
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        with self._lock:
            if self._started_at is None:
                self._started_at = time.monotonic()
            if self.terminated or self.killed:
                return 0
            if (
                self._exit_after_seconds is not None
                and time.monotonic() - self._started_at >= self._exit_after_seconds
            ):
                self._last_poll_result = self._exit_code
                return self._last_poll_result
            if self._poll_results:
                self._last_poll_result = self._poll_results.pop(0)
            return self._last_poll_result

    def terminate(self) -> None:
        with self._lock:
            self.terminated = True

    def kill(self) -> None:
        with self._lock:
            self.killed = True

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return self.poll() or 0


class _StubbornProcess(_FakeProcess):
    def __init__(self, terminate_error: OSError) -> None:
        super().__init__()
        self._terminate_error = terminate_error

    def terminate(self) -> None:
        raise self._terminate_error

    def wait(self, timeout: float | None = None) -> int:
        if not self.killed:
            raise subprocess.TimeoutExpired("ffmpeg", timeout)
        return 0


class BufferSupervisionTests(unittest.TestCase):
    def test_repeated_start_is_an_idempotent_no_op(self) -> None:
        process = _FakeProcess()
        launches = 0

        def process_factory(*args, **kwargs):
            nonlocal launches
            del args, kwargs
            launches += 1
            return process

        with tempfile.TemporaryDirectory() as temp_dir:
            buffer = self._buffer(temp_dir, process_factory=process_factory)
            buffer.start()
            try:
                self.assertTrue(_wait_until(lambda: launches == 1))
                with patch(
                    "services.buffer._assert_writable",
                    side_effect=AssertionError("start performed setup twice"),
                ):
                    buffer.start()
            finally:
                buffer.stop()

        self.assertEqual(launches, 1)

    def test_stop_serializes_with_an_in_progress_start(self) -> None:
        supervisor_start_entered = threading.Event()
        release_supervisor_start = threading.Event()
        stop_attempted = threading.Event()
        stop_returned = threading.Event()
        original_thread = threading.Thread

        class DelayedStartThread:
            def __init__(self, *, target, args, name) -> None:
                self._thread = original_thread(target=target, args=args, name=name)

            @property
            def ident(self):
                return self._thread.ident

            def start(self) -> None:
                supervisor_start_entered.set()
                release_supervisor_start.wait()
                self._thread.start()

            def join(self) -> None:
                self._thread.join()

        with tempfile.TemporaryDirectory() as temp_dir:
            buffer = self._buffer(
                temp_dir,
                process_factory=lambda *args, **kwargs: _FakeProcess(),
            )
            start_thread = original_thread(target=buffer.start)

            def stop_buffer() -> None:
                stop_attempted.set()
                buffer.stop()
                stop_returned.set()

            stop_thread = original_thread(target=stop_buffer)
            with patch("services.buffer.threading.Thread", DelayedStartThread):
                start_thread.start()
                self.assertTrue(supervisor_start_entered.wait(0.5))
                stop_thread.start()
                self.assertTrue(stop_attempted.wait(0.5))
                try:
                    self.assertFalse(stop_returned.wait(0.1))
                finally:
                    release_supervisor_start.set()
                    start_thread.join()
                    stop_thread.join()

            self.assertTrue(stop_returned.is_set())
            self.assertFalse(buffer._started)
            self.assertEqual(buffer._supervisors, {})
            self.assertEqual(buffer._processes, {})

    def test_restarts_child_that_exits_after_initial_startup_probe(self) -> None:
        first_process = _FakeProcess((None, 1))
        replacement_process = _FakeProcess()
        processes = iter((first_process, replacement_process))
        launches = 0
        launch_lock = threading.Lock()

        def process_factory(*args, **kwargs):
            nonlocal launches
            del args, kwargs
            with launch_lock:
                launches += 1
                return next(processes)

        with tempfile.TemporaryDirectory() as temp_dir:
            buffer = self._buffer(temp_dir, process_factory=process_factory)
            buffer.start()
            try:
                self.assertTrue(_wait_until(lambda: launches == 2))
            finally:
                buffer.stop()

        self.assertTrue(replacement_process.terminated)

    def test_launch_failure_retries_and_logs_without_input_url(self) -> None:
        input_url = "rtmp://user:secret@localhost/live/player_1"
        replacement_process = _FakeProcess()
        launches = 0
        launch_lock = threading.Lock()

        def process_factory(*args, **kwargs):
            nonlocal launches
            del args, kwargs
            with launch_lock:
                launches += 1
                if launches == 1:
                    raise OSError(f"connection refused for {input_url}")
                return replacement_process

        with tempfile.TemporaryDirectory() as temp_dir:
            buffer = self._buffer(
                temp_dir,
                process_factory=process_factory,
                input_urls={"player_1": input_url},
            )
            with self.assertLogs("services.buffer", level="WARNING") as logs:
                buffer.start()
                try:
                    self.assertTrue(_wait_until(lambda: launches == 2))
                finally:
                    buffer.stop()

        diagnostic = "\n".join(logs.output)
        self.assertIn("buffer_ffmpeg_launch_failed", diagnostic)
        self.assertIn("stream=player_1", diagnostic)
        self.assertIn("consecutive_failures=1", diagnostic)
        self.assertIn("restart_delay_seconds=0.010", diagnostic)
        self.assertIn("<redacted-input-url>", diagnostic)
        self.assertNotIn(input_url, diagnostic)

    def test_repeated_failures_use_capped_backoff(self) -> None:
        launch_times: list[float] = []
        launch_lock = threading.Lock()

        def process_factory(*args, **kwargs):
            del args, kwargs
            with launch_lock:
                launch_times.append(time.monotonic())
            return _FakeProcess((1,))

        with tempfile.TemporaryDirectory() as temp_dir:
            buffer = self._buffer(
                temp_dir,
                process_factory=process_factory,
                restart_backoff_initial_seconds=0.02,
                restart_backoff_max_seconds=0.04,
            )
            buffer.start()
            try:
                self.assertTrue(_wait_until(lambda: len(launch_times) >= 4))
            finally:
                buffer.stop()

        intervals = [
            later - earlier
            for earlier, later in zip(launch_times, launch_times[1:])
        ]
        self.assertGreaterEqual(intervals[0], 0.015)
        self.assertGreaterEqual(intervals[1], 0.03)
        self.assertGreaterEqual(intervals[2], 0.03)
        self.assertEqual(buffer._restart_delay(1_000_000), 0.04)

    def test_stream_failure_does_not_restart_healthy_stream(self) -> None:
        failed_process = _FakeProcess((1,))
        recovered_process = _FakeProcess()
        healthy_process = _FakeProcess()
        launches = {"player_1": 0, "player_2": 0}
        launch_lock = threading.Lock()

        def process_factory(command, **kwargs):
            del kwargs
            input_url = command[command.index("-i") + 1]
            stream_id = "player_1" if input_url.endswith("player_1") else "player_2"
            with launch_lock:
                launches[stream_id] += 1
                if stream_id == "player_1":
                    if launches[stream_id] == 1:
                        return failed_process
                    return recovered_process
                return healthy_process

        with tempfile.TemporaryDirectory() as temp_dir:
            buffer = self._buffer(
                temp_dir,
                process_factory=process_factory,
                input_urls={
                    "player_1": "rtmp://localhost/live/player_1",
                    "player_2": "rtmp://localhost/live/player_2",
                },
            )
            buffer.start()
            try:
                self.assertTrue(_wait_until(lambda: launches["player_1"] == 2))
                self.assertTrue(_wait_until(lambda: launches["player_2"] == 1))
                time.sleep(0.03)
                self.assertEqual(launches["player_2"], 1)
                self.assertFalse(healthy_process.terminated)
            finally:
                buffer.stop()

        self.assertTrue(healthy_process.terminated)
        self.assertTrue(recovered_process.terminated)

    def test_stable_runtime_resets_consecutive_failure_backoff(self) -> None:
        processes = iter(
            (
                _FakeProcess((1,)),
                _FakeProcess(exit_after_seconds=0.04),
                _FakeProcess((1,)),
                _FakeProcess(),
            )
        )
        launches = 0
        launch_lock = threading.Lock()

        def process_factory(*args, **kwargs):
            nonlocal launches
            del args, kwargs
            with launch_lock:
                launches += 1
                return next(processes)

        with tempfile.TemporaryDirectory() as temp_dir:
            buffer = self._buffer(
                temp_dir,
                process_factory=process_factory,
                restart_stable_seconds=0.03,
            )
            with self.assertLogs("services.buffer", level="WARNING") as logs:
                buffer.start()
                try:
                    self.assertTrue(_wait_until(lambda: launches == 4))
                finally:
                    buffer.stop()

        exit_logs = [
            message
            for message in logs.output
            if "buffer_ffmpeg_exited" in message
        ]
        self.assertEqual(len(exit_logs), 3)
        self.assertIn("pid=", exit_logs[0])
        self.assertIn("restart_delay_seconds=0.010", exit_logs[0])
        self.assertIn("restart_delay_seconds=0.010", exit_logs[1])
        self.assertIn("restart_delay_seconds=0.020", exit_logs[2])

    def test_launch_latency_does_not_count_toward_stable_runtime(self) -> None:
        now = 0.0
        processes = iter(
            (
                _FakeProcess((1,)),
                _FakeProcess((1,)),
                _FakeProcess(),
            )
        )
        launches = 0

        def process_factory(*args, **kwargs):
            nonlocal launches, now
            del args, kwargs
            launches += 1
            if launches == 2:
                now += 31.0
            return next(processes)

        with tempfile.TemporaryDirectory() as temp_dir:
            buffer = self._buffer(
                temp_dir,
                process_factory=process_factory,
                restart_stable_seconds=30.0,
                clock=lambda: now,
            )
            with self.assertLogs("services.buffer", level="WARNING") as logs:
                buffer.start()
                try:
                    self.assertTrue(_wait_until(lambda: launches == 3))
                finally:
                    buffer.stop()

        exit_logs = [
            message
            for message in logs.output
            if "buffer_ffmpeg_exited" in message
        ]
        self.assertEqual(len(exit_logs), 2)
        self.assertIn("restart_delay_seconds=0.010", exit_logs[0])
        self.assertIn("restart_delay_seconds=0.020", exit_logs[1])

    def test_shutdown_kills_stubborn_child_and_redacts_process_errors(self) -> None:
        input_url = "rtmp://user:secret@localhost/live/player_1"
        process = _StubbornProcess(
            OSError(f"terminate failed for {input_url}")
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            buffer = self._buffer(
                temp_dir,
                process_factory=lambda *args, **kwargs: process,
                input_urls={"player_1": input_url},
            )
            with self.assertLogs("services.buffer", level="WARNING") as logs:
                buffer.start()
                self.assertTrue(_wait_until(lambda: process._started_at is not None))
                buffer.stop()

        diagnostic = "\n".join(logs.output)
        self.assertTrue(process.killed)
        self.assertIn("buffer_ffmpeg_terminate_failed", diagnostic)
        self.assertIn("<redacted-input-url>", diagnostic)
        self.assertNotIn(input_url, diagnostic)

    def test_shutdown_interrupts_pending_restart_backoff(self) -> None:
        attempted = threading.Event()
        launches = 0

        def process_factory(*args, **kwargs):
            nonlocal launches
            del args, kwargs
            launches += 1
            attempted.set()
            raise OSError("input unavailable")

        with tempfile.TemporaryDirectory() as temp_dir:
            buffer = self._buffer(
                temp_dir,
                process_factory=process_factory,
                restart_backoff_initial_seconds=5.0,
                restart_backoff_max_seconds=5.0,
            )
            buffer.start()
            self.assertTrue(attempted.wait(0.5))

            started_at = time.monotonic()
            buffer.stop()
            shutdown_seconds = time.monotonic() - started_at

        self.assertLess(shutdown_seconds, 1.0)
        self.assertEqual(launches, 1)

    def _buffer(
        self,
        buffer_root: str,
        *,
        process_factory,
        input_urls: dict[str, str] | None = None,
        restart_backoff_initial_seconds: float = 0.01,
        restart_backoff_max_seconds: float = 0.04,
        restart_stable_seconds: float = 1.0,
        clock=time.monotonic,
    ) -> FFmpegRollingLookbackBuffer:
        urls = input_urls or {
            "player_1": "rtmp://localhost/live/player_1",
        }
        config = RollingBufferConfig(
            buffer_root=buffer_root,
            stream_input_urls=urls,
            stream_ids=tuple(urls),
        )
        return FFmpegRollingLookbackBuffer(
            config,
            process_factory=process_factory,
            logger=logging.getLogger("services.buffer"),
            supervision_poll_seconds=0.005,
            restart_backoff_initial_seconds=restart_backoff_initial_seconds,
            restart_backoff_max_seconds=restart_backoff_max_seconds,
            restart_stable_seconds=restart_stable_seconds,
            termination_timeout_seconds=0.05,
            clock=clock,
        )


def _wait_until(predicate, timeout_seconds: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


if __name__ == "__main__":
    unittest.main()
