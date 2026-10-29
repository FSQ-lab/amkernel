"""Protocol v2 wire-model and transition fixtures."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from amkernel.protocol import (
    ArtifactBeginResponse,
    ArtifactChunkResponse,
    ArtifactEndResponse,
    DisplayJsonResponse,
    DoneResponse,
    ExecuteRequest,
    ExecutionResponseState,
    ProtocolViolation,
    Response,
    RuntimeDiagnostics,
    encode_request,
    encode_response,
    parse_request_payload,
    parse_response_payload,
)

CORRELATION_ID = "00000000000040008000000000000001"
TRANSACTION_ID = "00000000000040008000000000000002"
RUNTIME = RuntimeDiagnostics(
    executable="/usr/bin/python3",
    python_version="3.13.9",
    working_directory="/workspace",
    environment_kind="system",
    implementation="CPython",
    platform="macOS-26.1-arm64",
)


def _payload(frame: bytes) -> bytes:
    return frame[4:]


def _response_payload(message_type: str, payload: dict[str, object]) -> bytes:
    return json.dumps(
        {
            "protocolVersion": 2,
            "type": message_type,
            "correlationId": CORRELATION_ID,
            "payload": payload,
        },
        separators=(",", ":"),
    ).encode()


def test_execute_packages_round_trip_and_reject_normalized_duplicates() -> None:
    request = ExecuteRequest(CORRELATION_ID, "42", ("Pillow", "zope.interface"))

    assert parse_request_payload(_payload(encode_request(request))) == request

    duplicate = json.loads(_payload(encode_request(request)))
    duplicate["payload"]["packages"] = ["zope.interface", "zope-interface"]
    with pytest.raises(ProtocolViolation, match="duplicate normalized"):
        parse_request_payload(json.dumps(duplicate, separators=(",", ":")).encode())


def test_output_frames_round_trip_with_canonical_chunk_base64() -> None:
    responses: list[Response] = [
        DisplayJsonResponse(CORRELATION_ID, 1, 1, {"answer": 42}),
        ArtifactBeginResponse(
            CORRELATION_ID,
            1,
            2,
            TRANSACTION_ID,
            "artifact",
            "answer.json",
            "application/json",
            3,
        ),
        ArtifactChunkResponse(CORRELATION_ID, 1, 2, TRANSACTION_ID, 0, b"abc"),
        ArtifactEndResponse(
            CORRELATION_ID,
            1,
            2,
            TRANSACTION_ID,
            1,
            hashlib.sha256(b"abc").hexdigest(),
        ),
    ]

    assert [
        parse_response_payload(_payload(encode_response(item))) for item in responses
    ] == responses

    invalid = _response_payload(
        "artifact_chunk",
        {
            "executionCount": 1,
            "sequence": 2,
            "transactionId": TRANSACTION_ID,
            "chunkIndex": 0,
            "data": "YQ===",
        },
    )
    with pytest.raises(ProtocolViolation, match="canonical base64"):
        parse_response_payload(invalid)

    empty = json.loads(invalid)
    empty["payload"]["data"] = ""
    with pytest.raises(ProtocolViolation, match="canonical bounded base64"):
        parse_response_payload(json.dumps(empty, separators=(",", ":")).encode())


def test_execution_state_accepts_protocol_v2_transition_fixture() -> None:
    fixture = json.loads(
        (Path(__file__).parents[1] / "fixtures" / "protocol_v2_transition.json").read_text()
    )
    responses = [
        parse_response_payload(json.dumps(item, separators=(",", ":")).encode())
        for item in fixture["responses"]
    ]
    state = ExecutionResponseState(CORRELATION_ID, 1)

    for response in responses:
        state.accept(response)

    assert state.terminal
    assert state.next_sequence == 3

    with pytest.raises(ProtocolViolation, match="after terminal"):
        state.accept(DisplayJsonResponse(CORRELATION_ID, 1, 3, None))


@pytest.mark.parametrize(
    "response, message",
    [
        (DisplayJsonResponse(CORRELATION_ID, 1, 2, None), "sequence"),
        (DisplayJsonResponse(CORRELATION_ID, 2, 1, None), "executionCount"),
        (DisplayJsonResponse("10000000000040008000000000000001", 1, 1, None), "uncorrelated"),
    ],
)
def test_execution_state_rejects_correlation_count_and_sequence_faults(
    response: DisplayJsonResponse, message: str
) -> None:
    state = ExecutionResponseState(CORRELATION_ID, 1)

    with pytest.raises(ProtocolViolation, match=message):
        state.accept(response)


def test_execution_state_rejects_interleaving_and_chunk_index_gaps() -> None:
    state = ExecutionResponseState(CORRELATION_ID, 1)
    state.accept(
        ArtifactBeginResponse(
            CORRELATION_ID,
            1,
            1,
            TRANSACTION_ID,
            "artifact",
            "data.bin",
            "application/octet-stream",
            1,
        )
    )

    with pytest.raises(ProtocolViolation, match="interleaves"):
        state.accept(DisplayJsonResponse(CORRELATION_ID, 1, 2, None))
    with pytest.raises(ProtocolViolation, match="contiguous"):
        state.accept(ArtifactChunkResponse(CORRELATION_ID, 1, 1, TRANSACTION_ID, 1, b"x"))


def test_execution_state_rejects_size_hash_and_incomplete_terminal() -> None:
    state = ExecutionResponseState(CORRELATION_ID, 1)
    state.accept(
        ArtifactBeginResponse(
            CORRELATION_ID,
            1,
            1,
            TRANSACTION_ID,
            "artifact",
            "data.bin",
            "application/octet-stream",
            2,
        )
    )
    state.accept(ArtifactChunkResponse(CORRELATION_ID, 1, 1, TRANSACTION_ID, 0, b"x"))

    with pytest.raises(ProtocolViolation, match="size mismatch"):
        state.accept(
            ArtifactEndResponse(
                CORRELATION_ID,
                1,
                1,
                TRANSACTION_ID,
                1,
                hashlib.sha256(b"x").hexdigest(),
            )
        )
    with pytest.raises(ProtocolViolation, match="incomplete"):
        state.accept(DoneResponse(CORRELATION_ID, "completed", 1, RUNTIME, False))


def test_protocol_parser_rejects_invalid_name_mime_uuid_and_hash() -> None:
    base = {
        "executionCount": 1,
        "sequence": 1,
        "transactionId": TRANSACTION_ID,
        "kind": "artifact",
        "name": "data.bin",
        "declaredMimeType": "application/octet-stream",
        "size": 0,
    }
    for key, value, message in [
        ("transactionId", "0" * 32, "transactionId"),
        ("name", "../data.bin", "path separator"),
        ("declaredMimeType", "not a mime", "MIME"),
    ]:
        payload = dict(base)
        payload[key] = value
        with pytest.raises(ProtocolViolation, match=message):
            parse_response_payload(_response_payload("artifact_begin", payload))

    with pytest.raises(ProtocolViolation, match="sha256"):
        parse_response_payload(
            _response_payload(
                "artifact_end",
                {
                    "executionCount": 1,
                    "sequence": 1,
                    "transactionId": TRANSACTION_ID,
                    "chunkCount": 0,
                    "sha256": "A" * 64,
                },
            )
        )
