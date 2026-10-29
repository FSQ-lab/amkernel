from pathlib import Path

import pytest

import amkernel.output as output_module
from amkernel.artifact_store import ArtifactStore
from amkernel.output import OutputPipeline
from amkernel.protocol import DisplayJsonResponse

pytestmark = pytest.mark.anyio


async def test_combined_limit_accounting_observer_and_canonical_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(output_module, "MAX_STREAM_BYTES", 6)
    monkeypatch.setattr(output_module, "STREAM_TAIL_BYTES", 3)
    monkeypatch.setattr(output_module, "MAX_LIVE_MESSAGE_BYTES", 4)
    store = ArtifactStore(temporary_parent=tmp_path)
    try:
        pipeline = OutputPipeline(await store.begin_bundle())
        observer = pipeline.attach_observer()
        pipeline.feed("stdout", b"abcd")
        pipeline.feed("stderr", b"ef\nzz")

        snapshot = await observer.next()
        assert (snapshot.revision, snapshot.channel, snapshot.text) == (2, "stderr", "ef")
        assert pipeline.limit_event.is_set()
        result = await pipeline.finish()
        assert result.stdout == "bcd"
        assert result.stderr == "ef"
        assert result.total_bytes == 9
        assert result.total_lines == 3
        assert result.discarded_bytes == 3
        assert result.discarded_lines == 2
        assert result.truncated is True
        assert result.limit_exceeded is True
        assert result.stderr_artifact is None
        assert result.artifacts == (result.stdout_artifact,)
        assert result.stdout_artifact is not None
        assert (await store.read(result.stdout_artifact.uri)).data == b"abcd"
    finally:
        await store.cleanup()


async def test_structured_completion_publishes_generic_progress(tmp_path: Path) -> None:
    store = ArtifactStore(temporary_parent=tmp_path)
    try:
        pipeline = OutputPipeline(await store.begin_bundle())
        observer = pipeline.attach_observer()
        pipeline.accept_response(
            DisplayJsonResponse(
                correlation_id="a" * 32,
                execution_count=1,
                sequence=1,
                value={"secret-name": True},
            )
        )

        snapshot = await observer.next()
        assert snapshot.revision == 1
        assert snapshot.channel == "display"
        assert snapshot.text == "20 bytes"
        assert "secret-name" not in snapshot.text
        await pipeline.abort()
    finally:
        await store.cleanup()


async def test_live_snapshot_bounds_sanitized_utf8_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(output_module, "MAX_LIVE_MESSAGE_BYTES", 4)
    store = ArtifactStore(temporary_parent=tmp_path)
    try:
        pipeline = OutputPipeline(await store.begin_bundle())
        observer = pipeline.attach_observer()
        pipeline.feed("stdout", b"\xff" * 8)

        snapshot = await observer.next()
        assert len(snapshot.text.encode("utf-8")) <= 4
        await pipeline.abort()
    finally:
        await store.cleanup()
