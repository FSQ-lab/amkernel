"""Official MCP SDK adapter for the single persistent Python Runtime."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import signal
import sys
import threading
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import FrameType
from typing import Annotated, Any, Literal, Protocol, TextIO, cast

import mcp.types as types
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import MCPError
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictStr,
    ValidationError,
    model_validator,
)

from amkernel import __version__
from amkernel.artifact_store import (
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    ArtifactRecord,
    ArtifactResource,
)
from amkernel.output import OutputObserver, OutputSnapshot
from amkernel.protocol import (
    MAX_ARTIFACT_BYTES,
    MAX_CODE_BYTES,
    MAX_IMAGE_DIMENSION,
    MAX_INLINE_IMAGE_BYTES,
    MAX_INLINE_IMAGE_ITEM_BYTES,
    MAX_LIVE_MESSAGE_BYTES,
    MAX_LOGICAL_NAME_CODEPOINTS,
    MAX_MIME_BYTES,
    MAX_OUTPUT_SEQUENCE,
    MAX_PACKAGE_COUNT,
    MAX_PACKAGE_NAME_BYTES,
    MAX_STORED_ITEMS,
    MAX_STRUCTURED_RESULT_BYTES,
    validate_package_names,
)
from amkernel.runtime import KernelRuntime
from amkernel.supervisor import ShutdownResult, SupervisedExecution

TOOL_NAME = "python_exec"
TOOL_TITLE = "Execute Python"
DEFAULT_TIMEOUT = 30.0
MAX_TITLE_CODEPOINTS = 200
LiveStatus = Literal["unavailable", "progress", "failed"]

TOOL_DESCRIPTION = (
    "Execute one Python cell in a persistent local Runtime.\n\n"
    "Calls serialize in FIFO order and share imports, variables, functions, mutations, and live "
    "objects until reset. Mutations completed before a Python exception remain. Set reset=true to "
    "destructively replace the kernel before this cell; reset and shutdown clean only AMKernel's "
    "managed process group, not escaped processes, sockets, or external sessions. input() is "
    "unsupported. Always inspect status and kernelState.\n\n"
    "Artifact resource URIs are ephemeral: capacity pressure or server shutdown can expire them. "
    "Read and copy every manifest part before making another large-output call. Artifact bytes are "
    "untrusted; random identifiers are not same-user access control.\n\n"
    "Code runs unrestricted with the permissions of the user who launched AMKernel. This is not a "
    "sandbox and execution is not workspace-confined."
)


def _validate_code_bytes(value: str) -> str:
    if len(value.encode("utf-8")) > MAX_CODE_BYTES:
        raise ValueError(f"code exceeds {MAX_CODE_BYTES} UTF-8 bytes")
    return value


Code = Annotated[
    StrictStr,
    Field(max_length=MAX_CODE_BYTES, description="One Python cell; empty cells are valid."),
    AfterValidator(_validate_code_bytes),
]


def _validate_packages(value: list[str]) -> list[str]:
    return list(validate_package_names(value))


PackageName = Annotated[
    StrictStr,
    Field(
        min_length=1,
        max_length=MAX_PACKAGE_NAME_BYTES,
        pattern=r"^[A-Za-z0-9]+(?:[._-]+[A-Za-z0-9]+)*$",
    ),
]
Packages = Annotated[
    list[PackageName],
    Field(max_length=MAX_PACKAGE_COUNT),
    AfterValidator(_validate_packages),
]
Title = Annotated[
    StrictStr,
    Field(max_length=MAX_TITLE_CODEPOINTS, description="Presentation metadata only."),
]
Timeout = Annotated[
    float,
    Field(strict=True, gt=0, le=3_600, allow_inf_nan=False, description="Active-cell seconds."),
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)


class PythonExecInput(_StrictModel):
    code: Code
    title: Title = ""
    timeout: Timeout = DEFAULT_TIMEOUT
    reset: StrictBool = False
    packages: Packages = Field(default_factory=list)


class ExecutionError(_StrictModel):
    type: str
    message: str
    traceback: list[str]


class ArtifactRef(_StrictModel):
    uri: str
    name: str = Field(min_length=1, max_length=MAX_LOGICAL_NAME_CODEPOINTS)
    declared_mime_type: str = Field(
        min_length=1, max_length=MAX_MIME_BYTES, alias="declaredMimeType"
    )
    mime_type: str = Field(min_length=1, max_length=MAX_MIME_BYTES, alias="mimeType")
    representation: Literal["raw", "manifest"]
    size: int = Field(ge=0, le=MAX_ARTIFACT_BYTES)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PackageInfo(_StrictModel):
    name: PackageName
    version: str = cast(str, None)
    error: Literal["not installed", "metadata unavailable", "invalid metadata"] = cast(
        Literal["not installed", "metadata unavailable", "invalid metadata"], None
    )

    @model_validator(mode="after")
    def _require_one_result(self) -> PackageInfo:
        if (self.version is None) == (self.error is None):
            raise ValueError("package requires exactly one of version or error")
        return self


class RuntimeInfo(_StrictModel):
    executable: str
    python_version: str = Field(alias="pythonVersion")
    working_directory: str = Field(alias="workingDirectory")
    environment_kind: Literal["project_venv", "active_venv", "system"] = Field(
        alias="environmentKind"
    )
    implementation: str
    platform: str
    packages: Annotated[list[PackageInfo], Field(max_length=MAX_PACKAGE_COUNT)]


class JsonDisplay(_StrictModel):
    sequence: int = Field(ge=1, le=MAX_OUTPUT_SEQUENCE)
    kind: Literal["json"]
    value: Any


class ImageDisplay(_StrictModel):
    sequence: int = Field(ge=1, le=MAX_OUTPUT_SEQUENCE)
    kind: Literal["image"]
    mime_type: Literal["image/png", "image/jpeg", "image/gif", "image/webp"] = Field(
        alias="mimeType"
    )
    size: int = Field(ge=0, le=MAX_ARTIFACT_BYTES)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    width: int = Field(ge=1, le=MAX_IMAGE_DIMENSION)
    height: int = Field(ge=1, le=MAX_IMAGE_DIMENSION)
    inline: bool
    artifact: ArtifactRef


class ArtifactDisplay(_StrictModel):
    sequence: int = Field(ge=1, le=MAX_OUTPUT_SEQUENCE)
    kind: Literal["artifact"]
    artifact: ArtifactRef


DisplayItem = Annotated[JsonDisplay | ImageDisplay | ArtifactDisplay, Field(discriminator="kind")]


class OutputInfo(_StrictModel):
    total_bytes: int = Field(ge=0, alias="totalBytes")
    total_lines: int = Field(ge=0, alias="totalLines")
    discarded_bytes: int = Field(ge=0, alias="discardedBytes")
    discarded_lines: int = Field(ge=0, alias="discardedLines")
    truncated: bool
    limit_bytes: int = Field(ge=1, alias="limitBytes")
    limit_exceeded: bool = Field(alias="limitExceeded")
    live: Literal["progress", "failed", "unavailable"]
    stdout_artifact: ArtifactRef = Field(default=cast(ArtifactRef, None), alias="stdoutArtifact")
    stderr_artifact: ArtifactRef = Field(default=cast(ArtifactRef, None), alias="stderrArtifact")


class PythonExecResult(_StrictModel):
    status: Literal["completed", "failed", "timed_out", "kernel_killed"]
    stdout: str
    stderr: str
    result: Any = None
    error: ExecutionError = cast(ExecutionError, None)
    execution_count: int = Field(ge=0, alias="executionCount")
    duration_ms: int = Field(ge=0, alias="durationMs")
    kernel_state: Literal["alive", "dead"] = Field(alias="kernelState")
    runtime: RuntimeInfo
    output: OutputInfo
    displays: Annotated[list[DisplayItem], Field(max_length=MAX_OUTPUT_SEQUENCE)]
    artifacts: Annotated[list[ArtifactRef], Field(max_length=MAX_STORED_ITEMS)]


INPUT_SCHEMA: dict[str, Any] = PythonExecInput.model_json_schema(by_alias=True)
OUTPUT_SCHEMA: dict[str, Any] = PythonExecResult.model_json_schema(by_alias=True)


class RuntimeAdapter(Protocol):
    @property
    def diagnostic_tail(self) -> str: ...

    async def execute(
        self,
        code: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        reset: bool = False,
        packages: tuple[str, ...] = (),
        observer: OutputObserver | None = None,
        result_finalizer: Callable[[SupervisedExecution], Awaitable[None]] | None = None,
    ) -> SupervisedExecution: ...

    async def read_resource(self, uri: str) -> ArtifactResource: ...

    async def shutdown(self) -> ShutdownResult: ...


class _DiagnosticEmitter:
    def __init__(self, stream: TextIO) -> None:
        self._stream = stream
        self._previous = ""

    def emit(self, current: str) -> None:
        detail = current[len(self._previous) :] if current.startswith(self._previous) else current
        self._previous = current
        self.write(detail)

    def write(self, detail: str) -> None:
        if not detail:
            return
        try:
            self._stream.write(detail)
            if not detail.endswith("\n"):
                self._stream.write("\n")
            self._stream.flush()
        except (OSError, ValueError):
            pass

    def emit_cleanup_failure(self, result: ShutdownResult) -> None:
        if result.cleaned:
            return
        detail = result.error or "managed kernel cleanup failed"
        self.write(f"AMKernel shutdown cleanup failed: {detail}\n")


def _structured_result(
    outcome: SupervisedExecution,
    *,
    live: Literal["unavailable", "progress", "failed"] = "unavailable",
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "status": outcome.status,
        "stdout": outcome.stdout,
        "stderr": outcome.stderr,
        "execution_count": outcome.execution_count,
        "duration_ms": outcome.duration_ms,
        "kernel_state": outcome.kernel_state,
        "runtime": RuntimeInfo(
            executable=outcome.runtime.executable,
            pythonVersion=outcome.runtime.python_version,
            workingDirectory=outcome.runtime.working_directory,
            environmentKind=outcome.runtime.environment_kind,
            implementation=outcome.runtime.implementation,
            platform=outcome.runtime.platform,
            packages=[
                PackageInfo(
                    name=package.name,
                    **(
                        {"version": package.version}
                        if package.version is not None
                        else {"error": package.error}
                    ),
                )
                for package in outcome.runtime.packages
            ],
        ),
        "output": OutputInfo(
            totalBytes=outcome.output.total_bytes,
            totalLines=outcome.output.total_lines,
            discardedBytes=outcome.output.discarded_bytes,
            discardedLines=outcome.output.discarded_lines,
            truncated=outcome.output.truncated,
            limitBytes=outcome.output.limit_bytes,
            limitExceeded=outcome.output.limit_exceeded,
            live=live,
            **(
                {"stdoutArtifact": _artifact_ref(outcome.output.stdout_artifact)}
                if outcome.output.stdout_artifact is not None
                else {}
            ),
            **(
                {"stderrArtifact": _artifact_ref(outcome.output.stderr_artifact)}
                if outcome.output.stderr_artifact is not None
                else {}
            ),
        ),
        "displays": _display_items(outcome),
        "artifacts": [_artifact_ref(artifact) for artifact in outcome.output.artifacts],
    }
    if outcome.has_result:
        fields["result"] = outcome.result
    if outcome.error is not None:
        fields["error"] = ExecutionError(
            type=outcome.error.type,
            message=outcome.error.message,
            traceback=list(outcome.error.traceback),
        )
    validated = PythonExecResult.model_validate(fields)
    return validated.model_dump(mode="json", by_alias=True, exclude_unset=True)


def _display_items(outcome: SupervisedExecution) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    inline_bytes = 0
    for display in outcome.output.displays:
        if display.kind == "json":
            fields.append({"sequence": display.sequence, "kind": "json", "value": display.value})
            continue
        artifact = display.artifact
        if artifact is None:
            raise ValueError("stored display is missing artifact metadata")
        if display.kind == "artifact":
            fields.append(
                {
                    "sequence": display.sequence,
                    "kind": "artifact",
                    "artifact": _artifact_ref(artifact),
                }
            )
            continue
        image = display.image
        if image is None:
            raise ValueError("stored image display is missing decoded metadata")
        inline = (
            artifact.size <= MAX_INLINE_IMAGE_ITEM_BYTES
            and inline_bytes + artifact.size <= MAX_INLINE_IMAGE_BYTES
        )
        if inline:
            inline_bytes += artifact.size
        fields.append(
            {
                "sequence": display.sequence,
                "kind": "image",
                "mimeType": artifact.declared_mime_type,
                "size": artifact.size,
                "sha256": artifact.sha256,
                "width": image.width,
                "height": image.height,
                "inline": inline,
                "artifact": _artifact_ref(artifact),
            }
        )
    return fields


def _artifact_ref(record: ArtifactRecord) -> ArtifactRef:
    return ArtifactRef(
        uri=record.uri,
        name=record.name,
        declaredMimeType=record.declared_mime_type,
        mimeType=record.mime_type,
        representation=record.representation,
        size=record.size,
        sha256=record.sha256,
    )


class _ProgressReporter:
    def __init__(
        self,
        context: ServerRequestContext[dict[str, Any]],
        diagnostics: _DiagnosticEmitter,
    ) -> None:
        self.observer = OutputObserver()
        self.status: Literal["progress", "failed"] = "progress"
        self._context = context
        self._diagnostics = diagnostics

    async def run(self) -> None:
        last_send = 0.0
        while True:
            snapshot = await self.observer.next()
            delay = 0.1 - (time.monotonic() - last_send)
            if delay > 0:
                await asyncio.sleep(delay)
                snapshot = self.observer.drain_latest(snapshot)
            try:
                await self._context.session.report_progress(
                    float(snapshot.revision),
                    None,
                    _progress_message(snapshot),
                )
            except Exception as error:
                self.status = "failed"
                self._diagnostics.write(
                    f"python_exec progress reporter failed: {type(error).__name__}\n"
                )
                return
            last_send = time.monotonic()

    async def close(self, task: asyncio.Task[None]) -> None:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def _progress_message(snapshot: OutputSnapshot) -> str:
    prefix = f"{snapshot.channel}: "
    remaining = MAX_LIVE_MESSAGE_BYTES - len(prefix.encode("utf-8"))
    payload = snapshot.text.encode("utf-8")[-remaining:]
    while payload and payload[0] & 0xC0 == 0x80:
        payload = payload[1:]
    return prefix + payload.decode("utf-8")


def _progress_reporter(
    context: ServerRequestContext[dict[str, Any]],
    diagnostics: _DiagnosticEmitter,
) -> _ProgressReporter | None:
    meta = context.meta
    if meta is None or (meta.get("progressToken") is None and meta.get("progress_token") is None):
        return None
    return _ProgressReporter(context, diagnostics)


async def _tool_content(
    runtime: RuntimeAdapter,
    outcome: SupervisedExecution,
    structured: dict[str, Any],
    canonical_json: str,
) -> list[types.ContentBlock]:
    content: list[types.ContentBlock] = [types.TextContent(type="text", text=canonical_json)]
    displays = {
        item["sequence"]: item for item in cast(list[dict[str, Any]], structured["displays"])
    }
    for display in outcome.output.displays:
        if display.kind == "json":
            continue
        artifact = display.artifact
        if artifact is None:
            raise ValueError("stored display is missing artifact metadata")
        if display.kind == "image" and displays[display.sequence]["inline"]:
            resource = await runtime.read_resource(artifact.uri)
            if resource.text:
                raise ValueError("inline image resource is not binary")
            content.append(
                types.ImageContent(
                    type="image",
                    data=base64.b64encode(resource.data).decode("ascii"),
                    mime_type=artifact.mime_type,
                )
            )
        content.append(_resource_link(artifact))

    for artifact in (outcome.output.stdout_artifact, outcome.output.stderr_artifact):
        if artifact is not None:
            content.append(_resource_link(artifact))
    return content


def _resource_link(record: ArtifactRecord) -> types.ResourceLink:
    artifact_id = record.uri.rsplit("/", 1)[-1]
    return types.ResourceLink(
        type="resource_link",
        uri=record.uri,
        name=f"artifact-{artifact_id}",
        title=record.name,
        mime_type=record.mime_type,
        size=record.size,
    )


async def _map_tool_result(
    runtime: RuntimeAdapter,
    outcome: SupervisedExecution,
    *,
    live: LiveStatus,
) -> types.CallToolResult:
    structured = _structured_result(outcome, live=live)
    text = json.dumps(
        structured,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    if len(text.encode("utf-8")) > MAX_STRUCTURED_RESULT_BYTES:
        raise ValueError("structured result exceeds terminal byte bound")
    content = await _tool_content(runtime, outcome, structured, text)
    return types.CallToolResult(
        content=content,
        structured_content=structured,
        is_error=False,
    )


def _minimal_tool_result(
    outcome: SupervisedExecution,
    *,
    live: LiveStatus,
) -> types.CallToolResult:
    structured = _structured_result(outcome, live=live)
    text = json.dumps(
        structured,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)],
        structured_content=structured,
        is_error=False,
    )


def _tool_error(message: str) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=message)],
        is_error=True,
    )


def create_server(
    runtime: RuntimeAdapter,
    *,
    diagnostic_stream: TextIO | None = None,
) -> Server[dict[str, Any]]:
    """Bind one Runtime to the sole model-facing MCP tool."""
    return _create_server(runtime, _DiagnosticEmitter(diagnostic_stream or sys.stderr))


def _create_server(
    runtime: RuntimeAdapter,
    diagnostics: _DiagnosticEmitter,
) -> Server[dict[str, Any]]:
    async def list_tools(
        _context: ServerRequestContext[dict[str, Any]],
        _params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=TOOL_NAME,
                    title=TOOL_TITLE,
                    description=TOOL_DESCRIPTION,
                    input_schema=INPUT_SCHEMA,
                    output_schema=OUTPUT_SCHEMA,
                )
            ]
        )

    async def list_resources(
        _context: ServerRequestContext[dict[str, Any]],
        _params: types.PaginatedRequestParams | None,
    ) -> types.ListResourcesResult:
        return types.ListResourcesResult(
            resources=[],
            cache_scope="private",
            result_type="complete",
            ttl_ms=0,
        )

    async def read_resource(
        _context: ServerRequestContext[dict[str, Any]],
        params: types.ReadResourceRequestParams,
    ) -> types.ReadResourceResult:
        try:
            resource = await runtime.read_resource(str(params.uri))
        except ArtifactNotFoundError as error:
            raise MCPError(types.INVALID_PARAMS, "resource not found") from error
        except ArtifactIntegrityError as error:
            diagnostics.emit(runtime.diagnostic_tail)
            raise MCPError(types.INTERNAL_ERROR, "resource integrity failure") from error
        if resource.text:
            content: types.TextResourceContents | types.BlobResourceContents = (
                types.TextResourceContents(
                    uri=resource.uri,
                    mime_type=resource.mime_type,
                    text=resource.data.decode("utf-8", errors="strict"),
                )
            )
        else:
            content = types.BlobResourceContents(
                uri=resource.uri,
                mime_type=resource.mime_type,
                blob=base64.b64encode(resource.data).decode("ascii"),
            )
        return types.ReadResourceResult(
            contents=[content],
            cache_scope="private",
            result_type="complete",
            ttl_ms=0,
        )

    async def call_tool(
        _context: ServerRequestContext[dict[str, Any]],
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult:
        if params.name != TOOL_NAME:
            return _tool_error(f"Unknown tool: {params.name}")
        try:
            request = PythonExecInput.model_validate(params.arguments or {})
        except ValidationError:
            diagnostics.write("python_exec rejected invalid arguments\n")
            return _tool_error("Invalid python_exec arguments")

        reporter = _progress_reporter(_context, diagnostics)
        reporter_task = asyncio.create_task(reporter.run()) if reporter is not None else None
        mapped: types.CallToolResult | None = None

        async def finalize(outcome: SupervisedExecution) -> None:
            nonlocal mapped
            if reporter is not None and reporter_task is not None:
                await reporter.close(reporter_task)
            mapped = await _map_tool_result(
                runtime,
                outcome,
                live=reporter.status if reporter is not None else "unavailable",
            )

        try:
            if reporter is None:
                outcome = await runtime.execute(
                    request.code,
                    timeout=request.timeout,
                    reset=request.reset,
                    packages=tuple(request.packages),
                    result_finalizer=finalize,
                )
            else:
                outcome = await runtime.execute(
                    request.code,
                    timeout=request.timeout,
                    reset=request.reset,
                    packages=tuple(request.packages),
                    observer=reporter.observer,
                    result_finalizer=finalize,
                )
            if mapped is None:
                if reporter is not None and reporter_task is not None:
                    await reporter.close(reporter_task)
                mapped = _minimal_tool_result(
                    outcome,
                    live=reporter.status if reporter is not None else "unavailable",
                )
        except Exception as error:
            diagnostics.write(f"python_exec adapter failure: {type(error).__name__}\n")
            return _tool_error("python_exec failed internally")
        finally:
            if reporter is not None and reporter_task is not None:
                await reporter.close(reporter_task)
            diagnostics.emit(runtime.diagnostic_tail)

        return mapped

    return Server(
        "amkernel",
        title="AMKernel",
        description="Persistent Python execution for agentic automation.",
        version=__version__,
        get_tool_input_schema=lambda name: INPUT_SCHEMA if name == TOOL_NAME else None,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
        on_list_resources=list_resources,
        on_read_resource=read_resource,
    )


@contextmanager
def _defer_sigterm_until_cleanup() -> Iterator[Callable[[asyncio.Task[None]], None]]:
    if os.name != "posix" or threading.current_thread() is not threading.main_thread():
        yield lambda _task: None
        return

    task: asyncio.Task[None] | None = None
    received = False
    received_frame: FrameType | None = None

    def handle_sigterm(_signal_number: int, frame: FrameType | None) -> None:
        nonlocal received, received_frame
        received = True
        received_frame = frame
        if task is not None and not task.done():
            task.cancel()

    def attach(current: asyncio.Task[None]) -> None:
        nonlocal task
        task = current
        if received and not current.done():
            current.cancel()

    previous = signal.signal(signal.SIGTERM, handle_sigterm)
    try:
        yield attach
    finally:
        if signal.getsignal(signal.SIGTERM) is handle_sigterm:
            signal.signal(signal.SIGTERM, previous)
        if received:
            if previous == signal.SIG_DFL:
                os.kill(os.getpid(), signal.SIGTERM)
            elif previous != signal.SIG_IGN and callable(previous):
                previous(signal.SIGTERM, received_frame)


async def _run_server_stdio(server: Server[dict[str, Any]]) -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


async def serve_stdio(
    working_directory: Path | None = None,
    *,
    diagnostic_stream: TextIO | None = None,
    runtime_factory: Callable[[Path | None], RuntimeAdapter] = KernelRuntime,
) -> int:
    """Serve stdio until transport close, then wait for managed cleanup."""
    diagnostics = _DiagnosticEmitter(diagnostic_stream or sys.stderr)
    runtime = runtime_factory(working_directory)
    server = _create_server(runtime, diagnostics)
    with _defer_sigterm_until_cleanup() as attach:
        serving = asyncio.create_task(_run_server_stdio(server))
        attach(serving)
        try:
            await serving
        finally:
            shutdown = await runtime.shutdown()
            diagnostics.emit(runtime.diagnostic_tail)
            diagnostics.emit_cleanup_failure(shutdown)
    return 0 if shutdown.cleaned else 1
