#!/usr/bin/env python3
"""Fail closed unless pinned Appium skill sources and copies match the manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = SKILL_ROOT / "references" / "official-skills.json"


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
        if ".git" in relative.parts:
            continue
        name = relative.as_posix()
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


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["GIT_CONFIG_GLOBAL"] = os.devnull
    environment["GIT_CONFIG_SYSTEM"] = os.devnull
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


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


def _canonical_repository(value: str) -> str:
    return value.removesuffix(".git").rstrip("/")


def _verify_provenance(root: Path, repository: str, commit: str) -> list[str]:
    errors: list[str] = []
    head = _git(root, "rev-parse", "--verify", "HEAD")
    if head.returncode != 0:
        return [f"official source: not a Git checkout: {root}"]
    if head.stdout.strip() != commit:
        errors.append(
            f"official source: HEAD mismatch: expected {commit}, got {head.stdout.strip()}"
        )

    branch = _git(root, "symbolic-ref", "-q", "HEAD")
    if branch.returncode == 0:
        errors.append(f"official source: HEAD must be detached, got {branch.stdout.strip()}")

    origin = _git(root, "config", "--get", "remote.origin.url")
    if origin.returncode != 0:
        errors.append("official source: missing origin URL")
    elif _canonical_repository(origin.stdout.strip()) != _canonical_repository(repository):
        errors.append(
            f"official source: origin mismatch: expected {repository}, got {origin.stdout.strip()}"
        )
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
        source_root, errors = _validated_root(project_root, source_location, "official source")
        source_files = _file_map(source.get("files"), "source.files")
        if source_root is not None:
            errors.extend(_verify_provenance(source_root, repository, commit))
            errors.extend(_verify_tree(source_root, source_files, "official source"))

        installed = manifest.get("installedSkills")
        if not isinstance(installed, list) or not installed:
            raise ValueError("installedSkills must be a non-empty array")
        for index, item in enumerate(installed):
            skill = _mapping(item, f"installedSkills[{index}]")
            name = skill.get("name")
            if not isinstance(name, str):
                raise ValueError(f"installedSkills[{index}].name must be a string")
            runtime_location = _location(
                skill.get("generatedLocation"),
                f"installedSkills[{index}].generatedLocation",
            )
            agent_location = _location(
                skill.get("selectedAgentLocation"),
                f"installedSkills[{index}].selectedAgentLocation",
            )
            if skill.get("selectedAgentMode") != "copy":
                raise ValueError(f"installedSkills[{index}].selectedAgentMode must be copy")
            files = _file_map(skill.get("files"), f"installedSkills[{index}].files")
            runtime_root, runtime_errors = _validated_root(
                project_root, runtime_location, f"runtime skill {name}"
            )
            errors.extend(runtime_errors)
            if runtime_root is not None:
                errors.extend(_verify_tree(runtime_root, files, f"runtime skill {name}"))
            agent_root, agent_errors = _validated_root(
                project_root, agent_location, f"selected-agent skill {name}"
            )
            errors.extend(agent_errors)
            if agent_root is not None:
                errors.extend(_verify_tree(agent_root, files, f"selected-agent skill {name}"))
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
