"""POSIX Python Runner supervision, deadlines, stream capture, and cleanup."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal, Protocol

from amkernel.protocol import (
    DIAGNOSTIC_FD_ARGUMENT,
    MAX_CONTROL_FRAME_BYTES,
    REQUEST_FD_ARGUMENT,
    RESPONSE_FD_ARGUMENT,
    DoneResponse,
    ErrorInfo,
    ExecuteRequest,
    InitializeRequest,
    JsonValue,
    ProtocolErrorResponse,
    ProtocolViolation,
    ReadyResponse,
    Response,
    RuntimeDiagnostics,
    ShutdownRequest,
    StartedResponse,
    encode_request,
    parse_response_payload,
)

COMMAND_ACK_TIMEOUT: Final = 5.0
INTERRUPT_GRACE: Final = 1.0
TERMINATE_GRACE: Final = 1.0
KILL_GRACE: Final = 1.0
SHUTDOWN_GRACE: Final = 1.0
STREAM_TAIL_BYTES: Final = 262_144
DIAGNOSTIC_TAIL_BYTES: Final = 65_536
_READ_CHUNK: Final = 65_536
_ENVIRONMENT_ALLOWLIST: Final = frozenset(
    {
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LOGNAME",
        "PATH",
        "SHELL",
        "TERM",
        "TMPDIR",
        "TZ",
        "USER",
    }
)

ExecutionStatus = Literal["completed", "failed", "timed_out", "kernel_killed"]
KernelState = Literal["alive", "dead"]
SupervisorState = Literal["starting", "alive", "dead", "closing", "closed"]


class KernelStartError(RuntimeError):
    """The Runner could not reach a validated ready state."""


class KernelUnavailableError(RuntimeError):
    """The Supervisor no longer owns a reusable Runner."""


class ConcurrentExecutionError(RuntimeError):
    """The Supervisor was asked to run more than one cell at once."""


class ExecutionAbandoned(RuntimeError):
    """An internal caller abandoned work before a terminal public outcome."""


@dataclass(frozen=True, slots=True)
class OutputMetadata:
    total_bytes: int
    total_lines: int
    truncated: bool


@dataclass(frozen=True, slots=True)
class SupervisedExecution:
    status: ExecutionStatus
    stdout: str
    stderr: str
    has_result: bool
    result: JsonValue
    error: ErrorInfo | None
    execution_count: int
    duration_ms: int
    kernel_state: KernelState
    runtime: RuntimeDiagnostics
    output: OutputMetadata


@dataclass(frozen=True, slots=True)
class ShutdownResult:
    cleaned: bool
    error: str | None = None


@dataclass(slots=True)
class _StreamTail:
    maximum_bytes: int
    total_bytes: int = 0
    newline_bytes: int = 0
    last_byte: int | None = None
    tail: bytearray = field(default_factory=bytearray)

    def feed(self, chunk: bytes) -> None:
        if not chunk:
            return
        self.total_bytes += len(chunk)
        self.newline_bytes += chunk.count(b"\n")
        self.last_byte = chunk[-1]
        self.tail.extend(chunk)
        overflow = len(self.tail) - self.maximum_bytes
        if overflow > 0:
            del self.tail[:overflow]

    @property
    def total_lines(self) -> int:
        partial = self.total_bytes > 0 and self.last_byte != 0x0A
        return self.newline_bytes + int(partial)

    @property
    def truncated(self) -> bool:
        return self.total_bytes > len(self.tail)

    def text(self) -> str:
        value = bytes(self.tail)
        if self.truncated:
            while value and value[0] & 0xC0 == 0x80:
                value = value[1:]
        return value.decode("utf-8", errors="replace")


@dataclass(slots=True)
class _ExecutionCapture:
    stdout: _StreamTail = field(default_factory=lambda: _StreamTail(STREAM_TAIL_BYTES))
    stderr: _StreamTail = field(default_factory=lambda: _StreamTail(STREAM_TAIL_BYTES))
    revision: int = 0

    def feed(self, channel: Literal["stdout", "stderr"], chunk: bytes) -> None:
        getattr(self, channel).feed(chunk)
        self.revision += 1


@dataclass(slots=True)
class _ActiveExecution:
    correlation_id: str
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    started_event: asyncio.Event = field(default_factory=asyncio.Event)
    done_event: asyncio.Event = field(default_factory=asyncio.Event)
    interrupt_sent: bool = False
    committed: bool = False
    write_complete: bool = False


@dataclass(frozen=True, slots=True)
class _CoreOutcome:
    status: ExecutionStatus
    has_result: bool
    result: JsonValue
    error: ErrorInfo | None
    execution_count: int
    duration_ms: int
    kernel_state: KernelState
    runtime: RuntimeDiagnostics


class _ProcessOperations(Protocol):
    def signal_group(self, process_group: int, signal_number: int) -> None: ...

    def group_exists(self, process_group: int) -> bool: ...


class _PosixProcessOperations:
    def signal_group(self, process_group: int, signal_number: int) -> None:
        os.killpg(process_group, signal_number)

    def group_exists(self, process_group: int) -> bool:
        try:
            os.killpg(process_group, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True


_POSIX_OPERATIONS = _PosixProcessOperations()


class KernelSupervisor:
    """Own one Runner process and expose one deep, serialized execution seam."""

    def __init__(
        self,
        *,
        launch_working_directory: Path,
        environment_kind: Literal["project_venv", "active_venv", "system"],
        process: asyncio.subprocess.Process,
        process_group: int,
        request_fd: int,
        response_reader: asyncio.StreamReader,
        response_transport: asyncio.ReadTransport,
        diagnostic_reader: asyncio.StreamReader,
        diagnostic_transport: asyncio.ReadTransport,
        operations: _ProcessOperations,
    ) -> None:
        self._launch_working_directory = launch_working_directory
        self._environment_kind = environment_kind
        self._process = process
        self._process_group = process_group
        self._request_fd = request_fd
        self._response_reader = response_reader
        self._response_transport = response_transport
        self._diagnostic_reader = diagnostic_reader
        self._diagnostic_transport = diagnostic_transport
        self._operations = operations
        self._state: SupervisorState = "starting"
        self._runtime = RuntimeDiagnostics(
            executable=os.path.abspath(sys.executable),
            python_version="unknown",
            working_directory=str(launch_working_directory),
            environment_kind=environment_kind,
        )
        self._execution_count = 0
        self._capture: _ExecutionCapture | None = None
        self._active: _ActiveExecution | None = None
        self._orphan_stdout = _StreamTail(DIAGNOSTIC_TAIL_BYTES)
        self._orphan_stderr = _StreamTail(DIAGNOSTIC_TAIL_BYTES)
        self._diagnostic = _StreamTail(DIAGNOSTIC_TAIL_BYTES)
        self._channels_closed = False
        self._runner_exit_observed = False
        self._process_exit_event = asyncio.Event()
        self._cleanup_error: str | None = None
        self._shutdown_task: asyncio.Task[ShutdownResult] | None = None
        self._shutdown_result: ShutdownResult | None = None
        self._process_wait_task = asyncio.create_task(process.wait())
        assert process.stdout is not None
        assert process.stderr is not None
        self._reader_tasks = [
            asyncio.create_task(self._drain_user_stream(process.stdout, "stdout")),
            asyncio.create_task(self._drain_user_stream(process.stderr, "stderr")),
            asyncio.create_task(self._drain_diagnostic()),
        ]
        self._death_monitor_task = asyncio.create_task(self._observe_process_exit())

    @classmethod
    async def start(
        cls,
        working_directory: Path | None = None,
        *,
        operations: _ProcessOperations = _POSIX_OPERATIONS,
    ) -> KernelSupervisor:
        """Spawn a Runner without allowing caller cancellation to orphan it."""
        operation = asyncio.create_task(cls._start_impl(working_directory, operations=operations))
        caller_cancelled = False
        while True:
            try:
                supervisor = await asyncio.shield(operation)
                break
            except asyncio.CancelledError:
                caller_cancelled = True
            except KernelStartError:
                raise
            except Exception as error:
                raise KernelStartError(str(error)) from error
        if caller_cancelled:
            await supervisor.shutdown()
            raise asyncio.CancelledError
        return supervisor

    @classmethod
    async def _start_impl(
        cls,
        working_directory: Path | None = None,
        *,
        operations: _ProcessOperations = _POSIX_OPERATIONS,
    ) -> KernelSupervisor:
        """Spawn and initialize one Runner using the current package interpreter."""
        cls._require_supported_platform()
        launch_directory = (working_directory or Path.cwd()).resolve(strict=True)
        environment_kind = _classify_environment(launch_directory)
        environment = _runner_environment()

        (
            request_read,
            request_write,
            response_read,
            response_write,
            diagnostic_read,
            diagnostic_write,
        ) = _create_protocol_pipes()
        child_descriptors = (request_read, response_write, diagnostic_write)
        process: asyncio.subprocess.Process | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                os.path.abspath(sys.executable),
                "-I",
                "-u",
                "-X",
                "utf8",
                "-m",
                "amkernel.runner",
                REQUEST_FD_ARGUMENT,
                str(request_read),
                RESPONSE_FD_ARGUMENT,
                str(response_write),
                DIAGNOSTIC_FD_ARGUMENT,
                str(diagnostic_write),
                cwd=launch_directory,
                env=environment,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                close_fds=True,
                pass_fds=child_descriptors,
                start_new_session=True,
            )
        finally:
            os.close(request_read)
            os.close(response_write)
            os.close(diagnostic_write)
            if process is None:
                os.close(request_write)
                os.close(response_read)
                os.close(diagnostic_read)

        response_transport: asyncio.ReadTransport | None = None
        diagnostic_transport: asyncio.ReadTransport | None = None
        supervisor: KernelSupervisor | None = None
        try:
            os.set_blocking(request_write, False)
            response_reader, response_transport = await _stream_reader_from_fd(response_read)
            diagnostic_reader, diagnostic_transport = await _stream_reader_from_fd(diagnostic_read)
            supervisor = cls(
                launch_working_directory=launch_directory,
                environment_kind=environment_kind,
                process=process,
                process_group=process.pid,
                request_fd=request_write,
                response_reader=response_reader,
                response_transport=response_transport,
                diagnostic_reader=diagnostic_reader,
                diagnostic_transport=diagnostic_transport,
                operations=operations,
            )
            await supervisor._initialize()
            return supervisor
        except BaseException as error:
            cleanup_error: str | None
            if supervisor is not None:
                cleanup_error = await supervisor._destructive_cleanup()
                supervisor._close_channels()
            else:
                _close_fd(request_write)
                if response_transport is not None:
                    response_transport.close()
                else:
                    _close_fd(response_read)
                if diagnostic_transport is not None:
                    diagnostic_transport.close()
                else:
                    _close_fd(diagnostic_read)
                cleanup_error = await _cleanup_spawned_process(process, operations)
            message = str(error)
            if cleanup_error is not None:
                message = f"{message}; cleanup failed: {cleanup_error}"
            raise KernelStartError(message) from error

    @staticmethod
    def _require_supported_platform() -> None:
        required = (
            os.name == "posix",
            hasattr(os, "register_at_fork"),
            hasattr(signal, "pthread_sigmask"),
            all(hasattr(signal, name) for name in ("SIGINT", "SIGTERM", "SIGKILL")),
        )
        if not all(required):
            raise RuntimeError("UnsupportedPlatformError: POSIX process primitives are required")

    @property
    def state(self) -> SupervisorState:
        return self._state

    @property
    def execution_count(self) -> int:
        return self._execution_count

    @property
    def runtime(self) -> RuntimeDiagnostics:
        return self._runtime

    @property
    def diagnostic_tail(self) -> str:
        return self._diagnostic.text()

    async def _initialize(self) -> None:
        correlation_id = uuid.uuid4().hex
        request = InitializeRequest(
            correlation_id,
            str(self._launch_working_directory),
            self._environment_kind,
        )
        async with asyncio.timeout(COMMAND_ACK_TIMEOUT):
            await self._write_request(encode_request(request))
            response = await self._next_response()
        if isinstance(response, ProtocolErrorResponse):
            raise ProtocolViolation(
                f"Runner rejected initialize: {response.code}: {response.message}"
            )
        if not isinstance(response, ReadyResponse) or response.correlation_id != correlation_id:
            raise ProtocolViolation("Runner did not return correlated ready")
        expected_executable = os.path.abspath(sys.executable)
        if response.runtime.executable != expected_executable:
            raise ProtocolViolation("Runner executable diagnostic mismatch")
        if response.runtime.working_directory != str(self._launch_working_directory):
            raise ProtocolViolation("Runner working-directory diagnostic mismatch")
        if response.runtime.environment_kind != self._environment_kind:
            raise ProtocolViolation("Runner environment-kind diagnostic mismatch")
        if (
            self._runner_exit_observed
            or self._process.returncode is not None
            or self._process_exit_event.is_set()
        ):
            raise OSError("Runner exited during initialization")
        self._runtime = response.runtime
        self._execution_count = 0
        self._state = "alive"

    async def execute(self, code: str, timeout: float) -> SupervisedExecution:
        """Execute one cell or return a truthful terminal dead-kernel outcome."""
        if self._state != "alive":
            raise KernelUnavailableError(f"Runner is {self._state}")
        if self._active is not None:
            raise ConcurrentExecutionError("Runner already has an active execution")
        if not (0 < timeout <= 3_600):
            raise ValueError("timeout must be greater than 0 and at most 3600 seconds")

        active = _ActiveExecution(uuid.uuid4().hex)
        capture = _ExecutionCapture()
        self._active = active
        self._capture = capture
        operation = asyncio.create_task(self._execute_active(active, code, timeout))
        caller_cancelled = False
        try:
            while True:
                try:
                    core = await asyncio.shield(operation)
                    break
                except asyncio.CancelledError:
                    caller_cancelled = True
                    active.cancel_event.set()
        finally:
            finalize_task = asyncio.create_task(self._finalize_execution(active, capture))
            while True:
                try:
                    await asyncio.shield(finalize_task)
                    break
                except asyncio.CancelledError:
                    caller_cancelled = True
                    active.cancel_event.set()
        if core.kernel_state == "dead":
            self._close_channels()
        if caller_cancelled:
            raise asyncio.CancelledError
        return _compose_execution(core, capture)

    async def _finalize_execution(
        self,
        active: _ActiveExecution,
        capture: _ExecutionCapture,
    ) -> None:
        await self._settle_capture(capture)
        self._capture = None
        self._active = None
        active.done_event.set()

    async def _execute_active(
        self,
        active: _ActiveExecution,
        code: str,
        timeout: float,
    ) -> _CoreOutcome:
        delivery_task = asyncio.create_task(self._deliver_execute(active, code))
        delivery_cancel_task = asyncio.create_task(active.cancel_event.wait())
        try:
            async with asyncio.timeout(COMMAND_ACK_TIMEOUT):
                await asyncio.wait(
                    {delivery_task, delivery_cancel_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if delivery_cancel_task.done():
                    if not active.committed:
                        await _cancel_tasks(delivery_task, delivery_cancel_task)
                        return _CoreOutcome(
                            "timed_out",
                            False,
                            None,
                            ErrorInfo("CancelledError", "cancelled before execution", ()),
                            self._execution_count,
                            0,
                            "alive",
                            self._runtime,
                        )
                    if not active.write_complete:
                        await _cancel_tasks(delivery_task, delivery_cancel_task)
                        return await self._fatal_outcome(
                            "RunnerProtocolTimeout",
                            "cancellation interrupted request delivery",
                            duration_ms=0,
                        )
                response = await delivery_task
        except (TimeoutError, OSError, ProtocolViolation) as error:
            await _cancel_tasks(delivery_task, delivery_cancel_task)
            return await self._fatal_outcome(
                "RunnerProtocolTimeout",
                f"execute delivery/ack failed: {error}",
                duration_ms=0,
            )
        finally:
            await _cancel_tasks(delivery_cancel_task)

        if isinstance(response, ProtocolErrorResponse):
            return await self._fatal_outcome(
                _protocol_error_type(response),
                f"{response.code}: {response.message}",
                duration_ms=0,
            )
        if (
            not isinstance(response, StartedResponse)
            or response.correlation_id != active.correlation_id
            or response.execution_count != self._execution_count + 1
        ):
            return await self._fatal_outcome(
                "RunnerProtocolError",
                "invalid or uncorrelated started response",
                duration_ms=0,
            )

        self._execution_count = response.execution_count
        active.started_event.set()
        started = time.monotonic()
        response_task = asyncio.create_task(self._next_response())
        timeout_task = asyncio.create_task(asyncio.sleep(timeout))
        cancel_task = asyncio.create_task(active.cancel_event.wait())
        await asyncio.wait(
            {response_task, timeout_task, cancel_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if timeout_task.done() or cancel_task.done():
            terminal: Response | None = None
            if response_task.done():
                try:
                    terminal = response_task.result()
                except (OSError, ProtocolViolation) as error:
                    await _cancel_tasks(response_task, timeout_task, cancel_task)
                    return await self._fatal_outcome(
                        "KernelExited",
                        f"response channel failed: {error}",
                        duration_ms=_duration_ms(started),
                        started=started,
                    )
            await _cancel_tasks(response_task, timeout_task, cancel_task)
            active.interrupt_sent = True
            reason = "cancellation" if cancel_task.done() else "deadline"
            return await self._interrupt_or_escalate(active, started, reason, terminal)

        await _cancel_tasks(timeout_task, cancel_task)
        try:
            terminal = response_task.result()
        except (OSError, ProtocolViolation) as error:
            return await self._fatal_outcome(
                "KernelExited",
                f"response channel failed: {error}",
                duration_ms=_duration_ms(started),
                started=started,
            )
        return await self._normal_terminal(active, terminal, started)

    async def _deliver_execute(self, active: _ActiveExecution, code: str) -> Response:
        await self._write_request(
            encode_request(ExecuteRequest(active.correlation_id, code)),
            active=active,
        )
        return await self._next_response()

    async def _normal_terminal(
        self,
        active: _ActiveExecution,
        response: Response,
        started: float,
    ) -> _CoreOutcome:
        if not isinstance(response, DoneResponse):
            if isinstance(response, ProtocolErrorResponse):
                error_type = _protocol_error_type(response)
                message = f"{response.code}: {response.message}"
            else:
                error_type = "RunnerProtocolError"
                message = "unexpected terminal response"
            return await self._fatal_outcome(
                error_type,
                message,
                duration_ms=_duration_ms(started),
                started=started,
            )
        if not self._valid_done(active, response):
            return await self._fatal_outcome(
                "RunnerProtocolError",
                "invalid or uncorrelated done response",
                duration_ms=_duration_ms(started),
                started=started,
            )
        self._runtime = response.runtime
        if response.outcome == "completed":
            return _CoreOutcome(
                "completed",
                response.has_result,
                response.result,
                None,
                response.execution_count,
                _duration_ms(started),
                "alive",
                response.runtime,
            )
        error = response.error or ErrorInfo("RunnerError", "missing error", ())
        return _CoreOutcome(
            "failed",
            False,
            None,
            error,
            response.execution_count,
            _duration_ms(started),
            "alive",
            response.runtime,
        )

    async def _interrupt_or_escalate(
        self,
        active: _ActiveExecution,
        started: float,
        reason: str,
        terminal: Response | None = None,
    ) -> _CoreOutcome:
        try:
            self._operations.signal_group(self._process_group, signal.SIGINT)
        except ProcessLookupError:
            return await self._fatal_outcome(
                "KernelExited",
                f"Runner exited before {reason} interrupt",
                duration_ms=_duration_ms(started),
                started=started,
            )
        except Exception as error:
            return await self._fatal_outcome(
                "CleanupError",
                f"failed to signal Runner for {reason}: {type(error).__name__}: {error}",
                duration_ms=_duration_ms(started),
                started=started,
            )

        if terminal is None:
            try:
                async with asyncio.timeout(INTERRUPT_GRACE):
                    response = await self._next_response()
            except (TimeoutError, OSError, ProtocolViolation):
                return await self._fatal_outcome(
                    "KernelKilled",
                    f"Runner did not settle after {reason} interrupt",
                    duration_ms=_duration_ms(started),
                    started=started,
                )
        else:
            response = terminal

        if isinstance(response, DoneResponse) and self._valid_done(active, response):
            self._runtime = response.runtime
            return _CoreOutcome(
                "timed_out",
                False,
                None,
                ErrorInfo("TimeoutError", f"cell interrupted by {reason}", ()),
                response.execution_count,
                _duration_ms(started),
                "alive",
                response.runtime,
            )
        if isinstance(response, ProtocolErrorResponse):
            error_type = _protocol_error_type(response)
            message = f"{response.code}: {response.message}"
        else:
            error_type = "RunnerProtocolError"
            message = "invalid terminal response after interrupt"
        return await self._fatal_outcome(
            error_type,
            message,
            duration_ms=_duration_ms(started),
            started=started,
        )

    def _valid_done(self, active: _ActiveExecution, response: DoneResponse) -> bool:
        return (
            response.correlation_id == active.correlation_id
            and response.execution_count == self._execution_count
            and response.runtime.executable == self._runtime.executable
            and response.runtime.python_version == self._runtime.python_version
            and response.runtime.environment_kind == self._runtime.environment_kind
        )

    async def cancel_active(self) -> KernelState:
        """Interrupt active work and wait until its state is stable."""
        active = self._active
        if active is None:
            return "alive" if self._state == "alive" else "dead"
        started_task = asyncio.create_task(active.started_event.wait())
        done_task = asyncio.create_task(active.done_event.wait())
        await asyncio.wait({started_task, done_task}, return_when=asyncio.FIRST_COMPLETED)
        await _cancel_tasks(started_task, done_task)
        if active.done_event.is_set():
            return "alive" if self._state == "alive" else "dead"
        active.cancel_event.set()
        await active.done_event.wait()
        return "alive" if self._state == "alive" else "dead"

    async def shutdown(self) -> ShutdownResult:
        """Close intake and remove the complete managed process group."""
        if self._state == "closed" and self._shutdown_result is not None:
            return self._shutdown_result
        if self._shutdown_task is None:
            self._shutdown_task = asyncio.create_task(self._shutdown_impl())
        operation = self._shutdown_task
        caller_cancelled = False
        while True:
            try:
                result = await asyncio.shield(operation)
                break
            except asyncio.CancelledError:
                caller_cancelled = True
        if self._state == "closed":
            self._shutdown_result = result
        elif not result.cleaned and self._shutdown_task is operation:
            self._shutdown_task = None
        if caller_cancelled:
            raise asyncio.CancelledError
        return result

    async def _shutdown_impl(self) -> ShutdownResult:
        if self._state == "closed":
            return ShutdownResult(True)
        self._state = "closing"
        active = self._active
        if active is not None:
            active.cancel_event.set()
            await active.done_event.wait()
        graceful_error: str | None = None
        if self._process.returncode is None and not self._channels_closed:
            try:
                correlation_id = uuid.uuid4().hex
                await self._write_request(encode_request(ShutdownRequest(correlation_id)))
                async with asyncio.timeout(SHUTDOWN_GRACE):
                    return_code = await asyncio.shield(self._process_wait_task)
                if return_code != 0:
                    graceful_error = f"Runner graceful shutdown exited with status {return_code}"
            except (TimeoutError, OSError, ProtocolViolation):
                pass
        cleanup_error = await self._escalate_group()
        final_error = cleanup_error or graceful_error
        self._state = "closed" if cleanup_error is None else "dead"
        self._close_channels()
        return ShutdownResult(final_error is None, final_error)

    async def _fatal_outcome(
        self,
        error_type: str,
        message: str,
        *,
        duration_ms: int,
        started: float | None = None,
    ) -> _CoreOutcome:
        cleanup_error = await self._destructive_cleanup()
        if started is not None:
            duration_ms = _duration_ms(started)
        if cleanup_error is not None:
            message = f"{message}; cleanup failed: {cleanup_error}"
            error_type = "CleanupError"
        return _CoreOutcome(
            "kernel_killed",
            False,
            None,
            ErrorInfo(error_type, message, ()),
            self._execution_count,
            duration_ms,
            "dead",
            self._runtime,
        )

    async def _destructive_cleanup(self) -> str | None:
        self._state = "dead"
        cleanup_error = await self._escalate_group()
        if cleanup_error is not None:
            self._cleanup_error = cleanup_error
        return cleanup_error

    async def _escalate_group(self) -> str | None:
        try:
            return await self._escalate_group_unchecked()
        except Exception as error:
            return f"process-group operation failed: {type(error).__name__}: {error}"

    async def _escalate_group_unchecked(self) -> str | None:
        if not self._operations.group_exists(self._process_group):
            await self._await_process_exit(0.1)
            return None
        try:
            self._operations.signal_group(self._process_group, signal.SIGTERM)
        except ProcessLookupError:
            if not self._operations.group_exists(self._process_group):
                await self._await_process_exit(0.1)
                return None
        if await self._wait_group_gone(TERMINATE_GRACE):
            await self._await_process_exit(0.1)
            return None
        try:
            self._operations.signal_group(self._process_group, signal.SIGKILL)
        except ProcessLookupError:
            if not self._operations.group_exists(self._process_group):
                await self._await_process_exit(0.1)
                return None
        if await self._wait_group_gone(KILL_GRACE):
            await self._await_process_exit(0.1)
            return None
        return "managed process group remains after SIGKILL"

    async def _wait_group_gone(self, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self._operations.group_exists(self._process_group):
                return True
            await asyncio.sleep(0.01)
        return not self._operations.group_exists(self._process_group)

    async def _await_process_exit(self, timeout: float) -> None:
        if self._process_wait_task.done():
            return
        try:
            async with asyncio.timeout(timeout):
                await asyncio.shield(self._process_wait_task)
        except TimeoutError:
            pass

    async def _observe_process_exit(self) -> None:
        while self._process.returncode is None:
            await asyncio.sleep(0.01)
        self._runner_exit_observed = True
        self._process_exit_event.set()
        active = self._active
        if active is not None:
            await active.done_event.wait()
        if self._state == "alive":
            self._state = "dead"
            cleanup_error = await self._escalate_group()
            if cleanup_error is not None:
                self._cleanup_error = cleanup_error
                self._diagnostic.feed(f"cleanup failed: {cleanup_error}\n".encode())
            self._close_channels()

    async def _write_request(
        self,
        frame: bytes,
        *,
        active: _ActiveExecution | None = None,
    ) -> None:
        view = memoryview(frame)
        loop = asyncio.get_running_loop()
        while view:
            if active is not None and not active.committed:
                active.committed = True
            try:
                written = os.write(self._request_fd, view)
            except InterruptedError:
                continue
            except BlockingIOError:
                ready = loop.create_future()
                loop.add_writer(self._request_fd, _resolve_future, ready)
                try:
                    await ready
                finally:
                    loop.remove_writer(self._request_fd)
                continue
            if written <= 0:
                raise BrokenPipeError("Runner request pipe accepted no bytes")
            view = view[written:]
        if active is not None:
            active.write_complete = True

    async def _next_response(self) -> Response:
        response_task = asyncio.create_task(self._read_response())
        exit_task = asyncio.create_task(self._process_exit_event.wait())
        try:
            await asyncio.wait(
                {response_task, exit_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if response_task.done():
                response = response_task.result()
                if (exit_task.done() or self._process.returncode is not None) and not isinstance(
                    response, ProtocolErrorResponse
                ):
                    raise OSError(
                        f"Runner exited with code {self._process.returncode} after response"
                    )
                return response
            raise OSError(f"Runner exited with code {self._process.returncode}")
        finally:
            await _cancel_tasks(response_task, exit_task)

    async def _read_response(self) -> Response:
        try:
            prefix = await self._response_reader.readexactly(4)
            length = int.from_bytes(prefix, "big")
            if length == 0 or length > MAX_CONTROL_FRAME_BYTES:
                raise ProtocolViolation(f"invalid response frame length: {length}")
            payload = await self._response_reader.readexactly(length)
        except asyncio.IncompleteReadError as error:
            raise OSError("Runner response channel closed") from error
        return parse_response_payload(payload)

    async def _drain_user_stream(
        self,
        reader: asyncio.StreamReader,
        channel: Literal["stdout", "stderr"],
    ) -> None:
        orphan = self._orphan_stdout if channel == "stdout" else self._orphan_stderr
        while chunk := await reader.read(_READ_CHUNK):
            capture = self._capture
            if capture is None:
                orphan.feed(chunk)
            else:
                capture.feed(channel, chunk)

    async def _drain_diagnostic(self) -> None:
        while chunk := await self._diagnostic_reader.read(_READ_CHUNK):
            self._diagnostic.feed(chunk)

    async def _settle_capture(self, _capture: _ExecutionCapture) -> None:
        # Runner flushes before its terminal frame; two loop turns drain pipe callbacks
        # already queued without extending attribution into a time-based quiet window.
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    def _close_channels(self) -> None:
        if self._channels_closed:
            return
        self._channels_closed = True
        try:
            os.close(self._request_fd)
        except OSError:
            pass
        self._response_transport.close()
        self._diagnostic_transport.close()
        for task in self._reader_tasks:
            task.cancel()


def _create_protocol_pipes() -> tuple[int, int, int, int, int, int]:
    descriptors: list[int] = []
    try:
        for _ in range(3):
            read_descriptor, write_descriptor = os.pipe()
            descriptors.extend((read_descriptor, write_descriptor))
    except BaseException:
        for descriptor in descriptors:
            _close_fd(descriptor)
        raise
    return (
        descriptors[0],
        descriptors[1],
        descriptors[2],
        descriptors[3],
        descriptors[4],
        descriptors[5],
    )


async def _cleanup_spawned_process(
    process: asyncio.subprocess.Process,
    operations: _ProcessOperations,
) -> str | None:
    errors: list[str] = []
    try:
        operations.signal_group(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except Exception as error:
        errors.append(f"SIGKILL failed: {type(error).__name__}: {error}")
    try:
        async with asyncio.timeout(KILL_GRACE):
            await process.wait()
    except TimeoutError:
        errors.append("Runner did not exit after SIGKILL")
    try:
        if operations.group_exists(process.pid):
            errors.append("managed process group remains after SIGKILL")
    except Exception as error:
        errors.append(f"group verification failed: {type(error).__name__}: {error}")
    return "; ".join(errors) or None


def _close_fd(descriptor: int) -> None:
    try:
        os.close(descriptor)
    except OSError:
        pass


def _protocol_error_type(response: ProtocolErrorResponse) -> str:
    if response.code == "runtime_diagnostics_error":
        return "RuntimeDiagnosticsError"
    return "RunnerProtocolError"


def _compose_execution(core: _CoreOutcome, capture: _ExecutionCapture) -> SupervisedExecution:
    output = OutputMetadata(
        total_bytes=capture.stdout.total_bytes + capture.stderr.total_bytes,
        total_lines=capture.stdout.total_lines + capture.stderr.total_lines,
        truncated=capture.stdout.truncated or capture.stderr.truncated,
    )
    return SupervisedExecution(
        status=core.status,
        stdout=capture.stdout.text(),
        stderr=capture.stderr.text(),
        has_result=core.has_result,
        result=core.result,
        error=core.error,
        execution_count=core.execution_count,
        duration_ms=core.duration_ms,
        kernel_state=core.kernel_state,
        runtime=core.runtime,
        output=output,
    )


async def _stream_reader_from_fd(fd: int) -> tuple[asyncio.StreamReader, asyncio.ReadTransport]:
    loop = asyncio.get_running_loop()
    stream = os.fdopen(fd, "rb", buffering=0)
    reader = asyncio.StreamReader(limit=MAX_CONTROL_FRAME_BYTES + 4)
    protocol = asyncio.StreamReaderProtocol(reader)
    transport, _ = await loop.connect_read_pipe(lambda: protocol, stream)
    return reader, transport


def _runner_environment() -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if key in _ENVIRONMENT_ALLOWLIST}
    if sys.prefix != sys.base_prefix:
        environment["VIRTUAL_ENV"] = os.path.abspath(sys.prefix)
    return environment


def _classify_environment(
    launch_working_directory: Path,
) -> Literal["project_venv", "active_venv", "system"]:
    if sys.prefix == sys.base_prefix:
        return "system"
    project_environment = launch_working_directory / ".venv"
    try:
        if project_environment.exists() and os.path.samefile(sys.prefix, project_environment):
            return "project_venv"
    except OSError:
        pass
    return "active_venv"


def _duration_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1_000))


async def _cancel_tasks(*tasks: asyncio.Task[object]) -> None:
    for task in tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def _resolve_future(future: asyncio.Future[None]) -> None:
    if not future.done():
        future.set_result(None)
