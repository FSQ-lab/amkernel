"""Versioned private protocol shared by the AMKernel host and Runner."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import posixpath
import re
import struct
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, BinaryIO, Final, Literal, TypeAlias, cast

PROTOCOL_VERSION: Final = 2

# Shared byte, count, frame, result, resource, and image bounds from ADR-0006.
MAX_CONTROL_FRAME_BYTES: Final = 8_388_608
MAX_CODE_BYTES: Final = 1_048_576
MAX_RESULT_BYTES: Final = 1_048_576
MAX_ERROR_BYTES: Final = 65_536
MAX_PROTOCOL_ERROR_MESSAGE_BYTES: Final = 4_096
MAX_PATH_BYTES: Final = 16_384
MAX_PYTHON_VERSION_BYTES: Final = 128
MAX_ERROR_TYPE_BYTES: Final = 256
MAX_ERROR_MESSAGE_BYTES: Final = 16_384
MAX_IMPLEMENTATION_BYTES: Final = 256
MAX_PLATFORM_BYTES: Final = 256
MAX_PACKAGE_COUNT: Final = 64
MAX_PACKAGE_NAME_BYTES: Final = 128
MAX_PACKAGE_VERSION_BYTES: Final = 1_024
MAX_LOGICAL_NAME_CODEPOINTS: Final = 255
MAX_MIME_BYTES: Final = 255
MAX_OUTPUT_SEQUENCE: Final = 128
MAX_OUTPUT_FRAMES: Final = 4_288
MAX_ARTIFACT_TRANSACTIONS: Final = 64
MAX_JSON_DISPLAYS: Final = 64
MAX_IMAGE_TRANSACTIONS: Final = 16
MAX_ARTIFACT_CHUNKS: Final = 4_096
MAX_ARTIFACT_BYTES: Final = 268_435_456
MAX_JSON_DISPLAY_ITEM_BYTES: Final = 1_048_576
MAX_JSON_DISPLAY_BYTES: Final = 4_194_304
MAX_ARTIFACT_CHUNK_BYTES: Final = 65_536
MAX_ARTIFACT_CHUNK_ENCODED_BYTES: Final = 87_384
STREAM_TAIL_BYTES: Final = 262_144
MAX_STREAM_BYTES: Final = 268_435_456
MAX_STORED_EXPLICIT_ITEMS: Final = 64
MAX_STORED_STREAM_ITEMS: Final = 2
MAX_STORED_ITEMS: Final = 66
MAX_STRUCTURED_RESULT_BYTES: Final = 4_194_304
EXECUTION_BUNDLE_RESERVATION_BYTES: Final = 570_425_344
ARTIFACT_STORE_QUOTA_BYTES: Final = 2_147_483_648
ARTIFACT_RESOURCE_PART_BYTES: Final = 8_388_608
MAX_ARTIFACT_PARTS: Final = 32
MAX_EXECUTION_PARTS: Final = 128
MAX_RESOURCE_READS: Final = 1
MAX_INLINE_IMAGE_ITEM_BYTES: Final = 4_194_304
MAX_INLINE_IMAGE_BYTES: Final = 8_388_608
MAX_IMAGE_DIMENSION: Final = 32_768
MAX_IMAGE_FRAMES: Final = 256
MAX_IMAGE_PIXEL_FRAMES: Final = 40_000_000
MAX_LIVE_MESSAGE_BYTES: Final = 8_192
MAX_LIVE_UPDATES_PER_SECOND: Final = 10

REQUEST_FD_ARGUMENT: Final = "--request-fd"
RESPONSE_FD_ARGUMENT: Final = "--response-fd"
DIAGNOSTIC_FD_ARGUMENT: Final = "--diagnostic-fd"

SAFE_MIME_TYPES: Final = frozenset(
    {
        "text/plain; charset=utf-8",
        "application/json",
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
    }
)
IMAGE_MIME_TYPES: Final = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})
_CORRELATION_ID = re.compile(r"^[0-9a-f]{32}$")

_UUID_HEX = re.compile(r"^[0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{15}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PACKAGE_NAME = re.compile(r"^[A-Za-z0-9]+(?:[._-]+[A-Za-z0-9]+)*$")
_MIME_TOKEN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_LENGTH = struct.Struct(">I")
_JSON_DUMPS = json.dumps
_JSON_LOADS = json.loads
_ISFINITE = math.isfinite
_NORMPATH = posixpath.normpath

EnvironmentKind: TypeAlias = Literal["project_venv", "active_venv", "system"]
DoneOutcome: TypeAlias = Literal["completed", "failed", "interrupted"]
ArtifactKind: TypeAlias = Literal["artifact", "image"]
PackageError: TypeAlias = Literal["not installed", "metadata unavailable", "invalid metadata"]
ProtocolErrorCode: TypeAlias = Literal[
    "version_mismatch",
    "invalid_sequence",
    "invalid_request",
    "runtime_diagnostics_error",
    "internal_protocol_error",
]
JsonValue: TypeAlias = bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"] | None


class ProtocolViolation(ValueError):
    """A malformed, oversized, or schema-invalid private protocol message."""

    def __init__(
        self,
        message: str,
        *,
        code: ProtocolErrorCode = "invalid_request",
        correlation_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.correlation_id = correlation_id


@dataclass(frozen=True, slots=True)
class RuntimePackage:
    """One requested distribution diagnostic."""

    name: str
    version: str | None = None
    error: PackageError | None = None


@dataclass(frozen=True, slots=True)
class RuntimeDiagnostics:
    """Interpreter facts reported by the Runner."""

    executable: str
    python_version: str
    working_directory: str
    environment_kind: EnvironmentKind
    implementation: str = "CPython"
    platform: str = "unknown"
    packages: tuple[RuntimePackage, ...] = ()


@dataclass(frozen=True, slots=True)
class ErrorInfo:
    """Bounded user-code error information."""

    type: str
    message: str
    traceback: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InitializeRequest:
    """Initialize one fresh Runner."""

    correlation_id: str
    launch_working_directory: str
    environment_kind: EnvironmentKind


@dataclass(frozen=True, slots=True)
class ExecuteRequest:
    """Execute one Python cell."""

    correlation_id: str
    code: str
    packages: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ShutdownRequest:
    """Shut down an idle Runner."""

    correlation_id: str


Request: TypeAlias = InitializeRequest | ExecuteRequest | ShutdownRequest


@dataclass(frozen=True, slots=True)
class ReadyResponse:
    """A fresh Runner is initialized and idle."""

    correlation_id: str
    runtime: RuntimeDiagnostics
    execution_count: int = 0


@dataclass(frozen=True, slots=True)
class StartedResponse:
    """The Runner accepted one cell and committed its execution count."""

    correlation_id: str
    execution_count: int


@dataclass(frozen=True, slots=True)
class DoneResponse:
    """The Runner returned to an idle request loop after a cell."""

    correlation_id: str
    outcome: DoneOutcome
    execution_count: int
    runtime: RuntimeDiagnostics
    has_result: bool
    result: JsonValue = None
    error: ErrorInfo | None = None


@dataclass(frozen=True, slots=True)
class DisplayJsonResponse:
    """One ordered strict-JSON display event."""

    correlation_id: str
    execution_count: int
    sequence: int
    value: JsonValue


@dataclass(frozen=True, slots=True)
class ArtifactBeginResponse:
    """Begin one noninterleaved artifact transaction."""

    correlation_id: str
    execution_count: int
    sequence: int
    transaction_id: str
    kind: ArtifactKind
    name: str
    declared_mime_type: str
    size: int


@dataclass(frozen=True, slots=True)
class ArtifactChunkResponse:
    """Carry one canonical-base64 artifact chunk as decoded bytes."""

    correlation_id: str
    execution_count: int
    sequence: int
    transaction_id: str
    chunk_index: int
    data: bytes


@dataclass(frozen=True, slots=True)
class ArtifactEndResponse:
    """Commit one complete artifact transaction."""

    correlation_id: str
    execution_count: int
    sequence: int
    transaction_id: str
    chunk_count: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ProtocolErrorResponse:
    """A fatal correlated protocol error emitted before Runner exit."""

    correlation_id: str
    code: ProtocolErrorCode
    message: str


Response: TypeAlias = (
    ReadyResponse
    | StartedResponse
    | DisplayJsonResponse
    | ArtifactBeginResponse
    | ArtifactChunkResponse
    | ArtifactEndResponse
    | DoneResponse
    | ProtocolErrorResponse
)


@dataclass(slots=True)
class _ArtifactTransaction:
    transaction_id: str
    sequence: int
    size: int
    chunk_count: int = 0
    received_bytes: int = 0
    digest: object = field(default_factory=hashlib.sha256)


@dataclass(slots=True)
class ExecutionResponseState:
    """Validate one started execution's correlation, sequence, and transactions."""

    correlation_id: str
    execution_count: int
    next_sequence: int = 1
    output_frames: int = 0
    artifact_transactions: int = 0
    image_transactions: int = 0
    json_displays: int = 0
    artifact_chunks: int = 0
    artifact_bytes: int = 0
    json_bytes: int = 0
    transaction_ids: set[str] = field(default_factory=set)
    active_transaction: _ArtifactTransaction | None = None
    terminal: bool = False

    def accept(self, response: Response) -> None:
        """Accept one decoded response or raise on any v2 transition violation."""
        if self.terminal:
            raise ProtocolViolation("response after terminal frame")
        if response.correlation_id != self.correlation_id:
            raise ProtocolViolation("uncorrelated execution response")
        if isinstance(response, ProtocolErrorResponse):
            self.terminal = True
            return
        if isinstance(response, DoneResponse):
            self._require_execution_count(response.execution_count)
            if self.active_transaction is not None:
                raise ProtocolViolation("done during incomplete artifact transaction")
            self.terminal = True
            return
        if not isinstance(
            response,
            (
                DisplayJsonResponse,
                ArtifactBeginResponse,
                ArtifactChunkResponse,
                ArtifactEndResponse,
            ),
        ):
            raise ProtocolViolation("invalid response after started")

        self.output_frames += 1
        if self.output_frames > MAX_OUTPUT_FRAMES:
            raise ProtocolViolation("output frame count exceeds maximum")
        self._require_execution_count(response.execution_count)

        if isinstance(response, DisplayJsonResponse):
            self._accept_display(response)
        elif isinstance(response, ArtifactBeginResponse):
            self._accept_begin(response)
        elif isinstance(response, ArtifactChunkResponse):
            self._accept_chunk(response)
        else:
            self._accept_end(response)

    def _accept_display(self, response: DisplayJsonResponse) -> None:
        if self.active_transaction is not None:
            raise ProtocolViolation("display interleaves artifact transaction")
        self._require_sequence(response.sequence)
        self.json_displays += 1
        if self.json_displays > MAX_JSON_DISPLAYS:
            raise ProtocolViolation("JSON display count exceeds maximum")
        self.json_bytes += json_size(response.value, MAX_JSON_DISPLAY_BYTES)
        if self.json_bytes > MAX_JSON_DISPLAY_BYTES:
            raise ProtocolViolation("JSON display bytes exceed maximum")
        self.next_sequence += 1

    def _accept_begin(self, response: ArtifactBeginResponse) -> None:
        if self.active_transaction is not None:
            raise ProtocolViolation("artifact transactions cannot interleave")
        self._require_sequence(response.sequence)
        if response.transaction_id in self.transaction_ids:
            raise ProtocolViolation("duplicate artifact transactionId")
        self.transaction_ids.add(response.transaction_id)
        self.artifact_transactions += 1
        if self.artifact_transactions > MAX_ARTIFACT_TRANSACTIONS:
            raise ProtocolViolation("artifact transaction count exceeds maximum")
        if response.kind == "image":
            self.image_transactions += 1
            if self.image_transactions > MAX_IMAGE_TRANSACTIONS:
                raise ProtocolViolation("image transaction count exceeds maximum")
        self.artifact_bytes += response.size
        if self.artifact_bytes > MAX_ARTIFACT_BYTES:
            raise ProtocolViolation("artifact bytes exceed maximum")
        self.active_transaction = _ArtifactTransaction(
            response.transaction_id, response.sequence, response.size
        )

    def _accept_chunk(self, response: ArtifactChunkResponse) -> None:
        transaction = self.active_transaction
        if transaction is None or response.transaction_id != transaction.transaction_id:
            raise ProtocolViolation("artifact chunk has no matching transaction")
        if response.sequence != transaction.sequence:
            raise ProtocolViolation("artifact chunk sequence mismatch")
        if response.chunk_index != transaction.chunk_count:
            raise ProtocolViolation("artifact chunkIndex is not contiguous")
        self.artifact_chunks += 1
        if self.artifact_chunks > MAX_ARTIFACT_CHUNKS:
            raise ProtocolViolation("artifact chunk count exceeds maximum")
        transaction.chunk_count += 1
        transaction.received_bytes += len(response.data)
        if transaction.received_bytes > transaction.size:
            raise ProtocolViolation("artifact chunks exceed declared size")
        digest = cast(Any, transaction.digest)
        digest.update(response.data)

    def _accept_end(self, response: ArtifactEndResponse) -> None:
        transaction = self.active_transaction
        if transaction is None or response.transaction_id != transaction.transaction_id:
            raise ProtocolViolation("artifact end has no matching transaction")
        if response.sequence != transaction.sequence:
            raise ProtocolViolation("artifact end sequence mismatch")
        if response.chunk_count != transaction.chunk_count:
            raise ProtocolViolation("artifact chunkCount mismatch")
        if transaction.received_bytes != transaction.size:
            raise ProtocolViolation("artifact size mismatch")
        digest = cast(Any, transaction.digest)
        if response.sha256 != digest.hexdigest():
            raise ProtocolViolation("artifact sha256 mismatch")
        self.active_transaction = None
        self.next_sequence += 1

    def _require_execution_count(self, execution_count: int) -> None:
        if execution_count != self.execution_count:
            raise ProtocolViolation("output executionCount mismatch")

    def _require_sequence(self, sequence: int) -> None:
        if sequence != self.next_sequence or sequence > MAX_OUTPUT_SEQUENCE:
            raise ProtocolViolation("output sequence gap or duplicate")


def encode_request(request: Request) -> bytes:
    """Encode one validated host request including its length prefix."""
    message_type, payload = _request_parts(request)
    return _encode_envelope(message_type, request.correlation_id, payload, parse_request_payload)


def encode_response(response: Response) -> bytes:
    """Encode one validated Runner response including its length prefix."""
    message_type, payload = _response_parts(response)
    return _encode_envelope(message_type, response.correlation_id, payload, parse_response_payload)


def parse_request_payload(payload: bytes) -> Request:
    """Parse a request and retain correlation for schema-valid envelopes."""
    try:
        return _parse_request_payload_inner(payload)
    except ProtocolViolation as error:
        if error.correlation_id is None:
            error.correlation_id = _peek_correlation_id(payload)
        raise


def _parse_request_payload_inner(payload: bytes) -> Request:
    """Parse and validate one request JSON payload without a length prefix."""
    message_type, correlation_id, body = _parse_envelope(payload)

    if message_type == "initialize":
        _require_exact_keys(body, {"launchWorkingDirectory", "environmentKind"})
        return InitializeRequest(
            correlation_id=correlation_id,
            launch_working_directory=_require_path(body, "launchWorkingDirectory", canonical=True),
            environment_kind=_require_environment_kind(body, "environmentKind"),
        )
    if message_type == "execute":
        _require_exact_keys(body, {"code", "packages"})
        return ExecuteRequest(
            correlation_id=correlation_id,
            code=_require_string(body, "code", maximum_bytes=MAX_CODE_BYTES),
            packages=_parse_package_names(body, "packages"),
        )
    if message_type == "shutdown":
        _require_exact_keys(body, set())
        return ShutdownRequest(correlation_id=correlation_id)

    raise ProtocolViolation(f"unknown request type: {message_type}", correlation_id=correlation_id)


def parse_response_payload(payload: bytes) -> Response:
    """Parse a response and retain correlation for schema-valid envelopes."""
    try:
        return _parse_response_payload_inner(payload)
    except ProtocolViolation as error:
        if error.correlation_id is None:
            error.correlation_id = _peek_correlation_id(payload)
        raise


def _parse_response_payload_inner(payload: bytes) -> Response:
    """Parse and validate one response JSON payload without a length prefix."""
    message_type, correlation_id, body = _parse_envelope(payload)

    if message_type == "ready":
        _require_exact_keys(body, {"executionCount", "runtime"})
        execution_count = _require_integer(body, "executionCount", minimum=0)
        if execution_count != 0:
            raise ProtocolViolation("ready executionCount must be 0", correlation_id=correlation_id)
        return ReadyResponse(
            correlation_id=correlation_id,
            execution_count=execution_count,
            runtime=_parse_runtime(_require_object(body, "runtime"), correlation_id),
        )
    if message_type == "started":
        _require_exact_keys(body, {"executionCount"})
        return StartedResponse(
            correlation_id=correlation_id,
            execution_count=_require_integer(body, "executionCount", minimum=1),
        )
    if message_type == "display_json":
        _require_exact_keys(body, {"executionCount", "sequence", "value"})
        value = cast(JsonValue, body["value"])
        if json_size(value, MAX_JSON_DISPLAY_ITEM_BYTES) > MAX_JSON_DISPLAY_ITEM_BYTES:
            raise ProtocolViolation("display_json value exceeds maximum size")
        return DisplayJsonResponse(
            correlation_id=correlation_id,
            execution_count=_require_integer(body, "executionCount", minimum=1),
            sequence=_require_bounded_integer(body, "sequence", 1, MAX_OUTPUT_SEQUENCE),
            value=snapshot_json(value, MAX_JSON_DISPLAY_ITEM_BYTES),
        )
    if message_type == "artifact_begin":
        _require_exact_keys(
            body,
            {
                "executionCount",
                "sequence",
                "transactionId",
                "kind",
                "name",
                "declaredMimeType",
                "size",
            },
        )
        return ArtifactBeginResponse(
            correlation_id=correlation_id,
            execution_count=_require_integer(body, "executionCount", minimum=1),
            sequence=_require_bounded_integer(body, "sequence", 1, MAX_OUTPUT_SEQUENCE),
            transaction_id=_require_uuid(body, "transactionId"),
            kind=_require_artifact_kind(body, "kind"),
            name=_require_logical_name(body, "name"),
            declared_mime_type=_require_mime(body, "declaredMimeType"),
            size=_require_bounded_integer(body, "size", 0, MAX_ARTIFACT_BYTES),
        )
    if message_type == "artifact_chunk":
        _require_exact_keys(
            body, {"executionCount", "sequence", "transactionId", "chunkIndex", "data"}
        )
        return ArtifactChunkResponse(
            correlation_id=correlation_id,
            execution_count=_require_integer(body, "executionCount", minimum=1),
            sequence=_require_bounded_integer(body, "sequence", 1, MAX_OUTPUT_SEQUENCE),
            transaction_id=_require_uuid(body, "transactionId"),
            chunk_index=_require_bounded_integer(body, "chunkIndex", 0, MAX_ARTIFACT_CHUNKS - 1),
            data=_require_canonical_base64(body, "data"),
        )
    if message_type == "artifact_end":
        _require_exact_keys(
            body, {"executionCount", "sequence", "transactionId", "chunkCount", "sha256"}
        )
        return ArtifactEndResponse(
            correlation_id=correlation_id,
            execution_count=_require_integer(body, "executionCount", minimum=1),
            sequence=_require_bounded_integer(body, "sequence", 1, MAX_OUTPUT_SEQUENCE),
            transaction_id=_require_uuid(body, "transactionId"),
            chunk_count=_require_bounded_integer(body, "chunkCount", 0, MAX_ARTIFACT_CHUNKS),
            sha256=_require_sha256(body, "sha256"),
        )
    if message_type == "done":
        return _parse_done(body, correlation_id)
    if message_type == "protocol_error":
        _require_exact_keys(body, {"code", "message"})
        return ProtocolErrorResponse(
            correlation_id=correlation_id,
            code=_require_protocol_error_code(body, "code"),
            message=_require_string(
                body, "message", maximum_bytes=MAX_PROTOCOL_ERROR_MESSAGE_BYTES, nonempty=True
            ),
        )

    raise ProtocolViolation(f"unknown response type: {message_type}", correlation_id=correlation_id)


def read_request(stream: BinaryIO) -> Request | None:
    """Read one framed request, returning None only for clean prefix-boundary EOF."""
    payload = read_payload(stream)
    return None if payload is None else parse_request_payload(payload)


def read_response(stream: BinaryIO) -> Response | None:
    """Read one framed response, returning None only for clean prefix-boundary EOF."""
    payload = read_payload(stream)
    return None if payload is None else parse_response_payload(payload)


def read_payload(stream: BinaryIO) -> bytes | None:
    """Read one bounded length-prefixed JSON payload."""
    prefix = _read_exact(stream, _LENGTH.size, allow_initial_eof=True)
    if prefix is None:
        return None

    (length,) = _LENGTH.unpack(prefix)
    if length == 0:
        raise ProtocolViolation("zero-length protocol frame")
    if length > MAX_CONTROL_FRAME_BYTES:
        raise ProtocolViolation(f"protocol frame exceeds {MAX_CONTROL_FRAME_BYTES} bytes")

    payload = _read_exact(stream, length, allow_initial_eof=False)
    if payload is None:  # pragma: no cover - forbidden by allow_initial_eof=False
        raise ProtocolViolation("truncated protocol frame")
    return payload


def write_frame(stream: BinaryIO, frame: bytes) -> None:
    """Write and flush one already encoded frame, handling partial writes."""
    view = memoryview(frame)
    while view:
        try:
            written = stream.write(view)
        except InterruptedError:
            continue
        if written is None or written <= 0:
            raise BrokenPipeError("protocol stream accepted no bytes")
        view = view[written:]
    stream.flush()


def json_size(value: JsonValue, maximum_bytes: int | None = None) -> int:
    """Return compact JSON size without materializing the complete encoding."""
    if maximum_bytes is not None and maximum_bytes < 0:
        raise ValueError("maximum_bytes must be non-negative")
    return _json_encoded_size(value, maximum_bytes, set())


def snapshot_json(value: JsonValue, maximum_bytes: int) -> JsonValue:
    """Detach one JSON value after proving its complete encoding is bounded."""
    if json_size(value, maximum_bytes) > maximum_bytes:
        raise ProtocolViolation(f"JSON value exceeds {maximum_bytes} bytes")
    encoded = _dump_json(value)
    if len(encoded) > maximum_bytes:
        raise ProtocolViolation(f"JSON value exceeds {maximum_bytes} bytes")
    try:
        parsed = cast(JsonValue, _JSON_LOADS(encoded))
    except (RecursionError, ValueError) as error:
        raise ProtocolViolation(f"bounded JSON snapshot failed: {error}") from error
    _validate_json_value(parsed)
    return parsed


def _json_encoded_size(
    value: JsonValue,
    maximum_bytes: int | None,
    active: set[int],
) -> int:
    if value is None:
        return _bounded_size(4, maximum_bytes)
    if type(value) is bool:
        return _bounded_size(4 if value else 5, maximum_bytes)
    if type(value) is int:
        if maximum_bytes is not None and value:
            estimated_digits = (abs(value).bit_length() * 30_103) // 100_000 + 1
            estimated_digits += value < 0
            if estimated_digits > maximum_bytes:
                return maximum_bytes + 1
        try:
            return _bounded_size(len(str(value)), maximum_bytes)
        except ValueError as error:
            raise ProtocolViolation(f"integer cannot be encoded as JSON: {error}") from error
    if type(value) is float:
        if not _ISFINITE(value):
            raise ProtocolViolation("non-finite JSON number")
        return _bounded_size(len(_dump_json(value)), maximum_bytes)
    if type(value) is str:
        return _json_string_size(value, maximum_bytes)
    if type(value) is list:
        identity = id(value)
        if identity in active:
            raise ProtocolViolation("cyclic JSON array")
        active.add(identity)
        try:
            total = _bounded_size(2, maximum_bytes)
            if maximum_bytes is not None and total > maximum_bytes:
                return total
            for index, item in enumerate(value):
                if index:
                    total += 1
                remaining = None if maximum_bytes is None else max(0, maximum_bytes - total)
                total += _json_encoded_size(item, remaining, active)
                if maximum_bytes is not None and total > maximum_bytes:
                    return maximum_bytes + 1
            return total
        finally:
            active.remove(identity)
    if type(value) is dict:
        identity = id(value)
        if identity in active:
            raise ProtocolViolation("cyclic JSON object")
        active.add(identity)
        try:
            total = _bounded_size(2, maximum_bytes)
            if maximum_bytes is not None and total > maximum_bytes:
                return total
            for index, (key, item) in enumerate(value.items()):
                if type(key) is not str:
                    raise ProtocolViolation("JSON object keys must be strings")
                if index:
                    total += 1
                remaining = None if maximum_bytes is None else max(0, maximum_bytes - total)
                total += _json_string_size(key, remaining)
                total += 1
                remaining = None if maximum_bytes is None else max(0, maximum_bytes - total)
                total += _json_encoded_size(item, remaining, active)
                if maximum_bytes is not None and total > maximum_bytes:
                    return maximum_bytes + 1
            return total
        finally:
            active.remove(identity)
    raise ProtocolViolation(f"unsupported JSON value type: {type(value).__name__}")


def _json_string_size(value: str, maximum_bytes: int | None) -> int:
    total = 2
    short_escapes = {"\b", "\t", "\n", "\f", "\r"}
    for character in value:
        codepoint = ord(character)
        if character in {'"', "\\"} or character in short_escapes:
            total += 2
        elif codepoint < 0x20:
            total += 6
        elif 0xD800 <= codepoint <= 0xDFFF:
            raise ProtocolViolation("JSON string contains invalid Unicode surrogate")
        elif codepoint < 0x80:
            total += 1
        elif codepoint < 0x800:
            total += 2
        elif codepoint < 0x10000:
            total += 3
        else:
            total += 4
        if maximum_bytes is not None and total > maximum_bytes:
            return maximum_bytes + 1
    return total


def _bounded_size(size: int, maximum_bytes: int | None) -> int:
    if maximum_bytes is not None and size > maximum_bytes:
        return maximum_bytes + 1
    return size


def _encode_envelope(
    message_type: str,
    correlation_id: str,
    payload: Mapping[str, object],
    validator: Callable[[bytes], object],
) -> bytes:
    envelope: dict[str, object] = {
        "protocolVersion": PROTOCOL_VERSION,
        "type": message_type,
        "correlationId": correlation_id,
        "payload": dict(payload),
    }
    encoded = _dump_json(envelope)
    if not encoded:
        raise ProtocolViolation("empty encoded protocol frame")
    if len(encoded) > MAX_CONTROL_FRAME_BYTES:
        raise ProtocolViolation(
            f"encoded protocol frame exceeds {MAX_CONTROL_FRAME_BYTES} bytes",
            correlation_id=correlation_id if _valid_correlation_id(correlation_id) else None,
        )
    validator(encoded)
    return _LENGTH.pack(len(encoded)) + encoded


def _request_parts(request: Request) -> tuple[str, Mapping[str, object]]:
    if isinstance(request, InitializeRequest):
        return (
            "initialize",
            {
                "launchWorkingDirectory": request.launch_working_directory,
                "environmentKind": request.environment_kind,
            },
        )
    if isinstance(request, ExecuteRequest):
        return "execute", {"code": request.code, "packages": list(request.packages)}
    return "shutdown", {}


def _response_parts(response: Response) -> tuple[str, Mapping[str, object]]:
    if isinstance(response, ReadyResponse):
        return (
            "ready",
            {
                "executionCount": response.execution_count,
                "runtime": _runtime_to_wire(response.runtime),
            },
        )
    if isinstance(response, StartedResponse):
        return "started", {"executionCount": response.execution_count}
    if isinstance(response, DisplayJsonResponse):
        return "display_json", {
            "executionCount": response.execution_count,
            "sequence": response.sequence,
            "value": response.value,
        }
    if isinstance(response, ArtifactBeginResponse):
        return "artifact_begin", {
            "executionCount": response.execution_count,
            "sequence": response.sequence,
            "transactionId": response.transaction_id,
            "kind": response.kind,
            "name": response.name,
            "declaredMimeType": response.declared_mime_type,
            "size": response.size,
        }
    if isinstance(response, ArtifactChunkResponse):
        return "artifact_chunk", {
            "executionCount": response.execution_count,
            "sequence": response.sequence,
            "transactionId": response.transaction_id,
            "chunkIndex": response.chunk_index,
            "data": base64.b64encode(response.data).decode("ascii"),
        }
    if isinstance(response, ArtifactEndResponse):
        return "artifact_end", {
            "executionCount": response.execution_count,
            "sequence": response.sequence,
            "transactionId": response.transaction_id,
            "chunkCount": response.chunk_count,
            "sha256": response.sha256,
        }
    if isinstance(response, DoneResponse):
        if not response.has_result and response.result is not None:
            raise ProtocolViolation("hasResult=false requires result=None")
        payload: dict[str, object] = {
            "outcome": response.outcome,
            "executionCount": response.execution_count,
            "runtime": _runtime_to_wire(response.runtime),
            "hasResult": response.has_result,
        }
        if response.has_result:
            payload["result"] = response.result
        if response.error is not None:
            payload["error"] = _error_to_wire(response.error)
        return "done", payload
    return "protocol_error", {"code": response.code, "message": response.message}


def _parse_envelope(payload: bytes) -> tuple[str, str, dict[str, object]]:
    raw = _load_json_object(payload)
    correlation_id = raw.get("correlationId")
    valid_correlation = (
        correlation_id
        if isinstance(correlation_id, str) and _valid_correlation_id(correlation_id)
        else None
    )
    try:
        _validate_json_value(cast(JsonValue, raw))
    except RecursionError as error:
        raise ProtocolViolation(f"invalid JSON payload: {error}") from error
    _require_exact_keys(raw, {"protocolVersion", "type", "correlationId", "payload"})

    version = _require_integer(raw, "protocolVersion", minimum=0)
    if version != PROTOCOL_VERSION:
        raise ProtocolViolation(
            f"protocol version {version} does not match {PROTOCOL_VERSION}",
            code="version_mismatch",
            correlation_id=valid_correlation,
        )

    parsed_correlation = _require_string(raw, "correlationId", maximum_bytes=32)
    if not _valid_correlation_id(parsed_correlation):
        raise ProtocolViolation("invalid correlationId")

    message_type = _require_string(raw, "type", maximum_bytes=64, nonempty=True)
    body = _require_object(raw, "payload")
    return message_type, parsed_correlation, body


def _parse_done(body: dict[str, object], correlation_id: str) -> DoneResponse:
    allowed = {
        "outcome",
        "executionCount",
        "runtime",
        "hasResult",
        "result",
        "error",
    }
    _require_allowed_keys(body, allowed)
    required = {"outcome", "executionCount", "runtime", "hasResult"}
    missing = required - body.keys()
    if missing:
        raise ProtocolViolation(
            f"missing done fields: {sorted(missing)}", correlation_id=correlation_id
        )

    outcome = _require_done_outcome(body, "outcome")
    execution_count = _require_integer(body, "executionCount", minimum=1)
    runtime = _parse_runtime(_require_object(body, "runtime"), correlation_id)
    has_result = _require_boolean(body, "hasResult")
    has_result_field = "result" in body
    has_error_field = "error" in body

    if outcome == "completed":
        if has_result != has_result_field:
            raise ProtocolViolation(
                "completed result presence must match hasResult",
                correlation_id=correlation_id,
            )
        if has_error_field:
            raise ProtocolViolation(
                "completed response cannot contain error", correlation_id=correlation_id
            )
    else:
        if has_result or has_result_field:
            raise ProtocolViolation(
                f"{outcome} response cannot contain result", correlation_id=correlation_id
            )
        if not has_error_field:
            raise ProtocolViolation(
                f"{outcome} response requires error", correlation_id=correlation_id
            )

    result: JsonValue = None
    if has_result_field:
        result = cast(JsonValue, body["result"])
        if json_size(result, MAX_RESULT_BYTES) > MAX_RESULT_BYTES:
            raise ProtocolViolation(
                "done result exceeds maximum size", correlation_id=correlation_id
            )

    error = None
    if has_error_field:
        error = _parse_error(_require_object(body, "error"), correlation_id)
        if outcome == "interrupted" and error.type != "KeyboardInterrupt":
            raise ProtocolViolation(
                "interrupted error type must be KeyboardInterrupt",
                correlation_id=correlation_id,
            )

    return DoneResponse(
        correlation_id=correlation_id,
        outcome=outcome,
        execution_count=execution_count,
        runtime=runtime,
        has_result=has_result,
        result=result,
        error=error,
    )


def _parse_runtime(body: dict[str, object], correlation_id: str) -> RuntimeDiagnostics:
    _require_exact_keys(
        body,
        {
            "executable",
            "pythonVersion",
            "workingDirectory",
            "environmentKind",
            "implementation",
            "platform",
            "packages",
        },
    )
    return RuntimeDiagnostics(
        executable=_require_path(body, "executable", canonical=False),
        python_version=_require_string(
            body, "pythonVersion", maximum_bytes=MAX_PYTHON_VERSION_BYTES, nonempty=True
        ),
        working_directory=_require_path(body, "workingDirectory", canonical=True),
        environment_kind=_require_environment_kind(body, "environmentKind"),
        implementation=_require_control_free_string(
            body, "implementation", maximum_bytes=MAX_IMPLEMENTATION_BYTES
        ),
        platform=_require_control_free_string(body, "platform", maximum_bytes=MAX_PLATFORM_BYTES),
        packages=_parse_runtime_packages(body, correlation_id),
    )


def _parse_error(body: dict[str, object], correlation_id: str) -> ErrorInfo:
    _require_exact_keys(body, {"type", "message", "traceback"})
    error_type = _require_string(body, "type", maximum_bytes=MAX_ERROR_TYPE_BYTES, nonempty=True)
    message = _require_string(body, "message", maximum_bytes=MAX_ERROR_MESSAGE_BYTES)
    traceback_value = body.get("traceback")
    if not isinstance(traceback_value, list) or not all(
        isinstance(line, str) for line in traceback_value
    ):
        raise ProtocolViolation(
            "error traceback must be a string array", correlation_id=correlation_id
        )
    error = ErrorInfo(error_type, message, tuple(cast(list[str], traceback_value)))
    if json_size(cast(JsonValue, _error_to_wire(error)), MAX_ERROR_BYTES) > MAX_ERROR_BYTES:
        raise ProtocolViolation("encoded error exceeds maximum size", correlation_id=correlation_id)
    return error


def _runtime_to_wire(runtime: RuntimeDiagnostics) -> dict[str, object]:
    return {
        "executable": runtime.executable,
        "pythonVersion": runtime.python_version,
        "workingDirectory": runtime.working_directory,
        "environmentKind": runtime.environment_kind,
        "implementation": runtime.implementation,
        "platform": runtime.platform,
        "packages": [_runtime_package_to_wire(package) for package in runtime.packages],
    }


def _error_to_wire(error: ErrorInfo) -> dict[str, object]:
    return {
        "type": error.type,
        "message": error.message,
        "traceback": list(error.traceback),
    }


_INVALID_JSON_INTEGER = object()


def _parse_json_integer(value: str) -> int | object:
    try:
        return int(value)
    except ValueError:
        return _INVALID_JSON_INTEGER


def _load_json_object(payload: bytes) -> dict[str, object]:
    if not payload:
        raise ProtocolViolation("empty JSON payload")
    if len(payload) > MAX_CONTROL_FRAME_BYTES:
        raise ProtocolViolation("JSON payload exceeds maximum size")
    try:
        text = payload.decode("utf-8")
        parsed = _JSON_LOADS(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_constant,
            parse_int=_parse_json_integer,
        )
    except ProtocolViolation:
        raise
    except (UnicodeDecodeError, RecursionError, ValueError) as error:
        raise ProtocolViolation(f"invalid JSON payload: {error}") from error
    if not isinstance(parsed, dict):
        raise ProtocolViolation("protocol payload must be a JSON object")
    result = cast(dict[str, object], parsed)
    return result


def _peek_correlation_id(payload: bytes) -> str | None:
    try:
        parsed = _JSON_LOADS(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_int=_parse_json_integer,
        )
    except (UnicodeDecodeError, RecursionError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    correlation_id = parsed.get("correlationId")
    if isinstance(correlation_id, str) and _valid_correlation_id(correlation_id):
        return correlation_id
    return None


def _dump_json(value: object) -> bytes:
    try:
        return _JSON_DUMPS(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeEncodeError) as error:
        raise ProtocolViolation(f"value is not strict JSON: {error}") from error


class _DuplicateKeyError(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(f"duplicate key: {key}")
        result[key] = value
    return result


def _reject_nonfinite_constant(value: str) -> object:
    raise ProtocolViolation(f"non-finite JSON constant: {value}")


def _validate_json_value(value: JsonValue, active: set[int] | None = None) -> None:
    if value is None or type(value) in {bool, int, str}:
        return
    if type(value) is float:
        if not _ISFINITE(value):
            raise ProtocolViolation("non-finite JSON number")
        return
    if active is None:
        active = set()
    if type(value) is list:
        identity = id(value)
        if identity in active:
            raise ProtocolViolation("cyclic JSON array")
        active.add(identity)
        try:
            for item in value:
                _validate_json_value(item, active)
        finally:
            active.remove(identity)
        return
    if type(value) is dict:
        identity = id(value)
        if identity in active:
            raise ProtocolViolation("cyclic JSON object")
        active.add(identity)
        try:
            for key, item in value.items():
                if type(key) is not str:
                    raise ProtocolViolation("JSON object keys must be strings")
                _validate_json_value(item, active)
        finally:
            active.remove(identity)
        return
    raise ProtocolViolation(f"unsupported JSON value type: {type(value).__name__}")


def _require_exact_keys(body: Mapping[str, object], expected: set[str]) -> None:
    actual = set(body)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise ProtocolViolation(f"schema keys differ: missing={missing}, unknown={unknown}")


def _require_allowed_keys(body: Mapping[str, object], allowed: set[str]) -> None:
    unknown = sorted(set(body) - allowed)
    if unknown:
        raise ProtocolViolation(f"unknown schema keys: {unknown}")


def _require_object(body: Mapping[str, object], key: str) -> dict[str, object]:
    value = body.get(key)
    if not isinstance(value, dict):
        raise ProtocolViolation(f"{key} must be an object")
    return cast(dict[str, object], value)


def _require_string(
    body: Mapping[str, object],
    key: str,
    *,
    maximum_bytes: int,
    nonempty: bool = False,
) -> str:
    value = body.get(key)
    if type(value) is not str:
        raise ProtocolViolation(f"{key} must be an exact string")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise ProtocolViolation(f"{key} contains invalid Unicode") from error
    if nonempty and not value:
        raise ProtocolViolation(f"{key} must not be empty")
    if size > maximum_bytes:
        raise ProtocolViolation(f"{key} exceeds {maximum_bytes} UTF-8 bytes")
    return value


def normalize_package_name(value: str) -> str:
    """Return one validated PEP 503 normalized distribution name."""
    if not (1 <= len(value) <= MAX_PACKAGE_NAME_BYTES) or _PACKAGE_NAME.fullmatch(value) is None:
        raise ValueError("invalid Python distribution name")
    return re.sub(r"[-_.]+", "-", value).lower()


def validate_package_names(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Validate the bounded package request and reject normalized duplicates."""
    if len(values) > MAX_PACKAGE_COUNT:
        raise ValueError(f"packages exceeds {MAX_PACKAGE_COUNT} items")
    normalized: set[str] = set()
    result: list[str] = []
    for value in values:
        if type(value) is not str:
            raise ValueError("package names must be exact strings")
        key = normalize_package_name(value)
        if key in normalized:
            raise ValueError("duplicate normalized package name")
        normalized.add(key)
        result.append(value)
    return tuple(result)


def validate_logical_name(value: str) -> str:
    """Validate one public artifact logical name."""
    if not (1 <= len(value) <= MAX_LOGICAL_NAME_CODEPOINTS):
        raise ValueError("invalid artifact name length")
    if "/" in value or "\\" in value:
        raise ValueError("artifact name contains a path separator")
    if any(unicodedata.category(character) in {"Cc", "Cf"} for character in value):
        raise ValueError("artifact name contains a control or format character")
    return value


def validate_mime_type(value: str) -> str:
    """Validate one printable-ASCII media type with optional parameters."""
    if not (1 <= len(value) <= MAX_MIME_BYTES) or any(
        ord(character) < 0x20 or ord(character) > 0x7E for character in value
    ):
        raise ValueError("invalid MIME length or character")
    parts = _split_mime_parts(value)
    media_type = parts[0].strip()
    if media_type.count("/") != 1:
        raise ValueError("invalid MIME media type")
    major, minor = media_type.split("/", 1)
    if _MIME_TOKEN.fullmatch(major) is None or _MIME_TOKEN.fullmatch(minor) is None:
        raise ValueError("invalid MIME media type")
    for parameter in parts[1:]:
        item = parameter.strip()
        if "=" not in item:
            raise ValueError("invalid MIME parameter")
        name, raw_value = item.split("=", 1)
        if _MIME_TOKEN.fullmatch(name.strip()) is None or not _valid_mime_parameter_value(
            raw_value.strip()
        ):
            raise ValueError("invalid MIME parameter")
    return value


def _split_mime_parts(value: str) -> list[str]:
    parts: list[str] = []
    start = 0
    quoted = False
    escaped = False
    for index, character in enumerate(value):
        if escaped:
            escaped = False
        elif quoted and character == "\\":
            escaped = True
        elif character == '"':
            quoted = not quoted
        elif character == ";" and not quoted:
            parts.append(value[start:index])
            start = index + 1
    if quoted or escaped:
        raise ValueError("unterminated MIME quoted string")
    parts.append(value[start:])
    return parts


def _valid_mime_parameter_value(value: str) -> bool:
    if _MIME_TOKEN.fullmatch(value) is not None:
        return True
    if len(value) < 2 or value[0] != '"' or value[-1] != '"':
        return False
    escaped = False
    for character in value[1:-1]:
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == '"':
            return False
    return not escaped


def _parse_package_names(body: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = body.get(key)
    if not isinstance(value, list):
        raise ProtocolViolation(f"{key} must be an array")
    try:
        return validate_package_names(cast(list[str], value))
    except ValueError as error:
        raise ProtocolViolation(str(error)) from error


def _parse_runtime_packages(
    body: Mapping[str, object], correlation_id: str
) -> tuple[RuntimePackage, ...]:
    raw = body.get("packages")
    if not isinstance(raw, list) or len(raw) > MAX_PACKAGE_COUNT:
        raise ProtocolViolation("runtime packages must be a bounded array")
    result: list[RuntimePackage] = []
    names: list[str] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ProtocolViolation("runtime package must be an object")
        package = cast(dict[str, object], item)
        _require_allowed_keys(package, {"name", "version", "error"})
        if set(package) not in ({"name", "version"}, {"name", "error"}):
            raise ProtocolViolation("runtime package requires exactly one of version or error")
        name = _require_string(package, "name", maximum_bytes=MAX_PACKAGE_NAME_BYTES, nonempty=True)
        names.append(name)
        if "version" in package:
            version = _require_control_free_string(
                package, "version", maximum_bytes=MAX_PACKAGE_VERSION_BYTES
            )
            result.append(RuntimePackage(name=name, version=version))
        else:
            result.append(RuntimePackage(name=name, error=_require_package_error(package, "error")))
    try:
        validate_package_names(names)
    except ValueError as error:
        raise ProtocolViolation(str(error), correlation_id=correlation_id) from error
    return tuple(result)


def _runtime_package_to_wire(package: RuntimePackage) -> dict[str, object]:
    result: dict[str, object] = {"name": package.name}
    if (package.version is None) == (package.error is None):
        raise ProtocolViolation("runtime package requires exactly one of version or error")
    if package.version is not None:
        result["version"] = package.version
    else:
        result["error"] = package.error
    return result


def _require_control_free_string(
    body: Mapping[str, object], key: str, *, maximum_bytes: int
) -> str:
    value = _require_string(body, key, maximum_bytes=maximum_bytes, nonempty=True)
    if any(unicodedata.category(character) in {"Cc", "Cf"} for character in value):
        raise ProtocolViolation(f"{key} contains a control or format character")
    return value


def _require_bounded_integer(
    body: Mapping[str, object], key: str, minimum: int, maximum: int
) -> int:
    value = _require_integer(body, key, minimum=minimum)
    if value > maximum:
        raise ProtocolViolation(f"{key} must be at most {maximum}")
    return value


def _require_uuid(body: Mapping[str, object], key: str) -> str:
    value = _require_string(body, key, maximum_bytes=32)
    if _UUID_HEX.fullmatch(value) is None:
        raise ProtocolViolation(f"invalid {key}")
    return value


def _require_sha256(body: Mapping[str, object], key: str) -> str:
    value = _require_string(body, key, maximum_bytes=64)
    if _SHA256.fullmatch(value) is None:
        raise ProtocolViolation(f"invalid {key}")
    return value


def _require_artifact_kind(body: Mapping[str, object], key: str) -> ArtifactKind:
    value = _require_string(body, key, maximum_bytes=8)
    if value not in {"artifact", "image"}:
        raise ProtocolViolation(f"invalid {key}")
    return cast(ArtifactKind, value)


def _require_package_error(body: Mapping[str, object], key: str) -> PackageError:
    value = _require_string(body, key, maximum_bytes=32)
    if value not in {"not installed", "metadata unavailable", "invalid metadata"}:
        raise ProtocolViolation(f"invalid {key}")
    return cast(PackageError, value)


def _require_logical_name(body: Mapping[str, object], key: str) -> str:
    value = _require_string(body, key, maximum_bytes=MAX_CONTROL_FRAME_BYTES, nonempty=True)
    try:
        return validate_logical_name(value)
    except ValueError as error:
        raise ProtocolViolation(str(error)) from error


def _require_mime(body: Mapping[str, object], key: str) -> str:
    value = _require_string(body, key, maximum_bytes=MAX_MIME_BYTES, nonempty=True)
    try:
        return validate_mime_type(value)
    except ValueError as error:
        raise ProtocolViolation(str(error)) from error


def _require_canonical_base64(body: Mapping[str, object], key: str) -> bytes:
    value = _require_string(body, key, maximum_bytes=MAX_ARTIFACT_CHUNK_ENCODED_BYTES)
    try:
        encoded = value.encode("ascii")
        decoded = base64.b64decode(encoded, validate=True)
    except (UnicodeEncodeError, binascii.Error) as error:
        raise ProtocolViolation(f"{key} must be canonical base64") from error
    if (
        not decoded
        or len(decoded) > MAX_ARTIFACT_CHUNK_BYTES
        or base64.b64encode(decoded) != encoded
    ):
        raise ProtocolViolation(f"{key} must be canonical bounded base64")
    return decoded


def _require_path(body: Mapping[str, object], key: str, *, canonical: bool) -> str:
    value = _require_string(body, key, maximum_bytes=MAX_PATH_BYTES, nonempty=True)
    if not value.startswith("/"):
        raise ProtocolViolation(f"{key} must be an absolute POSIX path")
    if canonical and _NORMPATH(value) != value:
        raise ProtocolViolation(f"{key} must be canonical")
    return value


def _require_integer(body: Mapping[str, object], key: str, *, minimum: int) -> int:
    value = body.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProtocolViolation(f"{key} must be an integer")
    if value < minimum:
        raise ProtocolViolation(f"{key} must be at least {minimum}")
    return value


def _require_boolean(body: Mapping[str, object], key: str) -> bool:
    value = body.get(key)
    if not isinstance(value, bool):
        raise ProtocolViolation(f"{key} must be a boolean")
    return value


def _require_environment_kind(body: Mapping[str, object], key: str) -> EnvironmentKind:
    value = _require_string(body, key, maximum_bytes=32)
    if value not in {"project_venv", "active_venv", "system"}:
        raise ProtocolViolation(f"invalid {key}: {value}")
    return cast(EnvironmentKind, value)


def _require_done_outcome(body: Mapping[str, object], key: str) -> DoneOutcome:
    value = _require_string(body, key, maximum_bytes=32)
    if value not in {"completed", "failed", "interrupted"}:
        raise ProtocolViolation(f"invalid {key}: {value}")
    return cast(DoneOutcome, value)


def _require_protocol_error_code(body: Mapping[str, object], key: str) -> ProtocolErrorCode:
    value = _require_string(body, key, maximum_bytes=64)
    allowed = {
        "version_mismatch",
        "invalid_sequence",
        "invalid_request",
        "runtime_diagnostics_error",
        "internal_protocol_error",
    }
    if value not in allowed:
        raise ProtocolViolation(f"invalid {key}: {value}")
    return cast(ProtocolErrorCode, value)


def _valid_correlation_id(value: str) -> bool:
    return _CORRELATION_ID.fullmatch(value) is not None


def _read_exact(stream: BinaryIO, size: int, *, allow_initial_eof: bool) -> bytes | None:
    chunks = bytearray()
    while len(chunks) < size:
        try:
            chunk = stream.read(size - len(chunks))
        except InterruptedError:
            continue
        if chunk is None:
            raise ProtocolViolation("protocol stream returned no bytes")
        if not chunk:
            if allow_initial_eof and not chunks:
                return None
            raise ProtocolViolation("truncated protocol frame")
        chunks.extend(chunk)
    return bytes(chunks)
