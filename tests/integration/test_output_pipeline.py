"""Cross-module output bounds, memory plateau, and attribution semantics."""

from __future__ import annotations

import asyncio
import gc
import os
from pathlib import Path
from typing import Any, cast

import psutil
import pytest
from mcp.client import Client
from mcp.types import CallToolResult

from amkernel.runtime import KernelRuntime
from amkernel.server import create_server
from amkernel.supervisor import STREAM_TAIL_BYTES

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


async def wait_for_path(path: Path, timeout: float = 3.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if path.exists():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"timed out waiting for {path}")


def runner_process() -> psutil.Process:
    runners = [
        child
        for child in psutil.Process().children(recursive=True)
        if "amkernel.runner" in child.cmdline()
    ]
    assert len(runners) == 1
    return runners[0]


async def execute_with_rss_peaks(
    client: Client,
    runner: psutil.Process,
    total_bytes: int,
) -> tuple[dict[str, Any], int, int]:
    per_channel = total_bytes // 2
    chunk_bytes = 65_536
    iterations = per_channel // chunk_bytes
    code = (
        "import os\n"
        f"chunk = b'x' * {chunk_bytes}\n"
        f"for _ in range({iterations}):\n"
        "    os.write(1, chunk)\n"
        "    os.write(2, chunk)"
    )
    host = psutil.Process()
    host_peak = host.memory_info().rss
    runner_peak = runner.memory_info().rss
    call = asyncio.create_task(client.call_tool("python_exec", {"code": code, "timeout": 30.0}))
    while not call.done():
        host_peak = max(host_peak, host.memory_info().rss)
        runner_peak = max(runner_peak, runner.memory_info().rss)
        await asyncio.sleep(0.002)
    result = await call
    return structured(result), host_peak, runner_peak


async def test_large_output_counts_stay_exact_while_memory_plateaus(tmp_path: Path) -> None:
    runtime = KernelRuntime(tmp_path)
    try:
        async with asyncio.timeout(60), Client(create_server(runtime)) as client:
            await client.call_tool("python_exec", {"code": "None"})
            runner = runner_process()
            gc.collect()
            medium, host_medium, runner_medium = await execute_with_rss_peaks(
                client,
                runner,
                16 * 1024 * 1024,
            )
            gc.collect()
            large, host_large, runner_large = await execute_with_rss_peaks(
                client,
                runner,
                256 * 1024 * 1024,
            )

        for expected, result in (
            (16 * 1024 * 1024, medium),
            (256 * 1024 * 1024, large),
        ):
            assert result["status"] == "completed"
            assert result["output"] == {
                "totalBytes": expected,
                "totalLines": 2,
                "truncated": True,
            }
            assert len(result["stdout"].encode()) <= STREAM_TAIL_BYTES
            assert len(result["stderr"].encode()) <= STREAM_TAIL_BYTES
            assert result["artifacts"] == []

        maximum_growth = 16 * 1024 * 1024
        assert host_large - host_medium < maximum_growth
        assert runner_large - runner_medium < maximum_growth
    finally:
        assert (await asyncio.wait_for(runtime.shutdown(), timeout=5.0)).cleaned


async def test_idle_output_is_discarded_but_overlapping_output_is_attributed(
    tmp_path: Path,
) -> None:
    idle_gate = tmp_path / "idle-gate"
    idle_written = tmp_path / "idle-written"
    overlap_gate = tmp_path / "overlap-gate"
    active = tmp_path / "active"
    overlap_written = tmp_path / "overlap-written"
    runtime = KernelRuntime(tmp_path)
    try:
        async with asyncio.timeout(10), Client(create_server(runtime)) as client:
            idle_producer = await client.call_tool(
                "python_exec",
                {
                    "code": (
                        "import os, threading, time\n"
                        "from pathlib import Path\n"
                        "def idle_worker():\n"
                        f"    while not Path({str(idle_gate)!r}).exists(): time.sleep(0.01)\n"
                        "    os.write(1, b'idle-late\\n')\n"
                        f"    Path({str(idle_written)!r}).touch()\n"
                        "threading.Thread(target=idle_worker, daemon=True).start()"
                    )
                },
            )
            idle_gate.touch()
            await wait_for_path(idle_written)
            after_idle = await client.call_tool("python_exec", {"code": "42"})

            overlapping_producer = await client.call_tool(
                "python_exec",
                {
                    "code": (
                        "def overlap_worker():\n"
                        f"    while not Path({str(overlap_gate)!r}).exists(): time.sleep(0.01)\n"
                        "    os.write(1, b'overlap\\n')\n"
                        f"    Path({str(overlap_written)!r}).touch()\n"
                        "threading.Thread(target=overlap_worker, daemon=True).start()"
                    )
                },
            )
            overlapped_call = asyncio.create_task(
                client.call_tool(
                    "python_exec",
                    {
                        "code": (
                            f"Path({str(active)!r}).touch()\n"
                            f"while not Path({str(overlap_written)!r}).exists(): time.sleep(0.01)\n"
                            "'complete'"
                        )
                    },
                )
            )
            await wait_for_path(active)
            overlap_gate.touch()
            overlapped = await overlapped_call

        assert structured(idle_producer)["stdout"] == ""
        assert structured(after_idle)["stdout"] == ""
        assert structured(overlapping_producer)["stdout"] == ""
        assert structured(overlapped)["stdout"] == "overlap\n"
        assert structured(overlapped)["result"] == "complete"
    finally:
        assert (await asyncio.wait_for(runtime.shutdown(), timeout=5.0)).cleaned


async def test_first_instruction_fragmented_exec_and_fork_output_remains_user_data(
    tmp_path: Path,
) -> None:
    runtime = KernelRuntime(tmp_path)
    try:
        async with asyncio.timeout(10), Client(create_server(runtime)) as client:
            result = await client.call_tool(
                "python_exec",
                {
                    "code": (
                        "__import__('os').write(1, b'first')\n"
                        "import os, subprocess, sys\n"
                        "os.write(1, b'A')\nos.write(2, b'1')\n"
                        "os.write(1, b'\\xff')\nos.write(2, b'2')\n"
                        "os.write(1, b'B')\n"
                        "subprocess.run([sys.executable, '-c', "
                        "\"import os; os.write(1,b'exec-out'); os.write(2,b'exec-err')\"], "
                        "check=True)\n"
                        "pid = os.fork()\n"
                        "if pid == 0:\n"
                        "    os.write(1, b'fork-out')\n"
                        "    os.write(2, b'fork-err')\n"
                        "    os._exit(0)\n"
                        "os.waitpid(pid, 0)\n"
                        "'complete'"
                    )
                },
            )

        public = structured(result)
        expected_stdout = b"firstA\xffBexec-outfork-out"
        expected_stderr = b"12exec-errfork-err"
        assert public["status"] == "completed"
        assert public["result"] == "complete"
        assert public["stdout"] == expected_stdout.decode(errors="replace")
        assert public["stderr"] == expected_stderr.decode(errors="replace")
        assert public["output"]["totalBytes"] == len(expected_stdout) + len(expected_stderr)
        assert public["output"]["totalLines"] == 2
    finally:
        assert (await asyncio.wait_for(runtime.shutdown(), timeout=5.0)).cleaned
