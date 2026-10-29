"""Behavior and fault-injection tests for the process Artifact Store."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import stat
import threading
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import amkernel.artifact_store as store_module
from amkernel.artifact_store import (
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    ArtifactRecord,
    ArtifactStore,
    ArtifactStoreError,
)
from amkernel.protocol import ARTIFACT_RESOURCE_PART_BYTES

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def identifier(value: int) -> str:
    return uuid.UUID(int=value, version=4).hex


async def publish(
    store: ArtifactStore,
    name: str,
    data: bytes,
    mime: str = "text/plain; charset=utf-8",
) -> ArtifactRecord:
    bundle = await store.begin_bundle()
    writer = bundle.open_artifact(name, mime)
    writer.write(data)
    record = writer.finish()
    await bundle.publish()
    return record


async def test_raw_boundary_and_manifest_parts_recover_exact_bytes(tmp_path: Path) -> None:
    store = ArtifactStore(temporary_parent=tmp_path)
    raw_data = b"r" * ARTIFACT_RESOURCE_PART_BYTES
    manifest_data = raw_data + b"m"
    try:
        bundle = await store.begin_bundle()
        raw_writer = bundle.open_artifact("raw.txt", "text/plain; charset=utf-8")
        raw_writer.write(raw_data)
        raw = raw_writer.finish()
        manifest_writer = bundle.open_artifact("large.bin", "text/html")
        manifest_writer.write(manifest_data)
        manifest = manifest_writer.finish()
        await bundle.publish()

        assert raw.representation == "raw"
        assert raw.mime_type == "text/plain; charset=utf-8"
        assert (await store.read(raw.uri)).data == raw_data
        with pytest.raises(ArtifactNotFoundError, match="resource not found"):
            await store.read(f"{raw.uri}/part/0")

        assert manifest.representation == "manifest"
        assert manifest.mime_type == "application/vnd.amkernel.artifact-manifest+json"
        response = await store.read(manifest.uri)
        document = json.loads(response.data)
        assert response.text
        assert document["name"] == "large.bin"
        assert document["declaredMimeType"] == "text/html"
        assert document["size"] == len(manifest_data)
        assert len(document["parts"]) == 2
        recovered_parts = []
        for part in document["parts"]:
            recovered_parts.append((await store.read(part["uri"])).data)
        recovered = b"".join(recovered_parts)
        assert recovered == manifest_data
    finally:
        await store.cleanup()


async def test_32_part_and_66_item_128_part_plateaus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_module, "ARTIFACT_RESOURCE_PART_BYTES", 4)
    store = ArtifactStore(temporary_parent=tmp_path)
    try:
        bundle = await store.begin_bundle()
        for index in range(64):
            writer = bundle.open_artifact(f"empty-{index}", "application/octet-stream")
            writer.finish()
        large_records = []
        for index in range(2):
            writer = bundle.open_artifact(f"large-{index}", "application/octet-stream")
            writer.write(bytes(range(128)))
            large_records.append(writer.finish())
        records = await bundle.publish()

        assert len(records) == 66
        for record in large_records:
            manifest = json.loads((await store.read(record.uri)).data)
            assert len(manifest["parts"]) == 32
            recovered_parts = []
            for part in manifest["parts"]:
                recovered_parts.append((await store.read(part["uri"])).data)
            recovered = b"".join(recovered_parts)
            assert recovered == bytes(range(128))
    finally:
        await store.cleanup()


async def test_reservation_evicts_only_whole_oldest_bundle(tmp_path: Path) -> None:
    store = ArtifactStore(
        temporary_parent=tmp_path,
        quota_bytes=30_000,
        reservation_bytes=20_000,
    )
    try:
        oldest = await publish(store, "old", b"1")
        retained = await publish(store, "retained", b"2")
        newest = await publish(store, "new", b"3")

        with pytest.raises(ArtifactNotFoundError, match="resource not found"):
            await store.read(oldest.uri)
        assert (await store.read(retained.uri)).data == b"2"
        assert (await store.read(newest.uri)).data == b"3"
    finally:
        await store.cleanup()


async def test_artifact_id_three_collision_exhaustion_never_overwrites(tmp_path: Path) -> None:
    values: Iterator[str] = iter(
        [
            identifier(1),
            identifier(2),
            identifier(3),
            identifier(4),
            identifier(3),
            identifier(3),
            identifier(3),
            identifier(5),
        ]
    )
    store = ArtifactStore(temporary_parent=tmp_path, id_factory=lambda: next(values))
    try:
        original = await publish(store, "original", b"kept")
        bundle = await store.begin_bundle()
        with pytest.raises(ArtifactStoreError, match="collision exhaustion"):
            bundle.open_artifact("collision", "application/octet-stream")
        await bundle.abort()
        assert (await store.read(original.uri)).data == b"kept"
    finally:
        await store.cleanup()


async def test_malformed_foreign_and_tampered_resources_reveal_no_path(tmp_path: Path) -> None:
    first = ArtifactStore(temporary_parent=tmp_path)
    second = ArtifactStore(temporary_parent=tmp_path)
    try:
        record = await publish(first, "evidence.bin", b"trusted", "application/x-private")
        for uri in (
            "file:///etc/passwd",
            f"{record.uri}/part/00",
            f"{record.uri}/part/{'9' * 5_000}",
            f"{record.uri}/extra",
            record.uri.replace(first.server_id, second.server_id),
        ):
            with pytest.raises(ArtifactNotFoundError) as failure:
                await first.read(uri)
            assert str(tmp_path) not in str(failure.value)

        bundle, artifact = next(iter(first._artifacts.values()))
        bundle_fd = os.open(bundle.directory, os.O_RDONLY | os.O_DIRECTORY, dir_fd=first._root_fd)
        try:
            artifact_fd = os.open(
                artifact.directory,
                os.O_RDONLY | os.O_DIRECTORY,
                dir_fd=bundle_fd,
            )
            try:
                part_name = artifact.parts[0].name
                os.chmod(part_name, 0o600, dir_fd=artifact_fd)
                descriptor = os.open(part_name, os.O_WRONLY, dir_fd=artifact_fd)
                try:
                    os.write(descriptor, b"X")
                finally:
                    os.close(descriptor)
            finally:
                os.close(artifact_fd)
        finally:
            os.close(bundle_fd)

        with pytest.raises(
            ArtifactIntegrityError, match="resource integrity failure"
        ) as integrity_failure:
            await first.read(record.uri)
        assert str(tmp_path) not in str(integrity_failure.value)
    finally:
        await first.cleanup()
        await second.cleanup()


async def test_permissions_and_substituted_root_cleanup_refusal(tmp_path: Path) -> None:
    store = ArtifactStore(temporary_parent=tmp_path)
    record = await publish(store, "mode.bin", b"data")
    root_path = tmp_path / store._root_name
    displaced = tmp_path / "displaced"
    assert stat.S_IMODE(root_path.stat().st_mode) == 0o700

    bundle, artifact = store._artifacts[record.uri.rsplit("/", 1)[-1]]
    part_path = root_path / bundle.directory / artifact.directory / artifact.parts[0].name
    assert stat.S_IMODE(part_path.stat().st_mode) == 0o400

    root_path.rename(displaced)
    root_path.mkdir(mode=0o700)
    with pytest.raises(ArtifactStoreError, match="identity mismatch"):
        await store.cleanup()
    assert root_path.exists()
    assert displaced.exists()

    root_path.rmdir()
    displaced.rename(root_path)
    store._closed = False
    await store.cleanup()
    assert not root_path.exists()


async def test_substituted_bundle_entry_is_not_followed(tmp_path: Path) -> None:
    store = ArtifactStore(temporary_parent=tmp_path)
    record = await publish(store, "safe.bin", b"safe")
    root_path = tmp_path / store._root_name
    bundle, _artifact = store._artifacts[record.uri.rsplit("/", 1)[-1]]
    bundle_path = root_path / bundle.directory
    displaced = root_path / "displaced-bundle"
    external = tmp_path / "external"
    external.mkdir()
    sentinel = external / "sentinel"
    sentinel.write_bytes(b"untouched")

    bundle_path.rename(displaced)
    bundle_path.symlink_to(external, target_is_directory=True)
    with pytest.raises(ArtifactStoreError, match="unexpected entry"):
        await store.cleanup()

    assert sentinel.read_bytes() == b"untouched"
    bundle_path.unlink()
    displaced.rename(bundle_path)
    store._closed = False
    await store.cleanup()
    assert sentinel.read_bytes() == b"untouched"


async def test_active_bundles_reserve_artifact_ids_store_wide(tmp_path: Path) -> None:
    shared = identifier(3)
    values: Iterator[str] = iter(
        [
            identifier(1),
            identifier(2),
            shared,
            identifier(4),
            shared,
            shared,
            shared,
            identifier(5),
        ]
    )
    store = ArtifactStore(temporary_parent=tmp_path, id_factory=lambda: next(values))
    first = await store.begin_bundle()
    writer = first.open_artifact("first", "application/octet-stream")
    writer.write(b"first")
    first_record = writer.finish()
    second = await store.begin_bundle()
    try:
        with pytest.raises(ArtifactStoreError, match="collision exhaustion"):
            second.open_artifact("second", "application/octet-stream")
        await first.publish()
        await second.abort()
        assert (await store.read(first_record.uri)).data == b"first"
    finally:
        await store.cleanup()


async def test_cancelled_read_keeps_lease_and_admission_until_worker_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ArtifactStore(temporary_parent=tmp_path)
    record = await publish(store, "slow", b"slow")
    started = threading.Event()
    release = threading.Event()
    original = store._load_file

    def slow_load(*args: Any) -> bytes:
        started.set()
        release.wait(timeout=5)
        return original(*args)

    monkeypatch.setattr(store, "_load_file", slow_load)
    read_task = asyncio.create_task(store.read(record.uri))
    assert await asyncio.to_thread(started.wait, 2)
    read_task.cancel()
    await asyncio.sleep(0)
    assert not read_task.done()

    admission = asyncio.create_task(store.begin_bundle())
    await asyncio.sleep(0)
    assert not admission.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await read_task
    bundle = await admission
    await bundle.abort()
    await store.cleanup()


async def test_same_layout_bundle_substitution_is_rejected(tmp_path: Path) -> None:
    store = ArtifactStore(temporary_parent=tmp_path)
    record = await publish(store, "safe.bin", b"safe")
    root = tmp_path / store._root_name
    bundle, _artifact = store._artifacts[record.uri.rsplit("/", 1)[-1]]
    real = root / bundle.directory
    displaced = tmp_path / "real-bundle"
    real.rename(displaced)
    shutil.copytree(displaced, real)

    with pytest.raises(ArtifactStoreError, match="unexpected entry"):
        await store.cleanup()

    shutil.rmtree(real)
    displaced.rename(real)
    store._closed = False
    await store.cleanup()


async def test_root_substitution_after_validation_fails_tombstone_identity_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ArtifactStore(temporary_parent=tmp_path)
    root = tmp_path / store._root_name
    displaced = tmp_path / "real-root"
    original_validate = store._validate_root_layout

    def substitute_after_validation() -> None:
        original_validate()
        root.rename(displaced)
        root.mkdir(mode=0o700)

    monkeypatch.setattr(store, "_validate_root_layout", substitute_after_validation)
    with pytest.raises(ArtifactStoreError, match="root identity mismatch"):
        await store.cleanup()

    tombstones = list(tmp_path.glob("amkernel-tombstone-*"))
    assert len(tombstones) == 1
    tombstones[0].rmdir()
    displaced.rename(root)
    store._closed = False
    monkeypatch.setattr(store, "_validate_root_layout", original_validate)
    await store.cleanup()


async def test_cleanup_failure_remains_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ArtifactStore(temporary_parent=tmp_path)
    bundle = await store.begin_bundle()
    writer = bundle.open_artifact("kept.bin", "application/octet-stream")
    writer.write(b"kept")
    writer.finish()
    await bundle.publish()
    validate = store._validate_root_layout
    attempts = 0

    def fail_once() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ArtifactStoreError("injected cleanup failure")
        validate()

    monkeypatch.setattr(store, "_validate_root_layout", fail_once)
    with pytest.raises(ArtifactStoreError, match="injected cleanup failure"):
        await store.cleanup()

    await store.cleanup()
    assert attempts == 2
    assert not list(tmp_path.glob("amkernel-*"))


async def test_partial_bundle_deletion_revokes_indexes_and_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ArtifactStore(temporary_parent=tmp_path)
    bundle = await store.begin_bundle()
    first_writer = bundle.open_artifact("first.bin", "application/octet-stream")
    first_writer.write(b"first")
    first = first_writer.finish()
    second_writer = bundle.open_artifact("second.bin", "application/octet-stream")
    second_writer.write(b"second")
    second = second_writer.finish()
    await bundle.publish()
    unlink = os.unlink
    unlink_calls = 0

    def fail_second_unlink(path: str, *, dir_fd: int | None = None) -> None:
        nonlocal unlink_calls
        unlink_calls += 1
        if unlink_calls == 2:
            raise OSError("injected partial deletion failure")
        unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(os, "unlink", fail_second_unlink)
    retained_charge = store._retained_charge
    with pytest.raises(ArtifactStoreError, match="bundle deletion failed"):
        await bundle.discard()
    assert store._retained_charge == retained_charge

    for uri in (first.uri, second.uri):
        with pytest.raises(ArtifactNotFoundError, match="resource not found"):
            await store.read(uri)

    next_bundle = await store.begin_bundle()
    assert store._retained_charge == 0
    await next_bundle.abort()
    await store.cleanup()
    assert unlink_calls >= 3
    assert not list(tmp_path.glob("amkernel-*"))


async def test_partial_staged_abort_retries_monotonically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ArtifactStore(temporary_parent=tmp_path)
    bundle = await store.begin_bundle()
    first_writer = bundle.open_artifact("first.bin", "application/octet-stream")
    first_writer.write(b"first")
    first_writer.finish()
    second_writer = bundle.open_artifact("second.bin", "application/octet-stream")
    second_writer.write(b"second")
    second_writer.finish()
    unlink = os.unlink
    unlink_calls = 0

    def fail_second_unlink(path: str, *, dir_fd: int | None = None) -> None:
        nonlocal unlink_calls
        unlink_calls += 1
        if unlink_calls == 2:
            raise OSError("injected partial deletion failure")
        unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(os, "unlink", fail_second_unlink)
    with pytest.raises(ArtifactStoreError, match="bundle deletion failed"):
        await bundle.abort()

    assert not bundle.settled
    await bundle.abort()
    assert bundle.settled
    await store.cleanup()
    assert unlink_calls >= 3
    assert not list(tmp_path.glob("amkernel-*"))


async def test_partial_writer_discard_is_completed_by_bundle_abort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ArtifactStore(temporary_parent=tmp_path)
    bundle = await store.begin_bundle()
    writer = bundle.open_artifact("parts.bin", "application/octet-stream")
    writer.write(b"a" * (ARTIFACT_RESOURCE_PART_BYTES * 2))
    unlink = os.unlink
    unlink_calls = 0

    def fail_second_unlink(path: str, *, dir_fd: int | None = None) -> None:
        nonlocal unlink_calls
        unlink_calls += 1
        if unlink_calls == 2:
            raise OSError("injected writer cleanup failure")
        unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(os, "unlink", fail_second_unlink)
    with pytest.raises(ArtifactStoreError, match="bundle deletion failed"):
        writer.discard()

    assert not writer._finished
    await bundle.abort()
    assert bundle.settled
    await store.cleanup()
    assert unlink_calls >= 3
    assert not list(tmp_path.glob("amkernel-*"))
