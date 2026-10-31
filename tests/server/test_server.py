"""Official MCP Client tests for the public python_exec adapter."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import replace
from io import StringIO
from itertools import pairwise
from pathlib import Path
from typing import cast

import mcp.types as types
import pytest
from mcp.client import Client
from mcp.server.lowlevel import Server
from mcp.server.session import ServerSession
from mcp.shared.dispatcher import ProgressFnT
from mcp.shared.exceptions import MCPError

import amkernel.server as server_module
from amkernel.artifact_store import (
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    ArtifactRecord,
    ArtifactResource,
)
from amkernel.output import DisplayRecord, OutputObserver, OutputResult, OutputSnapshot
from amkernel.protocol import ErrorInfo, JsonValue, RuntimeDiagnostics
from amkernel.server import (
    MAX_TITLE_CODEPOINTS,
    OUTPUT_SCHEMA,
    TOOL_DESCRIPTION,
    create_server,
    serve_stdio,
)
from amkernel.structured_output import ImageInfo
from amkernel.supervisor import (
    ExecutionStatus,
    KernelState,
    ShutdownResult,
    SupervisedExecution,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeRuntime:
    def __init__(
        self,
        *outcomes: SupervisedExecution | Exception,
        resource: ArtifactResource | Exception | None = None,
    ) -> None:
        self.outcomes = deque(outcomes)
        self.resource = resource
        self.resource_calls: list[str] = []
        self.calls: list[tuple[str, float, bool, tuple[str, ...]]] = []
        self.diagnostic_tail = ""
        self.diagnostic_after = ""
        self.shutdown_result = ShutdownResult(True)
        self.shutdown_calls = 0
        self.progress_snapshots: list[OutputSnapshot] = []
        self.progress_interval = 0.0

    async def execute(
        self,
        code: str,
        *,
        timeout: float = 30.0,
        reset: bool = False,
        packages: tuple[str, ...] = (),
        observer: OutputObserver | None = None,
        result_finalizer: Callable[[SupervisedExecution], Awaitable[None]] | None = None,
    ) -> SupervisedExecution:
        self.calls.append((code, timeout, reset, packages))
        if observer is not None:
            for snapshot in self.progress_snapshots:
                observer._publish(snapshot)
                await asyncio.sleep(self.progress_interval)
        self.diagnostic_tail = self.diagnostic_after
        outcome = self.outcomes.popleft()
        if isinstance(outcome, Exception):
            raise outcome
        if result_finalizer is not None:
            await result_finalizer(outcome)
        return outcome

    async def read_resource(self, uri: str) -> ArtifactResource:
        self.resource_calls.append(uri)
        if self.resource is None:
            raise ArtifactNotFoundError("resource not found")
        if isinstance(self.resource, Exception):
            raise self.resource
        return self.resource

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
        output=OutputResult(
            stdout="out",
            stderr="err",
            total_bytes=6,
            total_lines=2,
            discarded_bytes=0,
            discarded_lines=0,
            truncated=False,
            limit_bytes=256 * 1024 * 1024,
            limit_exceeded=False,
        ),
    )


def artifact_record(
    name: str,
    *,
    mime_type: str = "application/octet-stream",
    size: int = 3,
) -> ArtifactRecord:
    identifier = name.replace(".", "-")
    return ArtifactRecord(
        uri=f"amkernel://artifact/server/{identifier}",
        name=name,
        declared_mime_type=mime_type,
        mime_type=mime_type,
        representation="raw",
        size=size,
        sha256="a" * 64,
    )


async def test_final_content_uses_official_models_in_deterministic_order() -> None:
    image = artifact_record("plot.png", mime_type="image/png")
    attachment = artifact_record("data.bin")
    stdout = artifact_record("stdout.txt", mime_type="text/plain; charset=utf-8")
    stderr = artifact_record("stderr.txt", mime_type="text/plain; charset=utf-8")
    execution = replace(
        outcome(has_result=True, result=42),
        output=OutputResult(
            stdout="out",
            stderr="err",
            total_bytes=6,
            total_lines=2,
            discarded_bytes=0,
            discarded_lines=0,
            truncated=False,
            limit_bytes=268_435_456,
            limit_exceeded=False,
            stdout_artifact=stdout,
            stderr_artifact=stderr,
            displays=(
                DisplayRecord(
                    sequence=1,
                    kind="image",
                    artifact=image,
                    image=ImageInfo(1, 1, 1, 1),
                ),
                DisplayRecord(sequence=2, kind="json", value={"answer": 42}),
                DisplayRecord(sequence=3, kind="artifact", artifact=attachment),
            ),
            explicit_artifacts=(image, attachment),
        ),
    )
    runtime = FakeRuntime(
        execution,
        resource=ArtifactResource(
            uri=image.uri,
            mime_type="image/png",
            data=b"png",
            text=False,
        ),
    )

    async with Client(create_server(runtime)) as client:
        result = await client.call_tool("python_exec", {"code": "42"})

    assert not result.is_error
    assert result.structured_content is not None
    canonical = json.dumps(
        result.structured_content,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    assert isinstance(result.content[0], types.TextContent)
    assert result.content[0].text == canonical
    assert isinstance(result.content[1], types.ImageContent)
    assert result.content[1].data == "cG5n"
    assert result.content[1].mime_type == "image/png"
    links = result.content[2:6]
    assert all(isinstance(item, types.ResourceLink) for item in links)
    assert [str(item.uri) for item in links if isinstance(item, types.ResourceLink)] == [
        image.uri,
        attachment.uri,
        stdout.uri,
        stderr.uri,
    ]
    assert [item.name for item in links if isinstance(item, types.ResourceLink)] == [
        "artifact-plot-png",
        "artifact-data-bin",
        "artifact-stdout-txt",
        "artifact-stderr-txt",
    ]
    assert [item.title for item in links if isinstance(item, types.ResourceLink)] == [
        "plot.png",
        "data.bin",
        "stdout.txt",
        "stderr.txt",
    ]
    assert len(result.content) == 6
    assert runtime.resource_calls == [image.uri]


async def test_progress_is_latest_only_rate_limited_and_request_scoped() -> None:
    runtime = FakeRuntime(outcome())
    runtime.progress_snapshots = [
        OutputSnapshot(revision=index, channel="stdout", text=f"update-{index}")
        for index in range(1, 31)
    ]
    runtime.progress_interval = 0.01
    observed: list[tuple[float, float, str | None]] = []

    async def progress(progress: float, _total: float | None, message: str | None) -> None:
        observed.append((time.monotonic(), progress, message))

    async with Client(create_server(runtime)) as client:
        result = await client.call_tool(
            "python_exec",
            {"code": "print('x')"},
            progress_callback=cast(ProgressFnT, progress),
            meta=cast(types.RequestParamsMeta, {"progressToken": "progress-test"}),
        )

    assert not result.is_error
    assert result.structured_content is not None
    assert result.structured_content["output"]["live"] == "progress"
    assert 1 <= len(observed) < len(runtime.progress_snapshots)
    assert [revision for _, revision, _ in observed] == sorted(
        revision for _, revision, _ in observed
    )
    assert all(later[0] - earlier[0] >= 0.09 for earlier, later in pairwise(observed))
    assert observed[-1][2] is not None
    assert len(observed[-1][2].encode("utf-8")) <= 8_192
    assert all(message.startswith("stdout: ") for _, _, message in observed if message)


async def test_progress_latency_never_delays_terminal_result() -> None:
    runtime = FakeRuntime(outcome())
    runtime.progress_snapshots = [OutputSnapshot(revision=1, channel="stdout", text="pending")]
    runtime.progress_interval = 0.05
    started = asyncio.Event()

    async def slow_progress(_progress: float, _total: float | None, _message: str | None) -> None:
        started.set()
        await asyncio.sleep(10)

    began = time.monotonic()
    async with Client(create_server(runtime)) as client:
        result = await client.call_tool(
            "python_exec",
            {"code": "print('x')"},
            progress_callback=cast(ProgressFnT, slow_progress),
            meta=cast(types.RequestParamsMeta, {"progressToken": "slow-progress"}),
        )
    elapsed = time.monotonic() - began

    assert started.is_set()
    assert elapsed < 0.5
    assert not result.is_error
    assert result.structured_content is not None
    assert result.structured_content["output"]["live"] == "progress"


async def test_client_progress_callback_failure_cannot_change_terminal_result() -> None:
    runtime = FakeRuntime(outcome())
    runtime.progress_snapshots = [OutputSnapshot(revision=1, channel="stdout", text="pending")]
    runtime.progress_interval = 0.05
    called = asyncio.Event()

    async def failing_progress(
        _progress: float, _total: float | None, _message: str | None
    ) -> None:
        called.set()
        raise RuntimeError("client callback detail")

    async with Client(create_server(runtime)) as client:
        result = await client.call_tool(
            "python_exec",
            {"code": "print('x')"},
            progress_callback=cast(ProgressFnT, failing_progress),
            meta=cast(types.RequestParamsMeta, {"progressToken": "failing-progress"}),
        )

    assert called.is_set()
    assert not result.is_error
    assert result.structured_content is not None
    assert result.structured_content["status"] == "completed"
    assert result.structured_content["output"]["live"] == "progress"


async def test_progress_failure_is_generic_and_marks_live_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = FakeRuntime(outcome())
    runtime.progress_snapshots = [OutputSnapshot(revision=1, channel="stderr", text="bounded")]
    runtime.progress_interval = 0.05

    async def fail_progress(
        _session: ServerSession,
        _progress: float,
        _total: float | None = None,
        _message: str | None = None,
    ) -> None:
        raise RuntimeError("private progress transport detail")

    monkeypatch.setattr(ServerSession, "report_progress", fail_progress)
    stream = StringIO()
    async with Client(create_server(runtime, diagnostic_stream=stream)) as client:
        result = await client.call_tool(
            "python_exec",
            {"code": "print('x')"},
            meta=cast(types.RequestParamsMeta, {"progressToken": "failed-progress"}),
        )

    assert not result.is_error
    assert result.structured_content is not None
    assert result.structured_content["status"] == "completed"
    assert result.structured_content["output"]["live"] == "failed"
    assert "RuntimeError" in stream.getvalue()
    assert "private progress transport detail" not in stream.getvalue()


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
    assert properties["packages"]["maxItems"] == 64
    package_items = properties["packages"]["items"]
    assert package_items["maxLength"] == 128
    assert package_items["pattern"] == r"^[A-Za-z0-9]+(?:[._-]+[A-Za-z0-9]+)*$"
    assert tool.output_schema == OUTPUT_SCHEMA
    fixture = json.loads(
        (Path(__file__).parents[1] / "fixtures" / "python_exec_v2_schema.json").read_text()
    )
    assert fixture == {
        "inputSchema": tool.input_schema,
        "outputSchema": tool.output_schema,
    }
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


async def test_resources_list_and_read_publish_exact_current_protocol_fields() -> None:
    uri = "amkernel://artifact/00000000000040008000000000000001/00000000000040008000000000000002"
    runtime = FakeRuntime(
        outcome(),
        resource=ArtifactResource(uri, "application/octet-stream", b"binary", False),
    )

    async with Client(create_server(runtime)) as client:
        listed = await client.list_resources()
        read = await client.read_resource(uri)

    assert listed.resources == []
    assert listed.next_cursor is None
    assert listed.cache_scope == "private"
    assert listed.result_type == "complete"
    assert listed.ttl_ms == 0
    assert read.cache_scope == "private"
    assert read.result_type == "complete"
    assert read.ttl_ms == 0
    assert len(read.contents) == 1
    content = read.contents[0]
    assert isinstance(content, types.BlobResourceContents)
    assert content.uri == uri
    assert content.mime_type == "application/octet-stream"
    assert content.blob == "YmluYXJ5"
    assert runtime.resource_calls == [uri]


@pytest.mark.parametrize(
    ("failure", "code", "message"),
    [
        (ArtifactNotFoundError("private path"), types.INVALID_PARAMS, "resource not found"),
        (
            ArtifactIntegrityError("private path"),
            types.INTERNAL_ERROR,
            "resource integrity failure",
        ),
    ],
)
async def test_resource_failures_are_generic_protocol_errors(
    failure: Exception, code: int, message: str
) -> None:
    runtime = FakeRuntime(outcome(), resource=failure)
    runtime.diagnostic_tail = "Artifact Store resource integrity failure\n"

    async with Client(create_server(runtime)) as client:
        with pytest.raises(MCPError) as observed:
            await client.read_resource("amkernel://artifact/foreign/item")

    assert observed.value.code == code
    assert observed.value.message == message
    assert "private path" not in str(observed.value)


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
            {"code": "None", "timeout": 2, "reset": True, "packages": ["Pillow"]},
        )

    assert not absent.is_error
    assert absent.structured_content is not None
    assert "result" not in absent.structured_content
    assert json.loads(text_content(absent)) == absent.structured_content
    assert not null.is_error
    assert null.structured_content is not None
    assert null.structured_content["result"] is None
    assert json.loads(text_content(null)) == null.structured_content
    assert runtime.calls == [
        ("x = 1", 30.0, False, ()),
        ("None", 2.0, True, ("Pillow",)),
    ]


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
    assert result.structured_content["displays"] == []
    assert result.structured_content["artifacts"] == []
    assert result.structured_content["output"] == {
        "totalBytes": 6,
        "totalLines": 2,
        "discardedBytes": 0,
        "discardedLines": 0,
        "truncated": False,
        "limitBytes": 268_435_456,
        "limitExceeded": False,
        "live": "unavailable",
    }


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
        {"code": "1", "packages": ["bad name"]},
        {"code": "1", "packages": ["zope.interface", "zope-interface"]},
        {"code": "1", "packages": ["x"] * 65},
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
