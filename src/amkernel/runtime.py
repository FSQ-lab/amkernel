"""FIFO orchestration for one persistent Python Runner."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from amkernel.protocol import ErrorInfo, RuntimeDiagnostics
from amkernel.supervisor import (
    KernelStartError,
    KernelSupervisor,
    KernelUnavailableError,
    OutputMetadata,
    ShutdownResult,
    SupervisedExecution,
    configured_runtime,
)

RuntimeState = Literal["new", "alive", "dead", "closed"]
_HOST_DIAGNOSTIC_BYTES = 65_536


class RuntimeClosedError(RuntimeError):
    """The Runtime has stopped accepting execution calls."""


class _Supervisor(Protocol):
    @property
    def state(self) -> str: ...

    @property
    def execution_count(self) -> int: ...

    @property
    def runtime(self) -> RuntimeDiagnostics: ...

    @property
    def diagnostic_tail(self) -> str: ...

    async def execute(self, code: str, timeout: float) -> SupervisedExecution: ...

    async def shutdown(self) -> ShutdownResult: ...


SupervisorFactory = Callable[[Path], Awaitable[_Supervisor]]


@dataclass(slots=True)
class _Command:
    code: str
    timeout: float
    reset: bool
    result: asyncio.Future[SupervisedExecution]
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)


async def _start_supervisor(working_directory: Path) -> _Supervisor:
    return await KernelSupervisor.start(working_directory)


class KernelRuntime:
    """Serialize execute/reset calls and own one truthful kernel lifecycle."""

    def __init__(
        self,
        working_directory: Path | None = None,
        *,
        supervisor_factory: SupervisorFactory = _start_supervisor,
    ) -> None:
        initial_runtime = configured_runtime(working_directory)
        self._working_directory = Path(initial_runtime.working_directory)
        self._supervisor_factory = supervisor_factory
        self._state: RuntimeState = "new"
        self._supervisor: _Supervisor | None = None
        self._last_runtime = initial_runtime
        self._last_execution_count = 0
        self._configured_runtime = initial_runtime
        self._commands: deque[_Command] = deque()
        self._wake_worker = asyncio.Event()
        self._worker_task: asyncio.Task[None] | None = None
        self._active_command: _Command | None = None
        self._shutdown_task: asyncio.Task[ShutdownResult] | None = None
        self._shutdown_result: ShutdownResult | None = None
        self._worker_cleanup_result: ShutdownResult | None = None
        self._startup_failure: KernelStartError | None = None
        self._diagnostic_tail = ""
        self._last_supervisor_diagnostic = ""

    @property
    def state(self) -> RuntimeState:
        return self._state

    @property
    def execution_count(self) -> int:
        return self._last_execution_count

    @property
    def runtime(self) -> RuntimeDiagnostics:
        return self._last_runtime

    @property
    def diagnostic_tail(self) -> str:
        return self._diagnostic_tail

    async def execute(
        self,
        code: str,
        *,
        timeout: float = 30.0,
        reset: bool = False,
    ) -> SupervisedExecution:
        """Queue one cell; caller cancellation abandons or interrupts only that call."""
        if self._state == "closed":
            raise RuntimeClosedError("Runtime is closed")

        loop = asyncio.get_running_loop()
        command = _Command(code, timeout, reset, loop.create_future())
        self._commands.append(command)
        self._ensure_worker()
        self._wake_worker.set()
        try:
            return await asyncio.shield(command.result)
        except asyncio.CancelledError:
            command.cancelled.set()
            command.result.cancel()
            self._wake_worker.set()
            raise

    async def shutdown(self) -> ShutdownResult:
        """Stop intake immediately and stabilize all owned process work."""
        if self._shutdown_task is None:
            if self._shutdown_result is not None:
                return self._shutdown_result
            self._state = "closed"
            self._shutdown_task = asyncio.create_task(self._shutdown_impl())

        operation = self._shutdown_task
        caller_cancelled = False
        while True:
            try:
                result = await asyncio.shield(operation)
                break
            except asyncio.CancelledError:
                caller_cancelled = True
        self._shutdown_result = result
        if caller_cancelled:
            raise asyncio.CancelledError
        return result

    def _ensure_worker(self) -> None:
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._run_worker())

    async def _run_worker(self) -> None:
        while True:
            while not self._commands:
                if self._state == "closed":
                    self._worker_cleanup_result = await self._close_supervisor()
                    return
                self._wake_worker.clear()
                await self._wake_worker.wait()

            command = self._commands.popleft()
            if command.cancelled.is_set() or command.result.cancelled():
                continue
            if self._state == "closed":
                self._reject_command(command)
                continue

            self._active_command = command
            try:
                outcome = await self._process(command)
            except Exception as error:
                if not command.result.done():
                    command.result.set_exception(error)
            else:
                if (
                    outcome is not None
                    and not command.cancelled.is_set()
                    and not command.result.done()
                    and not self._is_closed()
                ):
                    command.result.set_result(outcome)
            finally:
                if self._is_closed():
                    self._reject_command(command)
                self._active_command = None

            if self._is_closed():
                self._reject_queued_commands()
                self._worker_cleanup_result = await self._close_supervisor()
                return

    async def _process(self, command: _Command) -> SupervisedExecution | None:
        if command.reset:
            reset_failure = await self._replace_supervisor()
            if reset_failure is not None:
                return reset_failure
        elif self._state == "new":
            start_failure = await self._start_new_supervisor()
            if start_failure is not None:
                return start_failure
        elif self._state == "dead":
            return self._dead_execution(
                "KernelUnavailable",
                "kernel is dead; reset=true is required for recovery",
            )

        if self._state == "closed" or command.cancelled.is_set():
            return None

        supervisor = self._supervisor
        if supervisor is None or self._state != "alive":
            return self._dead_execution("KernelUnavailable", "kernel is not available")

        execution = asyncio.create_task(supervisor.execute(command.code, command.timeout))
        cancellation = asyncio.create_task(command.cancelled.wait())
        try:
            done, _ = await asyncio.wait(
                {execution, cancellation},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancellation in done:
                execution.cancel()
                await asyncio.gather(execution, return_exceptions=True)
                self._observe_supervisor(supervisor)
                return None
            outcome = await execution
        except KernelUnavailableError:
            if not self._is_closed():
                self._state = "dead"
            self._observe_supervisor(supervisor)
            return self._dead_execution("KernelUnavailable", "kernel is not available")
        finally:
            if not cancellation.done():
                cancellation.cancel()
            await asyncio.gather(cancellation, return_exceptions=True)

        self._record_execution(supervisor, outcome)
        return outcome

    async def _replace_supervisor(self) -> SupervisedExecution | None:

        current = self._supervisor
        if current is not None:
            cleanup = await current.shutdown()
            self._observe_supervisor(current)
            if not cleanup.cleaned:
                if self._state != "closed":
                    self._state = "dead"
                self._record_host_diagnostic(cleanup.error or "reset cleanup failed")
                return self._dead_execution(
                    "ResetCleanupError",
                    "managed kernel cleanup failed during reset",
                )
        elif self._startup_failure is not None:
            cleanup = await self._startup_failure.retry_cleanup()
            if not cleanup.cleaned:
                if not self._is_closed():
                    self._state = "dead"
                self._record_host_diagnostic(cleanup.error or "startup cleanup retry failed")
                return self._dead_execution(
                    "ResetCleanupError",
                    "managed kernel cleanup failed during reset",
                )
            self._startup_failure = None

        self._supervisor = None
        self._last_execution_count = 0
        self._last_runtime = self._configured_runtime
        if self._state == "closed":
            return None
        self._state = "dead"
        return await self._start_new_supervisor()

    async def _start_new_supervisor(self) -> SupervisedExecution | None:
        try:
            supervisor = await self._supervisor_factory(self._working_directory)
        except KernelStartError as error:
            self._record_host_diagnostic(str(error))
            if error.cleanup_pending:
                self._startup_failure = error
            if not self._is_closed():
                self._state = "dead"
            return self._dead_execution("KernelStartError", "kernel failed to start")
        except Exception as error:
            self._record_host_diagnostic(f"{type(error).__name__}: {error}")
            if not self._is_closed():
                self._state = "dead"
            return self._dead_execution("KernelStartError", "kernel failed to start")

        self._supervisor = supervisor
        self._startup_failure = None
        self._last_runtime = supervisor.runtime
        self._last_execution_count = supervisor.execution_count
        self._last_supervisor_diagnostic = ""
        self._capture_supervisor_diagnostic(supervisor)
        if self._is_closed():
            return None
        self._state = "alive"
        return None

    def _record_execution(
        self,
        supervisor: _Supervisor,
        outcome: SupervisedExecution,
    ) -> None:
        self._last_runtime = outcome.runtime
        self._last_execution_count = outcome.execution_count
        self._capture_supervisor_diagnostic(supervisor)
        if not self._is_closed():
            self._state = "alive" if outcome.kernel_state == "alive" else "dead"

    def _observe_supervisor(self, supervisor: _Supervisor) -> None:
        self._last_runtime = supervisor.runtime
        self._last_execution_count = supervisor.execution_count
        self._capture_supervisor_diagnostic(supervisor)
        if self._state != "closed":
            self._state = "alive" if supervisor.state == "alive" else "dead"

    def _dead_execution(self, error_type: str, message: str) -> SupervisedExecution:
        return SupervisedExecution(
            status="kernel_killed",
            stdout="",
            stderr="",
            has_result=False,
            result=None,
            error=ErrorInfo(error_type, message, ()),
            execution_count=self._last_execution_count,
            duration_ms=0,
            kernel_state="dead",
            runtime=self._last_runtime,
            output=OutputMetadata(0, 0, False),
        )

    async def _shutdown_impl(self) -> ShutdownResult:
        self._reject_queued_commands()
        active = self._active_command
        if active is not None:
            active.cancelled.set()
            self._reject_command(active)
        self._wake_worker.set()

        direct_result = await self._close_supervisor()
        worker = self._worker_task
        if worker is not None and worker is not asyncio.current_task():
            await worker
        worker_result = self._worker_cleanup_result
        if direct_result.cleaned and (worker_result is None or worker_result.cleaned):
            return ShutdownResult(True)
        errors = [
            result.error
            for result in (direct_result, worker_result)
            if result is not None and not result.cleaned and result.error is not None
        ]
        return ShutdownResult(False, "; ".join(dict.fromkeys(errors)) or "cleanup failed")

    async def _close_supervisor(self) -> ShutdownResult:
        supervisor = self._supervisor
        if supervisor is not None:
            result = await supervisor.shutdown()
            self._observe_supervisor(supervisor)
            return result
        startup_failure = self._startup_failure
        if startup_failure is None:
            return ShutdownResult(True)
        result = await startup_failure.retry_cleanup()
        if result.cleaned:
            self._startup_failure = None
        else:
            self._record_host_diagnostic(result.error or "startup cleanup retry failed")
        return result

    def _capture_supervisor_diagnostic(self, supervisor: _Supervisor) -> None:
        current = supervisor.diagnostic_tail
        previous = self._last_supervisor_diagnostic
        detail = current[len(previous) :] if current.startswith(previous) else current
        self._last_supervisor_diagnostic = current
        if detail:
            self._record_host_diagnostic(detail)

    def _record_host_diagnostic(self, message: str) -> None:
        combined = f"{self._diagnostic_tail}{message}\n".encode("utf-8", errors="replace")
        tail = combined[-_HOST_DIAGNOSTIC_BYTES:]
        while tail and tail[0] & 0xC0 == 0x80:
            tail = tail[1:]
        self._diagnostic_tail = tail.decode("utf-8", errors="replace")

    def _is_closed(self) -> bool:
        # State may change across awaits in another task; keep that race visible to mypy.
        return self._state == "closed"

    def _reject_queued_commands(self) -> None:
        while self._commands:
            command = self._commands.popleft()
            command.cancelled.set()
            self._reject_command(command)

    @staticmethod
    def _reject_command(command: _Command) -> None:
        if not command.result.done():
            command.result.set_exception(RuntimeClosedError("Runtime is closed"))
