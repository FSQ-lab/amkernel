"""Deterministic real-Supervisor deadline/terminal race evidence."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from amkernel.artifact_store import ArtifactStore
from amkernel.protocol import DoneResponse, Response
from amkernel.supervisor import KernelSupervisor, SupervisedExecution

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(os.name != "posix", reason="Stage 1 Runtime is POSIX-only"),
]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_deadline_wins_real_terminal_races_and_runner_reuses_immediately(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    supervisor = await KernelSupervisor.start(tmp_path)
    store = ArtifactStore(temporary_parent=tmp_path)

    async def execute(code: str, timeout: float) -> SupervisedExecution:
        return await supervisor.execute(
            code,
            timeout,
            output_bundle=await store.begin_bundle(),
        )

    original_next_response = supervisor._next_response
    real_sleep = asyncio.sleep
    deadline = asyncio.Event()
    terminal_ready = asyncio.Event()
    terminal_release = asyncio.Event()

    async def controlled_sleep(delay: float) -> None:
        if delay == 123.456:
            await deadline.wait()
            return
        await real_sleep(delay)

    async def gated_response() -> Response:
        response = await original_next_response()
        if isinstance(response, DoneResponse):
            terminal_ready.set()
            await terminal_release.wait()
        return response

    monkeypatch.setattr(asyncio, "sleep", controlled_sleep)
    monkeypatch.setattr(supervisor, "_next_response", gated_response)
    terminal_release.set()
    try:
        initialized = await execute("values = []", 1.0)
        assert initialized.status == "completed"

        for index in range(20):
            deadline = asyncio.Event()
            terminal_ready = asyncio.Event()
            terminal_release = asyncio.Event()
            execution = asyncio.create_task(execute(f"values.append({index})\n{index}", 123.456))
            await asyncio.wait_for(terminal_ready.wait(), timeout=2.0)
            deadline.set()
            terminal_release.set()

            result = await asyncio.wait_for(execution, timeout=2.0)

            assert result.status == "timed_out"
            assert result.kernel_state == "alive"
            assert result.error is not None
            assert result.error.type == "TimeoutError"
            assert result.execution_count == index + 2

        observed = await execute("values", 1.0)
        assert observed.status == "completed"
        assert observed.result == list(range(20))
        assert observed.kernel_state == "alive"
    finally:
        assert (await asyncio.wait_for(supervisor.shutdown(), timeout=5.0)).cleaned
        await store.cleanup()
