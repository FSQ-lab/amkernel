"""Real stdio MCP lifecycle through the official Python Client."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import psutil
import pytest
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters
from mcp.types import CallToolResult, TextContent

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
    return content


def text_content(result: CallToolResult) -> str:
    block = result.content[0]
    assert isinstance(block, TextContent)
    return block.text


async def wait_pid_gone(pid: int, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not psutil.pid_exists(pid):
            return True
        await asyncio.sleep(0.02)
    return not psutil.pid_exists(pid)


async def test_official_stdio_client_observes_full_execution_lifecycle(tmp_path: Path) -> None:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "amkernel"],
        cwd=tmp_path,
    )
    child_pid: int | None = None

    async with Client(parameters, read_timeout_seconds=15.0) as client:
        noisy = await client.call_tool(
            "python_exec",
            {"code": ('import os\nos.write(1, b\'{"jsonrpc":"2.0","id":999}\\n\')\n7')},
        )
        listed = await client.list_tools()
        assert [tool.name for tool in listed.tools] == ["python_exec"]

        initial = await client.call_tool("python_exec", {"code": "values = []"})
        failed = await client.call_tool(
            "python_exec",
            {"code": "values.append('kept')\nraise ValueError('bad')"},
        )
        observed = await client.call_tool("python_exec", {"code": "values"})
        reset = await client.call_tool(
            "python_exec",
            {"code": "'values' in globals()", "reset": True},
        )
        timed_out = await client.call_tool(
            "python_exec",
            {"code": "import time\ntime.sleep(30)", "timeout": 0.05},
        )
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
        unavailable = await client.call_tool("python_exec", {"code": "42"})
        recovered = await client.call_tool(
            "python_exec",
            {"code": "42", "reset": True},
        )
        child = await client.call_tool(
            "python_exec",
            {
                "code": (
                    "import subprocess, sys\n"
                    "child = subprocess.Popen([sys.executable, '-c', "
                    "'import time; time.sleep(30)'])\n"
                    "child.pid"
                )
            },
        )

        assert not initial.is_error
        assert json.loads(text_content(initial)) == initial.structured_content
        assert structured(noisy)["result"] == 7
        assert structured(noisy)["stdout"] == '{"jsonrpc":"2.0","id":999}\n'
        assert structured(failed)["status"] == "failed"
        assert structured(failed)["kernelState"] == "alive"
        assert structured(observed)["result"] == ["kept"]
        assert structured(reset)["result"] is False
        assert structured(reset)["executionCount"] == 1
        assert structured(timed_out)["status"] == "timed_out"
        assert structured(timed_out)["kernelState"] == "alive"
        assert structured(killed)["status"] == "kernel_killed"
        assert structured(killed)["kernelState"] == "dead"
        assert structured(unavailable)["error"]["type"] == "KernelUnavailable"
        assert structured(recovered)["result"] == 42
        assert structured(recovered)["executionCount"] == 1
        child_value = structured(child)["result"]
        assert type(child_value) is int
        child_pid = child_value
        assert psutil.pid_exists(child_pid)

    assert child_pid is not None
    assert await wait_pid_gone(child_pid)
