"""Native-process behavior tests for the persistent Python Runner."""

from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO, cast

import pytest

import amkernel.runner as runner_module
from amkernel.protocol import (
    DIAGNOSTIC_FD_ARGUMENT,
    REQUEST_FD_ARGUMENT,
    RESPONSE_FD_ARGUMENT,
    DoneResponse,
    ExecuteRequest,
    InitializeRequest,
    ProtocolErrorResponse,
    ReadyResponse,
    Response,
    ShutdownRequest,
    StartedResponse,
    encode_request,
    read_response,
    write_frame,
)

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Stage 1 Runner is POSIX-only")


class RunnerProcess:
    """Test-only host for the real Runner subprocess and private pipes."""

    def __init__(self, working_directory: Path) -> None:
        request_read, request_write = os.pipe()
        response_read, response_write = os.pipe()
        diagnostic_read, diagnostic_write = os.pipe()
        child_descriptors = (request_read, response_write, diagnostic_write)

        command = [
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
        ]
        self.process = subprocess.Popen(
            command,
            cwd=working_directory,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=child_descriptors,
            close_fds=True,
            start_new_session=True,
        )
        os.close(request_read)
        os.close(response_write)
        os.close(diagnostic_write)

        self.request = cast(BinaryIO, os.fdopen(request_write, "wb", buffering=0))
        self.response = cast(BinaryIO, os.fdopen(response_read, "rb", buffering=0))
        self.diagnostic = cast(BinaryIO, os.fdopen(diagnostic_read, "rb", buffering=0))
        assert self.process.stdout is not None
        assert self.process.stderr is not None
        self.stdout = cast(BinaryIO, self.process.stdout)
        self.stderr = cast(BinaryIO, self.process.stderr)
        self.working_directory = working_directory.resolve()

        self.send(
            InitializeRequest(
                self.correlation_id(),
                str(self.working_directory),
                "active_venv",
            )
        )
        ready = self.read_response()
        if not isinstance(ready, ReadyResponse):
            raise AssertionError(f"expected ready response, got {ready!r}")
        self.ready = ready

    @staticmethod
    def correlation_id() -> str:
        return uuid.uuid4().hex

    def send(self, request: InitializeRequest | ExecuteRequest | ShutdownRequest) -> None:
        write_frame(self.request, encode_request(request))

    def read_response(self, timeout: float = 5.0) -> Response:
        readable, _, _ = select.select([self.response], [], [], timeout)
        if not readable:
            raise AssertionError(
                f"Runner response timed out; returncode={self.process.poll()}, "
                f"stderr={self.read_available(self.stderr)!r}, "
                f"diagnostic={self.read_available(self.diagnostic)!r}"
            )
        response = read_response(self.response)
        if response is None:
            raise AssertionError("unexpected Runner response EOF")
        return response

    def start_execute(self, code: str) -> tuple[str, StartedResponse]:
        correlation_id = self.correlation_id()
        self.send(ExecuteRequest(correlation_id, code))
        started = self.read_response()
        assert isinstance(started, StartedResponse)
        assert started.correlation_id == correlation_id
        return correlation_id, started

    def finish_execute(self, correlation_id: str) -> DoneResponse | ProtocolErrorResponse:
        response = self.read_response()
        assert response.correlation_id == correlation_id
        assert isinstance(response, (DoneResponse, ProtocolErrorResponse))
        return response

    def execute(self, code: str) -> DoneResponse:
        correlation_id, _ = self.start_execute(code)
        response = self.finish_execute(correlation_id)
        assert isinstance(response, DoneResponse)
        return response

    @staticmethod
    def read_available(stream: BinaryIO, timeout: float = 0.05) -> bytes:
        chunks = bytearray()
        while True:
            readable, _, _ = select.select([stream], [], [], timeout)
            if not readable:
                return bytes(chunks)
            chunk = os.read(stream.fileno(), 65_536)
            if not chunk:
                return bytes(chunks)
            chunks.extend(chunk)
            timeout = 0.0

    def read_stdout(self, expected_bytes: int, timeout: float = 2.0) -> bytes:
        deadline = time.monotonic() + timeout
        chunks = bytearray()
        while len(chunks) < expected_bytes:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            readable, _, _ = select.select([self.stdout], [], [], remaining)
            if not readable:
                break
            chunk = os.read(self.stdout.fileno(), expected_bytes - len(chunks))
            if not chunk:
                break
            chunks.extend(chunk)
        return bytes(chunks)

    def shutdown(self) -> int:
        if self.process.poll() is None:
            self.send(ShutdownRequest(self.correlation_id()))
        return self.process.wait(timeout=3.0)

    def cleanup(self) -> None:
        try:
            if self.process.poll() is None:
                self.request.close()
                try:
                    os.killpg(self.process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    self.process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(self.process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    self.process.wait(timeout=1.0)
            else:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
        finally:
            for stream in (
                self.request,
                self.response,
                self.diagnostic,
                self.stdout,
                self.stderr,
            ):
                stream.close()


@pytest.fixture
def runner(tmp_path: Path) -> Iterator[RunnerProcess]:
    process = RunnerProcess(tmp_path)
    try:
        yield process
    finally:
        process.cleanup()


def test_ready_reports_exact_runtime(runner: RunnerProcess) -> None:
    assert runner.ready.execution_count == 0
    assert runner.ready.runtime.executable == os.path.abspath(sys.executable)
    assert runner.ready.runtime.working_directory == str(runner.working_directory)
    assert runner.ready.runtime.environment_kind == "active_venv"


def test_namespace_and_live_objects_persist(runner: RunnerProcess) -> None:
    first = runner.execute("items = []")
    second = runner.execute("items.append(1)\nitems")
    third = runner.execute("items.append(2)\nlen(items)")

    assert first.outcome == "completed"
    assert first.execution_count == 1
    assert not first.has_result
    assert second.result == [1]
    assert second.execution_count == 2
    assert third.result == 2
    assert third.execution_count == 3


def test_trailing_none_differs_from_no_expression(runner: RunnerProcess) -> None:
    no_expression = runner.execute("value = None")
    trailing_none = runner.execute("None")

    assert not no_expression.has_result
    assert trailing_none.has_result
    assert trailing_none.result is None


def test_error_preserves_mutation_and_runner(runner: RunnerProcess) -> None:
    runner.execute("values = []")
    failed = runner.execute("values.append('kept')\nraise ValueError('bad value')")
    observed = runner.execute("values")

    assert failed.outcome == "failed"
    assert failed.error is not None
    assert failed.error.type == "ValueError"
    assert failed.error.message == "bad value"
    assert any("<amkernel-cell-2>" in line for line in failed.error.traceback)
    assert observed.result == ["kept"]
    assert observed.execution_count == 3


def test_system_exit_is_an_ordinary_failure(runner: RunnerProcess) -> None:
    failed = runner.execute("raise SystemExit(7)")
    next_result = runner.execute("6 * 7")

    assert failed.outcome == "failed"
    assert failed.error is not None
    assert failed.error.type == "SystemExit"
    assert next_result.result == 42


def test_non_json_and_failing_repr_are_bounded(runner: RunnerProcess) -> None:
    non_json = runner.execute("{1, 2}")
    failing_repr = runner.execute(
        "class BadRepr:\n    def __repr__(self):\n        raise RuntimeError('no repr')\nBadRepr()"
    )

    assert isinstance(non_json.result, dict)
    assert non_json.result["kind"] == "repr"
    assert non_json.result["typeName"] == "set"
    assert isinstance(failing_repr.result, dict)
    assert failing_repr.result["kind"] == "repr"
    assert "repr failed" in cast(str, failing_repr.result["value"])
    assert failing_repr.result["truncated"] is True


def test_cycle_and_nonfinite_values_use_repr(runner: RunnerProcess) -> None:
    cycle = runner.execute("value = []\nvalue.append(value)\nvalue")
    nonfinite = runner.execute("float('nan')")

    assert isinstance(cycle.result, dict)
    assert cycle.result["kind"] == "repr"
    assert isinstance(nonfinite.result, dict)
    assert nonfinite.result["kind"] == "repr"


def test_json_looking_and_invalid_utf8_output_cannot_corrupt_frames(
    runner: RunnerProcess,
) -> None:
    emitted = b'{"protocolVersion":999,"type":"done"}\n\xffpartial'
    code = f"import os\nos.write(1, {emitted!r})\n{{'status': 'still-valid'}}"

    done = runner.execute(code)

    assert done.result == {"status": "still-valid"}
    assert runner.read_stdout(len(emitted)) == emitted


def test_sigint_returns_interrupted_and_runner_remains_usable(runner: RunnerProcess) -> None:
    correlation_id, started = runner.start_execute("import time\ntime.sleep(30)")
    os.killpg(runner.process.pid, signal.SIGINT)
    interrupted = runner.finish_execute(correlation_id)
    assert isinstance(interrupted, DoneResponse)

    assert interrupted.outcome == "interrupted"
    assert interrupted.execution_count == started.execution_count
    assert interrupted.error is not None
    assert interrupted.error.type == "KeyboardInterrupt"
    assert runner.execute("21 * 2").result == 42


def test_user_raised_keyboard_interrupt_is_neutral_runner_outcome(
    runner: RunnerProcess,
) -> None:
    interrupted = runner.execute("raise KeyboardInterrupt")

    assert interrupted.outcome == "interrupted"
    assert runner.execute("'alive'").result == "alive"


def test_shutdown_exits_cleanly(runner: RunnerProcess) -> None:
    assert runner.shutdown() == 0


def test_fork_child_does_not_hold_control_descriptors(tmp_path: Path) -> None:
    process = RunnerProcess(tmp_path)
    try:
        forked = process.execute(
            "import os, time\n"
            "pid = os.fork()\n"
            "if pid == 0:\n"
            "    time.sleep(30)\n"
            "    os._exit(0)\n"
            "pid"
        )
        child_pid = cast(int, forked.result)

        started = time.monotonic()
        assert process.shutdown() == 0
        assert time.monotonic() - started < 2.0
        os.kill(child_pid, signal.SIGKILL)
    finally:
        process.cleanup()


def spawn_uninitialized_runner(working_directory: Path) -> RunnerProcess:
    process = RunnerProcess.__new__(RunnerProcess)
    request_read, request_write = os.pipe()
    response_read, response_write = os.pipe()
    diagnostic_read, diagnostic_write = os.pipe()
    command = [
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
    ]
    process.process = subprocess.Popen(
        command,
        cwd=working_directory,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        pass_fds=(request_read, response_write, diagnostic_write),
        close_fds=True,
        start_new_session=True,
    )
    os.close(request_read)
    os.close(response_write)
    os.close(diagnostic_write)
    process.request = cast(BinaryIO, os.fdopen(request_write, "wb", buffering=0))
    process.response = cast(BinaryIO, os.fdopen(response_read, "rb", buffering=0))
    process.diagnostic = cast(BinaryIO, os.fdopen(diagnostic_read, "rb", buffering=0))
    assert process.process.stdout is not None
    assert process.process.stderr is not None
    process.stdout = cast(BinaryIO, process.process.stdout)
    process.stderr = cast(BinaryIO, process.process.stderr)
    process.working_directory = working_directory.resolve()
    return process


def test_version_mismatch_returns_correlated_error_then_exits(tmp_path: Path) -> None:
    process = spawn_uninitialized_runner(tmp_path)
    correlation_id = RunnerProcess.correlation_id()

    incompatible = json.dumps(
        {
            "protocolVersion": 2,
            "type": "initialize",
            "correlationId": correlation_id,
            "payload": {
                "launchWorkingDirectory": str(tmp_path.resolve()),
                "environmentKind": "active_venv",
            },
        },
        separators=(",", ":"),
    ).encode()
    write_frame(process.request, len(incompatible).to_bytes(4, "big") + incompatible)

    try:
        response = process.read_response()
        assert isinstance(response, ProtocolErrorResponse)
        assert response.correlation_id == correlation_id
        assert response.code == "version_mismatch"
        assert process.process.wait(timeout=2.0) == 2
    finally:
        process.cleanup()


def test_initial_runtime_diagnostics_failure_has_distinct_code(tmp_path: Path) -> None:
    working_directory = tmp_path / "removed"
    working_directory.mkdir()
    launch_path = str(working_directory.resolve())
    process = spawn_uninitialized_runner(working_directory)
    working_directory.rmdir()
    correlation_id = RunnerProcess.correlation_id()
    process.send(InitializeRequest(correlation_id, launch_path, "active_venv"))

    try:
        response = process.read_response()
        assert isinstance(response, ProtocolErrorResponse)
        assert response.correlation_id == correlation_id
        assert response.code == "runtime_diagnostics_error"
        assert process.process.wait(timeout=2.0) == 2
    finally:
        process.cleanup()


def test_oversized_result_and_type_name_stay_bounded(runner: RunnerProcess) -> None:
    oversized_json = runner.execute("'x' * 1_048_577")
    oversized_type = runner.execute(
        "class HugeName:\n    pass\nHugeName.__qualname__ = 'T' * 10_000\nHugeName()"
    )

    assert isinstance(oversized_json.result, dict)
    assert oversized_json.result["kind"] == "repr"
    assert oversized_json.result["truncated"] is True
    assert isinstance(oversized_type.result, dict)
    assert len(cast(str, oversized_type.result["typeName"]).encode()) <= 256
    assert len(json.dumps(oversized_type.result, ensure_ascii=False).encode()) <= 8_192


def test_failing_exception_message_is_bounded_and_runner_survives(
    runner: RunnerProcess,
) -> None:
    failed = runner.execute(
        "class BadError(Exception):\n"
        "    def __str__(self):\n"
        "        raise RuntimeError('cannot render')\n"
        "raise BadError()"
    )

    assert failed.outcome == "failed"
    assert failed.error is not None
    assert "custom __str__ omitted" in failed.error.message
    assert runner.execute("'still alive'").result == "still alive"


def test_large_error_message_is_bounded_and_runner_survives(
    runner: RunnerProcess,
) -> None:
    failed = runner.execute("raise ValueError('\\x00' * (32 * 1024 * 1024))")

    assert failed.outcome == "failed"
    assert failed.error is not None
    assert len(failed.error.message.encode()) <= 2_048
    assert sum(len(line.encode()) for line in failed.error.traceback) <= 7_100
    assert runner.execute("'alive'").result == "alive"


def test_syntax_error_increments_count_and_runner_survives(runner: RunnerProcess) -> None:
    failed = runner.execute("if True print('invalid')")

    assert failed.outcome == "failed"
    assert failed.execution_count == 1
    assert failed.error is not None
    assert failed.error.type == "SyntaxError"
    assert runner.execute("42").execution_count == 2


def test_stage_one_namespace_has_no_prelude_helpers(runner: RunnerProcess) -> None:
    observed = runner.execute(
        "[name for name in ('display', 'artifact', 'read', 'write', 'env') if name in globals()]"
    )

    assert observed.result == []


def test_runner_restores_sigint_handler_after_user_mutation(runner: RunnerProcess) -> None:
    runner.execute("import signal\nsignal.signal(signal.SIGINT, signal.SIG_IGN)")
    correlation_id, _ = runner.start_execute(
        "import time\nprint('entered', flush=True)\ntime.sleep(30)"
    )
    readable, _, _ = select.select([runner.stdout], [], [], 2.0)
    assert readable
    assert runner.stdout.readline() == b"entered\n"
    os.killpg(runner.process.pid, signal.SIGINT)
    interrupted = runner.finish_execute(correlation_id)

    assert isinstance(interrupted, DoneResponse)
    assert interrupted.outcome == "interrupted"
    assert runner.execute("'alive'").result == "alive"


def test_idle_sigint_does_not_kill_next_cell(runner: RunnerProcess) -> None:
    os.killpg(runner.process.pid, signal.SIGINT)
    time.sleep(0.05)

    assert runner.execute("6 * 7").result == 42


def test_working_directory_change_is_reported_and_persists(runner: RunnerProcess) -> None:
    changed = runner.execute("import os\nos.mkdir('nested')\nos.chdir('nested')")
    observed = runner.execute("os.getcwd()")

    expected = str(runner.working_directory / "nested")
    assert changed.runtime.working_directory == expected
    assert observed.result == expected


def test_deleted_working_directory_is_fatal_protocol_error(runner: RunnerProcess) -> None:
    correlation_id, _ = runner.start_execute(
        "import os, tempfile\npath = tempfile.mkdtemp()\nos.chdir(path)\nos.rmdir(path)"
    )
    response = runner.finish_execute(correlation_id)

    assert isinstance(response, ProtocolErrorResponse)
    assert response.code == "runtime_diagnostics_error"
    assert runner.process.wait(timeout=2.0) == 2


def test_compile_error_in_trailing_expression_does_not_run_prefix(
    runner: RunnerProcess,
) -> None:
    failed = runner.execute("marker = 1\nyield 2")
    observed = runner.execute("'marker' in globals()")

    assert failed.outcome == "failed"
    assert failed.error is not None
    assert failed.error.type == "SyntaxError"
    assert observed.result is False


def test_json_result_is_snapshotted_before_user_flush(runner: RunnerProcess) -> None:
    done = runner.execute(
        "import sys\n"
        "result = {'ok': True}\n"
        "class MutatingStream:\n"
        "    def write(self, value):\n"
        "        return len(value)\n"
        "    def flush(self):\n"
        "        result['mutated'] = {1}\n"
        "sys.stdout = MutatingStream()\n"
        "result"
    )

    assert done.outcome == "completed"
    assert done.result == {"ok": True}
    assert runner.execute("42").result == 42


def test_runtime_identity_ignores_user_mutation(runner: RunnerProcess) -> None:
    expected = runner.ready.runtime
    done = runner.execute(
        "import platform, sys\n"
        "sys.executable = '/tmp/fake-python'\n"
        "sys.prefix = '/tmp/fake-prefix'\n"
        "sys.base_prefix = '/tmp/fake-base'\n"
        "platform.python_version = lambda: '0.0.0'\n"
        "42"
    )

    assert done.runtime.executable == expected.executable
    assert done.runtime.python_version == expected.python_version
    assert done.runtime.environment_kind == expected.environment_kind
    assert runner.execute("'alive'").runtime.python_version == expected.python_version


def test_oversized_high_escape_result_does_not_kill_runner(
    runner: RunnerProcess,
) -> None:
    done = runner.execute("'\\x00' * (32 * 1024 * 1024)")

    assert isinstance(done.result, dict)
    assert done.result["kind"] == "repr"
    assert done.result["truncated"] is True
    assert runner.execute("'alive'").result == "alive"


def test_type_metadata_failure_uses_unknown_truncated_fallback(
    runner: RunnerProcess,
) -> None:
    done = runner.execute(
        "class HostileName(str):\n"
        "    def __bool__(self): raise RuntimeError('bool')\n"
        "    def __eq__(self, other): raise RuntimeError('eq')\n"
        "    def __format__(self, spec): raise RuntimeError('format')\n"
        "class Odd:\n"
        "    pass\n"
        "Odd.__qualname__ = HostileName('Odd')\n"
        "Odd()"
    )

    assert isinstance(done.result, dict)
    assert done.result["typeName"] == "<unknown>"
    assert done.result["truncated"] is True


def test_internal_dispatch_failure_is_correlated(runner: RunnerProcess) -> None:
    correlation_id, _ = runner.start_execute(
        "import __main__\n__main__._INSTALL_SIGNAL_HANDLER = None\n42"
    )
    response = runner.finish_execute(correlation_id)

    assert isinstance(response, ProtocolErrorResponse)
    assert response.code == "internal_protocol_error"
    assert runner.process.wait(timeout=2.0) == 2


def test_completion_sigint_races_always_leave_terminal_response(
    runner: RunnerProcess,
) -> None:
    for _ in range(50):
        correlation_id, _ = runner.start_execute("sum(range(10_000))")
        os.killpg(runner.process.pid, signal.SIGINT)
        response = runner.finish_execute(correlation_id)
        assert isinstance(response, DoneResponse)

    assert runner.execute("'alive'").result == "alive"


def test_large_integer_frame_returns_correlated_protocol_error(
    runner: RunnerProcess,
) -> None:
    correlation_id = RunnerProcess.correlation_id()
    malformed = (
        b'{"protocolVersion":'
        + (b"9" * 5_000)
        + b',"type":"shutdown","correlationId":"'
        + correlation_id.encode()
        + b'","payload":{}}'
    )
    write_frame(runner.request, len(malformed).to_bytes(4, "big") + malformed)

    response = runner.read_response()
    assert isinstance(response, ProtocolErrorResponse)
    assert response.correlation_id == correlation_id
    assert response.code == "invalid_request"
    assert runner.process.wait(timeout=2.0) == 2


def test_finalization_seam_converts_pending_sigint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def interrupt_once(_operation: int, _mask: set[int]) -> set[int]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise KeyboardInterrupt
        return set()

    monkeypatch.setattr(runner_module, "_PTHREAD_SIGMASK", interrupt_once)
    state = runner_module._SignalState(executing=True)
    completed = runner_module._CellResult("completed", True, 42, None)

    observed = runner_module._block_sigint_for_finalization(state, completed)

    assert observed.outcome == "interrupted"
    assert observed.error is not None
    assert observed.error.type == "KeyboardInterrupt"
    assert state.executing is False
    assert calls == 2


def test_utf8_truncation_uses_full_exact_boundary() -> None:
    assert runner_module._truncate_utf8("abc", 3) == ("abc", False)
    assert runner_module._truncate_utf8("abcd", 3) == ("…", True)
    assert runner_module._truncate_utf8("é", 2) == ("é", False)


def test_large_integer_error_argument_is_summarized_without_conversion(
    runner: RunnerProcess,
) -> None:
    failed = runner.execute(
        "import sys\nsys.set_int_max_str_digits(0)\nraise ValueError(10 ** 100_000)"
    )

    assert failed.error is not None
    assert "approximately" in failed.error.message
    assert len(failed.error.message.encode()) <= 2_048
    assert runner.execute("'alive'").result == "alive"


def test_deep_exception_chain_is_bounded_and_runner_survives(
    runner: RunnerProcess,
) -> None:
    failed = runner.execute(
        "previous = None\n"
        "for index in range(200):\n"
        "    try:\n"
        "        if previous is None:\n"
        "            raise ValueError('root')\n"
        "        raise ValueError(f'layer {index}') from previous\n"
        "    except ValueError as current:\n"
        "        previous = current\n"
        "raise previous"
    )

    assert failed.error is not None
    assert any("chain truncated" in line for line in failed.error.traceback)
    assert runner.execute("'alive'").result == "alive"


def test_hostile_exception_attribute_access_does_not_kill_runner(
    runner: RunnerProcess,
) -> None:
    failed = runner.execute(
        "class HostileError(Exception):\n"
        "    def __getattribute__(self, name):\n"
        "        if name == '__traceback__':\n"
        "            raise RuntimeError('blocked')\n"
        "        return super().__getattribute__(name)\n"
        "raise HostileError('safe message')"
    )

    assert failed.outcome == "failed"
    assert failed.error is not None
    assert runner.execute("'alive'").result == "alive"


def test_traceback_preserves_syntax_caret_keyerror_and_cause_headers(
    runner: RunnerProcess,
) -> None:
    syntax = runner.execute("if True print('invalid')")
    key_error = runner.execute("{}['missing']")
    caused = runner.execute(
        "try:\n"
        "    raise KeyError('root')\n"
        "except KeyError as root:\n"
        "    raise ValueError('outer') from root"
    )

    assert syntax.error is not None
    assert any("^" in line for line in syntax.error.traceback)
    assert key_error.error is not None
    assert key_error.error.message == "'missing'"
    assert caused.error is not None
    assert any("direct cause" in line for line in caused.error.traceback)


def test_hostile_error_argument_subclasses_do_not_run_hooks(
    runner: RunnerProcess,
) -> None:
    codes = [
        (
            "class HostileStr(str):\n"
            "    def __iter__(self): raise RuntimeError('iter')\n"
            "    def __repr__(self): raise RuntimeError('repr')\n"
            "    def __format__(self, spec): raise RuntimeError('format')\n"
            "raise ValueError(HostileStr('value'))"
        ),
        (
            "class HostileBytes(bytes):\n"
            "    def __len__(self): raise RuntimeError('len')\n"
            "    def __repr__(self): raise RuntimeError('repr')\n"
            "raise ValueError(HostileBytes(b'value'))"
        ),
        (
            "class HostileTuple(tuple):\n"
            "    def __len__(self): raise RuntimeError('len')\n"
            "    def __iter__(self): raise RuntimeError('iter')\n"
            "error = ValueError()\n"
            "error.args = HostileTuple(('value',))\n"
            "raise error"
        ),
    ]

    for code in codes:
        failed = runner.execute(code)
        assert failed.outcome == "failed"
        assert failed.error is not None

    assert runner.execute("'alive'").result == "alive"


def test_hostile_exception_metaclass_never_reaches_formatter(
    runner: RunnerProcess,
) -> None:
    failed = runner.execute(
        "class HostileMeta(type):\n"
        "    def __getattribute__(cls, name):\n"
        "        if name in {'__module__', '__qualname__', '__str__'}:\n"
        "            raise RuntimeError('metadata hook')\n"
        "        return super().__getattribute__(name)\n"
        "class HostileError(Exception, metaclass=HostileMeta):\n"
        "    pass\n"
        "raise HostileError('bounded')"
    )

    assert failed.outcome == "failed"
    assert failed.error is not None
    assert runner.execute("'alive'").result == "alive"
