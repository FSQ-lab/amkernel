"""Real Runner subprocess evidence for framing and EOF transitions."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import uuid
from pathlib import Path
from typing import IO, BinaryIO

import pytest

from amkernel.protocol import (
    DIAGNOSTIC_FD_ARGUMENT,
    REQUEST_FD_ARGUMENT,
    RESPONSE_FD_ARGUMENT,
    DoneResponse,
    ExecuteRequest,
    InitializeRequest,
    ProtocolErrorResponse,
    ReadyResponse,
    ShutdownRequest,
    StartedResponse,
    encode_request,
    read_response,
)
from amkernel.supervisor import configured_runtime

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(os.name != "posix", reason="Stage 1 Runtime is POSIX-only"),
]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class RawRunner:
    def __init__(
        self,
        process: subprocess.Popen[bytes],
        request: BinaryIO,
        response: BinaryIO,
        diagnostic: BinaryIO,
    ) -> None:
        self.process = process
        self.request = request
        self.response = response
        self.diagnostic = diagnostic

    @classmethod
    def start(cls, working_directory: Path) -> RawRunner:
        request_read, request_write = os.pipe()
        response_read, response_write = os.pipe()
        diagnostic_read, diagnostic_write = os.pipe()
        child_fds = (request_read, response_write, diagnostic_write)
        process = subprocess.Popen(
            [
                sys.executable,
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
            ],
            cwd=working_directory,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
            pass_fds=child_fds,
            start_new_session=True,
        )
        os.close(request_read)
        os.close(response_write)
        os.close(diagnostic_write)
        return cls(
            process,
            os.fdopen(request_write, "wb", buffering=0),
            os.fdopen(response_read, "rb", buffering=0),
            os.fdopen(diagnostic_read, "rb", buffering=0),
        )

    def initialize(self, working_directory: Path) -> ReadyResponse:
        correlation_id = uuid.uuid4().hex
        configured = configured_runtime(working_directory)
        self.request.write(
            encode_request(
                InitializeRequest(
                    correlation_id,
                    configured.working_directory,
                    configured.environment_kind,
                )
            )
        )
        response = read_response(self.response)
        assert isinstance(response, ReadyResponse)
        assert response.correlation_id == correlation_id
        return response

    def send(self, *frames: bytes) -> None:
        self.request.write(b"".join(frames))

    def send_payload(self, payload: bytes, *, declared_extra: int = 0) -> None:
        self.request.write((len(payload) + declared_extra).to_bytes(4, "big") + payload)

    async def wait(self, timeout: float = 5.0) -> int:
        return await asyncio.wait_for(asyncio.to_thread(self.process.wait), timeout=timeout)

    async def close(self) -> None:
        streams: list[IO[bytes]] = [self.request, self.response, self.diagnostic]
        if self.process.stdout is not None:
            streams.append(self.process.stdout)
        if self.process.stderr is not None:
            streams.append(self.process.stderr)
        for stream in streams:
            try:
                stream.close()
            except OSError:
                pass
        if self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        await asyncio.wait_for(asyncio.to_thread(self.process.wait), timeout=5.0)


async def test_real_runner_rejects_bad_typed_request_and_exits(tmp_path: Path) -> None:
    runner = RawRunner.start(tmp_path)
    try:
        runner.initialize(tmp_path)
        correlation_id = uuid.uuid4().hex
        payload = json.dumps(
            {
                "protocolVersion": 2,
                "type": "execute",
                "correlationId": correlation_id,
                "payload": {"code": 42, "packages": []},
            },
            separators=(",", ":"),
        ).encode()
        runner.send_payload(payload)
        response = await asyncio.wait_for(asyncio.to_thread(read_response, runner.response), 2.0)

        assert isinstance(response, ProtocolErrorResponse)
        assert response.correlation_id == correlation_id
        assert response.code == "invalid_request"
        assert await runner.wait() == 2
    finally:
        await runner.close()


async def test_real_runner_accepts_coalesced_execute_and_shutdown_frames(tmp_path: Path) -> None:
    runner = RawRunner.start(tmp_path)
    try:
        runner.initialize(tmp_path)
        execute_id = uuid.uuid4().hex
        runner.send(
            encode_request(ExecuteRequest(execute_id, "42")),
            encode_request(ShutdownRequest(uuid.uuid4().hex)),
        )
        started = await asyncio.wait_for(asyncio.to_thread(read_response, runner.response), 2.0)
        done = await asyncio.wait_for(asyncio.to_thread(read_response, runner.response), 2.0)

        assert isinstance(started, StartedResponse)
        assert started.correlation_id == execute_id
        assert isinstance(done, DoneResponse)
        assert done.correlation_id == execute_id
        assert done.result == 42
        assert await runner.wait() == 0
    finally:
        await runner.close()


async def test_real_runner_truncated_payload_and_unexpected_eof_are_bounded(
    tmp_path: Path,
) -> None:
    truncated = RawRunner.start(tmp_path)
    eof = RawRunner.start(tmp_path)
    try:
        truncated.initialize(tmp_path)
        payload = b'{"protocolVersion":1'
        truncated.send_payload(payload, declared_extra=100)
        truncated.request.close()
        assert await truncated.wait() == 2
        diagnostic = truncated.diagnostic.read().decode(errors="replace")
        assert "truncated protocol frame" in diagnostic

        eof.initialize(tmp_path)
        eof.request.close()
        assert await eof.wait() == 2
        assert "unexpected request EOF" in eof.diagnostic.read().decode(errors="replace")
    finally:
        await truncated.close()
        await eof.close()
