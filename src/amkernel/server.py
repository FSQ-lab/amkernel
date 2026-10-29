"""Official MCP SDK adapter for the single persistent Python Runtime."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol, TextIO, cast

import mcp.types as types
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictStr,
    ValidationError,
)

from amkernel import __version__
from amkernel.protocol import MAX_CODE_BYTES
from amkernel.runtime import KernelRuntime
from amkernel.supervisor import ShutdownResult, SupervisedExecution

TOOL_NAME = "python_exec"
TOOL_TITLE = "Execute Python"
DEFAULT_TIMEOUT = 30.0
MAX_TITLE_CODEPOINTS = 200

TOOL_DESCRIPTION = (
    "Execute one Python cell in a persistent local Runtime.\n\n"
    "Calls serialize in FIFO order and share imports, variables, functions, mutations, and live "
    "objects until reset. Mutations completed before a Python exception remain. Set reset=true to "
    "destructively replace the kernel before this cell; reset and shutdown clean only AMKernel's "
    "managed process group, not escaped processes, sockets, or external sessions. input() is "
    "unsupported. Always inspect status and kernelState.\n\n"
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


class ExecutionError(_StrictModel):
    type: str
    message: str
    traceback: list[str]


class ArtifactRef(_StrictModel):
    uri: str
    mime_type: str = Field(alias="mimeType")
    size: int = Field(ge=0)
    sha256: str


class RuntimeInfo(_StrictModel):
    executable: str
    python_version: str = Field(alias="pythonVersion")
    working_directory: str = Field(alias="workingDirectory")
    environment_kind: Literal["project_venv", "active_venv", "system"] = Field(
        alias="environmentKind"
    )


class OutputInfo(_StrictModel):
    total_bytes: int = Field(ge=0, alias="totalBytes")
    total_lines: int = Field(ge=0, alias="totalLines")
    truncated: bool
    artifact: ArtifactRef = cast(ArtifactRef, None)


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
    artifacts: list[ArtifactRef]


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
    ) -> SupervisedExecution: ...

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


def _structured_result(outcome: SupervisedExecution) -> dict[str, Any]:
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
        ),
        "output": OutputInfo(
            totalBytes=outcome.output.total_bytes,
            totalLines=outcome.output.total_lines,
            truncated=outcome.output.truncated,
        ),
        "artifacts": [],
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

        try:
            outcome = await runtime.execute(
                request.code,
                timeout=request.timeout,
                reset=request.reset,
            )
            structured = _structured_result(outcome)
            text = json.dumps(structured, ensure_ascii=False, allow_nan=False, indent=2)
        except Exception as error:
            diagnostics.write(f"python_exec adapter failure: {type(error).__name__}\n")
            return _tool_error("python_exec failed internally")
        finally:
            diagnostics.emit(runtime.diagnostic_tail)

        return types.CallToolResult(
            content=[types.TextContent(type="text", text=text)],
            structured_content=structured,
            is_error=False,
        )

    return Server(
        "amkernel",
        title="AMKernel",
        description="Persistent Python execution for agentic automation.",
        version=__version__,
        get_tool_input_schema=lambda name: INPUT_SCHEMA if name == TOOL_NAME else None,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )


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
    try:
        await _run_server_stdio(server)
    finally:
        shutdown = await runtime.shutdown()
        diagnostics.emit(runtime.diagnostic_tail)
        diagnostics.emit_cleanup_failure(shutdown)
    return 0 if shutdown.cleaned else 1
