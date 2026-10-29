"""Official MCP Client tests for the public python_exec adapter."""

from __future__ import annotations

import asyncio
import json
import os
import signal
from collections import deque
from io import StringIO

import mcp.types as types
import pytest
from mcp.client import Client
from mcp.server.lowlevel import Server

import amkernel.server as server_module
from amkernel.protocol import ErrorInfo, JsonValue, RuntimeDiagnostics
from amkernel.server import (
    MAX_TITLE_CODEPOINTS,
    OUTPUT_SCHEMA,
    TOOL_DESCRIPTION,
    create_server,
    serve_stdio,
)
from amkernel.supervisor import (
    ExecutionStatus,
    KernelState,
    OutputMetadata,
    ShutdownResult,
    SupervisedExecution,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeRuntime:
    def __init__(self, *outcomes: SupervisedExecution | Exception) -> None:
        self.outcomes = deque(outcomes)
        self.calls: list[tuple[str, float, bool]] = []
        self.diagnostic_tail = ""
        self.diagnostic_after = ""
        self.shutdown_result = ShutdownResult(True)
        self.shutdown_calls = 0

    async def execute(
        self,
        code: str,
        *,
        timeout: float = 30.0,
        reset: bool = False,
    ) -> SupervisedExecution:
        self.calls.append((code, timeout, reset))
        self.diagnostic_tail = self.diagnostic_after
        outcome = self.outcomes.popleft()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def shutdown(self) -> ShutdownResult:
        self.shutdown_calls += 1
        return self.shutdown_result


def outcome(
    *,
    status: ExecutionStatus = "completed",
    has_result: bool = False,
    result: JsonValue = None,
    error: ErrorInfo | None = None,
    count: int = 1,
    kernel_state: KernelState = "alive",
) -> SupervisedExecution:
    return SupervisedExecution(
        status=status,
        stdout="out",
        stderr="err",
        has_result=has_result,
        result=result,
        error=error,
        execution_count=count,
        duration_ms=12,
        kernel_state=kernel_state,
        runtime=RuntimeDiagnostics(
            executable="/project/.venv/bin/python",
            python_version="3.11.16",
            working_directory="/project",
            environment_kind="project_venv",
        ),
        output=OutputMetadata(6, 2, False),
    )


def text_content(result: types.CallToolResult) -> str:
    block = result.content[0]
    assert isinstance(block, types.TextContent)
    return block.text


async def test_tool_discovery_publishes_exact_public_contract() -> None:
    runtime = FakeRuntime(outcome())
    server = create_server(runtime)

    async with Client(server) as client:
        listed = await client.list_tools()

    assert len(listed.tools) == 1
    tool = listed.tools[0]
    assert tool.name == "python_exec"
    assert tool.title == "Execute Python"
    assert tool.description == TOOL_DESCRIPTION
    assert "not a sandbox" in tool.description
    assert "not workspace-confined" in tool.description
    assert "managed process group" in tool.description
    assert tool.input_schema["additionalProperties"] is False
    assert tool.input_schema["required"] == ["code"]
    properties = tool.input_schema["properties"]
    assert properties["code"]["maxLength"] == 1_048_576
    assert properties["title"]["maxLength"] == MAX_TITLE_CODEPOINTS
    assert properties["timeout"]["exclusiveMinimum"] == 0
    assert properties["timeout"]["maximum"] == 3_600
    assert properties["reset"]["type"] == "boolean"
    assert tool.output_schema == OUTPUT_SCHEMA
    output_schema = tool.output_schema
    assert output_schema is not None
    assert "result" not in output_schema["required"]
    assert "error" not in output_schema["required"]
    assert output_schema["properties"]["executionCount"]["minimum"] == 0
    assert output_schema["properties"]["durationMs"]["minimum"] == 0
    assert output_schema["$defs"]["ExecutionError"]["additionalProperties"] is False
    assert output_schema["$defs"]["RuntimeInfo"]["additionalProperties"] is False
    assert output_schema["$defs"]["OutputInfo"]["additionalProperties"] is False
    assert output_schema["$defs"]["ArtifactRef"]["additionalProperties"] is False


async def test_structured_content_distinguishes_absent_result_from_null() -> None:
    runtime = FakeRuntime(
        outcome(has_result=False),
        outcome(has_result=True, result=None, count=2),
    )
    server = create_server(runtime)

    async with Client(server) as client:
        absent = await client.call_tool("python_exec", {"code": "x = 1", "title": "assign"})
        null = await client.call_tool(
            "python_exec",
            {"code": "None", "timeout": 2, "reset": True},
        )

    assert not absent.is_error
    assert absent.structured_content is not None
    assert "result" not in absent.structured_content
    assert json.loads(text_content(absent)) == absent.structured_content
    assert not null.is_error
    assert null.structured_content is not None
    assert null.structured_content["result"] is None
    assert json.loads(text_content(null)) == null.structured_content
    assert runtime.calls == [("x = 1", 30.0, False), ("None", 2.0, True)]


@pytest.mark.parametrize(
    ("execution", "expected_status", "expected_state"),
    [
        (
            outcome(
                status="failed",
                error=ErrorInfo("ValueError", "bad", ("trace line",)),
            ),
            "failed",
            "alive",
        ),
        (
            outcome(
                status="timed_out",
                error=ErrorInfo("TimeoutError", "timed out", ()),
            ),
            "timed_out",
            "alive",
        ),
        (
            outcome(
                status="kernel_killed",
                error=ErrorInfo("KernelExited", "kernel process exited unexpectedly", ()),
                kernel_state="dead",
            ),
            "kernel_killed",
            "dead",
        ),
    ],
)
async def test_execution_statuses_are_successful_mcp_results(
    execution: SupervisedExecution,
    expected_status: str,
    expected_state: str,
) -> None:
    runtime = FakeRuntime(execution)

    async with Client(create_server(runtime)) as client:
        result = await client.call_tool("python_exec", {"code": "raise ValueError"})

    assert not result.is_error
    assert execution.error is not None
    assert result.structured_content is not None
    assert result.structured_content["status"] == expected_status
    assert result.structured_content["kernelState"] == expected_state
    assert result.structured_content["error"] == {
        "type": execution.error.type,
        "message": execution.error.message,
        "traceback": list(execution.error.traceback),
    }
    assert result.structured_content["artifacts"] == []
    assert "artifact" not in result.structured_content["output"]


@pytest.mark.parametrize(
    "arguments",
    [
        {"code": "1", "\nforged-host-line": "x" * 10_000},
        {"code": "1", "unknown": True},
        {"code": "1", "title": "x" * (MAX_TITLE_CODEPOINTS + 1)},
        {"code": "1", "title": None},
        {"code": "1", "timeout": 0},
        {"code": "1", "timeout": float("nan")},
        {"code": "1", "reset": "false"},
        {"code": "é" * 524_288 + "a"},
    ],
)
async def test_invalid_arguments_fail_before_runtime_dispatch(arguments: dict[str, object]) -> None:
    runtime = FakeRuntime(outcome())
    stream = StringIO()

    async with Client(create_server(runtime, diagnostic_stream=stream)) as client:
        result = await client.call_tool("python_exec", arguments)

    assert result.is_error
    assert runtime.calls == []
    assert stream.getvalue() == "python_exec rejected invalid arguments\n"


async def test_adapter_defect_is_generic_mcp_tool_error() -> None:
    runtime = FakeRuntime(RuntimeError("private adapter detail"))

    async with Client(create_server(runtime)) as client:
        result = await client.call_tool("python_exec", {"code": "1"})

    assert result.is_error
    assert "private adapter detail" not in text_content(result)
    assert result.structured_content is None


async def test_malformed_runtime_output_becomes_generic_tool_error() -> None:
    runtime = FakeRuntime(outcome(count=-1))

    async with Client(create_server(runtime)) as client:
        result = await client.call_tool("python_exec", {"code": "1"})

    assert result.is_error
    assert "-1" not in text_content(result)
    assert result.structured_content is None


async def test_runtime_diagnostics_are_written_only_to_host_stream() -> None:
    stream = StringIO()
    runtime = FakeRuntime(outcome(has_result=True, result=42))
    runtime.diagnostic_after = "process-group operation failed: injected\n"

    async with Client(create_server(runtime, diagnostic_stream=stream)) as client:
        result = await client.call_tool("python_exec", {"code": "42"})

    assert not result.is_error
    assert "process-group operation failed: injected" in stream.getvalue()
    assert "process-group operation failed" not in text_content(result)
    assert "process-group operation failed" not in json.dumps(result.structured_content)


async def test_serve_stdio_reports_cleanup_failure_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = FakeRuntime(outcome())
    runtime.diagnostic_tail = "host diagnostic\n"
    runtime.shutdown_result = ShutdownResult(False, "group remains")
    stream = StringIO()

    async def return_immediately(_server: Server[dict[str, object]]) -> None:
        return None

    monkeypatch.setattr(server_module, "_run_server_stdio", return_immediately)

    exit_code = await serve_stdio(
        diagnostic_stream=stream,
        runtime_factory=lambda _working_directory: runtime,
    )

    assert exit_code == 1
    assert runtime.shutdown_calls == 1
    assert stream.getvalue().count("host diagnostic") == 1
    assert "AMKernel shutdown cleanup failed: group remains" in stream.getvalue()


async def test_serve_stdio_cleans_runtime_when_transport_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = FakeRuntime(outcome())

    async def fail_transport(_server: Server[dict[str, object]]) -> None:
        raise RuntimeError("transport failed")

    monkeypatch.setattr(server_module, "_run_server_stdio", fail_transport)

    with pytest.raises(RuntimeError, match="transport failed"):
        await serve_stdio(runtime_factory=lambda _working_directory: runtime)

    assert runtime.shutdown_calls == 1


async def test_serve_stdio_defers_sigterm_through_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BlockingShutdownRuntime(FakeRuntime):
        def __init__(self) -> None:
            super().__init__(outcome())
            self.shutdown_entered = asyncio.Event()
            self.shutdown_release = asyncio.Event()

        async def shutdown(self) -> ShutdownResult:
            self.shutdown_calls += 1
            self.shutdown_entered.set()
            await self.shutdown_release.wait()
            return self.shutdown_result

    runtime = BlockingShutdownRuntime()
    observed: list[int] = []

    async def return_immediately(_server: Server[dict[str, object]]) -> None:
        return None

    def prior_handler(signal_number: int, _frame: object) -> None:
        observed.append(signal_number)

    monkeypatch.setattr(server_module, "_run_server_stdio", return_immediately)
    original = signal.signal(signal.SIGTERM, prior_handler)
    try:
        operation = asyncio.create_task(
            serve_stdio(runtime_factory=lambda _working_directory: runtime)
        )
        await runtime.shutdown_entered.wait()
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.sleep(0)

        assert observed == []
        assert not operation.done()
        runtime.shutdown_release.set()
        assert await operation == 0

        assert runtime.shutdown_calls == 1
        assert observed == [signal.SIGTERM]
        assert signal.getsignal(signal.SIGTERM) is prior_handler
    finally:
        signal.signal(signal.SIGTERM, original)


async def test_serve_stdio_restores_sigterm_handler_when_shutdown_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingShutdownRuntime(FakeRuntime):
        async def shutdown(self) -> ShutdownResult:
            self.shutdown_calls += 1
            raise RuntimeError("shutdown failed")

    runtime = FailingShutdownRuntime(outcome())

    async def return_immediately(_server: Server[dict[str, object]]) -> None:
        return None

    monkeypatch.setattr(server_module, "_run_server_stdio", return_immediately)
    original = signal.getsignal(signal.SIGTERM)

    with pytest.raises(RuntimeError, match="shutdown failed"):
        await serve_stdio(runtime_factory=lambda _working_directory: runtime)

    assert runtime.shutdown_calls == 1
    assert signal.getsignal(signal.SIGTERM) is original
