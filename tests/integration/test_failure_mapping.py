"""Cross-module infrastructure failure mapping and recovery suppression."""

from __future__ import annotations

import asyncio
import os
from io import StringIO
from pathlib import Path
from typing import Any, cast

import pytest
from mcp.client import Client
from mcp.server.lowlevel import Server
from mcp.types import CallToolResult

import amkernel.server as server_module
from amkernel.runtime import KernelRuntime
from amkernel.server import create_server, serve_stdio
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


class ToggleGroupVerification:
    """Signal real groups while deterministically denying cleanup verification."""

    def __init__(self) -> None:
        self.stuck = True

    def signal_group(self, process_group: int, signal_number: int) -> None:
        os.killpg(process_group, signal_number)

    def group_exists(self, process_group: int) -> bool:
        if self.stuck:
            return True
        try:
            os.killpg(process_group, 0)
        except ProcessLookupError:
            return False
        return True


class SupervisorFactory:
    def __init__(self, operations: ToggleGroupVerification) -> None:
        self.operations = operations
        self.calls = 0
        self.supervisors: list[KernelSupervisor] = []

    async def __call__(self, working_directory: Path) -> KernelSupervisor:
        self.calls += 1
        supervisor = await KernelSupervisor.start(working_directory, operations=self.operations)
        self.supervisors.append(supervisor)
        return supervisor


async def test_cleanup_failure_is_generic_public_host_diagnostic_and_blocks_reset(
    tmp_path: Path,
) -> None:
    operations = ToggleGroupVerification()
    factory = SupervisorFactory(operations)
    runtime = KernelRuntime(tmp_path, supervisor_factory=factory)
    host_diagnostics = StringIO()
    try:
        async with (
            asyncio.timeout(12),
            Client(create_server(runtime, diagnostic_stream=host_diagnostics)) as client,
        ):
            killed = await client.call_tool(
                "python_exec",
                {
                    "code": (
                        "import time\n"
                        "while True:\n"
                        "    try:\n"
                        "        time.sleep(1)\n"
                        "    except KeyboardInterrupt:\n"
                        "        pass"
                    ),
                    "timeout": 0.05,
                },
            )
            reset = await client.call_tool(
                "python_exec",
                {"code": "42", "reset": True},
            )

        killed_result = structured(killed)
        assert killed_result["status"] == "kernel_killed"
        assert killed_result["error"] == {
            "type": "CleanupError",
            "message": "managed kernel cleanup failed",
            "traceback": [],
        }
        assert "SIGKILL" not in str(killed_result)
        assert "managed process group remains after SIGKILL" in host_diagnostics.getvalue()

        reset_result = structured(reset)
        assert reset_result["status"] == "kernel_killed"
        assert reset_result["error"]["type"] == "ResetCleanupError"
        assert factory.calls == 1
    finally:
        operations.stuck = False
        assert (await asyncio.wait_for(runtime.shutdown(), timeout=5.0)).cleaned


async def test_real_shutdown_failure_reaches_host_and_nonzero_stdio_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operations = ToggleGroupVerification()
    factory = SupervisorFactory(operations)
    runtime = KernelRuntime(tmp_path, supervisor_factory=factory)
    host_diagnostics = StringIO()
    public_result: CallToolResult | None = None

    async def exercise(server: Server[dict[str, Any]]) -> None:
        nonlocal public_result
        async with Client(server) as client:
            public_result = await client.call_tool("python_exec", {"code": "42"})

    monkeypatch.setattr(server_module, "_run_server_stdio", exercise)
    try:
        exit_code = await serve_stdio(
            tmp_path,
            diagnostic_stream=host_diagnostics,
            runtime_factory=lambda _working_directory: runtime,
        )

        assert exit_code == 1
        assert public_result is not None
        assert structured(public_result)["result"] == 42
        assert "managed process group" not in str(structured(public_result))
        assert "AMKernel shutdown cleanup failed" in host_diagnostics.getvalue()
        assert "managed process group remains after SIGKILL" in host_diagnostics.getvalue()
        assert factory.calls == 1
    finally:
        operations.stuck = False
        if factory.supervisors:
            assert (await asyncio.wait_for(factory.supervisors[0].shutdown(), timeout=5.0)).cleaned
