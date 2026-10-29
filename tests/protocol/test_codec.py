"""Focused tests for the private Runner protocol codec."""

from __future__ import annotations

import io
import json
import struct
from collections.abc import Iterable
from typing import BinaryIO, cast

import pytest

from amkernel.protocol import (
    MAX_CODE_BYTES,
    MAX_CONTROL_FRAME_BYTES,
    DoneResponse,
    ErrorInfo,
    ExecuteRequest,
    InitializeRequest,
    ProtocolErrorResponse,
    ProtocolViolation,
    ReadyResponse,
    Request,
    Response,
    RuntimeDiagnostics,
    ShutdownRequest,
    StartedResponse,
    encode_request,
    encode_response,
    parse_request_payload,
    parse_response_payload,
    read_request,
    write_frame,
)

CORRELATION_ID = "00000000000040008000000000000001"
RUNTIME = RuntimeDiagnostics(
    executable="/workspace/.venv/bin/python",
    python_version="3.11.16",
    working_directory="/workspace",
    environment_kind="project_venv",
)


def payload(frame: bytes) -> bytes:
    size = struct.unpack(">I", frame[:4])[0]
    assert size == len(frame) - 4
    return frame[4:]


@pytest.mark.parametrize(
    "message",
    [
        InitializeRequest(CORRELATION_ID, "/workspace", "project_venv"),
        ExecuteRequest(CORRELATION_ID, "value = 1\nvalue"),
        ShutdownRequest(CORRELATION_ID),
    ],
)
def test_request_round_trip(message: Request) -> None:
    encoded = encode_request(message)
    assert read_request(io.BytesIO(encoded)) == message


@pytest.mark.parametrize(
    "message",
    [
        ReadyResponse(CORRELATION_ID, RUNTIME),
        StartedResponse(CORRELATION_ID, 1),
        DoneResponse(CORRELATION_ID, "completed", 1, RUNTIME, True, None),
        DoneResponse(
            CORRELATION_ID,
            "failed",
            2,
            RUNTIME,
            False,
            error=ErrorInfo("ValueError", "bad", ("ValueError: bad",)),
        ),
        DoneResponse(
            CORRELATION_ID,
            "interrupted",
            3,
            RUNTIME,
            False,
            error=ErrorInfo("KeyboardInterrupt", "", ("KeyboardInterrupt",)),
        ),
        ProtocolErrorResponse(CORRELATION_ID, "invalid_sequence", "wrong state"),
    ],
)
def test_response_round_trip(message: Response) -> None:
    encoded = encode_response(message)
    assert parse_response_payload(payload(encoded)) == message


def test_maximum_high_escape_code_fits_private_frame() -> None:
    request = ExecuteRequest(CORRELATION_ID, "\x00" * MAX_CODE_BYTES)

    encoded = encode_request(request)

    assert len(encoded) - 4 <= MAX_CONTROL_FRAME_BYTES
    assert read_request(io.BytesIO(encoded)) == request


def test_code_over_public_limit_is_rejected_before_encoding() -> None:
    with pytest.raises(ProtocolViolation, match="code exceeds"):
        encode_request(ExecuteRequest(CORRELATION_ID, "x" * (MAX_CODE_BYTES + 1)))


def test_duplicate_nested_key_is_rejected() -> None:
    duplicate = (
        b'{"protocolVersion":1,"type":"execute",'
        b'"correlationId":"00000000000040008000000000000001",'
        b'"payload":{"code":"x","code":"y"}}'
    )

    with pytest.raises(ProtocolViolation, match="duplicate key"):
        parse_request_payload(duplicate)


def test_version_mismatch_retains_valid_correlation() -> None:
    incompatible = json.dumps(
        {
            "protocolVersion": 3,
            "type": "shutdown",
            "correlationId": CORRELATION_ID,
            "payload": {},
        },
        separators=(",", ":"),
    ).encode()

    with pytest.raises(ProtocolViolation) as caught:
        parse_request_payload(incompatible)

    assert caught.value.code == "version_mismatch"
    assert caught.value.correlation_id == CORRELATION_ID


def test_unknown_fields_are_rejected() -> None:
    invalid = json.dumps(
        {
            "protocolVersion": 2,
            "type": "shutdown",
            "correlationId": CORRELATION_ID,
            "payload": {"unexpected": True},
        },
        separators=(",", ":"),
    ).encode()

    with pytest.raises(ProtocolViolation, match="unknown") as caught:
        parse_request_payload(invalid)
    assert caught.value.correlation_id == CORRELATION_ID


def test_nonfinite_result_is_rejected() -> None:
    invalid = (
        b'{"protocolVersion":1,"type":"done",'
        b'"correlationId":"00000000000040008000000000000001",'
        b'"payload":{"outcome":"completed","executionCount":1,'
        b'"runtime":{"executable":"/python","pythonVersion":"3.11",'
        b'"workingDirectory":"/workspace","environmentKind":"system"},'
        b'"hasResult":true,"result":1e400}}'
    )

    with pytest.raises(ProtocolViolation, match="non-finite") as caught:
        parse_response_payload(invalid)
    assert caught.value.correlation_id == CORRELATION_ID


def test_done_conditional_fields_are_enforced() -> None:
    with pytest.raises(ProtocolViolation, match="requires error"):
        encode_response(DoneResponse(CORRELATION_ID, "failed", 1, RUNTIME, False))


def test_aggregate_error_bound_is_enforced() -> None:
    oversized = ErrorInfo("ValueError", "x" * 16_384, ("y" * 65_536,))

    with pytest.raises(ProtocolViolation, match="encoded error exceeds"):
        encode_response(
            DoneResponse(
                CORRELATION_ID,
                "failed",
                1,
                RUNTIME,
                False,
                error=oversized,
            )
        )


class ChunkedReader:
    """A stream that returns at most one configured chunk per read."""

    def __init__(self, value: bytes, chunks: Iterable[int]) -> None:
        self._stream = io.BytesIO(value)
        self._chunks = iter(chunks)

    def read(self, size: int = -1) -> bytes:
        try:
            maximum = next(self._chunks)
        except StopIteration:
            maximum = size
        return self._stream.read(min(size, maximum))


class PartialWriter:
    """A stream that accepts only a few bytes per write."""

    def __init__(self) -> None:
        self._stream = io.BytesIO()

    def write(self, value: bytes | bytearray | memoryview[bytes]) -> int:
        return self._stream.write(bytes(value[:3]))

    def flush(self) -> None:
        pass

    def getvalue(self) -> bytes:
        return self._stream.getvalue()


def test_fragmented_reads_and_partial_writes_are_lossless() -> None:
    expected = encode_request(ExecuteRequest(CORRELATION_ID, "40 + 2"))
    reader = ChunkedReader(expected, [1] * len(expected))

    assert read_request(cast(BinaryIO, reader)) == ExecuteRequest(CORRELATION_ID, "40 + 2")

    writer = PartialWriter()
    write_frame(cast(BinaryIO, writer), expected)
    assert writer.getvalue() == expected


def test_clean_eof_differs_from_truncated_frame() -> None:
    assert read_request(io.BytesIO()) is None

    with pytest.raises(ProtocolViolation, match="truncated"):
        read_request(io.BytesIO(b"\x00\x00"))


def test_zero_and_oversized_lengths_fail_before_payload_read() -> None:
    with pytest.raises(ProtocolViolation, match="zero-length"):
        read_request(io.BytesIO(struct.pack(">I", 0)))

    with pytest.raises(ProtocolViolation, match="exceeds"):
        read_request(io.BytesIO(struct.pack(">I", MAX_CONTROL_FRAME_BYTES + 1)))


def test_has_result_false_rejects_hidden_value() -> None:
    with pytest.raises(ProtocolViolation, match="hasResult=false"):
        encode_response(
            DoneResponse(
                CORRELATION_ID,
                "completed",
                1,
                RUNTIME,
                False,
                result=42,
            )
        )


def test_deeply_nested_json_becomes_protocol_violation() -> None:
    deeply_nested = (
        b'{"protocolVersion":1,"type":"done",'
        b'"correlationId":"00000000000040008000000000000001",'
        b'"payload":{"outcome":"completed","executionCount":1,'
        b'"runtime":{"executable":"/python","pythonVersion":"3.11",'
        b'"workingDirectory":"/workspace","environmentKind":"system"},'
        b'"hasResult":true,"result":' + (b"[" * 2_000) + b"0" + (b"]" * 2_000) + b"}}"
    )

    with pytest.raises(ProtocolViolation, match="invalid JSON"):
        parse_response_payload(deeply_nested)


def test_oversized_json_integer_is_rejected_with_correlation() -> None:
    oversized_integer = (
        b'{"protocolVersion":1,"type":"done",'
        b'"correlationId":"00000000000040008000000000000001",'
        b'"payload":{"outcome":"completed","executionCount":1,'
        b'"runtime":{"executable":"/python","pythonVersion":"3.11",'
        b'"workingDirectory":"/workspace","environmentKind":"system"},'
        b'"hasResult":true,"result":' + (b"9" * 5_000) + b"}}"
    )

    with pytest.raises(ProtocolViolation) as caught:
        parse_response_payload(oversized_integer)
    assert caught.value.correlation_id == CORRELATION_ID
