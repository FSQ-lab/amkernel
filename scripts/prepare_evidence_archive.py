"""Build and validate one deterministic release evidence archive."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

_VERSION = re.compile(r"0\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")
_COMMIT = re.compile(r"[0-9a-f]{40}")


class EvidenceArchiveError(RuntimeError):
    """The release evidence cannot form one safe immutable archive."""


def _sha256_stream(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return _sha256_stream(stream)


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvidenceArchiveError(f"cannot read valid JSON from {path}: {error}") from error
    if not isinstance(value, dict):
        raise EvidenceArchiveError(f"expected a JSON object in {path}")
    return value


def _source_members(evidence_dir: Path) -> list[tuple[str, Path, int, str]]:
    if not evidence_dir.is_dir() or evidence_dir.is_symlink():
        raise EvidenceArchiveError(f"evidence directory is missing or linked: {evidence_dir}")
    members: list[tuple[str, Path, int, str]] = []
    for path in sorted(evidence_dir.rglob("*")):
        if path.is_symlink():
            raise EvidenceArchiveError(f"linked evidence path is forbidden: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise EvidenceArchiveError(f"non-file evidence path is forbidden: {path}")
        relative = path.relative_to(evidence_dir).as_posix()
        members.append((relative, path, path.stat().st_size, _sha256(path)))
    if not members:
        raise EvidenceArchiveError("evidence directory contains no files")
    return members


def build(
    evidence_dir: Path,
    output_dir: Path,
    version: str,
    commit: str,
) -> tuple[Path, Path]:
    """Create a deterministic archive and its external content manifest."""
    if not _VERSION.fullmatch(version):
        raise EvidenceArchiveError("version must be one publishable 0.MINOR.PATCH version")
    if not _COMMIT.fullmatch(commit):
        raise EvidenceArchiveError("commit must be a full lowercase SHA-1")
    members = _source_members(evidence_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / f"amkernel-evidence-{version}.tar.gz"
    manifest_path = output_dir / f"amkernel-evidence-{version}.manifest.json"

    with archive_path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for relative, path, size, _digest in members:
                    info = tarfile.TarInfo(f"evidence/{relative}")
                    info.size = size
                    info.mode = 0o644
                    info.mtime = 0
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    with path.open("rb") as stream:
                        archive.addfile(info, stream)

    manifest = {
        "schemaVersion": 1,
        "version": version,
        "commit": commit,
        "archive": {
            "name": archive_path.name,
            "sizeBytes": archive_path.stat().st_size,
            "sha256": _sha256(archive_path),
        },
        "members": [
            {"path": relative, "sizeBytes": size, "sha256": digest}
            for relative, _path, size, digest in members
        ],
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    validate(archive_path, manifest_path, version=version, commit=commit)
    return archive_path, manifest_path


def validate(archive_path: Path, manifest_path: Path, *, version: str, commit: str) -> None:
    """Reject archive, provenance, member, or digest drift."""
    manifest = _object(manifest_path)
    if set(manifest) != {"schemaVersion", "version", "commit", "archive", "members"}:
        raise EvidenceArchiveError("evidence manifest has unexpected fields")
    if manifest["schemaVersion"] != 1:
        raise EvidenceArchiveError("evidence manifest schemaVersion must be 1")
    if manifest["version"] != version:
        raise EvidenceArchiveError("evidence manifest version mismatch")
    if manifest["commit"] != commit:
        raise EvidenceArchiveError("evidence manifest commit mismatch")

    archive_record = manifest["archive"]
    if not isinstance(archive_record, dict) or set(archive_record) != {
        "name",
        "sizeBytes",
        "sha256",
    }:
        raise EvidenceArchiveError("evidence manifest archive record is invalid")
    expected_archive = {
        "name": archive_path.name,
        "sizeBytes": archive_path.stat().st_size,
        "sha256": _sha256(archive_path),
    }
    if archive_record != expected_archive:
        raise EvidenceArchiveError("evidence archive metadata or SHA-256 mismatch")

    records = manifest["members"]
    if not isinstance(records, list) or not records:
        raise EvidenceArchiveError("evidence manifest members must be a non-empty list")
    expected: dict[str, tuple[int, str]] = {}
    for record in records:
        if not isinstance(record, dict) or set(record) != {"path", "sizeBytes", "sha256"}:
            raise EvidenceArchiveError("evidence manifest member is invalid")
        path = record["path"]
        pure = PurePosixPath(path) if isinstance(path, str) else PurePosixPath("/")
        if not isinstance(path, str) or not path or pure.is_absolute() or ".." in pure.parts:
            raise EvidenceArchiveError("evidence manifest member path is unsafe")
        if path in expected:
            raise EvidenceArchiveError(f"duplicate evidence manifest member: {path}")
        size = record["sizeBytes"]
        digest = record["sha256"]
        if not isinstance(size, int) or size < 0 or not isinstance(digest, str):
            raise EvidenceArchiveError(f"evidence manifest member metadata is invalid: {path}")
        expected[path] = (size, digest)
    if list(expected) != sorted(expected):
        raise EvidenceArchiveError("evidence manifest members are not sorted")

    observed: set[str] = set()
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            for member in archive.getmembers():
                if not member.isfile() or not member.name.startswith("evidence/"):
                    raise EvidenceArchiveError(f"unsafe evidence archive member: {member.name}")
                relative = member.name.removeprefix("evidence/")
                if relative in observed or relative not in expected:
                    raise EvidenceArchiveError(f"unexpected evidence archive member: {relative}")
                stream = archive.extractfile(member)
                if stream is None:
                    raise EvidenceArchiveError(f"cannot read evidence archive member: {relative}")
                size, digest = expected[relative]
                if member.size != size or _sha256_stream(stream) != digest:
                    raise EvidenceArchiveError(f"evidence archive member mismatch: {relative}")
                observed.add(relative)
    except (OSError, tarfile.TarError) as error:
        raise EvidenceArchiveError(f"cannot read evidence archive: {error}") from error
    if observed != set(expected):
        missing = sorted(set(expected) - observed)
        raise EvidenceArchiveError(f"evidence archive members are missing: {missing}")


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    try:
        archive_path, manifest_path = build(
            args.evidence_dir.resolve(),
            args.output_dir.resolve(),
            args.version,
            args.commit,
        )
    except (OSError, UnicodeError, EvidenceArchiveError) as error:
        parser.error(str(error))
    print(archive_path)
    print(manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
