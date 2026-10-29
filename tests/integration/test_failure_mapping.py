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
from amkernel.artifact_store import ArtifactBundle, ArtifactStoreError
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


async def test_terminal_result_failure_kills_discards_and_requires_reset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = KernelRuntime(tmp_path)
    diagnostics = StringIO()
    real_tool_content = server_module._tool_content
    injected = False
    discard = ArtifactBundle.discard
    discard_attempts = 0

    async def fail_discard_once(bundle: ArtifactBundle) -> None:
        nonlocal discard_attempts
        discard_attempts += 1
        if discard_attempts == 1:
            raise ArtifactStoreError("private discard failure")
        await discard(bundle)

    async def fail_once(
        adapter: object,
        outcome: object,
        structured_content: dict[str, Any],
        text: str,
    ) -> list[object]:
        nonlocal injected
        if not injected:
            injected = True
            raise ArtifactStoreError("private terminal construction detail")
        return await real_tool_content(adapter, outcome, structured_content, text)  # type: ignore[arg-type,return-value]

    monkeypatch.setattr(server_module, "_tool_content", fail_once)
    monkeypatch.setattr(ArtifactBundle, "discard", fail_discard_once)
    try:
        async with Client(create_server(runtime, diagnostic_stream=diagnostics)) as client:
            failed = structured(
                await client.call_tool(
                    "python_exec",
                    {"code": "print('kept')\nartifact('secret.txt', 'hidden')"},
                )
            )
            unavailable = structured(await client.call_tool("python_exec", {"code": "42"}))
            recovered = structured(
                await client.call_tool("python_exec", {"code": "42", "reset": True})
            )

        assert failed["status"] == "kernel_killed"
        assert failed["kernelState"] == "dead"
        assert failed["error"] == {
            "type": "ArtifactStoreError",
            "message": "execution output storage failed",
            "traceback": [],
        }
        assert failed["stdout"] == "kept\n"
        assert failed["displays"] == []
        assert failed["artifacts"] == []
        assert unavailable["error"]["type"] == "KernelUnavailable"
        assert recovered["status"] == "completed"
        assert recovered["result"] == 42
        assert discard_attempts == 2
        assert "private terminal construction detail" not in str(failed)
        assert "private terminal construction detail" in diagnostics.getvalue()
    finally:
        assert (await runtime.shutdown()).cleaned


async def test_supervisor_abort_failure_blocks_reset_until_store_cleanup_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = KernelRuntime(tmp_path)
    diagnostics = StringIO()
    store = runtime._artifact_store
    begin_bundle = store.begin_bundle
    seeded = False

    async def begin_seeded_bundle() -> ArtifactBundle:
        nonlocal seeded
        bundle = await begin_bundle()
        if not seeded:
            seeded = True
            for name in ("first.bin", "second.bin"):
                writer = bundle.open_artifact(name, "application/octet-stream")
                writer.write(name.encode())
                writer.finish()
        return bundle

    unlink = os.unlink
    unlink_calls = 0

    def fail_cleanup_retries(path: str, *, dir_fd: int | None = None) -> None:
        nonlocal unlink_calls
        unlink_calls += 1
        if 2 <= unlink_calls <= 5:
            raise OSError("private staged cleanup failure")
        unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(store, "begin_bundle", begin_seeded_bundle)
    monkeypatch.setattr(os, "unlink", fail_cleanup_retries)
    try:
        async with Client(create_server(runtime, diagnostic_stream=diagnostics)) as client:
            failed = structured(await client.call_tool("python_exec", {"code": "42"}))
            blocked = structured(
                await client.call_tool("python_exec", {"code": "42", "reset": True})
            )
            recovered = structured(
                await client.call_tool("python_exec", {"code": "42", "reset": True})
            )

        assert failed["status"] == "kernel_killed"
        assert failed["error"]["type"] == "ArtifactStoreError"
        assert blocked["status"] == "kernel_killed"
        assert blocked["error"]["type"] == "ResetCleanupError"
        assert recovered["status"] == "completed"
        assert recovered["result"] == 42
        assert unlink_calls >= 6
        assert "private staged cleanup failure" in diagnostics.getvalue()
    finally:
        assert (await runtime.shutdown()).cleaned


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
