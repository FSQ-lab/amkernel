"""Black-box contracts crossing Runner, Supervisor, Runtime, and MCP Adapter."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, cast

import psutil
import pytest
from mcp.client import Client
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


async def wait_for_queued_code(runtime: KernelRuntime, expected: list[str]) -> None:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        queued = [command.code for command in runtime._commands]
        if queued == expected:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"queued code did not reach expected order: {queued!r}")


async def test_public_result_and_error_boundaries_remain_structured(tmp_path: Path) -> None:
    runtime = KernelRuntime(tmp_path)
    try:
        async with asyncio.timeout(15), Client(create_server(runtime)) as client:
            nested = await client.call_tool(
                "python_exec",
                {"code": "{'items': [1, True, None, {'nested': 'value'}]}"},
            )
            non_json = await client.call_tool("python_exec", {"code": "{1, 2}"})
            cycle = await client.call_tool(
                "python_exec",
                {"code": "value = []\nvalue.append(value)\nvalue"},
            )
            bad_repr = await client.call_tool(
                "python_exec",
                {
                    "code": (
                        "class BadRepr:\n"
                        "    def __repr__(self):\n"
                        "        raise RuntimeError('no repr')\n"
                        "BadRepr()"
                    )
                },
            )
            nonfinite = await client.call_tool("python_exec", {"code": "float('nan')"})
            oversized = await client.call_tool("python_exec", {"code": "'x' * 1_048_577"})
            failed = await client.call_tool(
                "python_exec",
                {"code": "values = ['kept']\nraise ValueError('\\x00' * (2 * 1024 * 1024))"},
            )
            recovered = await client.call_tool("python_exec", {"code": "values"})
            maximum_code = "\0" * 1_048_576
            assert len(maximum_code.encode("utf-8")) == 1_048_576
            maximum = await client.call_tool("python_exec", {"code": maximum_code})

        assert structured(nested)["result"] == {"items": [1, True, None, {"nested": "value"}]}
        for result in (non_json, cycle, bad_repr, nonfinite, oversized):
            representation = structured(result)["result"]
            assert representation["kind"] == "repr"
            assert len(json.dumps(representation, separators=(",", ":")).encode()) <= 8_192
        error = structured(failed)["error"]
        assert structured(failed)["status"] == "failed"
        assert len(json.dumps(error, separators=(",", ":")).encode()) <= 65_536
        assert structured(recovered)["result"] == ["kept"]
        assert structured(recovered)["kernelState"] == "alive"
        assert structured(maximum)["status"] == "failed"
        assert structured(maximum)["error"]["type"] == "SyntaxError"
    finally:
        assert (await asyncio.wait_for(runtime.shutdown(), timeout=5.0)).cleaned


async def test_real_runtime_fifo_and_queued_cancellation_are_observable(
    tmp_path: Path,
) -> None:
    started = tmp_path / "started"
    release = tmp_path / "release"
    runtime = KernelRuntime(tmp_path)
    try:
        async with asyncio.timeout(10), Client(create_server(runtime)) as client:
            await client.list_tools()
            first = asyncio.create_task(
                client.call_tool(
                    "python_exec",
                    {
                        "code": (
                            "import time\n"
                            "from pathlib import Path\n"
                            "order = []\n"
                            f"Path({str(started)!r}).write_text('ready')\n"
                            f"while not Path({str(release)!r}).exists(): time.sleep(0.01)\n"
                            "order.append('first')"
                        )
                    },
                )
            )
            await wait_for_path(started)
            abandoned = asyncio.create_task(
                client.call_tool("python_exec", {"code": "order.append('abandoned')"})
            )
            last = asyncio.create_task(
                client.call_tool("python_exec", {"code": "order.append('last')\norder"})
            )
            await wait_for_queued_code(
                runtime,
                ["order.append('abandoned')", "order.append('last')\norder"],
            )
            abandoned.cancel()
            with pytest.raises(asyncio.CancelledError):
                await abandoned
            release.touch()

            first_result, last_result = await asyncio.gather(first, last)

        assert structured(first_result)["executionCount"] == 1
        assert structured(last_result)["executionCount"] == 2
        assert structured(last_result)["result"] == ["first", "last"]
    finally:
        assert (await asyncio.wait_for(runtime.shutdown(), timeout=5.0)).cleaned


async def test_official_client_active_cancellation_stabilizes_live_kernel(
    tmp_path: Path,
) -> None:
    started = tmp_path / "active-started"
    runtime = KernelRuntime(tmp_path)
    try:
        async with asyncio.timeout(10), Client(create_server(runtime)) as client:
            await client.list_tools()
            active = asyncio.create_task(
                client.call_tool(
                    "python_exec",
                    {
                        "code": (
                            "import time\n"
                            "from pathlib import Path\n"
                            f"Path({str(started)!r}).write_text('ready')\n"
                            "time.sleep(30)"
                        ),
                        "timeout": 30.0,
                    },
                )
            )
            await wait_for_path(started)
            active.cancel()
            with pytest.raises(asyncio.CancelledError):
                await active

            observed = await client.call_tool("python_exec", {"code": "'alive'"})

        assert structured(observed)["status"] == "completed"
        assert structured(observed)["kernelState"] == "alive"
        assert structured(observed)["executionCount"] == 2
        assert structured(observed)["result"] == "alive"
    finally:
        assert (await asyncio.wait_for(runtime.shutdown(), timeout=5.0)).cleaned


async def test_deleted_cwd_death_and_explicit_reset_are_publicly_truthful(tmp_path: Path) -> None:
    runtime = KernelRuntime(tmp_path)
    try:
        async with asyncio.timeout(10), Client(create_server(runtime)) as client:
            killed = await client.call_tool(
                "python_exec",
                {
                    "code": (
                        "import os, tempfile\n"
                        f"path = tempfile.mkdtemp(dir={str(tmp_path)!r})\n"
                        "os.chdir(path)\n"
                        "os.rmdir(path)"
                    )
                },
            )
            unavailable = await client.call_tool("python_exec", {"code": "42"})
            recovered = await client.call_tool(
                "python_exec",
                {"code": "import os\nos.getcwd()", "reset": True},
            )

        assert structured(killed)["status"] == "kernel_killed"
        assert structured(killed)["error"]["type"] == "RuntimeDiagnosticsError"
        assert structured(killed)["kernelState"] == "dead"
        assert structured(unavailable)["error"]["type"] == "KernelUnavailable"
        assert structured(recovered)["status"] == "completed"
        assert structured(recovered)["executionCount"] == 1
        assert structured(recovered)["result"] == str(tmp_path)
    finally:
        assert (await asyncio.wait_for(runtime.shutdown(), timeout=5.0)).cleaned


async def test_public_environment_is_filtered_isolated_and_noninteractive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    temporary = tmp_path / "tmp"
    home.mkdir()
    temporary.mkdir()
    forwarded = {
        "HOME": str(home),
        "LANG": "C",
        "LC_ALL": "C",
        "LC_CTYPE": "C",
        "LOGNAME": "amkernel-logname-sentinel",
        "PATH": "/amkernel/path-sentinel",
        "SHELL": "/amkernel/shell-sentinel",
        "TERM": "amkernel-term-sentinel",
        "TMPDIR": str(temporary),
        "TZ": "UTC0",
        "USER": "amkernel-user-sentinel",
    }
    denied = {
        "OPENAI_API_KEY": "openai-secret",
        "ANTHROPIC_API_KEY": "anthropic-secret",
        "AWS_ACCESS_KEY_ID": "aws-access",
        "AWS_SECRET_ACCESS_KEY": "aws-secret",
        "AZURE_CLIENT_SECRET": "azure-secret",
        "GOOGLE_APPLICATION_CREDENTIALS": "/gcp-secret.json",
        "HTTP_PROXY": "http://upper-proxy.invalid",
        "HTTPS_PROXY": "https://upper-proxy.invalid",
        "ALL_PROXY": "socks://upper-proxy.invalid",
        "NO_PROXY": "upper-no-proxy",
        "http_proxy": "http://lower-proxy.invalid",
        "https_proxy": "https://lower-proxy.invalid",
        "all_proxy": "socks://lower-proxy.invalid",
        "no_proxy": "lower-no-proxy",
        "PYTHONHOME": "/untrusted-home",
        "PYTHONPATH": "/untrusted-path",
        "PYTHONWARNINGS": "error",
        "VIRTUAL_ENV": "/forged-parent-venv",
        "AMKERNEL_RANDOM_SECRET": "application-secret",
    }
    for key, value in (forwarded | denied).items():
        monkeypatch.setenv(key, value)
    host = psutil.Process()
    listeners_before = {
        str(connection.laddr)
        for connection in host.net_connections(kind="inet")
        if connection.status == psutil.CONN_LISTEN
    }
    runtime = KernelRuntime(tmp_path)
    try:
        async with asyncio.timeout(10), Client(create_server(runtime)) as client:
            observed = await client.call_tool(
                "python_exec",
                {
                    "code": (
                        "import os, site, sys\n"
                        "{'environment': dict(os.environ), "
                        "'isolated': sys.flags.isolated, "
                        "'utf8': sys.flags.utf8_mode, "
                        "'writeThrough': sys.stdout.write_through, "
                        "'userSite': site.ENABLE_USER_SITE, "
                        "'stdinIsNone': sys.stdin is None}"
                    )
                },
            )
            interactive = await client.call_tool("python_exec", {"code": "input()"})

        result = structured(observed)["result"]
        environment = result["environment"]
        expected = forwarded | {"VIRTUAL_ENV": os.path.abspath(sys.prefix)}
        observed_environment = dict(environment)
        expected_lc_ctype = expected.pop("LC_CTYPE")
        observed_lc_ctype = observed_environment.pop("LC_CTYPE")
        if sys.platform == "darwin":
            assert observed_environment.pop("__CF_USER_TEXT_ENCODING")
        assert observed_environment == expected
        assert observed_lc_ctype in {expected_lc_ctype, "UTF-8"}
        assert result["isolated"] == 1
        assert result["utf8"] == 1
        assert result["stdinIsNone"] is False
        assert result["writeThrough"] is True
        assert result["userSite"] is False
        assert structured(interactive)["status"] == "failed"
        assert structured(interactive)["error"]["type"] == "EOFError"

        runners = [
            child
            for child in psutil.Process().children(recursive=True)
            if "amkernel.runner" in child.cmdline()
        ]
        assert len(runners) == 1
        runner = runners[0]
        if hasattr(runner, "uids"):
            assert runner.uids().effective == psutil.Process().uids().effective
        assert runner.net_connections(kind="inet") == []
        listeners_after = {
            str(connection.laddr)
            for connection in host.net_connections(kind="inet")
            if connection.status == psutil.CONN_LISTEN
        }
        assert listeners_after <= listeners_before
    finally:
        assert (await asyncio.wait_for(runtime.shutdown(), timeout=5.0)).cleaned
