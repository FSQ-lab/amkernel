#!/usr/bin/env python3
"""Fail closed unless pinned Appium skill sources and copies match the manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = SKILL_ROOT / "references" / "official-skills.json"
OFFICIAL_STATE = Path(".agents") / "amkernel-official.json"
MAIN_METADATA = Path(".agents") / "skills" / "amkernel" / ".amkernel-metadata.json"


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _tree_entries(root: Path) -> tuple[set[str], set[str], set[str]]:
    files: set[str] = set()
    symlinks: set[str] = set()
    invalid: set[str] = set()
    if not root.is_dir():
        return files, symlinks, invalid
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        name = relative.as_posix()
        if ".git" in relative.parts:
            invalid.add(name)
            continue
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            symlinks.add(name)
        elif stat.S_ISREG(mode):
            files.add(name)
        elif not stat.S_ISDIR(mode):
            invalid.add(name)
    return files, symlinks, invalid


def _verify_tree(root: Path, expected: dict[str, str], label: str) -> list[str]:
    errors: list[str] = []
    if not root.is_dir() or root.is_symlink():
        return [f"{label}: missing or linked directory: {root}"]

    actual, symlinks, invalid = _tree_entries(root)
    for relative in sorted(symlinks):
        errors.append(f"{label}: symbolic links are forbidden: {relative}")
    for relative in sorted(invalid):
        errors.append(f"{label}: non-regular entries are forbidden: {relative}")
    expected_paths = set(expected)
    for relative in sorted(expected_paths - actual):
        errors.append(f"{label}: missing file: {relative}")
    for relative in sorted(actual - expected_paths):
        errors.append(f"{label}: unexpected file: {relative}")
    for relative in sorted(actual & expected_paths):
        actual_digest = _digest(root / relative)
        if actual_digest != expected[relative]:
            errors.append(
                f"{label}: sha256 mismatch: {relative}: "
                f"expected {expected[relative]}, got {actual_digest}"
            )
    return errors


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _file_map(value: Any, label: str) -> dict[str, str]:
    mapping = _mapping(value, label)
    result: dict[str, str] = {}
    for path, digest in mapping.items():
        if not isinstance(path, str) or not isinstance(digest, str):
            raise ValueError(f"{label} keys and values must be strings")
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise ValueError(f"{label} contains unsafe path: {path!r}")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError(f"{label} contains invalid sha256 for {path!r}")
        result[path] = digest
    return result


def _location(value: Any, label: str) -> Path:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} contains unsafe path: {value!r}")
    return path


def _validated_root(
    project_root: Path, location: Path, label: str
) -> tuple[Path | None, list[str]]:
    current = project_root
    try:
        project_mode = project_root.lstat().st_mode
    except OSError as error:
        return None, [f"{label}: inaccessible project root: {error}"]
    if not stat.S_ISDIR(project_mode):
        return None, [f"{label}: project root is not a real directory: {project_root}"]

    for component in location.parts:
        current = current / component
        try:
            mode = current.lstat().st_mode
        except OSError as error:
            return None, [f"{label}: inaccessible location component {current}: {error}"]
        if stat.S_ISLNK(mode):
            return None, [f"{label}: linked location component is forbidden: {current}"]
        if not stat.S_ISDIR(mode):
            return None, [f"{label}: location component is not a directory: {current}"]

    resolved_project = project_root.resolve(strict=True)
    resolved_current = current.resolve(strict=True)
    try:
        resolved_current.relative_to(resolved_project)
    except ValueError:
        return None, [f"{label}: location escapes project root: {current}"]
    return current, []


def _load_receipt(project_root: Path) -> tuple[dict[str, Any] | None, list[str]]:
    current = project_root
    for component in OFFICIAL_STATE.parent.parts:
        current = current / component
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            return None, [f"official source receipt: missing: {current}"]
        except OSError as error:
            return None, [f"official source receipt: inaccessible: {current}: {error}"]
        if stat.S_ISLNK(mode):
            return None, [
                f"official source receipt: linked location component is forbidden: {current}"
            ]
        if not stat.S_ISDIR(mode):
            return None, [
                f"official source receipt: location component is not a directory: {current}"
            ]
    path = current / OFFICIAL_STATE.name
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return None, [f"official source receipt: missing: {path}"]
    except OSError as error:
        return None, [f"official source receipt: inaccessible: {error}"]
    if stat.S_ISLNK(mode):
        return None, [f"official source receipt: linked file is forbidden: {path}"]
    if not stat.S_ISREG(mode):
        return None, [f"official source receipt: not a regular file: {path}"]
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        return _mapping(document, "official source receipt"), []
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        return None, [f"official source receipt: invalid: {error}"]


def _load_main_metadata(project_root: Path) -> tuple[str | None, list[str]]:
    root, errors = _validated_root(
        project_root, MAIN_METADATA.parent, "main Skill metadata"
    )
    if root is None:
        return None, errors
    path = root / MAIN_METADATA.name
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return None, [f"main Skill metadata: missing: {path}"]
    except OSError as error:
        return None, [f"main Skill metadata: inaccessible: {error}"]
    if stat.S_ISLNK(mode):
        return None, [f"main Skill metadata: linked file is forbidden: {path}"]
    if not stat.S_ISREG(mode):
        return None, [f"main Skill metadata: not a regular file: {path}"]
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        value = _mapping(document, "main Skill metadata")
        runtime_version = value.get("runtimeVersion")
        if not isinstance(runtime_version, str) or not runtime_version.strip():
            raise ValueError("runtimeVersion must be a non-empty string")
        _file_map(value.get("files"), "main Skill metadata files")
        return runtime_version, []
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        return None, [f"main Skill metadata: invalid: {error}"]


def _verify_receipt(
    receipt: dict[str, Any],
    repository: str,
    commit: str,
    source_location: Path,
    source_files: dict[str, str],
    archive_path: str,
    archive_digest: str,
    installed: dict[str, tuple[Path, dict[str, str]]],
    runtime_version: str,
) -> list[str]:
    errors: list[str] = []
    if receipt.get("schemaVersion") != 1:
        errors.append("official source receipt: schemaVersion must be 1")
    receipt_version = receipt.get("runtimeVersion")
    if not isinstance(receipt_version, str):
        errors.append("official source receipt: runtimeVersion must be a string")
    elif receipt_version != runtime_version:
        errors.append(
            "official source receipt: runtimeVersion mismatch: "
            f"expected {runtime_version}, got {receipt_version}"
        )
    if receipt.get("repository") != repository:
        errors.append("official source receipt: repository mismatch")
    if receipt.get("commit") != commit:
        errors.append("official source receipt: commit mismatch")
    archive = receipt.get("archive")
    if not isinstance(archive, dict):
        errors.append("official source receipt: archive must be an object")
    else:
        if archive.get("path") != archive_path:
            errors.append("official source receipt: archive path mismatch")
        if archive.get("sha256") != archive_digest:
            errors.append("official source receipt: archive sha256 mismatch")
    receipt_source = receipt.get("source")
    if not isinstance(receipt_source, dict):
        errors.append("official source receipt: source must be an object")
    else:
        if receipt_source.get("path") != source_location.as_posix():
            errors.append("official source receipt: source path mismatch")
        if receipt_source.get("files") != source_files:
            errors.append("official source receipt: source files mismatch")
    receipt_skills = receipt.get("skills")
    if not isinstance(receipt_skills, dict):
        errors.append("official source receipt: skills must be an object")
    else:
        if set(receipt_skills) != set(installed):
            errors.append("official source receipt: skill list mismatch")
        for name, (location, files) in installed.items():
            entry = receipt_skills.get(name)
            if not isinstance(entry, dict):
                errors.append(f"official source receipt: invalid entry for {name}")
                continue
            if entry.get("path") != location.as_posix():
                errors.append(f"official source receipt: path mismatch for {name}")
            if entry.get("files") != files:
                errors.append(f"official source receipt: files mismatch for {name}")
    return errors


def verify(manifest_path: Path, project_root: Path) -> list[str]:
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = _mapping(document, "manifest")
        if manifest.get("schemaVersion") != 1:
            raise ValueError("schemaVersion must be 1")

        repository = manifest.get("repository")
        commit = manifest.get("commit")
        if not isinstance(repository, str):
            raise ValueError("repository must be a string")
        if (
            not isinstance(commit, str)
            or len(commit) != 40
            or any(char not in "0123456789abcdef" for char in commit)
        ):
            raise ValueError("commit must be a full lowercase Git object ID")

        source = _mapping(manifest.get("source"), "source")
        source_location = _location(source.get("generatedLocation"), "source.generatedLocation")
        source_files = _file_map(source.get("files"), "source.files")

        installed_document = manifest.get("installedSkills")
        if not isinstance(installed_document, list) or not installed_document:
            raise ValueError("installedSkills must be a non-empty array")
        entries: dict[str, tuple[Path, dict[str, str]]] = {}
        for index, item in enumerate(installed_document):
            skill = _mapping(item, f"installedSkills[{index}]")
            name = skill.get("name")
            if not isinstance(name, str):
                raise ValueError(f"installedSkills[{index}].name must be a string")
            if name in entries:
                raise ValueError(f"duplicate installed skill name: {name}")
            runtime_location = _location(
                skill.get("generatedLocation"),
                f"installedSkills[{index}].generatedLocation",
            )
            files = _file_map(skill.get("files"), f"installedSkills[{index}].files")
            entries[name] = (runtime_location, files)

        receipt, receipt_errors = _load_receipt(project_root)
        if receipt_errors:
            return receipt_errors
        if receipt is None:
            return ["official source receipt: missing"]
        archive = source.get("archive")
        if not isinstance(archive, dict):
            raise ValueError("source.archive must be an object for a source receipt")
        archive_location = _location(archive.get("path"), "source.archive.path").as_posix()
        archive_digest = archive.get("sha256")
        if not isinstance(archive_digest, str):
            raise ValueError("source.archive.sha256 must be a string")
        runtime_version, metadata_errors = _load_main_metadata(project_root)
        if metadata_errors or runtime_version is None:
            return metadata_errors or ["main Skill metadata: invalid runtimeVersion"]
        errors = _verify_receipt(
            receipt,
            repository,
            commit,
            source_location,
            source_files,
            archive_location,
            archive_digest,
            entries,
            runtime_version,
        )
        if errors:
            return errors
        source_root, source_errors = _validated_root(
            project_root, source_location, "official source"
        )
        errors.extend(source_errors)
        if source_root is not None:
            errors.extend(_verify_tree(source_root, source_files, "official source"))
        for name, (runtime_location, files) in entries.items():
            runtime_root, runtime_errors = _validated_root(
                project_root, runtime_location, f"runtime skill {name}"
            )
            errors.extend(runtime_errors)
            if runtime_root is not None:
                errors.extend(_verify_tree(runtime_root, files, f"runtime skill {name}"))
        return errors
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        return [f"manifest verification failed: {error}"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    arguments = parser.parse_args()

    errors = verify(arguments.manifest.resolve(), arguments.project_root.resolve())
    if errors:
        for error in errors:
            print(error)
        return 1
    print("Pinned Appium source and installed skill copies verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
