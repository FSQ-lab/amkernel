"""Real bootstrap and cross-module fatal protocol boundary evidence."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import time
import uuid
from dataclasses import replace
from io import StringIO
from pathlib import Path
from typing import Any, Literal, cast

import pytest
from mcp.client import Client
from mcp.types import CallToolResult

from amkernel.protocol import MAX_CODE_BYTES, ProtocolViolation, Response, StartedResponse
from amkernel.runtime import KernelRuntime
from amkernel.server import create_server
from amkernel.supervisor import KernelSupervisor

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(os.name != "posix", reason="Stage 1 Runtime is POSIX-only"),
]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def structured(result: CallToolResult) -> dict[str, Any]:
    content = result.structured_content
    assert isinstance(content, dict)
    return cast(dict[str, Any], content)


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ([], "--request-fd must appear exactly once"),
        (
            [
                "--request-fd",
                "3",
                "--request-fd",
                "6",
                "--response-fd",
                "4",
                "--diagnostic-fd",
                "5",
            ],
            "--request-fd must appear exactly once",
        ),
        (
            [
                "--request-fd",
                "3",
                "--response-fd",
                "4",
                "--diagnostic-fd",
                "5",
                "--unknown",
                "value",
            ],
            "unrecognized arguments: --unknown value",
        ),
    ],
)
async def test_real_runner_rejects_missing_duplicate_and_extra_bootstrap_descriptors(
    arguments: list[str],
    expected: str,
) -> None:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-I",
        "-m",
        "amkernel.runner",
        *arguments,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5.0)

    assert process.returncode == 2
    assert stdout == b""
    assert expected in stderr.decode(errors="replace")


FaultMode = Literal["send", "wrong_started", "mangled"]


async def test_blocked_maximum_frame_times_out_from_first_byte(tmp_path: Path) -> None:
    supervisor = await KernelSupervisor.start(tmp_path)
    os.killpg(supervisor._process_group, signal.SIGSTOP)
    started = time.monotonic()
    try:
        result = await supervisor.execute("\0" * MAX_CODE_BYTES, timeout=30.0)

        assert result.status == "kernel_killed"
        assert result.kernel_state == "dead"
        assert result.execution_count == 0
        assert result.duration_ms == 0
        assert result.error is not None
        assert result.error.type == "RunnerProtocolTimeout"
        assert 5.0 <= time.monotonic() - started < 9.0
    finally:
        assert (await asyncio.wait_for(supervisor.shutdown(), timeout=5.0)).cleaned


async def test_cancellation_after_full_delivery_before_started_is_fatal(
    tmp_path: Path,
) -> None:
    supervisor = await KernelSupervisor.start(tmp_path)
    os.killpg(supervisor._process_group, signal.SIGSTOP)
    execution = asyncio.create_task(supervisor.execute("42", timeout=30.0))
    try:
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            active = supervisor._active
            if active is not None and active.write_complete:
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("execute frame was not fully delivered")

        execution.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(execution, timeout=9.0)

        assert supervisor.state == "dead"
        assert supervisor.execution_count == 0
    finally:
        if not execution.done():
            execution.cancel()
            await asyncio.gather(execution, return_exceptions=True)
        assert (await asyncio.wait_for(supervisor.shutdown(), timeout=5.0)).cleaned


class FaultingSupervisorFactory:
    def __init__(self, mode: FaultMode, monkeypatch: pytest.MonkeyPatch) -> None:
        self.mode = mode
        self.monkeypatch = monkeypatch
        self.calls = 0

    async def __call__(self, working_directory: Path) -> KernelSupervisor:
        self.calls += 1
        supervisor = await KernelSupervisor.start(working_directory)
        if self.mode == "send":

            async def fail_send(_frame: bytes, *, active: object = None) -> None:
                del active
                raise OSError("injected execute send failure")

            self.monkeypatch.setattr(supervisor, "_write_request", fail_send)
        elif self.mode == "wrong_started":
            original = supervisor._next_response

            async def wrong_started() -> Response:
                response = await original()
                if isinstance(response, StartedResponse):
                    return replace(response, correlation_id=uuid.uuid4().hex)
                return response

            self.monkeypatch.setattr(supervisor, "_next_response", wrong_started)
        else:

            async def malformed_response() -> Response:
                raise ProtocolViolation("injected malformed response frame")

            self.monkeypatch.setattr(supervisor, "_read_response", malformed_response)
        return supervisor


@pytest.mark.parametrize(
    ("mode", "error_type", "diagnostic"),
    [
        ("send", "RunnerProtocolTimeout", "injected execute send failure"),
        ("wrong_started", "RunnerProtocolError", "invalid or uncorrelated started response"),
        ("mangled", "RunnerProtocolTimeout", "injected malformed response frame"),
    ],
)
async def test_fatal_execute_protocol_faults_preserve_count_and_never_auto_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: FaultMode,
    error_type: str,
    diagnostic: str,
) -> None:
    factory = FaultingSupervisorFactory(mode, monkeypatch)
    runtime = KernelRuntime(tmp_path, supervisor_factory=factory)
    host_diagnostics = StringIO()
    try:
        async with (
            asyncio.timeout(10),
            Client(create_server(runtime, diagnostic_stream=host_diagnostics)) as client,
        ):
            killed = await client.call_tool("python_exec", {"code": "42"})
            unavailable = await client.call_tool("python_exec", {"code": "43"})

        killed_result = structured(killed)
        assert killed_result["status"] == "kernel_killed"
        assert killed_result["kernelState"] == "dead"
        assert killed_result["executionCount"] == 0
        assert killed_result["durationMs"] == 0
        assert killed_result["stdout"] == ""
        assert killed_result["stderr"] == ""
        assert killed_result["error"]["type"] == error_type
        assert diagnostic not in str(killed_result)
        assert diagnostic in host_diagnostics.getvalue()
        assert structured(unavailable)["error"]["type"] == "KernelUnavailable"
        assert factory.calls == 1
    finally:
        assert (await asyncio.wait_for(runtime.shutdown(), timeout=5.0)).cleaned
