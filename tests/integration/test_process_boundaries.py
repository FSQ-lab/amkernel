"""Transport-close cleanup and explicit external-resource non-ownership."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any, cast

import psutil
import pytest
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters
from mcp.types import CallToolResult

from amkernel.runtime import KernelRuntime
from amkernel.server import create_server

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
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"timed out waiting for {path}")


async def wait_pid_gone(pid: int, timeout: float = 4.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not psutil.pid_exists(pid):
            return True
        await asyncio.sleep(0.02)
    return not psutil.pid_exists(pid)


def process_group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    return True


async def wait_group_gone(process_group: int, timeout: float = 4.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not process_group_exists(process_group):
            return True
        await asyncio.sleep(0.02)
    return not process_group_exists(process_group)


async def test_stdio_transport_close_bounds_stubborn_active_cleanup(tmp_path: Path) -> None:
    pid_file = tmp_path / "managed-processes.json"
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "amkernel"],
        cwd=tmp_path,
    )
    call: asyncio.Task[CallToolResult] | None = None
    server_pid: int | None = None
    runner_pid: int | None = None
    runner_group: int | None = None
    child_pid: int | None = None
    started = time.monotonic()

    try:
        async with asyncio.timeout(12):
            async with Client(parameters, read_timeout_seconds=3_600.0) as client:
                await client.list_tools()
                code = (
                    "import json, os, subprocess, sys, time\n"
                    "from pathlib import Path\n"
                    "child = subprocess.Popen([sys.executable, '-c', "
                    "'import signal,time; "
                    "signal.signal(signal.SIGINT, signal.SIG_IGN); "
                    "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                    "time.sleep(30)'])\n"
                    f"Path({str(pid_file)!r}).write_text(json.dumps({{"
                    "'server': os.getppid(), 'runner': os.getpid(), "
                    "'group': os.getpgrp(), 'child': child.pid}))\n"
                    "while True:\n"
                    "    try:\n"
                    "        time.sleep(1)\n"
                    "    except KeyboardInterrupt:\n"
                    "        pass"
                )
                call = asyncio.create_task(
                    client.call_tool("python_exec", {"code": code, "timeout": 3_600.0})
                )
                await wait_for_path(pid_file)
                identities = json.loads(pid_file.read_text())
                server_pid = identities["server"]
                runner_pid = identities["runner"]
                runner_group = identities["group"]
                child_pid = identities["child"]
                assert all(psutil.pid_exists(pid) for pid in (server_pid, runner_pid, child_pid))

            assert time.monotonic() - started < 8.0
            assert call is not None
            if not call.done():
                call.cancel()
            await asyncio.gather(call, return_exceptions=True)
            assert await wait_pid_gone(server_pid)
            assert await wait_pid_gone(runner_pid)
            assert await wait_pid_gone(child_pid)
            assert await wait_group_gone(runner_group)
    finally:
        if call is not None and not call.done():
            call.cancel()
            await asyncio.gather(call, return_exceptions=True)
        for process_group in (runner_group, server_pid):
            if process_group is not None and process_group_exists(process_group):
                try:
                    os.killpg(process_group, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        for pid in (runner_pid, child_pid, server_pid):
            if pid is not None:
                assert await wait_pid_gone(pid)


async def test_stdio_active_request_cancellation_stabilizes_same_kernel(
    tmp_path: Path,
) -> None:
    identity_file = tmp_path / "stdio-cancel.json"
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "amkernel"],
        cwd=tmp_path,
    )
    runner_pid: int | None = None
    runner_group: int | None = None
    try:
        async with (
            asyncio.timeout(10),
            Client(
                parameters,
                read_timeout_seconds=30.0,
            ) as client,
        ):
            await client.list_tools()
            active = asyncio.create_task(
                client.call_tool(
                    "python_exec",
                    {
                        "code": (
                            "import json, os, time\n"
                            "from pathlib import Path\n"
                            f"Path({str(identity_file)!r}).write_text(json.dumps({{"
                            "'runner': os.getpid(), 'group': os.getpgrp()}))\n"
                            "time.sleep(30)"
                        ),
                        "timeout": 30.0,
                    },
                )
            )
            await wait_for_path(identity_file)
            identities = json.loads(identity_file.read_text())
            runner_pid = identities["runner"]
            runner_group = identities["group"]
            active.cancel()
            with pytest.raises(asyncio.CancelledError):
                await active

            observed = await client.call_tool("python_exec", {"code": "'alive'"})

            assert structured(observed)["status"] == "completed"
            assert structured(observed)["kernelState"] == "alive"
            assert structured(observed)["executionCount"] == 2
            assert structured(observed)["result"] == "alive"

        assert await wait_pid_gone(runner_pid)
        assert await wait_group_gone(runner_group)
    finally:
        if runner_group is not None and process_group_exists(runner_group):
            try:
                os.killpg(runner_group, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if runner_pid is not None:
            assert await wait_pid_gone(runner_pid)


def spawn_descendant_code() -> str:
    return (
        "import os, subprocess, sys\n"
        "child = subprocess.Popen([sys.executable, '-c', "
        "'import signal,time; signal.signal(signal.SIGINT, signal.SIG_IGN); "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)'])\n"
        "{'runner': os.getpid(), 'group': os.getpgrp(), 'child': child.pid}"
    )


def managed_descendant_code(identity_file: Path, *, catch_interrupt: bool) -> str:
    blocking = (
        "while True:\n    try:\n        time.sleep(1)\n    except KeyboardInterrupt:\n        pass"
        if catch_interrupt
        else "time.sleep(30)"
    )
    return (
        "import json, os, subprocess, sys, time\n"
        "from pathlib import Path\n"
        "child = subprocess.Popen([sys.executable, '-c', "
        "'import signal,time; signal.signal(signal.SIGINT, signal.SIG_IGN); "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)'])\n"
        f"Path({str(identity_file)!r}).write_text(json.dumps({{"
        "'runner': os.getpid(), 'group': os.getpgrp(), 'child': child.pid}))\n"
        f"{blocking}"
    )


async def test_reset_removes_old_runner_group_and_descendant(tmp_path: Path) -> None:
    runtime = KernelRuntime(tmp_path)
    child_pid: int | None = None
    runner_group: int | None = None
    try:
        async with asyncio.timeout(10), Client(create_server(runtime)) as client:
            spawned = await client.call_tool(
                "python_exec",
                {"code": spawn_descendant_code()},
            )
            identities = structured(spawned)["result"]
            child_pid = identities["child"] if isinstance(identities, dict) else None
            runner_group = identities["group"] if isinstance(identities, dict) else None
            reset = await client.call_tool(
                "python_exec",
                {"code": "42", "reset": True},
            )

        assert child_pid is not None and runner_group is not None
        assert structured(reset)["executionCount"] == 1
        assert structured(reset)["result"] == 42
        assert await wait_pid_gone(child_pid)
        assert await wait_group_gone(runner_group)
    finally:
        assert (await asyncio.wait_for(runtime.shutdown(), timeout=5.0)).cleaned


async def test_destructive_timeout_removes_runner_group_and_descendant(tmp_path: Path) -> None:
    runtime = KernelRuntime(tmp_path)
    identity_file = tmp_path / "timeout-identities.json"
    child_pid: int | None = None
    runner_group: int | None = None
    try:
        async with asyncio.timeout(10), Client(create_server(runtime)) as client:
            killed = await client.call_tool(
                "python_exec",
                {
                    "code": managed_descendant_code(identity_file, catch_interrupt=True),
                    "timeout": 0.05,
                },
            )
            identities = json.loads(identity_file.read_text())
            child_pid = identities["child"]
            runner_group = identities["group"]

        assert structured(killed)["status"] == "kernel_killed"
        assert structured(killed)["kernelState"] == "dead"
        assert await wait_pid_gone(child_pid)
        assert await wait_group_gone(runner_group)
    finally:
        assert (await asyncio.wait_for(runtime.shutdown(), timeout=5.0)).cleaned


@pytest.mark.parametrize("catch_interrupt", [False, True])
async def test_active_cancellation_tracks_and_cleans_managed_descendant(
    tmp_path: Path,
    catch_interrupt: bool,
) -> None:
    runtime = KernelRuntime(tmp_path)
    identity_file = tmp_path / f"cancel-{catch_interrupt}.json"
    child_pid: int | None = None
    runner_group: int | None = None
    try:
        async with asyncio.timeout(12), Client(create_server(runtime)) as client:
            await client.list_tools()
            active = asyncio.create_task(
                client.call_tool(
                    "python_exec",
                    {
                        "code": managed_descendant_code(
                            identity_file,
                            catch_interrupt=catch_interrupt,
                        ),
                        "timeout": 30.0,
                    },
                )
            )
            await wait_for_path(identity_file)
            identities = json.loads(identity_file.read_text())
            child_pid = identities["child"]
            runner_group = identities["group"]
            active.cancel()
            with pytest.raises(asyncio.CancelledError):
                await active

            observed = await client.call_tool("python_exec", {"code": "42"})
            if catch_interrupt:
                assert structured(observed)["error"]["type"] == "KernelUnavailable"
                assert await wait_pid_gone(child_pid)
                assert await wait_group_gone(runner_group)
            else:
                assert structured(observed)["status"] == "completed"
                assert structured(observed)["executionCount"] == 2
                assert psutil.pid_exists(child_pid)

            reset = await client.call_tool(
                "python_exec",
                {"code": "'recovered'", "reset": True},
            )

        assert structured(reset)["executionCount"] == 1
        assert await wait_pid_gone(child_pid)
        assert await wait_group_gone(runner_group)
    finally:
        assert (await asyncio.wait_for(runtime.shutdown(), timeout=5.0)).cleaned


async def test_escaped_external_process_is_not_claimed_as_managed(tmp_path: Path) -> None:
    runtime = KernelRuntime(tmp_path)
    escaped_pid: int | None = None
    try:
        async with asyncio.timeout(10), Client(create_server(runtime)) as client:
            escaped = await client.call_tool(
                "python_exec",
                {
                    "code": (
                        "import subprocess, sys\n"
                        "external = subprocess.Popen(\n"
                        "    [sys.executable, '-c', 'import time; time.sleep(30)'],\n"
                        "    stdin=subprocess.DEVNULL,\n"
                        "    stdout=subprocess.DEVNULL,\n"
                        "    stderr=subprocess.DEVNULL,\n"
                        "    close_fds=True,\n"
                        "    start_new_session=True,\n"
                        ")\n"
                        "external.pid"
                    )
                },
            )
            value = structured(escaped)["result"]
            assert type(value) is int
            escaped_pid = value
            assert psutil.pid_exists(escaped_pid)

        shutdown = await asyncio.wait_for(runtime.shutdown(), timeout=5.0)
        assert shutdown.cleaned
        assert psutil.pid_exists(escaped_pid)
    finally:
        try:
            cleanup = await asyncio.wait_for(runtime.shutdown(), timeout=5.0)
        finally:
            if escaped_pid is not None and psutil.pid_exists(escaped_pid):
                try:
                    os.killpg(escaped_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                assert await wait_pid_gone(escaped_pid)
        assert cleanup.cleaned
