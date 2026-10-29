"""Bounded process-scoped storage for immutable execution artifacts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
import tempfile
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal

from amkernel.protocol import (
    ARTIFACT_RESOURCE_PART_BYTES,
    ARTIFACT_STORE_QUOTA_BYTES,
    EXECUTION_BUNDLE_RESERVATION_BYTES,
    MAX_ARTIFACT_BYTES,
    MAX_ARTIFACT_PARTS,
    MAX_EXECUTION_PARTS,
    MAX_STORED_ITEMS,
    SAFE_MIME_TYPES,
    validate_logical_name,
    validate_mime_type,
)

_ITEM_CHARGE: Final = 4_096
_PART_CHARGE: Final = 4_096
_MANIFEST_MIME: Final = "application/vnd.amkernel.artifact-manifest+json"
_URI_PREFIX: Final = "amkernel://artifact/"
_MAX_MANIFEST_BYTES: Final = 65_536
_ID_ATTEMPTS: Final = 3


class ArtifactStoreError(RuntimeError):
    """Artifact storage, quota, integrity, or cleanup failed."""


class ArtifactNotFoundError(ArtifactStoreError):
    """A resource URI is malformed, foreign, or no longer retained."""


class ArtifactIntegrityError(ArtifactStoreError):
    """Retained bytes no longer match their immutable metadata."""


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    """Path-free immutable metadata published to callers."""

    uri: str
    name: str
    declared_mime_type: str
    mime_type: str
    representation: Literal["raw", "manifest"]
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ArtifactResource:
    """One bounded, verified resource response."""

    uri: str
    mime_type: str
    data: bytes
    text: bool


_Identity = tuple[int, int]


def _identity(observed: os.stat_result) -> _Identity:
    return observed.st_dev, observed.st_ino


@dataclass(frozen=True, slots=True)
class _Part:
    name: str
    offset: int
    size: int
    sha256: str
    identity: _Identity


@dataclass(frozen=True, slots=True)
class _Artifact:
    record: ArtifactRecord
    directory: str
    directory_identity: _Identity
    parts: tuple[_Part, ...]
    manifest_name: str | None
    manifest_size: int | None
    manifest_sha256: str | None
    manifest_identity: _Identity | None


@dataclass(slots=True)
class _Bundle:
    identifier: str
    directory: str
    artifacts: dict[str, _Artifact]
    directory_identity: _Identity
    charge: int
    leases: int = 0


@dataclass(slots=True)
class _DeletionProgress:
    tombstones: dict[str, str] = field(default_factory=dict)
    completed: set[str] = field(default_factory=set)


@dataclass(slots=True)
class _DeletingBundle:
    bundle: _Bundle
    progress: _DeletionProgress = field(default_factory=_DeletionProgress)


IdFactory = Callable[[], str]


def _new_id() -> str:
    return uuid.uuid4().hex


def _valid_id(value: str) -> bool:
    try:
        parsed = uuid.UUID(hex=value)
    except (ValueError, AttributeError):
        return False
    return parsed.version == 4 and parsed.hex == value


def _safe_mime(declared: str) -> str:
    return declared if declared in SAFE_MIME_TYPES else "application/octet-stream"


class ArtifactStore:
    """Own one private root and serve bounded immutable artifact resources."""

    def __init__(
        self,
        *,
        temporary_parent: Path | None = None,
        id_factory: IdFactory = _new_id,
        quota_bytes: int = ARTIFACT_STORE_QUOTA_BYTES,
        reservation_bytes: int = EXECUTION_BUNDLE_RESERVATION_BYTES,
    ) -> None:
        if quota_bytes < reservation_bytes:
            raise ValueError("artifact quota must fit one execution reservation")
        if os.name != "posix":
            raise ArtifactStoreError("Artifact Store requires POSIX descriptor operations")
        self._id_factory = id_factory
        self._quota_bytes = quota_bytes
        self._reservation_bytes = reservation_bytes
        self._parent = Path(temporary_parent or tempfile.gettempdir())
        self._parent_fd = os.open(self._parent, os.O_RDONLY | os.O_DIRECTORY)
        self._server_id, self._root_name = self._create_root()
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        self._root_fd = os.open(
            self._root_name,
            os.O_RDONLY | os.O_DIRECTORY | nofollow,
            dir_fd=self._parent_fd,
        )
        root_stat = os.fstat(self._root_fd)
        self._root_identity = _identity(root_stat)
        os.fchmod(self._root_fd, 0o700)
        self._deleting_bundles: dict[str, _DeletingBundle] = {}
        self._bundles: OrderedDict[str, _Bundle] = OrderedDict()
        self._artifacts: dict[str, tuple[_Bundle, _Artifact]] = {}
        self._reserved_artifact_ids: set[str] = set()
        self._active: set[ArtifactBundle] = set()
        self._retained_charge = 0
        self._reserved_charge = 0
        self._gate = asyncio.Lock()
        self._read_admission = asyncio.Semaphore(1)
        self._closed = False
        self._cleanup_complete = False
        self._cleanup_name = self._root_name

    @property
    def server_id(self) -> str:
        return self._server_id

    def _create_root(self) -> tuple[str, str]:
        for _ in range(_ID_ATTEMPTS):
            identifier = self._id_factory()
            if not _valid_id(identifier):
                raise ArtifactStoreError("ID factory returned an invalid UUIDv4")
            name = f"amkernel-{identifier}"
            try:
                os.mkdir(name, mode=0o700, dir_fd=self._parent_fd)
            except FileExistsError:
                continue
            return identifier, name
        os.close(self._parent_fd)
        raise ArtifactStoreError("Artifact Store ID collision exhaustion")

    async def begin_bundle(self) -> ArtifactBundle:
        """Reserve exact call capacity and return one unpublished bundle."""
        async with self._read_admission:
            async with self._gate:
                self._require_open()
                self._retry_deleting_bundles()
                while (
                    self._retained_charge + self._reserved_charge + self._reservation_bytes
                    > self._quota_bytes
                ):
                    if not self._evict_oldest_unleased():
                        raise ArtifactStoreError("Artifact Store quota is unavailable")
                identifier, stage_name, stage_identity = self._create_bundle_directory()
                bundle = ArtifactBundle(self, identifier, stage_name, stage_identity)
                self._active.add(bundle)
                self._reserved_charge += self._reservation_bytes
                return bundle

    def _create_bundle_directory(self) -> tuple[str, str, _Identity]:
        for _ in range(_ID_ATTEMPTS):
            identifier = self._id_factory()
            if not _valid_id(identifier):
                raise ArtifactStoreError("ID factory returned an invalid UUIDv4")
            name = f"stage-{identifier}"
            try:
                os.mkdir(name, mode=0o700, dir_fd=self._root_fd)
            except FileExistsError:
                continue
            os.chmod(name, 0o700, dir_fd=self._root_fd, follow_symlinks=False)
            observed = os.stat(name, dir_fd=self._root_fd, follow_symlinks=False)
            return identifier, name, _identity(observed)
        raise ArtifactStoreError("bundle ID collision exhaustion")

    async def read(self, uri: str) -> ArtifactResource:
        """Atomically lease, load, and reverify one retained resource."""
        async with self._read_admission:
            async with self._gate:
                self._require_open()
                artifact_id, part_index = self._parse_uri(uri)
                indexed = self._artifacts.get(artifact_id)
                if indexed is None:
                    raise ArtifactNotFoundError("resource not found")
                bundle, artifact = indexed
                if part_index is None:
                    if artifact.record.representation == "manifest":
                        file_name = artifact.manifest_name
                        expected_size = artifact.manifest_size
                        expected_hash = artifact.manifest_sha256
                        expected_identity = artifact.manifest_identity
                        mime_type = _MANIFEST_MIME
                        text = True
                    else:
                        part = artifact.parts[0]
                        file_name = part.name
                        expected_size = part.size
                        expected_hash = part.sha256
                        expected_identity = part.identity
                        mime_type = artifact.record.mime_type
                        text = False
                else:
                    if artifact.record.representation != "manifest":
                        raise ArtifactNotFoundError("resource not found")
                    if part_index < 0 or part_index >= len(artifact.parts):
                        raise ArtifactNotFoundError("resource not found")
                    part = artifact.parts[part_index]
                    file_name = part.name
                    expected_size = part.size
                    expected_hash = part.sha256
                    expected_identity = part.identity
                    mime_type = "application/octet-stream"
                    text = False
                if file_name is None or expected_identity is None:
                    raise ArtifactIntegrityError("resource integrity failure")
                bundle.leases += 1
            load_task = asyncio.create_task(
                asyncio.to_thread(
                    self._load_file,
                    bundle.directory,
                    bundle.directory_identity,
                    artifact.directory,
                    artifact.directory_identity,
                    file_name,
                    expected_identity,
                )
            )
            try:
                try:
                    data = await asyncio.shield(load_task)
                except asyncio.CancelledError:
                    try:
                        await load_task
                    except Exception:
                        pass
                    raise
                if len(data) > max(ARTIFACT_RESOURCE_PART_BYTES, _MAX_MANIFEST_BYTES):
                    raise ArtifactIntegrityError("resource integrity failure")
                if expected_size is not None and len(data) != expected_size:
                    raise ArtifactIntegrityError("resource integrity failure")
                if expected_hash is not None and hashlib.sha256(data).hexdigest() != expected_hash:
                    raise ArtifactIntegrityError("resource integrity failure")
                if text:
                    try:
                        data.decode("utf-8", errors="strict")
                    except UnicodeDecodeError as error:
                        raise ArtifactIntegrityError("resource integrity failure") from error
                return ArtifactResource(uri, mime_type, data, text)
            finally:
                async with self._gate:
                    bundle.leases -= 1

    def _parse_uri(self, uri: str) -> tuple[str, int | None]:
        prefix = f"{_URI_PREFIX}{self._server_id}/"
        if not uri.startswith(prefix):
            raise ArtifactNotFoundError("resource not found")
        suffix = uri[len(prefix) :]
        fields = suffix.split("/")
        if not fields or not _valid_id(fields[0]):
            raise ArtifactNotFoundError("resource not found")
        if len(fields) == 1:
            return fields[0], None
        if len(fields) == 3 and fields[1] == "part" and fields[2].isascii() and fields[2].isdigit():
            if len(fields[2]) > 2:
                raise ArtifactNotFoundError("resource not found")
            if fields[2] != "0" and fields[2].startswith("0"):
                raise ArtifactNotFoundError("resource not found")
            return fields[0], int(fields[2])
        raise ArtifactNotFoundError("resource not found")

    def _load_file(
        self,
        bundle_name: str,
        bundle_identity: _Identity,
        artifact_name: str,
        artifact_identity: _Identity,
        file_name: str,
        file_identity: _Identity,
    ) -> bytes:
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        bundle_fd = os.open(
            bundle_name,
            os.O_RDONLY | os.O_DIRECTORY | nofollow,
            dir_fd=self._root_fd,
        )
        try:
            if _identity(os.fstat(bundle_fd)) != bundle_identity:
                raise ArtifactIntegrityError("resource integrity failure")
            artifact_fd = os.open(
                artifact_name,
                os.O_RDONLY | os.O_DIRECTORY | nofollow,
                dir_fd=bundle_fd,
            )
            try:
                if _identity(os.fstat(artifact_fd)) != artifact_identity:
                    raise ArtifactIntegrityError("resource integrity failure")
                descriptor = os.open(file_name, os.O_RDONLY | nofollow, dir_fd=artifact_fd)
                try:
                    observed = os.fstat(descriptor)
                    if not stat.S_ISREG(observed.st_mode) or _identity(observed) != file_identity:
                        raise ArtifactIntegrityError("resource integrity failure")
                    chunks: list[bytes] = []
                    remaining = max(ARTIFACT_RESOURCE_PART_BYTES, _MAX_MANIFEST_BYTES) + 1
                    while remaining:
                        chunk = os.read(descriptor, min(65_536, remaining))
                        if not chunk:
                            break
                        chunks.append(chunk)
                        remaining -= len(chunk)
                    return b"".join(chunks)
                finally:
                    os.close(descriptor)
            finally:
                os.close(artifact_fd)
        except (FileNotFoundError, NotADirectoryError, OSError) as error:
            raise ArtifactIntegrityError("resource integrity failure") from error
        finally:
            os.close(bundle_fd)

    async def cleanup(self) -> None:
        """Identity-check, tombstone, and descriptor-relatively remove the owned root."""
        async with self._read_admission:
            async with self._gate:
                if self._cleanup_complete:
                    return
                self._closed = True
                try:
                    for bundle in tuple(self._active):
                        bundle._abort_locked()
                except OSError as error:
                    raise ArtifactStoreError("Artifact Store cleanup left residue") from error
                try:
                    observed = os.stat(
                        self._cleanup_name,
                        dir_fd=self._parent_fd,
                        follow_symlinks=False,
                    )
                except OSError as error:
                    raise ArtifactStoreError("Artifact Store root identity unavailable") from error
                if not stat.S_ISDIR(observed.st_mode) or _identity(observed) != self._root_identity:
                    raise ArtifactStoreError("Artifact Store root identity mismatch")
                try:
                    self._validate_root_layout()
                except OSError as error:
                    raise ArtifactStoreError(
                        "Artifact Store cleanup found an unexpected entry"
                    ) from error
                if self._cleanup_name == self._root_name:
                    self._cleanup_name = self._rename_to_tombstone()
                try:
                    for published_bundle in tuple(self._bundles.values()):
                        self._revoke_bundle(published_bundle)
                    self._retry_deleting_bundles()
                    if os.listdir(self._root_fd):
                        raise ArtifactStoreError("Artifact Store cleanup left residue")
                    os.rmdir(self._cleanup_name, dir_fd=self._parent_fd)
                    try:
                        os.stat(
                            self._cleanup_name,
                            dir_fd=self._parent_fd,
                            follow_symlinks=False,
                        )
                    except FileNotFoundError:
                        pass
                    else:
                        raise ArtifactStoreError("Artifact Store cleanup left root residue")
                except OSError as error:
                    raise ArtifactStoreError("Artifact Store cleanup left residue") from error
                os.close(self._root_fd)
                os.close(self._parent_fd)
                self._cleanup_complete = True

    def _rename_to_tombstone(self) -> str:
        for _ in range(_ID_ATTEMPTS):
            identifier = self._id_factory()
            if not _valid_id(identifier):
                raise ArtifactStoreError("ID factory returned an invalid UUIDv4")
            candidate = f"amkernel-tombstone-{identifier}"
            try:
                os.stat(candidate, dir_fd=self._parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                os.rename(
                    self._root_name,
                    candidate,
                    src_dir_fd=self._parent_fd,
                    dst_dir_fd=self._parent_fd,
                )
                renamed = os.stat(candidate, dir_fd=self._parent_fd, follow_symlinks=False)
                if not stat.S_ISDIR(renamed.st_mode) or _identity(renamed) != self._root_identity:
                    raise ArtifactStoreError("Artifact Store root identity mismatch") from None
                return candidate
            except OSError as error:
                raise ArtifactStoreError("Artifact Store cleanup failed") from error
        raise ArtifactStoreError("cleanup tombstone collision exhaustion")

    def _validate_root_layout(self) -> None:
        expected = {bundle.directory for bundle in self._bundles.values()}
        for deletion in self._deleting_bundles.values():
            bundle = deletion.bundle
            expected.add(deletion.progress.tombstones.get("bundle", bundle.directory))
        if set(os.listdir(self._root_fd)) != expected:
            raise ArtifactStoreError("Artifact Store cleanup found an unexpected entry")
        for bundle in self._bundles.values():
            self._validate_bundle_layout(bundle)
        for deletion in self._deleting_bundles.values():
            bundle = deletion.bundle
            name = deletion.progress.tombstones.get("bundle", bundle.directory)
            observed = os.stat(name, dir_fd=self._root_fd, follow_symlinks=False)
            if (
                not stat.S_ISDIR(observed.st_mode)
                or _identity(observed) != bundle.directory_identity
            ):
                raise ArtifactStoreError("Artifact Store cleanup found an unexpected entry")

    def _validate_bundle_layout(self, bundle: _Bundle) -> None:
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(
                bundle.directory,
                os.O_RDONLY | os.O_DIRECTORY | nofollow,
                dir_fd=self._root_fd,
            )
        except OSError as error:
            raise ArtifactStoreError("Artifact Store cleanup found an unexpected entry") from error
        try:
            if _identity(os.fstat(descriptor)) != bundle.directory_identity:
                raise ArtifactStoreError("Artifact Store cleanup found an unexpected entry")
            expected_directories = {artifact.directory for artifact in bundle.artifacts.values()}
            if set(os.listdir(descriptor)) != expected_directories:
                raise ArtifactStoreError("Artifact Store cleanup found an unexpected entry")
            for artifact in bundle.artifacts.values():
                artifact_fd = os.open(
                    artifact.directory,
                    os.O_RDONLY | os.O_DIRECTORY | nofollow,
                    dir_fd=descriptor,
                )
                try:
                    if _identity(os.fstat(artifact_fd)) != artifact.directory_identity:
                        raise ArtifactStoreError("Artifact Store cleanup found an unexpected entry")
                    expected_identities = {part.name: part.identity for part in artifact.parts}
                    if artifact.manifest_name is not None:
                        assert artifact.manifest_identity is not None
                        expected_identities[artifact.manifest_name] = artifact.manifest_identity
                    if set(os.listdir(artifact_fd)) != set(expected_identities):
                        raise ArtifactStoreError("Artifact Store cleanup found an unexpected entry")
                    for name, expected_identity in expected_identities.items():
                        observed = os.stat(name, dir_fd=artifact_fd, follow_symlinks=False)
                        if (
                            not stat.S_ISREG(observed.st_mode)
                            or _identity(observed) != expected_identity
                        ):
                            raise ArtifactStoreError(
                                "Artifact Store cleanup found an unexpected entry"
                            )
                finally:
                    os.close(artifact_fd)
        except OSError as error:
            raise ArtifactStoreError("Artifact Store cleanup found an unexpected entry") from error
        finally:
            os.close(descriptor)

    def _evict_oldest_unleased(self) -> bool:
        for bundle in tuple(self._bundles.values()):
            if bundle.leases:
                continue
            deletion = self._revoke_bundle(bundle)
            try:
                self._remove_published_bundle(deletion)
            except OSError as error:
                raise ArtifactStoreError("Artifact Store bundle deletion failed") from error
            self._complete_deletion(bundle.identifier, deletion)
            return True
        return False

    def _retry_deleting_bundles(self) -> None:
        for identifier, deletion in tuple(self._deleting_bundles.items()):
            try:
                self._remove_published_bundle(deletion)
            except OSError as error:
                raise ArtifactStoreError("Artifact Store bundle deletion failed") from error
            self._complete_deletion(identifier, deletion)

    def _complete_deletion(self, identifier: str, deletion: _DeletingBundle) -> None:
        del self._deleting_bundles[identifier]
        self._retained_charge -= deletion.bundle.charge

    def _revoke_bundle(self, bundle: _Bundle) -> _DeletingBundle:
        deletion = _DeletingBundle(bundle)
        self._deleting_bundles[bundle.identifier] = deletion
        del self._bundles[bundle.identifier]
        for artifact_id in bundle.artifacts:
            del self._artifacts[artifact_id]
        return deletion

    def _rename_deleting_entry(
        self,
        parent_fd: int,
        name: str,
        expected_identity: _Identity,
        progress: _DeletionProgress,
        key: str,
    ) -> str:
        retained = progress.tombstones.get(key)
        if retained is not None:
            observed = os.stat(retained, dir_fd=parent_fd, follow_symlinks=False)
            if _identity(observed) != expected_identity:
                raise ArtifactStoreError("Artifact Store cleanup found a substituted entry")
            return retained
        for _ in range(_ID_ATTEMPTS):
            candidate = f"delete-{uuid.uuid4().hex}"
            try:
                os.stat(candidate, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                os.rename(name, candidate, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                progress.tombstones[key] = candidate
                observed = os.stat(candidate, dir_fd=parent_fd, follow_symlinks=False)
                if _identity(observed) != expected_identity:
                    raise ArtifactStoreError(
                        "Artifact Store cleanup found a substituted entry"
                    ) from None
                return candidate
        raise ArtifactStoreError("Artifact Store cleanup tombstone collision exhaustion")

    def _unlink_deleting_file(
        self,
        parent_fd: int,
        name: str,
        expected_identity: _Identity,
        progress: _DeletionProgress,
        key: str,
    ) -> None:
        if key in progress.completed:
            return
        current = progress.tombstones.get(key, name)
        descriptor = os.open(
            current,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
        try:
            observed = os.fstat(descriptor)
            if not stat.S_ISREG(observed.st_mode) or _identity(observed) != expected_identity:
                raise ArtifactStoreError("Artifact Store cleanup found a substituted entry")
            tombstone = self._rename_deleting_entry(
                parent_fd, name, expected_identity, progress, key
            )
            os.unlink(tombstone, dir_fd=parent_fd)
            try:
                os.stat(tombstone, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                progress.tombstones.pop(key, None)
                progress.completed.add(key)
            else:
                raise ArtifactStoreError("Artifact Store cleanup left file residue")
        finally:
            os.close(descriptor)

    def _remove_deleting_directory(
        self,
        parent_fd: int,
        name: str,
        expected_identity: _Identity,
        progress: _DeletionProgress,
        key: str,
    ) -> None:
        if key in progress.completed:
            return
        current = progress.tombstones.get(key, name)
        descriptor = os.open(
            current,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
        try:
            observed = os.fstat(descriptor)
            if not stat.S_ISDIR(observed.st_mode) or _identity(observed) != expected_identity:
                raise ArtifactStoreError("Artifact Store cleanup found a substituted entry")
            if os.listdir(descriptor):
                raise ArtifactStoreError("Artifact Store cleanup left directory residue")
            tombstone = self._rename_deleting_entry(
                parent_fd, name, expected_identity, progress, key
            )
            os.rmdir(tombstone, dir_fd=parent_fd)
            try:
                os.stat(tombstone, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                progress.tombstones.pop(key, None)
                progress.completed.add(key)
            else:
                raise ArtifactStoreError("Artifact Store cleanup left directory residue")
        finally:
            os.close(descriptor)

    def _rename_owned_entry(self, parent_fd: int, name: str, expected_identity: _Identity) -> str:
        for _ in range(_ID_ATTEMPTS):
            candidate = f"delete-{uuid.uuid4().hex}"
            try:
                os.stat(candidate, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                os.rename(name, candidate, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                observed = os.stat(candidate, dir_fd=parent_fd, follow_symlinks=False)
                if _identity(observed) != expected_identity:
                    raise ArtifactStoreError(
                        "Artifact Store cleanup found a substituted entry"
                    ) from None
                return candidate
        raise ArtifactStoreError("Artifact Store cleanup tombstone collision exhaustion")

    def _unlink_owned_file(self, parent_fd: int, name: str, expected_identity: _Identity) -> None:
        descriptor = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
        try:
            observed = os.fstat(descriptor)
            if not stat.S_ISREG(observed.st_mode) or _identity(observed) != expected_identity:
                raise ArtifactStoreError("Artifact Store cleanup found a substituted entry")
            tombstone = self._rename_owned_entry(parent_fd, name, expected_identity)
            os.unlink(tombstone, dir_fd=parent_fd)
            try:
                os.stat(tombstone, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise ArtifactStoreError("Artifact Store cleanup left file residue")
        finally:
            os.close(descriptor)

    def _remove_owned_directory(
        self,
        parent_fd: int,
        name: str,
        expected_identity: _Identity,
        descriptor: int,
    ) -> None:
        observed = os.fstat(descriptor)
        if not stat.S_ISDIR(observed.st_mode) or _identity(observed) != expected_identity:
            raise ArtifactStoreError("Artifact Store cleanup found a substituted entry")
        tombstone = self._rename_owned_entry(parent_fd, name, expected_identity)
        os.rmdir(tombstone, dir_fd=parent_fd)
        try:
            os.stat(tombstone, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise ArtifactStoreError("Artifact Store cleanup left directory residue")

    def _remove_published_bundle(self, deletion: _DeletingBundle) -> None:
        bundle = deletion.bundle
        progress = deletion.progress
        if "bundle" in progress.completed:
            return
        if "bundle" in progress.tombstones:
            self._remove_deleting_directory(
                self._root_fd,
                bundle.directory,
                bundle.directory_identity,
                progress,
                "bundle",
            )
            return
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        bundle_fd = os.open(
            bundle.directory,
            os.O_RDONLY | os.O_DIRECTORY | nofollow,
            dir_fd=self._root_fd,
        )
        try:
            if _identity(os.fstat(bundle_fd)) != bundle.directory_identity:
                raise ArtifactStoreError("Artifact Store cleanup found a substituted entry")
            for artifact_id, artifact in bundle.artifacts.items():
                directory_key = f"artifact:{artifact_id}"
                if directory_key in progress.completed:
                    continue
                if directory_key not in progress.tombstones:
                    artifact_fd = os.open(
                        artifact.directory,
                        os.O_RDONLY | os.O_DIRECTORY | nofollow,
                        dir_fd=bundle_fd,
                    )
                    try:
                        if _identity(os.fstat(artifact_fd)) != artifact.directory_identity:
                            raise ArtifactStoreError(
                                "Artifact Store cleanup found a substituted entry"
                            )
                        expected_files = {part.name: part.identity for part in artifact.parts}
                        if artifact.manifest_name is not None:
                            assert artifact.manifest_identity is not None
                            expected_files[artifact.manifest_name] = artifact.manifest_identity
                        for file_name, file_identity in expected_files.items():
                            self._unlink_deleting_file(
                                artifact_fd,
                                file_name,
                                file_identity,
                                progress,
                                f"{directory_key}/file:{file_name}",
                            )
                    finally:
                        os.close(artifact_fd)
                self._remove_deleting_directory(
                    bundle_fd,
                    artifact.directory,
                    artifact.directory_identity,
                    progress,
                    directory_key,
                )
        finally:
            os.close(bundle_fd)
        self._remove_deleting_directory(
            self._root_fd,
            bundle.directory,
            bundle.directory_identity,
            progress,
            "bundle",
        )

    def _require_open(self) -> None:
        if self._closed:
            raise ArtifactStoreError("Artifact Store is closed")


class ArtifactBundle:
    """One reserved execution transaction; publish or abort exactly once."""

    def __init__(
        self,
        store: ArtifactStore,
        identifier: str,
        stage_name: str,
        stage_identity: _Identity,
    ) -> None:
        self._store = store
        self._identifier = identifier
        self._stage_name = stage_name
        self._stage_identity = stage_identity
        self._artifact_ids: set[str] = set()
        self._writers: set[ArtifactWriter] = set()
        self._artifacts: list[_Artifact] = []
        self._parts = 0
        self._charge = 0
        self._settled = False
        self._deletion_progress = _DeletionProgress()

    @property
    def settled(self) -> bool:
        return self._settled

    def open_artifact(
        self, name: str, declared_mime_type: str, *, safe_mime_type: str | None = None
    ) -> ArtifactWriter:
        """Open one incremental logical artifact with optional trusted serving MIME."""
        if self._settled:
            raise ArtifactStoreError("bundle is settled")
        if len(self._writers) + len(self._artifacts) >= MAX_STORED_ITEMS:
            raise ArtifactStoreError("execution artifact item limit exceeded")
        validate_logical_name(name)
        validate_mime_type(declared_mime_type)
        if safe_mime_type is not None:
            validate_mime_type(safe_mime_type)
        artifact_id, directory, directory_identity = self._create_artifact_directory()
        self._artifact_ids.add(artifact_id)
        writer = ArtifactWriter(
            self,
            artifact_id,
            directory,
            directory_identity,
            name,
            declared_mime_type,
            safe_mime_type,
        )
        self._writers.add(writer)
        return writer

    def _create_artifact_directory(self) -> tuple[str, str, _Identity]:
        stage_fd = os.open(
            self._stage_name,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=self._store._root_fd,
        )
        try:
            if _identity(os.fstat(stage_fd)) != self._stage_identity:
                raise ArtifactStoreError("bundle staging identity mismatch")
            for _ in range(_ID_ATTEMPTS):
                identifier = self._store._id_factory()
                if not _valid_id(identifier):
                    raise ArtifactStoreError("ID factory returned an invalid UUIDv4")
                name = f"artifact-{identifier}"
                if (
                    identifier in self._store._artifacts
                    or identifier in self._store._reserved_artifact_ids
                ):
                    continue
                try:
                    os.mkdir(name, mode=0o700, dir_fd=stage_fd)
                except FileExistsError:
                    continue
                os.chmod(name, 0o700, dir_fd=stage_fd, follow_symlinks=False)
                observed = os.stat(name, dir_fd=stage_fd, follow_symlinks=False)
                self._store._reserved_artifact_ids.add(identifier)
                return identifier, name, _identity(observed)
        finally:
            os.close(stage_fd)
        raise ArtifactStoreError("artifact ID collision exhaustion")

    async def publish(self) -> tuple[ArtifactRecord, ...]:
        """Atomically make every finished item visible."""
        async with self._store._gate:
            if self._settled or self not in self._store._active:
                raise ArtifactStoreError("bundle is settled")
            if self._writers:
                raise ArtifactStoreError("bundle has unfinished artifacts")
            artifacts = {
                artifact.record.uri.rsplit("/", 1)[-1]: artifact for artifact in self._artifacts
            }
            if set(artifacts) != self._artifact_ids or any(
                identifier in self._store._artifacts for identifier in artifacts
            ):
                raise ArtifactStoreError("artifact ID was already published")
            observed_stage = os.stat(
                self._stage_name,
                dir_fd=self._store._root_fd,
                follow_symlinks=False,
            )
            if _identity(observed_stage) != self._stage_identity:
                raise ArtifactStoreError("bundle staging identity mismatch")
            published_name = f"bundle-{self._identifier}"
            try:
                os.stat(published_name, dir_fd=self._store._root_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise ArtifactStoreError("published bundle name collision")
            try:
                os.rename(
                    self._stage_name,
                    published_name,
                    src_dir_fd=self._store._root_fd,
                    dst_dir_fd=self._store._root_fd,
                )
            except OSError as error:
                self._abort_locked()
                raise ArtifactStoreError("bundle publication failed") from error
            published = os.stat(
                published_name,
                dir_fd=self._store._root_fd,
                follow_symlinks=False,
            )
            if _identity(published) != self._stage_identity:
                raise ArtifactStoreError("published bundle identity mismatch")
            bundle = _Bundle(
                self._identifier,
                published_name,
                artifacts,
                self._stage_identity,
                self._charge,
            )
            self._store._bundles[self._identifier] = bundle
            for artifact_id, artifact in artifacts.items():
                self._store._artifacts[artifact_id] = (bundle, artifact)
            self._store._reserved_artifact_ids.difference_update(self._artifact_ids)
            self._store._retained_charge += self._charge
            self._store._reserved_charge -= self._store._reservation_bytes
            self._store._active.remove(self)
            self._settled = True
            return tuple(artifact.record for artifact in self._artifacts)

    async def discard(self) -> None:
        """Remove this execution bundle whether staged or already published."""
        async with self._store._gate:
            if not self._settled:
                self._abort_locked()
                return
            deletion = self._store._deleting_bundles.get(self._identifier)
            if deletion is None:
                published = self._store._bundles.get(self._identifier)
                if published is None:
                    return
                if published.leases:
                    raise ArtifactStoreError("execution bundle is in use")
                deletion = self._store._revoke_bundle(published)
            try:
                self._store._remove_published_bundle(deletion)
            except OSError as error:
                raise ArtifactStoreError("Artifact Store bundle deletion failed") from error
            self._store._complete_deletion(self._identifier, deletion)

    async def abort(self) -> None:
        async with self._store._gate:
            try:
                self._abort_locked()
            except OSError as error:
                raise ArtifactStoreError("Artifact Store bundle deletion failed") from error

    def _abort_locked(self) -> None:
        if self._settled:
            return
        progress = self._deletion_progress
        current_stage = progress.tombstones.get("stage", self._stage_name)
        try:
            stage_fd = os.open(
                current_stage,
                os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=self._store._root_fd,
            )
        except OSError as error:
            raise ArtifactStoreError("bundle staging identity mismatch") from error
        try:
            if _identity(os.fstat(stage_fd)) != self._stage_identity:
                raise ArtifactStoreError("bundle staging identity mismatch")
            self._remove_staged_contents(stage_fd)
            self._store._remove_deleting_directory(
                self._store._root_fd,
                self._stage_name,
                self._stage_identity,
                progress,
                "stage",
            )
        finally:
            os.close(stage_fd)
        self._store._active.discard(self)
        self._store._reserved_artifact_ids.difference_update(self._artifact_ids)
        self._store._reserved_charge -= self._store._reservation_bytes
        self._settled = True

    def _remove_staged_contents(self, stage_fd: int) -> None:
        entries: list[tuple[str, _Identity, dict[str, _Identity]]] = []
        for artifact in self._artifacts:
            files = {part.name: part.identity for part in artifact.parts}
            if artifact.manifest_name is not None:
                assert artifact.manifest_identity is not None
                files[artifact.manifest_name] = artifact.manifest_identity
            entries.append((artifact.directory, artifact.directory_identity, files))
        for writer in self._writers:
            entries.append(
                (
                    writer._directory,
                    writer._directory_identity,
                    {part.name: part.identity for part in writer._parts},
                )
            )
        progress = self._deletion_progress
        expected_directories = {
            progress.tombstones.get(key, directory)
            for directory, _, _ in entries
            if (key := f"artifact:{directory}") not in progress.completed
        }
        if set(os.listdir(stage_fd)) != expected_directories:
            raise ArtifactStoreError("Artifact Store cleanup found an unexpected entry")
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        for directory, directory_identity, files in entries:
            directory_key = f"artifact:{directory}"
            if directory_key in progress.completed:
                continue
            current_directory = progress.tombstones.get(directory_key, directory)
            artifact_fd = os.open(
                current_directory,
                os.O_RDONLY | os.O_DIRECTORY | nofollow,
                dir_fd=stage_fd,
            )
            try:
                if _identity(os.fstat(artifact_fd)) != directory_identity:
                    raise ArtifactStoreError("Artifact Store cleanup found an unexpected entry")
                expected_files = {
                    progress.tombstones.get(key, name)
                    for name in files
                    if (key := f"{directory_key}/file:{name}") not in progress.completed
                }
                if set(os.listdir(artifact_fd)) != expected_files:
                    raise ArtifactStoreError("Artifact Store cleanup found an unexpected entry")
                for name, file_identity in files.items():
                    self._store._unlink_deleting_file(
                        artifact_fd,
                        name,
                        file_identity,
                        progress,
                        f"{directory_key}/file:{name}",
                    )
                self._store._remove_deleting_directory(
                    stage_fd,
                    directory,
                    directory_identity,
                    progress,
                    directory_key,
                )
            finally:
                os.close(artifact_fd)

    def _discard(self, writer: ArtifactWriter) -> None:
        if writer not in self._writers or self._settled:
            raise ArtifactStoreError("artifact writer is not active")
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        progress = self._deletion_progress
        directory_key = f"artifact:{writer._directory}"
        try:
            current_stage = progress.tombstones.get("stage", self._stage_name)
            stage_fd = os.open(
                current_stage,
                os.O_RDONLY | os.O_DIRECTORY | nofollow,
                dir_fd=self._store._root_fd,
            )
            try:
                if _identity(os.fstat(stage_fd)) != self._stage_identity:
                    raise ArtifactStoreError("bundle staging identity mismatch")
                current_directory = progress.tombstones.get(directory_key, writer._directory)
                artifact_fd = os.open(
                    current_directory,
                    os.O_RDONLY | os.O_DIRECTORY | nofollow,
                    dir_fd=stage_fd,
                )
                try:
                    if _identity(os.fstat(artifact_fd)) != writer._directory_identity:
                        raise ArtifactStoreError("artifact staging identity mismatch")
                    files = {part.name: part.identity for part in writer._parts}
                    expected_files = {
                        progress.tombstones.get(key, name)
                        for name in files
                        if (key := f"{directory_key}/file:{name}") not in progress.completed
                    }
                    if set(os.listdir(artifact_fd)) != expected_files:
                        raise ArtifactStoreError("Artifact Store cleanup found an unexpected entry")
                    for name, identity in files.items():
                        self._store._unlink_deleting_file(
                            artifact_fd,
                            name,
                            identity,
                            progress,
                            f"{directory_key}/file:{name}",
                        )
                    self._store._remove_deleting_directory(
                        stage_fd,
                        writer._directory,
                        writer._directory_identity,
                        progress,
                        directory_key,
                    )
                finally:
                    os.close(artifact_fd)
            finally:
                os.close(stage_fd)
        except OSError as error:
            raise ArtifactStoreError("Artifact Store bundle deletion failed") from error
        self._writers.remove(writer)
        self._artifact_ids.remove(writer._artifact_id)
        self._store._reserved_artifact_ids.remove(writer._artifact_id)

    def _validate_finished(self, writer: ArtifactWriter, part_count: int, charge: int) -> int:
        if writer not in self._writers or self._settled:
            raise ArtifactStoreError("artifact writer is not active")
        new_parts = self._parts + part_count
        if new_parts > MAX_EXECUTION_PARTS:
            raise ArtifactStoreError("execution artifact part limit exceeded")
        if self._charge + charge > self._store._reservation_bytes:
            raise ArtifactStoreError("execution artifact reservation exceeded")
        return new_parts

    def _finished(self, writer: ArtifactWriter, artifact: _Artifact, charge: int) -> None:
        new_parts = self._validate_finished(writer, len(artifact.parts), charge)
        self._writers.remove(writer)
        self._artifacts.append(artifact)
        self._parts = new_parts
        self._charge += charge


class ArtifactWriter:
    """Incrementally hash and split one logical artifact into immutable parts."""

    def __init__(
        self,
        bundle: ArtifactBundle,
        artifact_id: str,
        directory: str,
        directory_identity: _Identity,
        name: str,
        declared_mime_type: str,
        safe_mime_type: str | None,
    ) -> None:
        self._bundle = bundle
        self._artifact_id = artifact_id
        self._directory = directory
        self._directory_identity = directory_identity
        self._name = name
        self._declared_mime_type = declared_mime_type
        self._safe_mime_type = safe_mime_type
        self._hash = hashlib.sha256()
        self._size = 0
        self._parts: list[_Part] = []
        self._buffer: bytearray | None = None
        self._buffer_size = 0
        self._finished = False

    def write(self, data: bytes | bytearray | memoryview) -> None:
        if self._finished:
            raise ArtifactStoreError("artifact writer is finished")
        view = memoryview(data)
        if self._size + len(view) > MAX_ARTIFACT_BYTES:
            raise ArtifactStoreError("artifact byte limit exceeded")
        self._hash.update(view)
        self._size += len(view)
        while view:
            if self._buffer is None:
                self._buffer = bytearray(ARTIFACT_RESOURCE_PART_BYTES)
            available = ARTIFACT_RESOURCE_PART_BYTES - self._buffer_size
            take = min(len(view), available)
            self._buffer[self._buffer_size : self._buffer_size + take] = view[:take]
            self._buffer_size += take
            view = view[take:]
            if self._buffer_size == ARTIFACT_RESOURCE_PART_BYTES:
                self._write_part()

    def discard(self) -> None:
        """Remove one unfinished logical artifact from its active bundle."""
        if self._finished:
            raise ArtifactStoreError("artifact writer is finished")
        try:
            self._bundle._discard(self)
        except OSError as error:
            raise ArtifactStoreError("artifact discard failed") from error
        self._buffer = None
        self._buffer_size = 0
        self._finished = True

    def _set_safe_mime_type(self, mime_type: str) -> None:
        """Promote serving MIME after Host content validation."""
        if self._finished:
            raise ArtifactStoreError("artifact writer is finished")
        validate_mime_type(mime_type)
        self._safe_mime_type = mime_type

    def finish(self) -> ArtifactRecord:
        if self._finished:
            raise ArtifactStoreError("artifact writer is finished")
        if self._buffer_size or not self._parts:
            self._write_part()
        if len(self._parts) > MAX_ARTIFACT_PARTS:
            raise ArtifactStoreError("artifact part limit exceeded")
        charge = self._size + _ITEM_CHARGE + len(self._parts) * _PART_CHARGE
        self._bundle._validate_finished(self, len(self._parts), charge)
        digest = self._hash.hexdigest()
        uri = f"{_URI_PREFIX}{self._bundle._store.server_id}/{self._artifact_id}"
        representation: Literal["raw", "manifest"] = (
            "raw" if self._size <= ARTIFACT_RESOURCE_PART_BYTES else "manifest"
        )
        mime_type = (
            self._safe_mime_type or _safe_mime(self._declared_mime_type)
            if representation == "raw"
            else _MANIFEST_MIME
        )
        manifest_name: str | None = None
        if representation == "manifest":
            manifest = {
                "version": 1,
                "name": self._name,
                "declaredMimeType": self._declared_mime_type,
                "size": self._size,
                "sha256": digest,
                "parts": [
                    {
                        "uri": f"{uri}/part/{index}",
                        "offset": part.offset,
                        "size": part.size,
                        "sha256": part.sha256,
                    }
                    for index, part in enumerate(self._parts)
                ],
            }
            encoded = json.dumps(
                manifest,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
            if len(encoded) >= _MAX_MANIFEST_BYTES:
                raise ArtifactStoreError("artifact manifest exceeds its bound")
            manifest_name = "manifest.json"
            manifest_size = len(encoded)
            manifest_sha256 = hashlib.sha256(encoded).hexdigest()
            manifest_identity = self._write_atomic_file(manifest_name, encoded)
        else:
            manifest_size = None
            manifest_sha256 = None
            manifest_identity = None
        record = ArtifactRecord(
            uri=uri,
            name=self._name,
            declared_mime_type=self._declared_mime_type,
            mime_type=mime_type,
            representation=representation,
            size=self._size,
            sha256=digest,
        )
        artifact = _Artifact(
            record,
            self._directory,
            self._directory_identity,
            tuple(self._parts),
            manifest_name,
            manifest_size,
            manifest_sha256,
            manifest_identity,
        )
        self._bundle._finished(self, artifact, charge)
        self._finished = True
        return record

    def _write_part(self) -> None:
        if len(self._parts) >= MAX_ARTIFACT_PARTS:
            raise ArtifactStoreError("artifact part limit exceeded")
        if self._buffer is None:
            self._buffer = bytearray(ARTIFACT_RESOURCE_PART_BYTES)
        data = memoryview(self._buffer)[: self._buffer_size]
        self._buffer_size = 0
        index = len(self._parts)
        name = f"part-{index}"
        identity = self._write_atomic_file(name, data)
        self._parts.append(
            _Part(
                name=name,
                offset=index * ARTIFACT_RESOURCE_PART_BYTES,
                size=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                identity=identity,
            )
        )

    def _write_atomic_file(
        self, final_name: str, data: bytes | bytearray | memoryview
    ) -> _Identity:
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        stage_fd = os.open(
            self._bundle._stage_name,
            os.O_RDONLY | os.O_DIRECTORY | nofollow,
            dir_fd=self._bundle._store._root_fd,
        )
        try:
            if _identity(os.fstat(stage_fd)) != self._bundle._stage_identity:
                raise ArtifactStoreError("bundle staging identity mismatch")
            artifact_fd = os.open(
                self._directory,
                os.O_RDONLY | os.O_DIRECTORY | nofollow,
                dir_fd=stage_fd,
            )
            try:
                if _identity(os.fstat(artifact_fd)) != self._directory_identity:
                    raise ArtifactStoreError("artifact staging identity mismatch")
                temporary = f"tmp-{uuid.uuid4().hex}"
                descriptor = os.open(
                    temporary,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
                    0o600,
                    dir_fd=artifact_fd,
                )
                try:
                    view = memoryview(data)
                    while view:
                        written = os.write(descriptor, view)
                        if written <= 0:
                            raise ArtifactStoreError("artifact write made no progress")
                        view = view[written:]
                    os.fsync(descriptor)
                    observed = os.fstat(descriptor)
                    if observed.st_size != len(data):
                        raise ArtifactStoreError("artifact write size mismatch")
                    os.fchmod(descriptor, 0o400)
                    file_identity = _identity(observed)
                except BaseException:
                    try:
                        os.unlink(temporary, dir_fd=artifact_fd)
                    except OSError:
                        pass
                    raise
                finally:
                    os.close(descriptor)
                try:
                    try:
                        os.stat(final_name, dir_fd=artifact_fd, follow_symlinks=False)
                    except FileNotFoundError:
                        pass
                    else:
                        raise ArtifactStoreError("artifact file already exists")
                    os.rename(
                        temporary,
                        final_name,
                        src_dir_fd=artifact_fd,
                        dst_dir_fd=artifact_fd,
                    )
                    published = os.stat(final_name, dir_fd=artifact_fd, follow_symlinks=False)
                    if _identity(published) != file_identity:
                        raise ArtifactStoreError("artifact file identity mismatch")
                    return file_identity
                except BaseException:
                    try:
                        os.unlink(temporary, dir_fd=artifact_fd)
                    except OSError:
                        pass
                    raise
            finally:
                os.close(artifact_fd)
        except OSError as error:
            raise ArtifactStoreError("artifact write failed") from error
        finally:
            os.close(stage_fd)
