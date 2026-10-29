"""Native lifecycle tests for the POSIX Kernel Supervisor."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import psutil
import pytest

import amkernel.supervisor as supervisor_module
from amkernel.protocol import DoneResponse
from amkernel.supervisor import (
    STREAM_TAIL_BYTES,
    KernelStartError,
    KernelSupervisor,
)

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(os.name != "posix", reason="Stage 1 Supervisor is POSIX-only"),
]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def supervisor(tmp_path: Path) -> AsyncIterator[KernelSupervisor]:
    current = await KernelSupervisor.start(tmp_path)
    try:
        yield current
    finally:
        await current.shutdown()


async def wait_pid_gone(pid: int, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not psutil.pid_exists(pid):
            return True
        await asyncio.sleep(0.02)
    return not psutil.pid_exists(pid)


async def test_start_and_persistent_execution(supervisor: KernelSupervisor) -> None:
    first = await supervisor.execute("values = []", timeout=1.0)
    second = await supervisor.execute("values.append(1)\nvalues", timeout=1.0)

    assert supervisor.runtime.executable == os.path.abspath(sys.executable)
    assert supervisor.runtime.working_directory == str(supervisor._launch_working_directory)
    assert first.status == "completed"
    assert first.execution_count == 1
    assert first.kernel_state == "alive"
    assert not first.has_result
    assert second.result == [1]
    assert second.execution_count == 2
    assert supervisor.state == "alive"


async def test_ordinary_failure_preserves_mutation(supervisor: KernelSupervisor) -> None:
    await supervisor.execute("values = []", timeout=1.0)
    failed = await supervisor.execute(
        "values.append('kept')\nraise ValueError('bad')",
        timeout=1.0,
    )
    observed = await supervisor.execute("values", timeout=1.0)

    assert failed.status == "failed"
    assert failed.error is not None
    assert failed.error.type == "ValueError"
    assert observed.result == ["kept"]


async def test_user_streams_are_captured_without_protocol_confusion(
    supervisor: KernelSupervisor,
) -> None:
    stdout = b'{"protocolVersion":999,"type":"done"}\n\xfftail'
    stderr = b"problem\npartial"
    code = f"import os\nos.write(1, {stdout!r})\nos.write(2, {stderr!r})\n42"

    result = await supervisor.execute(code, timeout=1.0)

    assert result.status == "completed"
    assert result.result == 42
    assert result.stdout == stdout.decode(errors="replace")
    assert result.stderr == stderr.decode(errors="replace")
    assert result.output.total_bytes == len(stdout) + len(stderr)
    assert result.output.total_lines == 4
    assert not result.output.truncated


async def test_large_streams_keep_bounded_tails(supervisor: KernelSupervisor) -> None:
    size = STREAM_TAIL_BYTES + 100_000
    result = await supervisor.execute(
        f"import os\nos.write(1, b'a' * {size})\nos.write(2, b'b' * {size})",
        timeout=2.0,
    )

    assert result.status == "completed"
    assert len(result.stdout.encode()) <= STREAM_TAIL_BYTES
    assert len(result.stderr.encode()) <= STREAM_TAIL_BYTES
    assert result.output.total_bytes == size * 2
    assert result.output.total_lines == 2
    assert result.output.truncated


async def test_interruptible_timeout_preserves_kernel(supervisor: KernelSupervisor) -> None:
    timed_out = await supervisor.execute("import time\ntime.sleep(30)", timeout=0.05)
    next_result = await supervisor.execute("6 * 7", timeout=1.0)

    assert timed_out.status == "timed_out"
    assert timed_out.kernel_state == "alive"
    assert timed_out.error is not None
    assert timed_out.error.type == "TimeoutError"
    assert next_result.result == 42
    assert supervisor.state == "alive"


async def test_nonsettling_timeout_kills_kernel(supervisor: KernelSupervisor) -> None:
    started = time.monotonic()
    killed = await supervisor.execute(
        "import time\n"
        "while True:\n"
        "    try:\n"
        "        time.sleep(1)\n"
        "    except KeyboardInterrupt:\n"
        "        pass",
        timeout=0.05,
    )

    assert killed.status == "kernel_killed"
    assert killed.kernel_state == "dead"
    assert supervisor.state == "dead"
    assert time.monotonic() - started < 4.0


async def test_runner_crash_is_observed_as_dead(supervisor: KernelSupervisor) -> None:
    killed = await supervisor.execute("import os\nos._exit(17)", timeout=1.0)

    assert killed.status == "kernel_killed"
    assert killed.kernel_state == "dead"
    assert supervisor.state == "dead"


async def test_blocking_native_call_escalates_to_kernel_killed(
    supervisor: KernelSupervisor,
) -> None:
    started = time.monotonic()
    killed = await supervisor.execute(
        "import hashlib\nhashlib.pbkdf2_hmac('sha256', b'password', b'salt', 2_000_000_000)",
        timeout=0.05,
    )

    assert killed.status == "kernel_killed"
    assert killed.kernel_state == "dead"
    assert time.monotonic() - started < 4.0


async def test_withheld_started_hits_command_ack_deadline(
    supervisor: KernelSupervisor,
) -> None:
    os.killpg(supervisor._process_group, signal.SIGSTOP)
    started = time.monotonic()

    killed = await supervisor.execute("42", timeout=1.0)

    assert killed.status == "kernel_killed"
    assert killed.execution_count == 0
    assert killed.duration_ms == 0
    assert time.monotonic() - started < 8.0
    assert supervisor.state == "dead"


async def test_active_cancellation_stabilizes_live_runner(
    supervisor: KernelSupervisor,
) -> None:
    execution = asyncio.create_task(supervisor.execute("import time\ntime.sleep(30)", timeout=30.0))
    await asyncio.sleep(0.05)

    state = await supervisor.cancel_active()
    result = await execution

    assert state == "alive"
    assert result.status == "timed_out"
    assert (await supervisor.execute("'alive'", timeout=1.0)).result == "alive"


async def test_idle_background_output_is_not_attributed_later(
    supervisor: KernelSupervisor,
    tmp_path: Path,
) -> None:
    marker = tmp_path / "orphan-written"
    first = await supervisor.execute(
        "import threading, time\n"
        "from pathlib import Path\n"
        f"orphan_marker = Path({str(marker)!r})\n"
        "def emit_orphan():\n"
        "    time.sleep(0.05)\n"
        "    print('orphan', flush=True)\n"
        "    orphan_marker.touch()\n"
        "threading.Thread(target=emit_orphan, daemon=True).start()",
        timeout=1.0,
    )
    deadline = time.monotonic() + 2.0
    while not marker.exists() and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    assert marker.exists()
    second = await supervisor.execute("42", timeout=1.0)

    assert first.stdout == ""
    assert second.stdout == ""


async def test_sigint_ignoring_descendant_remains_managed_until_shutdown(
    supervisor: KernelSupervisor,
) -> None:
    timed_out = await supervisor.execute(
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', "
        "'import signal,time; signal.signal(signal.SIGINT, signal.SIG_IGN); time.sleep(30)'])\n"
        "time.sleep(30)",
        timeout=0.05,
    )
    child_result = await supervisor.execute("child.pid", timeout=1.0)
    assert type(child_result.result) is int
    child_pid = child_result.result

    assert timed_out.status == "timed_out"
    assert psutil.pid_exists(child_pid)
    shutdown = await supervisor.shutdown()

    assert shutdown.cleaned
    assert await wait_pid_gone(child_pid)


async def test_shutdown_removes_managed_descendant(supervisor: KernelSupervisor) -> None:
    child_result = await supervisor.execute(
        "import subprocess, sys\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        "child.pid",
        timeout=1.0,
    )
    assert type(child_result.result) is int
    child_pid = child_result.result

    shutdown = await supervisor.shutdown()

    assert shutdown.cleaned
    assert supervisor.state == "closed"
    assert await wait_pid_gone(child_pid)


class StuckGroupOperations:
    """Signal real processes but report a permanently existing group."""

    def signal_group(self, process_group: int, signal_number: int) -> None:
        os.killpg(process_group, signal_number)

    def group_exists(self, _process_group: int) -> bool:
        return True


async def test_cleanup_failure_is_reported(tmp_path: Path) -> None:
    current = await KernelSupervisor.start(tmp_path, operations=StuckGroupOperations())

    result = await current.shutdown()

    assert not result.cleaned
    assert result.error is not None
    assert "remains after SIGKILL" in result.error
    assert current.state == "dead"


async def test_fatal_cleanup_details_remain_host_only(tmp_path: Path) -> None:
    current = await KernelSupervisor.start(tmp_path, operations=StuckGroupOperations())

    result = await current.execute(
        "import time\n"
        "while True:\n"
        "    try:\n"
        "        time.sleep(1)\n"
        "    except KeyboardInterrupt:\n"
        "        pass",
        timeout=0.05,
    )

    assert result.status == "kernel_killed"
    assert result.error is not None
    assert result.error.type == "CleanupError"
    assert result.error.message == "managed kernel cleanup failed"
    assert "SIGKILL" not in result.error.message
    assert "SIGKILL" in current.diagnostic_tail


async def test_runner_environment_is_allowlist_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("PYTHONPATH", "/untrusted")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid")
    monkeypatch.setenv("AMKERNEL_RANDOM_SECRET", "secret")
    current = await KernelSupervisor.start(tmp_path)
    try:
        observed = await current.execute("import os\ndict(os.environ)", timeout=1.0)
        assert isinstance(observed.result, dict)
        environment = observed.result
        assert "OPENAI_API_KEY" not in environment
        assert "PYTHONPATH" not in environment
        assert "HTTP_PROXY" not in environment
        assert "AMKERNEL_RANDOM_SECRET" not in environment
        assert "PATH" in environment
        allowed = {
            "HOME",
            "LANG",
            "LC_ALL",
            "LC_CTYPE",
            "LOGNAME",
            "PATH",
            "SHELL",
            "TERM",
            "TMPDIR",
            "TZ",
            "USER",
            "VIRTUAL_ENV",
        }
        if sys.platform == "darwin":
            allowed.add("__CF_USER_TEXT_ENCODING")
        assert set(environment) <= allowed
    finally:
        await current.shutdown()


async def test_direct_execute_task_cancellation_stabilizes_runner(
    supervisor: KernelSupervisor,
) -> None:
    execution = asyncio.create_task(supervisor.execute("import time\ntime.sleep(30)", timeout=30.0))
    await asyncio.sleep(0.05)
    execution.cancel()

    with pytest.raises(asyncio.CancelledError):
        await execution

    assert supervisor.state == "alive"
    assert (await supervisor.execute("'alive'", timeout=1.0)).result == "alive"


class FailingInterruptOperations:
    """Fail only SIGINT while allowing destructive cleanup to proceed."""

    def signal_group(self, process_group: int, signal_number: int) -> None:
        if signal_number == signal.SIGINT:
            raise PermissionError("SIGINT denied")
        os.killpg(process_group, signal_number)

    def group_exists(self, process_group: int) -> bool:
        try:
            os.killpg(process_group, 0)
        except ProcessLookupError:
            return False
        return True


async def test_sigint_primitive_failure_returns_cleanup_error(tmp_path: Path) -> None:
    current = await KernelSupervisor.start(tmp_path, operations=FailingInterruptOperations())
    try:
        result = await current.execute("import time\ntime.sleep(30)", timeout=0.05)

        assert result.status == "kernel_killed"
        assert result.error is not None
        assert result.error.type == "CleanupError"
        assert current.state == "dead"
    finally:
        await current.shutdown()


async def test_idle_runner_death_is_observed_and_descendants_are_cleaned(
    supervisor: KernelSupervisor,
) -> None:
    result = await supervisor.execute(
        "import os, subprocess, sys, threading, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        "def die():\n"
        "    time.sleep(0.05)\n"
        "    os._exit(23)\n"
        "threading.Thread(target=die, daemon=True).start()\n"
        "child.pid",
        timeout=1.0,
    )
    assert type(result.result) is int
    child_pid = result.result

    deadline = time.monotonic() + 3.0
    while supervisor.state != "dead" and time.monotonic() < deadline:
        await asyncio.sleep(0.02)

    assert supervisor.state == "dead", (
        supervisor._process.returncode,
        supervisor._runner_exit_observed,
        supervisor._death_monitor_task.done(),
        supervisor._death_monitor_task.exception()
        if supervisor._death_monitor_task.done()
        else None,
    )
    assert await wait_pid_gone(child_pid)


async def test_shutdown_cancellation_waits_for_kill_cleanup(
    supervisor: KernelSupervisor,
    tmp_path: Path,
) -> None:
    ready = tmp_path / "term-handler-ready"
    child_code = (
        "import signal, time\n"
        "from pathlib import Path\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"Path({str(ready)!r}).touch()\n"
        "time.sleep(30)"
    )
    child = await supervisor.execute(
        "import subprocess, sys\n"
        f"child = subprocess.Popen([sys.executable, '-c', {child_code!r}])\n"
        "child.pid",
        timeout=1.0,
    )
    assert type(child.result) is int
    child_pid = child.result
    deadline = time.monotonic() + 2.0
    while not ready.exists() and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    assert ready.exists()

    shutdown = asyncio.create_task(supervisor.shutdown())
    while supervisor.state != "closing" and not shutdown.done():
        await asyncio.sleep(0)
    assert not shutdown.done()
    shutdown.cancel()

    with pytest.raises(asyncio.CancelledError):
        await shutdown

    assert supervisor.state == "closed"
    assert await wait_pid_gone(child_pid)


async def test_partial_write_cancellation_kills_uncertain_runner(
    supervisor: KernelSupervisor,
) -> None:
    os.killpg(supervisor._process_group, signal.SIGSTOP)
    execution = asyncio.create_task(supervisor.execute("\0" * 1_048_576, timeout=30.0))
    await asyncio.sleep(0.05)
    execution.cancel()

    with pytest.raises(asyncio.CancelledError):
        await execution

    assert supervisor.state == "dead"


async def test_simultaneous_terminal_and_deadline_maps_timed_out(
    supervisor: KernelSupervisor,
) -> None:
    completed = await supervisor.execute("42", timeout=1.0)
    active = supervisor_module._ActiveExecution(uuid.uuid4().hex)
    terminal = DoneResponse(
        correlation_id=active.correlation_id,
        outcome="completed",
        execution_count=completed.execution_count,
        runtime=completed.runtime,
        has_result=True,
        result=42,
    )

    outcome = await supervisor._interrupt_or_escalate(
        active,
        time.monotonic(),
        "deadline",
        terminal,
    )

    assert outcome.status == "timed_out"
    assert outcome.kernel_state == "alive"
    assert (await supervisor.execute("'alive'", timeout=1.0)).result == "alive"


async def test_cancelled_start_cleans_spawned_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = supervisor_module._stream_reader_from_fd
    release = asyncio.Event()
    calls = 0

    async def delayed_reader(fd: int) -> tuple[asyncio.StreamReader, asyncio.ReadTransport]:
        nonlocal calls
        calls += 1
        if calls == 1:
            await release.wait()
        return await original(fd)

    monkeypatch.setattr(supervisor_module, "_stream_reader_from_fd", delayed_reader)
    before = {process.pid for process in psutil.Process().children(recursive=True)}
    starting = asyncio.create_task(KernelSupervisor.start(tmp_path))
    await asyncio.sleep(0.05)
    starting.cancel()
    release.set()

    with pytest.raises(asyncio.CancelledError):
        await starting

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        after = {process.pid for process in psutil.Process().children(recursive=True)}
        if after <= before:
            break
        await asyncio.sleep(0.02)
    assert {process.pid for process in psutil.Process().children(recursive=True)} <= before


class FailOnceTerminateOperations:
    """Model one denied TERM, then deterministic descendant cleanup."""

    def __init__(self) -> None:
        self.failed = False
        self.child_pid: int | None = None

    def signal_group(self, process_group: int, signal_number: int) -> None:
        del process_group
        if signal_number == signal.SIGTERM and not self.failed:
            self.failed = True
            raise PermissionError("TERM denied once")
        if self.child_pid is None:
            return
        try:
            os.kill(self.child_pid, signal_number)
        except ProcessLookupError:
            pass

    def group_exists(self, process_group: int) -> bool:
        del process_group
        return self.child_pid is not None and psutil.pid_exists(self.child_pid)


async def test_idle_death_cleanup_failure_is_retained_and_reported(
    tmp_path: Path,
) -> None:
    operations = FailOnceTerminateOperations()
    current = await KernelSupervisor.start(tmp_path, operations=operations)
    result = await current.execute(
        "import os, subprocess, sys, threading, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        "threading.Thread(target=lambda: (time.sleep(0.05), os._exit(23)), daemon=True).start()\n"
        "child.pid",
        timeout=1.0,
    )
    assert type(result.result) is int
    child_pid = result.result
    operations.child_pid = child_pid

    deadline = time.monotonic() + 3.0
    while current.state != "dead" and time.monotonic() < deadline:
        await asyncio.sleep(0.02)

    assert current.state == "dead"
    assert current._cleanup_error is not None
    assert "TERM denied once" in current._cleanup_error
    assert "cleanup failed" in current.diagnostic_tail
    shutdown = await current.shutdown()
    assert shutdown.cleaned
    assert shutdown.error is None
    assert "TERM denied once" in current.diagnostic_tail
    assert await wait_pid_gone(child_pid)


async def test_concurrent_shutdown_calls_share_one_cleanup(
    supervisor: KernelSupervisor,
) -> None:
    first, second = await asyncio.gather(supervisor.shutdown(), supervisor.shutdown())

    assert first.cleaned
    assert second.cleaned
    assert supervisor.state == "closed"


async def test_shutdown_request_write_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
    supervisor: KernelSupervisor,
) -> None:
    blocked = asyncio.Event()

    async def block_write(_frame: bytes) -> None:
        await blocked.wait()

    monkeypatch.setattr(supervisor, "_write_request", block_write)
    started = time.monotonic()

    result = await supervisor.shutdown()

    assert result.cleaned
    assert supervisor.state == "closed"
    assert time.monotonic() - started < 4.0


async def test_unsupported_platform_fails_before_pipe_creation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def unsupported() -> None:
        raise RuntimeError("UnsupportedPlatformError: missing primitives")

    def forbidden_pipes() -> tuple[int, int, int, int, int, int]:
        raise AssertionError("pipes must not be created")

    monkeypatch.setattr(KernelSupervisor, "_require_supported_platform", staticmethod(unsupported))
    monkeypatch.setattr(supervisor_module, "_create_protocol_pipes", forbidden_pipes)

    with pytest.raises(KernelStartError, match="UnsupportedPlatformError"):
        await KernelSupervisor.start(tmp_path)


async def test_graceful_shutdown_requires_zero_runner_exit(
    supervisor: KernelSupervisor,
) -> None:
    await supervisor.execute(
        "import atexit, os\natexit.register(lambda: os._exit(17))",
        timeout=1.0,
    )

    result = await supervisor.shutdown()

    assert not result.cleaned
    assert result.error is not None
    assert "status 17" in result.error
    assert supervisor.state == "closed"
    repeated = await supervisor.shutdown()
    assert not repeated.cleaned
    assert repeated.error == result.error


@pytest.mark.parametrize("fail_on", [2, 3])
async def test_partial_pipe_acquisition_closes_prior_descriptors(
    monkeypatch: pytest.MonkeyPatch,
    fail_on: int,
) -> None:
    real_pipe = os.pipe
    opened: list[int] = []
    calls = 0

    def failing_pipe() -> tuple[int, int]:
        nonlocal calls
        calls += 1
        if calls == fail_on:
            raise OSError("pipe limit")
        pair = real_pipe()
        opened.extend(pair)
        return pair

    monkeypatch.setattr(os, "pipe", failing_pipe)
    with pytest.raises(OSError, match="pipe limit"):
        supervisor_module._create_protocol_pipes()

    for descriptor in opened:
        with pytest.raises(OSError):
            os.fstat(descriptor)


class FailFirstVerificationOperations:
    """Fail one group verification, then model successful retry cleanup."""

    def __init__(self) -> None:
        self.failed = False
        self.signaled = False

    def signal_group(self, process_group: int, signal_number: int) -> None:
        os.killpg(process_group, signal_number)
        self.signaled = True

    def group_exists(self, _process_group: int) -> bool:
        if not self.failed:
            self.failed = True
            raise PermissionError("verification denied once")
        return not self.signaled


async def test_initialization_cleanup_failure_remains_retryable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def fail_initialize(_supervisor: KernelSupervisor) -> None:
        raise RuntimeError("injected initialize failure")

    monkeypatch.setattr(KernelSupervisor, "_initialize", fail_initialize)
    before = {process.pid for process in psutil.Process().children(recursive=True)}

    with pytest.raises(KernelStartError) as captured:
        await KernelSupervisor.start(tmp_path, operations=FailFirstVerificationOperations())

    assert captured.value.cleanup_pending
    assert "cleanup failed" in str(captured.value)
    cleanup = await captured.value.retry_cleanup()
    assert cleanup.cleaned
    assert not captured.value.cleanup_pending

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        after = {process.pid for process in psutil.Process().children(recursive=True)}
        if after <= before:
            break
        await asyncio.sleep(0.02)
    assert {process.pid for process in psutil.Process().children(recursive=True)} <= before


async def test_cancelled_start_cleanup_failure_remains_retryable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original = supervisor_module._stream_reader_from_fd
    release = asyncio.Event()
    calls = 0

    async def delayed_reader(fd: int) -> tuple[asyncio.StreamReader, asyncio.ReadTransport]:
        nonlocal calls
        calls += 1
        if calls == 1:
            await release.wait()
        return await original(fd)

    monkeypatch.setattr(supervisor_module, "_stream_reader_from_fd", delayed_reader)
    before = {process.pid for process in psutil.Process().children(recursive=True)}
    starting = asyncio.create_task(
        KernelSupervisor.start(tmp_path, operations=FailFirstVerificationOperations())
    )
    await asyncio.sleep(0.05)
    starting.cancel()
    release.set()

    with pytest.raises(KernelStartError) as captured:
        await starting

    assert captured.value.cleanup_pending
    cleanup = await captured.value.retry_cleanup()
    assert cleanup.cleaned
    assert not captured.value.cleanup_pending

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        after = {process.pid for process in psutil.Process().children(recursive=True)}
        if after <= before:
            break
        await asyncio.sleep(0.02)
    assert {process.pid for process in psutil.Process().children(recursive=True)} <= before


async def test_failed_shutdown_can_retry_cleanup(tmp_path: Path) -> None:
    current = await KernelSupervisor.start(
        tmp_path,
        operations=FailFirstVerificationOperations(),
    )

    first, first_peer = await asyncio.gather(current.shutdown(), current.shutdown())
    second, second_peer = await asyncio.gather(current.shutdown(), current.shutdown())

    assert not first.cleaned
    assert first_peer == first
    assert first.error is not None
    assert "verification denied once" in first.error
    assert second.cleaned
    assert second_peer == second
    assert second.error is None
    assert current.state == "closed"
