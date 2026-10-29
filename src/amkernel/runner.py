"""Persistent Python Runner process for the private AMKernel protocol."""

from __future__ import annotations
import __future__

import argparse
import ast
import builtins
import os
import platform
import signal
import sys
import traceback
from collections.abc import Sized
from dataclasses import dataclass
from types import CodeType, FrameType, TracebackType
from typing import BinaryIO, cast

from amkernel.protocol import (
    DIAGNOSTIC_FD_ARGUMENT,
    MAX_ERROR_BYTES,
    MAX_ERROR_TYPE_BYTES,
    MAX_PROTOCOL_ERROR_MESSAGE_BYTES,
    MAX_RESULT_BYTES,
    REQUEST_FD_ARGUMENT,
    RESPONSE_FD_ARGUMENT,
    DoneOutcome,
    DoneResponse,
    EnvironmentKind,
    ErrorInfo,
    ExecuteRequest,
    InitializeRequest,
    JsonValue,
    ProtocolErrorCode,
    ProtocolErrorResponse,
    ProtocolViolation,
    ReadyResponse,
    Response,
    RuntimeDiagnostics,
    ShutdownRequest,
    StartedResponse,
    encode_response,
    json_size,
    read_request,
    snapshot_json,
    write_frame,
)

_REPR_BYTES = 4_096
_REPR_OBJECT_BYTES = 8_192
_TRACEBACK_TEXT_BYTES = 7_000
_ERROR_MESSAGE_BYTES = 2_048
_MAX_EXCEPTION_CHAIN = 32
_MAX_TRACEBACK_FRAMES = 100
_FUTURE_FLAGS = sum(
    getattr(__future__, feature).compiler_flag for feature in __future__.all_feature_names
)
_GETCWD = os.getcwd
_REALPATH = os.path.realpath
_ABSPATH = os.path.abspath
_EXISTS = os.path.exists
_JOIN = os.path.join
_SAMEFILE = os.path.samefile
_INITIAL_EXECUTABLE = _ABSPATH(sys.executable)
_INITIAL_PYTHON_VERSION = platform.python_version()
_INITIAL_PREFIX = sys.prefix
_INITIAL_BASE_PREFIX = sys.base_prefix
_PTHREAD_SIGMASK = signal.pthread_sigmask
_INSTALL_SIGNAL_HANDLER = signal.signal
_PENDING_SIGNALS = signal.sigpending
_WAIT_FOR_SIGNAL = signal.sigwait
_SIGINT = signal.SIGINT
_SIG_BLOCK = signal.SIG_BLOCK
_SIG_SETMASK = signal.SIG_SETMASK
_TRACEBACK_EXCEPTION = traceback.TracebackException


@dataclass(slots=True)
class _SignalState:
    executing: bool = False

    def handle_sigint(self, _signum: int, _frame: FrameType | None) -> None:
        if self.executing:
            self.executing = False
            raise KeyboardInterrupt


@dataclass(frozen=True, slots=True)
class _CellResult:
    outcome: DoneOutcome
    has_result: bool
    result: JsonValue
    error: ErrorInfo | None


@dataclass(frozen=True, slots=True)
class _Bootstrap:
    request: BinaryIO
    response: BinaryIO
    diagnostic: BinaryIO


class _RuntimeDiagnosticsFailure(RuntimeError):
    pass


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m amkernel.runner", allow_abbrev=False)
    parser.add_argument(REQUEST_FD_ARGUMENT, type=int, required=True)
    parser.add_argument(RESPONSE_FD_ARGUMENT, type=int, required=True)
    parser.add_argument(DIAGNOSTIC_FD_ARGUMENT, type=int, required=True)
    return parser


def _bootstrap(argv: list[str] | None) -> _Bootstrap:
    raw_arguments = list(sys.argv[1:] if argv is None else argv)
    for option in (REQUEST_FD_ARGUMENT, RESPONSE_FD_ARGUMENT, DIAGNOSTIC_FD_ARGUMENT):
        occurrences = sum(
            argument == option or argument.startswith(f"{option}=") for argument in raw_arguments
        )
        if occurrences != 1:
            raise ValueError(f"{option} must appear exactly once")
    arguments = _build_argument_parser().parse_args(raw_arguments)
    descriptors = (
        cast(int, arguments.request_fd),
        cast(int, arguments.response_fd),
        cast(int, arguments.diagnostic_fd),
    )
    if any(descriptor < 3 for descriptor in descriptors):
        raise ValueError("private protocol descriptors must be at least 3")
    if len(set(descriptors)) != len(descriptors):
        raise ValueError("private protocol descriptors must be distinct")

    for descriptor in descriptors:
        os.fstat(descriptor)
        os.set_inheritable(descriptor, False)

    def close_protocol_descriptors_in_child() -> None:
        for descriptor in descriptors:
            try:
                os.close(descriptor)
            except OSError:
                pass

    os.register_at_fork(after_in_child=close_protocol_descriptors_in_child)
    return _Bootstrap(
        request=cast(BinaryIO, os.fdopen(descriptors[0], "rb", buffering=0, closefd=False)),
        response=cast(BinaryIO, os.fdopen(descriptors[1], "wb", buffering=0, closefd=False)),
        diagnostic=cast(BinaryIO, os.fdopen(descriptors[2], "wb", buffering=0, closefd=False)),
    )


def _write_diagnostic(stream: BinaryIO, message: str) -> None:
    bounded, _ = _truncate_utf8(message, MAX_PROTOCOL_ERROR_MESSAGE_BYTES)
    encoded = f"{bounded}\n".encode("utf-8", errors="replace")
    try:
        stream.write(encoded)
        stream.flush()
    except (BrokenPipeError, OSError):
        pass


def _write_response(stream: BinaryIO, response: Response) -> None:
    write_frame(stream, encode_response(response))


def _send_protocol_error(
    response_stream: BinaryIO,
    correlation_id: str,
    code: ProtocolErrorCode,
    message: str,
) -> None:
    bounded_message, _ = _truncate_utf8(message, MAX_PROTOCOL_ERROR_MESSAGE_BYTES)
    _write_response(
        response_stream,
        ProtocolErrorResponse(correlation_id, code, bounded_message or code),
    )


def _classify_environment(launch_working_directory: str) -> EnvironmentKind:
    if _INITIAL_PREFIX == _INITIAL_BASE_PREFIX:
        return "system"
    project_environment = _JOIN(launch_working_directory, ".venv")
    try:
        if _EXISTS(project_environment) and _SAMEFILE(_INITIAL_PREFIX, project_environment):
            return "project_venv"
    except OSError:
        pass
    return "active_venv"


def _current_working_directory() -> str:
    try:
        return _REALPATH(_GETCWD())
    except OSError as error:
        raise _RuntimeDiagnosticsFailure(
            f"cannot resolve current working directory: {error}"
        ) from error


def _initial_runtime_diagnostics(launch_working_directory: str) -> RuntimeDiagnostics:
    return RuntimeDiagnostics(
        executable=_INITIAL_EXECUTABLE,
        python_version=_INITIAL_PYTHON_VERSION,
        working_directory=_current_working_directory(),
        environment_kind=_classify_environment(launch_working_directory),
    )


def _current_runtime_diagnostics(identity: RuntimeDiagnostics) -> RuntimeDiagnostics:
    return RuntimeDiagnostics(
        executable=identity.executable,
        python_version=identity.python_version,
        working_directory=_current_working_directory(),
        environment_kind=identity.environment_kind,
    )


def _validate_initialization(request: InitializeRequest, diagnostics: RuntimeDiagnostics) -> None:
    if diagnostics.working_directory != request.launch_working_directory:
        raise ProtocolViolation(
            "Runner working directory does not match initialize request",
            correlation_id=request.correlation_id,
        )
    if diagnostics.environment_kind != request.environment_kind:
        raise ProtocolViolation(
            "Runner environment kind does not match initialize request",
            correlation_id=request.correlation_id,
        )


def _namespace() -> dict[str, object]:
    return {
        "__name__": "__main__",
        "__package__": None,
        "__builtins__": builtins,
    }


def _compile_and_execute(code: str, execution_count: int, namespace: dict[str, object]) -> object:
    filename = f"<amkernel-cell-{execution_count}>"
    module = ast.parse(code, filename=filename, mode="exec")
    final_expression: ast.expr | None = None
    statements = module.body
    if statements and isinstance(statements[-1], ast.Expr):
        final_expression = statements[-1].value
        statements = statements[:-1]

    future_flags = 0
    prefix_code: CodeType | None = None
    if statements:
        prefix = ast.Module(body=statements, type_ignores=module.type_ignores)
        ast.fix_missing_locations(prefix)
        prefix_code = compile(prefix, filename, "exec", dont_inherit=True)
        future_flags = prefix_code.co_flags & _FUTURE_FLAGS

    expression_code: CodeType | None = None
    if final_expression is not None:
        expression = ast.Expression(body=final_expression)
        ast.fix_missing_locations(expression)
        expression_code = compile(
            expression,
            filename,
            "eval",
            flags=future_flags,
            dont_inherit=True,
        )

    if prefix_code is not None:
        exec(prefix_code, namespace, namespace)
    if expression_code is None:
        return _NO_RESULT
    return eval(expression_code, namespace, namespace)


class _NoResult:
    pass


_NO_RESULT = _NoResult()


def _execute_cell(code: str, execution_count: int, namespace: dict[str, object]) -> _CellResult:
    try:
        value = _compile_and_execute(code, execution_count, namespace)
        if value is _NO_RESULT:
            return _CellResult("completed", False, None, None)
        return _CellResult("completed", True, _normalize_result(value), None)
    except KeyboardInterrupt as error:
        return _CellResult("interrupted", False, None, _error_info(error))
    except BaseException as error:
        return _CellResult("failed", False, None, _error_info(error))


def _normalize_result(value: object) -> JsonValue:
    candidate = cast(JsonValue, value)
    try:
        encoded_size = json_size(candidate, MAX_RESULT_BYTES)
    except ProtocolViolation:
        return _bounded_repr(value)
    if encoded_size > MAX_RESULT_BYTES:
        return _bounded_repr(value, replaced=True, oversized_json=True)
    try:
        return snapshot_json(candidate, MAX_RESULT_BYTES)
    except ProtocolViolation:
        return _bounded_repr(value, replaced=True)


def _bounded_repr(
    value: object,
    *,
    replaced: bool = False,
    oversized_json: bool = False,
) -> JsonValue:
    type_name, type_replaced = _type_name(value)
    representation_failed = False
    representation_replaced = replaced
    if oversized_json:
        representation = _oversized_json_summary(value, type_name)
        representation_replaced = True
    elif type(value) in {bytes, bytearray, list, tuple, dict, set, frozenset}:
        representation = _container_summary(value, type_name)
        representation_replaced = True
    elif isinstance(value, (str, bytes, bytearray, list, tuple, dict, set, frozenset)):
        representation = f"<{type_name}; builtin subclass representation omitted>"
        representation_replaced = True
    else:
        try:
            representation = repr(value)
        except BaseException as error:
            representation_failed = True
            error_type, _ = _type_name(error)
            representation = f"<repr failed: {error_type}>"

    representation, value_truncated = _truncate_utf8(representation, _REPR_BYTES)
    truncated = type_replaced or value_truncated or representation_failed or representation_replaced

    result: dict[str, JsonValue] = {
        "kind": "repr",
        "typeName": type_name,
        "value": representation,
        "truncated": truncated,
    }
    while json_size(result, _REPR_OBJECT_BYTES) > _REPR_OBJECT_BYTES:
        truncated = True
        if representation:
            representation = representation[: max(0, len(representation) // 2)]
        elif type_name:
            type_name = type_name[: max(0, len(type_name) // 2)]
        else:  # pragma: no cover - fixed field overhead is below the limit
            raise ProtocolViolation("cannot bound representation object")
        result = {
            "kind": "repr",
            "typeName": type_name,
            "value": representation,
            "truncated": truncated,
        }
    return result


def _oversized_json_summary(value: object, type_name: str) -> str:
    if type(value) is str:
        prefix, _ = _truncate_utf8(value, _REPR_BYTES // 2)
        return f"{prefix!r} <{len(value)} characters; JSON result exceeds limit>"
    return _container_summary(value, type_name, suffix="JSON result exceeds limit")


def _container_summary(
    value: object,
    type_name: str,
    *,
    suffix: str = "bounded non-JSON representation",
) -> str:
    if type(value) not in {bytes, bytearray, list, tuple, dict, set, frozenset}:
        return f"<{type_name}; {suffix}>"
    length = len(cast(Sized, value))
    return f"<{type_name} len={length}; {suffix}>"


def _type_name(value: object) -> tuple[str, bool]:
    value_type = type(value)
    try:
        module = type.__getattribute__(value_type, "__module__")
        qualified_name = type.__getattribute__(value_type, "__qualname__")
    except BaseException:
        return "<unknown>", True
    if type(module) is not str or type(qualified_name) is not str or not qualified_name:
        return "<unknown>", True
    name = f"{module}.{qualified_name}" if module and module != "builtins" else qualified_name
    return _truncate_utf8(name, MAX_ERROR_TYPE_BYTES)


def _error_info(error: BaseException) -> ErrorInfo:
    error_type, _ = _type_name(error)
    message = _bounded_exception_message(error, error_type)
    traceback_lines = _bounded_traceback_lines(error, error_type, message)
    result = ErrorInfo(error_type, message, traceback_lines)
    wire: JsonValue = {
        "type": result.type,
        "message": result.message,
        "traceback": list(result.traceback),
    }
    if json_size(wire, MAX_ERROR_BYTES) > MAX_ERROR_BYTES:
        bounded_message, _ = _truncate_utf8(result.message, 1_024)
        result = ErrorInfo(
            result.type,
            bounded_message,
            ("[traceback truncated]",),
        )
    return result


class _SafeExceptionValue(Exception):
    """Proxy whose string form and SyntaxError fields are already bounded."""

    msg: str
    filename: str | None
    lineno: int | None
    end_lineno: int | None
    offset: int | None
    end_offset: int | None
    text: str | None
    print_file_and_line: bool | None


class _ExceptionChainTruncated(Exception):
    pass


@dataclass(slots=True)
class _TraceBudget:
    exceptions: int = _MAX_EXCEPTION_CHAIN
    frames: int = _MAX_TRACEBACK_FRAMES
    truncated: bool = False


def _bounded_exception_message(error: BaseException, error_type: str) -> str:
    error_class = type(error)
    try:
        custom_string = type.__getattribute__(error_class, "__str__") is not BaseException.__str__
        class_module = type.__getattribute__(error_class, "__module__")
    except BaseException:
        return f"<message unavailable for {error_type}>"
    if type(class_module) is not str:
        return f"<message unavailable for {error_type}>"
    if custom_string and class_module != "builtins":
        return f"<custom __str__ omitted for {error_type}>"

    if isinstance(error, SyntaxError):
        try:
            syntax_message = BaseException.__getattribute__(error, "msg")
        except BaseException:
            syntax_message = None
        if type(syntax_message) is str:
            bounded, _ = _truncate_utf8(syntax_message, _ERROR_MESSAGE_BYTES)
            return bounded

    try:
        arguments = BaseException.__getattribute__(error, "args")
    except BaseException:
        return f"<message unavailable for {error_type}>"
    if type(arguments) is not tuple or not arguments:
        return ""
    if len(arguments) == 1:
        return _bounded_error_argument(
            arguments[0],
            quote_string=type(error) is KeyError,
        )

    parts: list[str] = []
    remaining = _ERROR_MESSAGE_BYTES - 2
    for argument in arguments:
        part = _bounded_error_argument(argument, quote_string=True)
        separator = 2 if parts else 0
        bounded, truncated = _truncate_utf8(part, max(0, remaining - separator))
        if parts:
            parts.append(", ")
            remaining -= 2
        parts.append(bounded)
        remaining -= len(bounded.encode())
        if truncated or remaining <= 0:
            break
    message, _ = _truncate_utf8("(" + "".join(parts) + ")", _ERROR_MESSAGE_BYTES)
    return message


def _bounded_error_argument(value: object, *, quote_string: bool) -> str:
    if type(value) is str:
        bounded, _ = _truncate_utf8(value, _ERROR_MESSAGE_BYTES - 2)
        return repr(bounded) if quote_string else bounded
    if type(value) is int:
        integer = value
        estimated_digits = (abs(integer).bit_length() * 30_103) // 100_000 + 1
        estimated_digits += integer < 0
        if estimated_digits > _ERROR_MESSAGE_BYTES:
            return f"<int approximately {estimated_digits} digits>"
        try:
            return str(integer)
        except ValueError:
            return "<int exceeds conversion limit>"
    if type(value) in {float, bool, type(None)}:
        return repr(value)
    if type(value) in {bytes, bytearray}:
        return f"<{type(value).__name__} len={len(cast(Sized, value))}>"
    value_type, _ = _type_name(value)
    return f"<{value_type}>"


def _safe_traceback_exception(
    error: BaseException,
    message: str,
    seen: set[int] | None = None,
    budget: _TraceBudget | None = None,
) -> traceback.TracebackException | None:
    if seen is None:
        seen = set()
    if budget is None:
        budget = _TraceBudget()
    identity = id(error)
    if identity in seen:
        return None
    if budget.exceptions <= 0:
        budget.truncated = True
        return _TRACEBACK_EXCEPTION(
            _ExceptionChainTruncated,
            _SafeExceptionValue("exception chain truncated"),
            None,
            limit=0,
            lookup_lines=False,
            capture_locals=False,
            compact=True,
        )
    seen.add(identity)
    budget.exceptions -= 1

    error_class = type(error)
    safe_type_name, _ = _type_name(error)
    safe_error_class = _safe_exception_type(error_class, safe_type_name)
    proxy = _SafeExceptionValue(message)
    if issubclass(error_class, SyntaxError):
        _copy_syntax_error_fields(error, proxy, message)
    try:
        original_traceback = cast(
            TracebackType | None,
            BaseException.__getattribute__(error, "__traceback__"),
        )
    except BaseException:
        original_traceback = None
    frame_limit = _consume_traceback_budget(original_traceback, budget)
    rendered = _TRACEBACK_EXCEPTION(
        safe_error_class,
        proxy,
        original_traceback,
        limit=frame_limit,
        lookup_lines=False,
        capture_locals=False,
        compact=True,
    )

    try:
        cause = BaseException.__getattribute__(error, "__cause__")
        context = BaseException.__getattribute__(error, "__context__")
        suppress_context = bool(BaseException.__getattribute__(error, "__suppress_context__"))
    except BaseException:
        cause = None
        context = None
        suppress_context = False
    if isinstance(cause, BaseException):
        cause_type, _ = _type_name(cause)
        rendered.__cause__ = _safe_traceback_exception(
            cause,
            _bounded_exception_message(cause, cause_type),
            seen,
            budget,
        )
    if isinstance(context, BaseException) and not suppress_context:
        context_type, _ = _type_name(context)
        rendered.__context__ = _safe_traceback_exception(
            context,
            _bounded_exception_message(context, context_type),
            seen,
            budget,
        )
    rendered.__suppress_context__ = suppress_context
    return rendered


def _safe_exception_type(
    error_class: type[BaseException],
    safe_type_name: str,
) -> type[BaseException]:
    base: type[BaseException] = SyntaxError if issubclass(error_class, SyntaxError) else Exception
    try:
        return type(safe_type_name, (base,), {"__module__": "builtins"})
    except BaseException:
        return RuntimeError


def _consume_traceback_budget(
    current: TracebackType | None,
    budget: _TraceBudget,
) -> int:
    count = 0
    traceback_cursor = current
    while traceback_cursor is not None and count < budget.frames:
        try:
            traceback_cursor = traceback_cursor.tb_next
        except BaseException:
            traceback_cursor = None
        count += 1
    if traceback_cursor is not None:
        budget.truncated = True
    budget.frames -= count
    return count


def _copy_syntax_error_fields(
    error: BaseException,
    proxy: _SafeExceptionValue,
    message: str,
) -> None:
    proxy.msg = message
    for field in ("filename", "text"):
        try:
            value = BaseException.__getattribute__(error, field)
        except BaseException:
            value = None
        if type(value) is str:
            value, _ = _truncate_utf8(value, 4_096)
        else:
            value = None
        setattr(proxy, field, value)
    for field in ("lineno", "end_lineno", "offset", "end_offset"):
        try:
            value = BaseException.__getattribute__(error, field)
        except BaseException:
            value = None
        if type(value) is not int:
            value = None
        setattr(proxy, field, value)
    try:
        print_file_and_line = BaseException.__getattribute__(error, "print_file_and_line")
    except BaseException:
        print_file_and_line = None
    if type(print_file_and_line) is not bool:
        print_file_and_line = None
    proxy.print_file_and_line = print_file_and_line


def _bounded_traceback_lines(
    error: BaseException,
    error_type: str,
    message: str,
) -> tuple[str, ...]:
    budget = _TraceBudget()
    try:
        traceback_exception = _safe_traceback_exception(error, message, budget=budget)
        if traceback_exception is None:
            return (f"{error_type}: {message}",)
        rendered = traceback_exception.format(chain=True)
    except BaseException:
        return (f"{error_type}: {message}",)

    lines: list[str] = []
    remaining = _TRACEBACK_TEXT_BYTES
    was_truncated = False
    try:
        for chunk in rendered:
            bounded, chunk_truncated = _truncate_utf8(chunk, remaining)
            lines.extend(bounded.splitlines())
            remaining -= len(bounded.encode())
            if chunk_truncated or remaining <= 0:
                was_truncated = True
                break
    except BaseException:
        return (f"{error_type}: {message}",)

    if was_truncated:
        lines.append("[traceback truncated]")
    if not lines:
        lines.append(error_type)
    if budget.truncated and "[traceback truncated]" not in lines:
        lines.append("[traceback truncated]")
    return tuple(lines)


def _truncate_utf8(value: str, maximum_bytes: int) -> tuple[str, bool]:
    if maximum_bytes < 0:
        raise ValueError("maximum_bytes must be non-negative")
    characters: list[str] = []
    sizes: list[int] = []
    used = 0
    normalized = False
    for character in value:
        try:
            encoded = character.encode("utf-8")
            normalized_character = character
        except UnicodeEncodeError:
            encoded = "�".encode()
            normalized_character = "�"
            normalized = True
        if used + len(encoded) > maximum_bytes:
            ellipsis = "…" if maximum_bytes >= len("…".encode()) else ""
            content_limit = maximum_bytes - len(ellipsis.encode())
            while sizes and used > content_limit:
                used -= sizes.pop()
                characters.pop()
            return "".join(characters) + ellipsis, True
        characters.append(normalized_character)
        sizes.append(len(encoded))
        used += len(encoded)
    if normalized:
        return "".join(characters), True
    return value, False


def _flush_user_streams(diagnostic: BinaryIO) -> None:
    seen: set[int] = set()
    for stream in (sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__):
        if stream is None or id(stream) in seen:
            continue
        seen.add(id(stream))
        try:
            stream.flush()
        except BaseException as error:
            _write_diagnostic(diagnostic, f"user stream flush failed: {type(error).__name__}")


def _block_sigint_for_finalization(
    signal_state: _SignalState,
    cell_result: _CellResult,
) -> _CellResult:
    try:
        _PTHREAD_SIGMASK(_SIG_BLOCK, {_SIGINT})
    except KeyboardInterrupt as error:
        signal_state.executing = False
        cell_result = _CellResult("interrupted", False, None, _error_info(error))
        _PTHREAD_SIGMASK(_SIG_BLOCK, {_SIGINT})
    return cell_result

def _unblock_sigint_for_execution(baseline_mask: set[int]) -> None:
    # Darwin can leave an interrupt sent after Started pending across unmask.
    # Consume a signal already known to be pending, then map it synchronously.
    if _SIGINT in _PENDING_SIGNALS():
        _WAIT_FOR_SIGNAL({_SIGINT})
        _PTHREAD_SIGMASK(_SIG_SETMASK, baseline_mask)
        raise KeyboardInterrupt
    _PTHREAD_SIGMASK(_SIG_SETMASK, baseline_mask)


def _execute_request(
    request: ExecuteRequest,
    *,
    response: BinaryIO,
    diagnostic: BinaryIO,
    signal_state: _SignalState,
    baseline_mask: set[int],
    namespace: dict[str, object],
    execution_count: int,
    runtime_identity: RuntimeDiagnostics,
) -> tuple[int, bool]:
    next_count = execution_count + 1
    _PTHREAD_SIGMASK(_SIG_BLOCK, {_SIGINT})
    _INSTALL_SIGNAL_HANDLER(_SIGINT, signal_state.handle_sigint)
    signal_state.executing = True
    _write_response(response, StartedResponse(request.correlation_id, next_count))
    execution_count = next_count

    try:
        _unblock_sigint_for_execution(baseline_mask)
        cell_result = _execute_cell(request.code, execution_count, namespace)
        cell_result = _block_sigint_for_finalization(signal_state, cell_result)
    except KeyboardInterrupt as error:
        cell_result = _CellResult("interrupted", False, None, _error_info(error))
        cell_result = _block_sigint_for_finalization(signal_state, cell_result)
    finally:
        signal_state.executing = False
        _INSTALL_SIGNAL_HANDLER(_SIGINT, signal_state.handle_sigint)

    try:
        runtime = _current_runtime_diagnostics(runtime_identity)
    except _RuntimeDiagnosticsFailure as error:
        _flush_user_streams(diagnostic)
        _send_protocol_error(
            response,
            request.correlation_id,
            "runtime_diagnostics_error",
            str(error),
        )
        _PTHREAD_SIGMASK(_SIG_SETMASK, baseline_mask)
        return execution_count, False

    _flush_user_streams(diagnostic)
    _write_response(
        response,
        DoneResponse(
            correlation_id=request.correlation_id,
            outcome=cell_result.outcome,
            execution_count=execution_count,
            runtime=runtime,
            has_result=cell_result.has_result,
            result=cell_result.result,
            error=cell_result.error,
        ),
    )
    _PTHREAD_SIGMASK(_SIG_SETMASK, baseline_mask)
    return execution_count, True


def run_runner(bootstrap: _Bootstrap) -> int:
    """Run one initialized persistent namespace until shutdown or fatal protocol error."""
    signal_state = _SignalState()
    current_mask = _PTHREAD_SIGMASK(_SIG_BLOCK, set())
    baseline_mask = set(current_mask) - {_SIGINT}
    _INSTALL_SIGNAL_HANDLER(_SIGINT, signal_state.handle_sigint)
    _PTHREAD_SIGMASK(_SIG_SETMASK, baseline_mask)

    try:
        first_request = read_request(bootstrap.request)
    except ProtocolViolation as error:
        _write_diagnostic(bootstrap.diagnostic, f"initialize frame rejected: {error}")
        if error.correlation_id is not None:
            _send_protocol_error(
                bootstrap.response,
                error.correlation_id,
                error.code,
                str(error),
            )
        return 2

    if first_request is None:
        _write_diagnostic(bootstrap.diagnostic, "request EOF before initialize")
        return 2
    if not isinstance(first_request, InitializeRequest):
        _send_protocol_error(
            bootstrap.response,
            first_request.correlation_id,
            "invalid_sequence",
            "first request must be initialize",
        )
        return 2

    launch_working_directory = first_request.launch_working_directory
    try:
        runtime_identity = _initial_runtime_diagnostics(launch_working_directory)
    except _RuntimeDiagnosticsFailure as error:
        _send_protocol_error(
            bootstrap.response,
            first_request.correlation_id,
            "runtime_diagnostics_error",
            str(error),
        )
        return 2
    try:
        _validate_initialization(first_request, runtime_identity)
    except ProtocolViolation as error:
        _send_protocol_error(
            bootstrap.response,
            first_request.correlation_id,
            "invalid_request",
            str(error),
        )
        return 2

    _write_response(
        bootstrap.response,
        ReadyResponse(first_request.correlation_id, runtime_identity),
    )

    namespace = _namespace()
    execution_count = 0
    while True:
        try:
            request = read_request(bootstrap.request)
        except ProtocolViolation as error:
            _write_diagnostic(bootstrap.diagnostic, f"request frame rejected: {error}")
            if error.correlation_id is not None:
                _send_protocol_error(
                    bootstrap.response,
                    error.correlation_id,
                    error.code,
                    str(error),
                )
            return 2

        if request is None:
            _write_diagnostic(bootstrap.diagnostic, "unexpected request EOF")
            return 2
        if isinstance(request, ShutdownRequest):
            return 0
        if not isinstance(request, ExecuteRequest):
            _send_protocol_error(
                bootstrap.response,
                request.correlation_id,
                "invalid_sequence",
                "Runner accepts only execute or shutdown after initialize",
            )
            return 2

        try:
            execution_count, alive = _execute_request(
                request,
                response=bootstrap.response,
                diagnostic=bootstrap.diagnostic,
                signal_state=signal_state,
                baseline_mask=baseline_mask,
                namespace=namespace,
                execution_count=execution_count,
                runtime_identity=runtime_identity,
            )
        except BaseException as error:
            error_info = _error_info(error)
            message = f"{error_info.type}: {error_info.message}"
            try:
                _send_protocol_error(
                    bootstrap.response,
                    request.correlation_id,
                    "internal_protocol_error",
                    message,
                )
            except BaseException as response_error:
                _write_diagnostic(
                    bootstrap.diagnostic,
                    f"internal protocol response failed: {type(response_error).__name__}",
                )
            return 2
        if not alive:
            return 2


def main(argv: list[str] | None = None) -> int:
    """Parse bootstrap descriptors and run the private Runner process."""
    try:
        bootstrap = _bootstrap(argv)
    except (OSError, ValueError) as error:
        print(f"Runner bootstrap failed: {error}", file=sys.__stderr__, flush=True)
        return 2
    try:
        return run_runner(bootstrap)
    except BaseException as error:
        error_info = _error_info(error)
        rendered = "\n".join(error_info.traceback)
        _write_diagnostic(bootstrap.diagnostic, rendered)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
