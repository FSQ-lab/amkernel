"""Behavior tests for FIFO Runtime orchestration and lifecycle truth."""

from __future__ import annotations

import asyncio
import os
from collections import deque
from pathlib import Path

import pytest

from amkernel.protocol import JsonValue, RuntimeDiagnostics
from amkernel.runtime import KernelRuntime, RuntimeClosedError
from amkernel.supervisor import (
    ExecutionStatus,
    KernelStartError,
    KernelState,
    OutputMetadata,
    ShutdownResult,
    SupervisedExecution,
    configured_runtime,
)

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(os.name != "posix", reason="Stage 1 Runtime is POSIX-only"),
]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeSupervisor:
    def __init__(
        self,
        runtime: RuntimeDiagnostics,
        *,
        name: str = "kernel",
        cleanup: ShutdownResult | None = None,
    ) -> None:
        self.runtime = runtime
        self.name = name
        self.state = "alive"
        self.execution_count = 0
        self.cleanup = cleanup or ShutdownResult(True)
        self.calls: list[str] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.shutdown_started = asyncio.Event()
        self.shutdown_release = asyncio.Event()
        self.shutdown_release.set()
        self.cancelled = asyncio.Event()
        self.shutdown_calls = 0
        self.diagnostic_tail = ""

    async def execute(self, code: str, timeout: float) -> SupervisedExecution:
        del timeout
        self.calls.append(code)
        self.execution_count += 1
        self.started.set()
        if code == "block":
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise
        return execution(self.runtime, count=self.execution_count, result=f"{self.name}:{code}")

    async def shutdown(self) -> ShutdownResult:
        self.shutdown_calls += 1
        self.shutdown_started.set()
        await self.shutdown_release.wait()
        self.state = "closed" if self.cleanup.cleaned else "dead"
        return self.cleanup


class FakeFactory:
    def __init__(self, *outcomes: FakeSupervisor | Exception) -> None:
        self.outcomes = deque(outcomes)
        self.calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()

    async def __call__(self, _working_directory: Path) -> FakeSupervisor:
        self.calls += 1
        self.started.set()
        await self.release.wait()
        outcome = self.outcomes.popleft()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def execution(
    runtime: RuntimeDiagnostics,
    *,
    count: int,
    result: JsonValue = None,
    status: ExecutionStatus = "completed",
    kernel_state: KernelState = "alive",
) -> SupervisedExecution:
    return SupervisedExecution(
        status=status,
        stdout="",
        stderr="",
        has_result=True,
        result=result,
        error=None,
        execution_count=count,
        duration_ms=1,
        kernel_state=kernel_state,
        runtime=runtime,
        output=OutputMetadata(0, 0, False),
    )


async def test_runtime_is_lazy_and_shutdown_does_not_start_kernel(tmp_path: Path) -> None:
    factory = FakeFactory(FakeSupervisor(configured_runtime(tmp_path)))
    runtime = KernelRuntime(tmp_path, supervisor_factory=factory)

    assert runtime.state == "new"
    assert factory.calls == 0

    result = await runtime.shutdown()

    assert result.cleaned
    observed_state: str = runtime.state
    assert observed_state == "closed"
    assert factory.calls == 0


async def test_calls_execute_in_fifo_order(tmp_path: Path) -> None:
    supervisor = FakeSupervisor(configured_runtime(tmp_path))
    factory = FakeFactory(supervisor)
    runtime = KernelRuntime(tmp_path, supervisor_factory=factory)
    try:
        first = asyncio.create_task(runtime.execute("block"))
        await supervisor.started.wait()
        second = asyncio.create_task(runtime.execute("second"))
        await asyncio.sleep(0)
        third = asyncio.create_task(runtime.execute("third"))
        await asyncio.sleep(0)

        assert supervisor.calls == ["block"]
        supervisor.release.set()
        results = await asyncio.gather(first, second, third)

        assert supervisor.calls == ["block", "second", "third"]
        assert [item.execution_count for item in results] == [1, 2, 3]
    finally:
        await runtime.shutdown()


async def test_cancelled_queued_call_is_skipped(tmp_path: Path) -> None:
    supervisor = FakeSupervisor(configured_runtime(tmp_path))
    runtime = KernelRuntime(tmp_path, supervisor_factory=FakeFactory(supervisor))
    try:
        first = asyncio.create_task(runtime.execute("block"))
        await supervisor.started.wait()
        abandoned = asyncio.create_task(runtime.execute("abandoned"))
        await asyncio.sleep(0)
        last = asyncio.create_task(runtime.execute("last"))
        await asyncio.sleep(0)

        abandoned.cancel()
        with pytest.raises(asyncio.CancelledError):
            await abandoned
        supervisor.release.set()
        await first
        observed = await last

        assert supervisor.calls == ["block", "last"]
        assert observed.execution_count == 2
    finally:
        await runtime.shutdown()


async def test_cancellation_during_lazy_start_stabilizes_live_count_zero(tmp_path: Path) -> None:
    supervisor = FakeSupervisor(configured_runtime(tmp_path))
    factory = FakeFactory(supervisor)
    factory.release.clear()
    runtime = KernelRuntime(tmp_path, supervisor_factory=factory)
    try:
        cancelled = asyncio.create_task(runtime.execute("never-sent"))
        await factory.started.wait()
        cancelled.cancel()
        factory.release.set()

        with pytest.raises(asyncio.CancelledError):
            await cancelled
        while runtime.state == "new":
            await asyncio.sleep(0)

        assert runtime.state == "alive"
        assert runtime.execution_count == 0
        assert supervisor.calls == []
        next_result = await runtime.execute("next")
        assert next_result.execution_count == 1
    finally:
        await runtime.shutdown()


async def test_active_caller_cancellation_stabilizes_before_next_call(tmp_path: Path) -> None:
    supervisor = FakeSupervisor(configured_runtime(tmp_path))
    runtime = KernelRuntime(tmp_path, supervisor_factory=FakeFactory(supervisor))
    try:
        active = asyncio.create_task(runtime.execute("block"))
        await supervisor.started.wait()
        active.cancel()

        with pytest.raises(asyncio.CancelledError):
            await active
        await supervisor.cancelled.wait()
        while runtime.execution_count != 1:
            await asyncio.sleep(0)

        observed = await runtime.execute("next")
        assert observed.execution_count == 2
        assert supervisor.calls == ["block", "next"]
        assert runtime.state == "alive"
    finally:
        await runtime.shutdown()


async def test_supervisor_diagnostics_propagate_to_runtime_host_tail(tmp_path: Path) -> None:
    supervisor = FakeSupervisor(configured_runtime(tmp_path))
    runtime = KernelRuntime(tmp_path, supervisor_factory=FakeFactory(supervisor))
    try:
        await runtime.execute("first")
        supervisor.diagnostic_tail = "process-group operation failed: injected\n"

        observed = await runtime.execute("second")

        assert observed.status == "completed"
        assert "process-group operation failed: injected" in runtime.diagnostic_tail
    finally:
        await runtime.shutdown()


async def test_reset_waits_for_cleanup_then_restarts_at_one(tmp_path: Path) -> None:
    first = FakeSupervisor(configured_runtime(tmp_path), name="old")
    second = FakeSupervisor(configured_runtime(tmp_path), name="new")
    factory = FakeFactory(first, second)
    runtime = KernelRuntime(tmp_path, supervisor_factory=factory)
    try:
        initial = await runtime.execute("value")
        reset = await runtime.execute("fresh", reset=True)

        assert initial.result == "old:value"
        assert reset.result == "new:fresh"
        assert reset.execution_count == 1
        assert first.shutdown_calls == 1
        assert factory.calls == 2
    finally:
        await runtime.shutdown()


async def test_cancelled_reset_finishes_replacement_without_cell(tmp_path: Path) -> None:
    first = FakeSupervisor(configured_runtime(tmp_path), name="old")
    second = FakeSupervisor(configured_runtime(tmp_path), name="new")
    first.shutdown_release.clear()
    factory = FakeFactory(first, second)
    runtime = KernelRuntime(tmp_path, supervisor_factory=factory)
    try:
        await runtime.execute("value")
        reset = asyncio.create_task(runtime.execute("never-sent", reset=True))
        await first.shutdown_started.wait()
        reset.cancel()
        first.shutdown_release.set()

        with pytest.raises(asyncio.CancelledError):
            await reset
        while factory.calls < 2 or runtime.state != "alive":
            await asyncio.sleep(0)

        assert second.calls == []
        assert runtime.execution_count == 0
        observed = await runtime.execute("after")
        assert observed.result == "new:after"
        assert observed.execution_count == 1
    finally:
        await runtime.shutdown()


async def test_cancellation_during_replacement_start_retains_count_zero(tmp_path: Path) -> None:
    first = FakeSupervisor(configured_runtime(tmp_path), name="old")
    second = FakeSupervisor(configured_runtime(tmp_path), name="new")
    factory = FakeFactory(first, second)
    runtime = KernelRuntime(tmp_path, supervisor_factory=factory)
    try:
        await runtime.execute("value")
        factory.release.clear()
        reset = asyncio.create_task(runtime.execute("never-sent", reset=True))
        while factory.calls < 2:
            await asyncio.sleep(0)
        reset.cancel()
        factory.release.set()

        with pytest.raises(asyncio.CancelledError):
            await reset
        while runtime.state != "alive":
            await asyncio.sleep(0)

        assert second.calls == []
        assert runtime.execution_count == 0
        assert (await runtime.execute("after")).execution_count == 1
    finally:
        await runtime.shutdown()


async def test_reset_keeps_fifo_position_between_calls(tmp_path: Path) -> None:
    first = FakeSupervisor(configured_runtime(tmp_path), name="old")
    second = FakeSupervisor(configured_runtime(tmp_path), name="new")
    factory = FakeFactory(first, second)
    runtime = KernelRuntime(tmp_path, supervisor_factory=factory)
    try:
        before = asyncio.create_task(runtime.execute("block"))
        await first.started.wait()
        reset = asyncio.create_task(runtime.execute("fresh", reset=True))
        await asyncio.sleep(0)
        after = asyncio.create_task(runtime.execute("after"))
        await asyncio.sleep(0)
        first.release.set()

        results = await asyncio.gather(before, reset, after)

        assert [item.result for item in results] == ["old:block", "new:fresh", "new:after"]
        assert first.calls == ["block"]
        assert second.calls == ["fresh", "after"]
        assert [item.execution_count for item in results] == [1, 1, 2]
    finally:
        await runtime.shutdown()


async def test_reset_cleanup_failure_suppresses_replacement(tmp_path: Path) -> None:
    first = FakeSupervisor(
        configured_runtime(tmp_path),
        cleanup=ShutdownResult(False, "group remains"),
    )
    replacement = FakeSupervisor(configured_runtime(tmp_path))
    factory = FakeFactory(first, replacement)
    runtime = KernelRuntime(tmp_path, supervisor_factory=factory)
    try:
        await runtime.execute("value")
        failed = await runtime.execute("fresh", reset=True)

        assert failed.status == "kernel_killed"
        assert failed.kernel_state == "dead"
        assert failed.error is not None
        assert failed.error.type == "ResetCleanupError"
        assert failed.execution_count == 1
        assert runtime.state == "dead"
        assert factory.calls == 1
    finally:
        await runtime.shutdown()


async def test_start_failure_is_structured_and_only_reset_recovers(tmp_path: Path) -> None:
    replacement = FakeSupervisor(configured_runtime(tmp_path))
    factory = FakeFactory(KernelStartError("ready timeout"), replacement)
    runtime = KernelRuntime(tmp_path, supervisor_factory=factory)
    try:
        failed = await runtime.execute("first")
        unavailable = await runtime.execute("second")
        recovered = await runtime.execute("third", reset=True)

        assert failed.status == "kernel_killed"
        assert failed.error is not None
        assert failed.error.type == "KernelStartError"
        assert failed.execution_count == 0
        assert unavailable.error is not None
        assert unavailable.error.type == "KernelUnavailable"
        assert factory.calls == 2
        assert recovered.execution_count == 1
        assert recovered.kernel_state == "alive"
    finally:
        await runtime.shutdown()


async def test_start_cleanup_failure_blocks_replacement_until_retry_succeeds(
    tmp_path: Path,
) -> None:
    cleanup_results = deque([ShutdownResult(False, "group remains"), ShutdownResult(True)])

    async def cleanup() -> ShutdownResult:
        return cleanup_results.popleft()

    replacement = FakeSupervisor(configured_runtime(tmp_path))
    factory = FakeFactory(
        KernelStartError("ready failed; cleanup failed", cleanup=cleanup),
        replacement,
    )
    runtime = KernelRuntime(tmp_path, supervisor_factory=factory)
    try:
        failed_start = await runtime.execute("first")
        failed_reset = await runtime.execute("second", reset=True)
        recovered = await runtime.execute("third", reset=True)

        assert failed_start.error is not None
        assert failed_start.error.type == "KernelStartError"
        assert failed_start.error.message == "kernel failed to start"
        assert "cleanup failed" not in failed_start.error.message
        assert "cleanup failed" in runtime.diagnostic_tail
        assert failed_reset.error is not None
        assert failed_reset.error.message == "managed kernel cleanup failed during reset"
        assert "group remains" not in failed_reset.error.message
        assert "group remains" in runtime.diagnostic_tail
        assert failed_reset.error.type == "ResetCleanupError"
        assert factory.calls == 2
        assert recovered.status == "completed"
        assert recovered.execution_count == 1
    finally:
        await runtime.shutdown()


async def test_shutdown_remains_closed_when_lazy_start_fails(tmp_path: Path) -> None:
    factory = FakeFactory(KernelStartError("ready failed"))
    factory.release.clear()
    runtime = KernelRuntime(tmp_path, supervisor_factory=factory)
    call = asyncio.create_task(runtime.execute("never-sent"))
    await factory.started.wait()

    shutdown = asyncio.create_task(runtime.shutdown())
    await asyncio.sleep(0)
    factory.release.set()
    result = await asyncio.wait_for(shutdown, timeout=1.0)

    assert result.cleaned
    assert runtime.state == "closed"
    with pytest.raises(RuntimeClosedError):
        await call


async def test_shutdown_rejects_queued_work_and_interrupts_active_work(tmp_path: Path) -> None:
    supervisor = FakeSupervisor(configured_runtime(tmp_path))
    runtime = KernelRuntime(tmp_path, supervisor_factory=FakeFactory(supervisor))
    active = asyncio.create_task(runtime.execute("block"))
    await supervisor.started.wait()
    queued = asyncio.create_task(runtime.execute("queued"))
    await asyncio.sleep(0)

    shutdown = await runtime.shutdown()

    assert shutdown.cleaned
    assert runtime.state == "closed"
    assert supervisor.calls == ["block"]
    with pytest.raises(RuntimeClosedError):
        await active
    with pytest.raises(RuntimeClosedError):
        await queued
    with pytest.raises(RuntimeClosedError):
        await runtime.execute("late")


async def test_shutdown_during_replacement_never_runs_reset_cell(tmp_path: Path) -> None:
    first = FakeSupervisor(configured_runtime(tmp_path), name="old")
    second = FakeSupervisor(configured_runtime(tmp_path), name="new")
    first.shutdown_release.clear()
    factory = FakeFactory(first, second)
    runtime = KernelRuntime(tmp_path, supervisor_factory=factory)
    await asyncio.wait_for(runtime.execute("value"), timeout=1.0)
    reset = asyncio.create_task(runtime.execute("never-sent", reset=True))
    await asyncio.wait_for(first.shutdown_started.wait(), timeout=1.0)

    shutdown_task = asyncio.create_task(runtime.shutdown())
    first.shutdown_release.set()
    shutdown = await asyncio.wait_for(shutdown_task, timeout=1.0)

    assert shutdown.cleaned
    assert factory.calls == 1
    assert second.calls == []
    with pytest.raises(RuntimeClosedError):
        await reset


async def test_shutdown_during_lazy_start_cleans_created_kernel(tmp_path: Path) -> None:
    supervisor = FakeSupervisor(configured_runtime(tmp_path))
    factory = FakeFactory(supervisor)
    factory.release.clear()
    runtime = KernelRuntime(tmp_path, supervisor_factory=factory)
    call = asyncio.create_task(runtime.execute("never-sent"))
    await factory.started.wait()

    shutdown_task = asyncio.create_task(runtime.shutdown())
    await asyncio.sleep(0)
    peer_shutdown = asyncio.create_task(runtime.shutdown())
    await asyncio.sleep(0)

    assert not shutdown_task.done()
    assert not peer_shutdown.done()
    factory.release.set()
    shutdown, peer_result = await asyncio.gather(shutdown_task, peer_shutdown)

    assert shutdown.cleaned
    assert peer_result == shutdown
    assert supervisor.calls == []
    assert supervisor.shutdown_calls >= 1
    with pytest.raises(RuntimeClosedError):
        await call


async def test_cancelled_shutdown_still_finishes_cleanup(tmp_path: Path) -> None:
    supervisor = FakeSupervisor(configured_runtime(tmp_path))
    runtime = KernelRuntime(tmp_path, supervisor_factory=FakeFactory(supervisor))
    await runtime.execute("value")
    supervisor.shutdown_release.clear()
    shutdown_task = asyncio.create_task(runtime.shutdown())
    await supervisor.shutdown_started.wait()

    shutdown_task.cancel()
    supervisor.shutdown_release.set()

    with pytest.raises(asyncio.CancelledError):
        await shutdown_task
    assert runtime.state == "closed"
    assert supervisor.state == "closed"
    with pytest.raises(RuntimeClosedError):
        await runtime.execute("late")


async def test_queue_wait_does_not_consume_cell_timeout(tmp_path: Path) -> None:
    runtime = KernelRuntime(tmp_path)
    try:
        first = asyncio.create_task(runtime.execute("import time; time.sleep(0.15)", timeout=1.0))
        await asyncio.sleep(0.02)
        queued = asyncio.create_task(runtime.execute("42", timeout=0.05))

        await first
        observed = await queued

        assert observed.status == "completed"
        assert observed.result == 42
        assert observed.execution_count == 2
    finally:
        await runtime.shutdown()


async def test_real_runtime_persists_resets_and_refuses_dead_kernel(tmp_path: Path) -> None:
    runtime = KernelRuntime(tmp_path)
    try:
        await runtime.execute("values = []", timeout=1.0)
        persisted = await runtime.execute("values.append(1)\nvalues", timeout=1.0)
        reset = await runtime.execute("'values' in globals()", timeout=1.0, reset=True)
        killed = await runtime.execute("import os\nos._exit(17)", timeout=1.0)
        unavailable = await runtime.execute("42", timeout=1.0)
        recovered = await runtime.execute("42", timeout=1.0, reset=True)

        assert persisted.result == [1]
        assert persisted.execution_count == 2
        assert reset.result is False
        assert reset.execution_count == 1
        assert killed.kernel_state == "dead"
        assert unavailable.kernel_state == "dead"
        assert unavailable.error is not None
        assert unavailable.error.type == "KernelUnavailable"
        assert unavailable.execution_count == killed.execution_count
        assert recovered.result == 42
        assert recovered.execution_count == 1
        assert recovered.kernel_state == "alive"
    finally:
        await runtime.shutdown()


async def test_reset_restores_launch_working_directory(tmp_path: Path) -> None:
    child = tmp_path / "child"
    child.mkdir()
    runtime = KernelRuntime(tmp_path)
    try:
        changed = await runtime.execute(
            f"import os\nos.chdir({str(child)!r})\nos.getcwd()",
            timeout=1.0,
        )
        reset = await runtime.execute("import os\nos.getcwd()", timeout=1.0, reset=True)

        assert changed.result == str(child)
        assert changed.runtime.working_directory == str(child)
        assert reset.result == str(tmp_path)
        assert reset.runtime.working_directory == str(tmp_path)
    finally:
        await runtime.shutdown()


async def test_reset_start_failure_after_launch_directory_removal_is_structured(
    tmp_path: Path,
) -> None:
    runtime = KernelRuntime(tmp_path)
    try:
        removed = await runtime.execute(
            f"import os\nos.chdir('/')\nos.rmdir({str(tmp_path)!r})",
            timeout=1.0,
        )
        failed = await runtime.execute("42", timeout=1.0, reset=True)

        assert removed.status == "completed"
        assert failed.status == "kernel_killed"
        assert failed.kernel_state == "dead"
        assert failed.execution_count == 0
        assert failed.error is not None
        assert failed.error.type == "KernelStartError"
        assert failed.runtime.working_directory == str(tmp_path)
    finally:
        await runtime.shutdown()
