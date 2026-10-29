"""Execution-scoped stream spooling, bounds, previews, and publication."""

from __future__ import annotations

import asyncio
import json
import mmap
import tempfile
import time
from dataclasses import dataclass, field
from typing import IO, Literal

from amkernel.artifact_store import (
    ArtifactBundle,
    ArtifactRecord,
    ArtifactStoreError,
    ArtifactWriter,
)
from amkernel.protocol import (
    MAX_LIVE_MESSAGE_BYTES,
    MAX_STREAM_BYTES,
    SAFE_MIME_TYPES,
    STREAM_TAIL_BYTES,
    ArtifactBeginResponse,
    ArtifactChunkResponse,
    ArtifactEndResponse,
    DisplayJsonResponse,
    JsonValue,
    Response,
)
from amkernel.structured_output import (
    ImageInfo,
    StructuredOutputError,
    validate_safe_artifact,
)

StreamChannel = Literal["stdout", "stderr"]
OutputEventKind = Literal["stdout", "stderr", "display", "image", "artifact"]


@dataclass(frozen=True, slots=True)
class OutputSnapshot:
    """One replaceable advisory live-text snapshot."""

    revision: int
    channel: OutputEventKind
    text: str


class OutputObserver:
    """Expose only the latest stream snapshot without producer backpressure."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[OutputSnapshot] = asyncio.Queue(maxsize=1)

    async def next(self) -> OutputSnapshot:
        return await self._queue.get()

    def drain_latest(self, current: OutputSnapshot) -> OutputSnapshot:
        """Replace one held observation with the newest pending observation."""
        while True:
            try:
                current = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return current

    def _publish(self, snapshot: OutputSnapshot) -> None:
        if self._queue.full():
            self._queue.get_nowait()
        self._queue.put_nowait(snapshot)


@dataclass(slots=True)
class _ByteSummary:
    total_bytes: int = 0
    newline_bytes: int = 0
    last_byte: int | None = None

    def feed(self, chunk: bytes | memoryview) -> None:
        if not chunk:
            return
        self.total_bytes += len(chunk)
        self.newline_bytes += (
            chunk.count(b"\n") if isinstance(chunk, bytes) else bytes(chunk).count(b"\n")
        )
        self.last_byte = chunk[-1]

    @property
    def total_lines(self) -> int:
        return self.newline_bytes + int(self.total_bytes > 0 and self.last_byte != 0x0A)


@dataclass(slots=True)
class _StreamState:
    writer: ArtifactWriter
    observed: _ByteSummary = field(default_factory=_ByteSummary)
    discarded: _ByteSummary = field(default_factory=_ByteSummary)
    tail: bytearray = field(default_factory=bytearray)
    live_tail: bytearray = field(default_factory=bytearray)
    accepted_bytes: int = 0

    def accept(self, chunk: bytes | memoryview) -> None:
        if not chunk:
            return
        self.writer.write(chunk)
        self.accepted_bytes += len(chunk)
        self._append_bounded(self.tail, chunk, STREAM_TAIL_BYTES)
        self._append_bounded(self.live_tail, chunk, MAX_LIVE_MESSAGE_BYTES)

    @staticmethod
    def _append_bounded(target: bytearray, chunk: bytes | memoryview, maximum: int) -> None:
        target.extend(chunk)
        overflow = len(target) - maximum
        if overflow > 0:
            del target[:overflow]

    @property
    def truncated(self) -> bool:
        return self.accepted_bytes > len(self.tail)

    def preview(self) -> str:
        value = bytes(self.tail)
        if self.truncated:
            value = _trim_utf8_prefix(value)
        return value.decode("utf-8", errors="replace")

    def live_text(self) -> str:
        text = _trim_utf8_prefix(bytes(self.live_tail)).decode("utf-8", errors="replace")
        encoded = text.encode("utf-8")
        if len(encoded) <= MAX_LIVE_MESSAGE_BYTES:
            return text
        return _trim_utf8_prefix(encoded[-MAX_LIVE_MESSAGE_BYTES:]).decode("utf-8")


@dataclass(frozen=True, slots=True)
class DisplayRecord:
    sequence: int
    kind: Literal["json", "image", "artifact"]
    value: JsonValue | None = None
    artifact: ArtifactRecord | None = None
    image: ImageInfo | None = None


@dataclass(slots=True)
class _StructuredTransaction:
    begin: ArtifactBeginResponse
    writer: ArtifactWriter
    image: IO[bytes] | None


@dataclass(frozen=True, slots=True)
class OutputResult:
    stdout: str
    stderr: str
    total_bytes: int
    total_lines: int
    discarded_bytes: int
    discarded_lines: int
    truncated: bool
    limit_bytes: int
    limit_exceeded: bool
    stdout_artifact: ArtifactRecord | None = None
    stderr_artifact: ArtifactRecord | None = None
    displays: tuple[DisplayRecord, ...] = ()
    explicit_artifacts: tuple[ArtifactRecord, ...] = ()

    @classmethod
    def empty(cls) -> OutputResult:
        return cls("", "", 0, 0, 0, 0, False, MAX_STREAM_BYTES, False)

    @property
    def artifacts(self) -> tuple[ArtifactRecord, ...]:
        """Return helper artifacts in sequence order, followed by retained streams."""
        streams = tuple(
            artifact
            for artifact in (self.stdout_artifact, self.stderr_artifact)
            if artifact is not None
        )
        return self.explicit_artifacts + streams


class OutputPipeline:
    """Combine both observed streams into one bounded immutable execution result."""

    def __init__(self, bundle: ArtifactBundle) -> None:
        self._bundle = bundle
        self._streams = {
            "stdout": _StreamState(bundle.open_artifact("stdout", "application/octet-stream")),
            "stderr": _StreamState(bundle.open_artifact("stderr", "application/octet-stream")),
        }
        self._accepted_bytes = 0
        self._limit_exceeded = False
        self._failure: ArtifactStoreError | None = None
        self._settled = False
        self._revision = 0
        self._observer: OutputObserver | None = None
        self.limit_event = asyncio.Event()
        self.failure_event = asyncio.Event()
        self._displays: list[DisplayRecord] = []
        self._explicit_records: list[tuple[int, ArtifactRecord]] = []
        self._transaction: _StructuredTransaction | None = None
        self.limit_time: float | None = None
        self.failure_time: float | None = None

    def attach_observer(self, observer: OutputObserver | None = None) -> OutputObserver:
        if self._observer is not None:
            raise RuntimeError("output observer is already attached")
        attached = observer if observer is not None else OutputObserver()
        self._observer = attached
        return attached

    @property
    def failure(self) -> ArtifactStoreError | None:
        return self._failure

    @property
    def limit_exceeded(self) -> bool:
        return self._limit_exceeded

    def feed(self, channel: StreamChannel, chunk: bytes) -> None:
        if not chunk:
            return
        stream = self._streams[channel]
        stream.observed.feed(chunk)
        if self._failure is not None:
            return
        if self._limit_exceeded:
            stream.discarded.feed(chunk)
            return

        remaining = MAX_STREAM_BYTES - self._accepted_bytes
        accepted = memoryview(chunk)[:remaining]
        discarded = memoryview(chunk)[remaining:]
        try:
            stream.accept(accepted)
        except ArtifactStoreError as error:
            self._failure = error
            self.failure_time = time.monotonic()
            self.failure_event.set()
            return
        self._accepted_bytes += len(accepted)
        if accepted:
            self._publish(channel, stream.live_text())
        if discarded:
            self._limit_exceeded = True
            self.limit_time = time.monotonic()
            stream.discarded.feed(discarded)
            self.limit_event.set()

    def accept_response(self, response: Response) -> None:
        """Persist one already protocol-validated structured output event."""
        try:
            if isinstance(response, DisplayJsonResponse):
                self._displays.append(DisplayRecord(response.sequence, "json", response.value))
                size = len(
                    json.dumps(
                        response.value,
                        ensure_ascii=False,
                        allow_nan=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                )
                self._publish("display", f"{size} bytes")
            elif isinstance(response, ArtifactBeginResponse):
                validation = (
                    tempfile.SpooledTemporaryFile(max_size=8_388_608)
                    if response.kind == "image" or response.declared_mime_type in SAFE_MIME_TYPES
                    else None
                )
                writer = self._bundle.open_artifact(
                    response.name,
                    response.declared_mime_type,
                    safe_mime_type=(
                        response.declared_mime_type
                        if response.kind == "image"
                        else "application/octet-stream"
                    ),
                )
                self._transaction = _StructuredTransaction(response, writer, validation)
            elif isinstance(response, ArtifactChunkResponse):
                transaction = self._require_transaction(response.transaction_id)
                transaction.writer.write(response.data)
                if transaction.image is not None:
                    transaction.image.write(response.data)
            elif isinstance(response, ArtifactEndResponse):
                transaction = self._require_transaction(response.transaction_id)
                image_info = None
                if transaction.image is not None:
                    transaction.image.flush()
                    try:
                        if transaction.image.tell() == 0:
                            validated = validate_safe_artifact(
                                b"", transaction.begin.declared_mime_type
                            )
                        else:
                            with mmap.mmap(
                                transaction.image.fileno(), 0, access=mmap.ACCESS_READ
                            ) as mapped:
                                validated = validate_safe_artifact(
                                    mapped, transaction.begin.declared_mime_type
                                )
                    except StructuredOutputError:
                        if transaction.begin.kind == "image":
                            raise
                    else:
                        if transaction.begin.kind == "image":
                            if validated is None:
                                raise StructuredOutputError("image validation returned no metadata")
                            image_info = validated
                        else:
                            transaction.writer._set_safe_mime_type(
                                transaction.begin.declared_mime_type
                            )
                    finally:
                        transaction.image.close()
                record = transaction.writer.finish()
                self._displays.append(
                    DisplayRecord(
                        transaction.begin.sequence,
                        transaction.begin.kind,
                        artifact=record,
                        image=image_info,
                    )
                )
                self._explicit_records.append((transaction.begin.sequence, record))
                self._transaction = None
                self._publish(transaction.begin.kind, f"{record.size} bytes")
        except (ArtifactStoreError, OSError, StructuredOutputError) as error:
            if self._failure is None:
                self._failure = (
                    error
                    if isinstance(error, ArtifactStoreError)
                    else ArtifactStoreError("structured output validation failed")
                )
                self.failure_time = time.monotonic()
                self.failure_event.set()

    def _publish(self, channel: OutputEventKind, text: str) -> None:
        self._revision += 1
        observer = self._observer
        if observer is not None:
            observer._publish(OutputSnapshot(self._revision, channel, text))

    def _require_transaction(self, transaction_id: str) -> _StructuredTransaction:
        transaction = self._transaction
        if transaction is None or transaction.begin.transaction_id != transaction_id:
            raise ArtifactStoreError("structured output transaction mismatch")
        return transaction

    def snapshot_result(self) -> OutputResult:
        """Return current path-free accounting without unpublished references."""
        return self._result({}, include_artifacts=False)

    async def finish(self) -> OutputResult:
        if self._settled:
            raise ArtifactStoreError("output pipeline is settled")
        if self._failure is not None:
            await self.abort()
            raise self._failure

        records: dict[str, ArtifactRecord] = {}
        try:
            if self._transaction is not None:
                if self._transaction.image is not None:
                    self._transaction.image.close()
                self._transaction.writer.discard()
                self._transaction = None
            retained = bool(self._explicit_records)
            for channel in ("stdout", "stderr"):
                stream = self._streams[channel]
                if stream.truncated:
                    records[channel] = stream.writer.finish()
                    retained = True
                else:
                    stream.writer.discard()
            if retained:
                await self._bundle.publish()
            else:
                await self._bundle.abort()
        except (ArtifactStoreError, OSError) as error:
            await self._abort_after_failure()
            if isinstance(error, OSError):
                raise ArtifactStoreError("output cleanup failed") from error
            raise
        self._settled = True
        return self._result(records)

    async def abort(self) -> None:
        if self._settled:
            return
        if self._transaction is not None and self._transaction.image is not None:
            self._transaction.image.close()
        await self._bundle.abort()
        self._transaction = None
        self._settled = True

    async def _abort_after_failure(self) -> None:
        try:
            await self._bundle.abort()
        except (ArtifactStoreError, OSError):
            pass
        self._settled = True

    def _result(
        self, records: dict[str, ArtifactRecord], *, include_artifacts: bool = True
    ) -> OutputResult:
        stdout = self._streams["stdout"]
        stderr = self._streams["stderr"]
        return OutputResult(
            stdout=stdout.preview(),
            stderr=stderr.preview(),
            total_bytes=stdout.observed.total_bytes + stderr.observed.total_bytes,
            total_lines=stdout.observed.total_lines + stderr.observed.total_lines,
            discarded_bytes=stdout.discarded.total_bytes + stderr.discarded.total_bytes,
            discarded_lines=stdout.discarded.total_lines + stderr.discarded.total_lines,
            truncated=stdout.truncated or stderr.truncated,
            limit_bytes=MAX_STREAM_BYTES,
            limit_exceeded=self._limit_exceeded,
            stdout_artifact=records.get("stdout"),
            stderr_artifact=records.get("stderr"),
            displays=tuple(
                sorted(
                    (
                        display
                        for display in self._displays
                        if include_artifacts or display.kind == "json"
                    ),
                    key=lambda item: item.sequence,
                )
            ),
            explicit_artifacts=(
                tuple(
                    record for _, record in sorted(self._explicit_records, key=lambda item: item[0])
                )
                if include_artifacts
                else ()
            ),
        )


def _trim_utf8_prefix(value: bytes) -> bytes:
    while value and value[0] & 0xC0 == 0x80:
        value = value[1:]
    return value
