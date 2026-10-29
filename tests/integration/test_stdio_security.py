"""Raw stdio evidence for default no-network/no-elevation/protocol-only behavior."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from pathlib import Path
from typing import Any

import psutil
import pytest
from mcp.types.version import LATEST_HANDSHAKE_VERSION

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(os.name != "posix", reason="Stage 1 Runtime is POSIX-only"),
]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def send_message(process: asyncio.subprocess.Process, message: dict[str, Any]) -> None:
    assert process.stdin is not None
    process.stdin.write(json.dumps(message, separators=(",", ":")).encode() + b"\n")
    await process.stdin.drain()


async def read_response(process: asyncio.subprocess.Process, request_id: int) -> dict[str, Any]:
    assert process.stdout is not None
    line = await asyncio.wait_for(process.stdout.readline(), timeout=5.0)
    assert line.endswith(b"\n")
    response = json.loads(line)
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == request_id
    assert "error" not in response
    return dict(response)


async def test_default_stdio_emits_only_mcp_and_opens_no_network_or_privilege(
    tmp_path: Path,
) -> None:
    baseline = psutil.Process()
    baseline_uid = baseline.uids().effective
    baseline_gid = baseline.gids().effective
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "amkernel",
        cwd=tmp_path,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    observed_connections: list[tuple[int, str]] = []
    observed_credentials: list[tuple[int, int, int]] = []
    observed_pids: set[int] = set()
    stop_sampling = asyncio.Event()

    async def sample_process_tree() -> None:
        while not stop_sampling.is_set():
            try:
                root = psutil.Process(process.pid)
                processes = [root, *root.children(recursive=True)]
            except psutil.NoSuchProcess:
                return
            for current in processes:
                try:
                    observed_pids.add(current.pid)
                    observed_credentials.append(
                        (current.pid, current.uids().effective, current.gids().effective)
                    )
                    for connection in current.net_connections(kind="inet"):
                        observed_connections.append((current.pid, str(connection.laddr)))
                except psutil.NoSuchProcess:
                    continue
                except psutil.AccessDenied:
                    pytest.skip("host denies per-process socket inspection")
            await asyncio.sleep(0.002)

    sampler = asyncio.create_task(sample_process_tree())
    runner_pid: int | None = None
    runner_group: int | None = None
    try:
        async with asyncio.timeout(15):
            await send_message(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": LATEST_HANDSHAKE_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "raw-evidence", "version": "1"},
                    },
                },
            )
            initialized = await read_response(process, 1)
            assert initialized["result"]["serverInfo"]["name"] == "amkernel"
            await send_message(
                process,
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
            )
            await send_message(
                process,
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            )
            listed = await read_response(process, 2)
            assert [tool["name"] for tool in listed["result"]["tools"]] == ["python_exec"]
            await send_message(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "python_exec",
                        "arguments": {
                            "code": (
                                "import os\n"
                                "{'runner': os.getpid(), 'group': os.getpgrp(), "
                                "'server': os.getppid(), 'uid': os.geteuid(), "
                                "'gid': os.getegid()}"
                            )
                        },
                    },
                },
            )
            called = await read_response(process, 3)
            runtime_identity = called["result"]["structuredContent"]["result"]
            runner_pid = runtime_identity["runner"]
            runner_group = runtime_identity["group"]
            assert runtime_identity["server"] == process.pid
            assert runtime_identity["uid"] == baseline_uid
            assert runtime_identity["gid"] == baseline_gid

            assert process.stdin is not None
            process.stdin.close()
            await process.stdin.wait_closed()
            assert await asyncio.wait_for(process.wait(), timeout=5.0) == 0
            assert process.stdout is not None
            assert await process.stdout.read() == b""

        stop_sampling.set()
        await sampler
        assert observed_credentials
        assert all(
            uid == baseline_uid and gid == baseline_gid for _, uid, gid in observed_credentials
        )
        assert runner_pid is not None
        assert process.pid in observed_pids
        assert runner_pid in observed_pids
        assert observed_connections == []
        assert not psutil.pid_exists(runner_pid)
    finally:
        stop_sampling.set()
        await asyncio.gather(sampler, return_exceptions=True)
        for process_group in (runner_group, process.pid):
            if process_group is None:
                continue
            try:
                os.killpg(process_group, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process.returncode is None:
            process.kill()
        await process.wait()
