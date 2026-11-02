"""Validate one hosted CI wheel and prepare immutable release metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path
from typing import Any

_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
_COMMIT = re.compile(r"[0-9a-f]{40}")

_VERSION = re.compile(r"0\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)")


class ReleaseCandidateError(RuntimeError):
    """The retained CI artifact is not an admissible release candidate."""


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReleaseCandidateError(f"cannot read valid JSON from {path}: {error}") from error
    if not isinstance(value, dict):
        raise ReleaseCandidateError(f"expected a JSON object in {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _release_section(changelog: str, version: str) -> str:
    marker = f"## [{version}]"
    starts = [
        match.start() for match in re.finditer(rf"(?m)^{re.escape(marker)}(?:\s|$)", changelog)
    ]
    if len(starts) != 1:
        raise ReleaseCandidateError(f"expected exactly one {marker} changelog section")
    start = starts[0]
    next_heading = re.search(r"(?m)^## \[", changelog[start + len(marker) :])
    end = start + len(marker) + next_heading.start() if next_heading is not None else len(changelog)
    section = changelog[start:end].strip()
    if not re.match(
        rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}$", section.splitlines()[0]
    ):
        raise ReleaseCandidateError("release changelog heading must include an ISO date")
    return section


def _wheel_metadata(wheel: Path) -> tuple[str, str]:
    try:
        with zipfile.ZipFile(wheel) as archive:
            metadata_names = [
                name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
            ]
            if len(metadata_names) != 1:
                raise ReleaseCandidateError(
                    f"expected one wheel METADATA file, found {len(metadata_names)}"
                )
            metadata = BytesParser().parsebytes(archive.read(metadata_names[0]))
    except (OSError, zipfile.BadZipFile, KeyError) as error:
        raise ReleaseCandidateError(f"cannot inspect wheel {wheel}: {error}") from error
    return metadata.get("Name", ""), metadata.get("Version", "")


def prepare(
    root: Path,
    artifact_dir: Path,
    run_json: Path,
    commit: str,
    run_id: str,
    notes_output: Path,
    github_output: Path,
) -> None:
    """Validate the exact retained candidate and write release notes and outputs."""
    if not _COMMIT.fullmatch(commit):
        raise ReleaseCandidateError("commit must be a full lowercase SHA-1")
    if not run_id.isascii() or not run_id.isdecimal():
        raise ReleaseCandidateError("run ID must be decimal")

    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    version = project.get("project", {}).get("version")
    if not isinstance(version, str) or not _VERSION.fullmatch(version) or version == "0.0.0":
        raise ReleaseCandidateError("project.version must be one publishable 0.MINOR.PATCH version")

    run = _object(run_json)
    required_run = {
        "head_sha": commit,
        "head_branch": "main",
        "conclusion": "success",
        "event": "push",
        "path": ".github/workflows/ci.yml",
        "run_attempt": 1,
    }
    for field, expected in required_run.items():
        if run.get(field) != expected:
            raise ReleaseCandidateError(
                f"CI run {field} must be {expected!r}, got {run.get(field)!r}"
            )

    wheels = sorted((artifact_dir / "dist").glob("*.whl"))
    if len(wheels) != 1:
        raise ReleaseCandidateError(f"expected exactly one retained wheel, found {len(wheels)}")
    wheel = wheels[0]
    expected_filename = f"amkernel-{version}-py3-none-any.whl"
    if wheel.name != expected_filename:
        raise ReleaseCandidateError(
            f"wheel filename must be {expected_filename!r}, got {wheel.name!r}"
        )
    name, embedded_version = _wheel_metadata(wheel)
    if name != "amkernel" or embedded_version != version:
        raise ReleaseCandidateError(
            f"wheel metadata must be amkernel {version}, got {name!r} {embedded_version!r}"
        )

    evidence = _object(artifact_dir / "package-smoke.json")
    digest = _sha256(wheel)
    expected_evidence = {
        "artifact": f"dist/{wheel.name}",
        "artifactSha256": digest,
        "installedVersion": f"amkernel {version}",
        "lockSha256": _sha256(artifact_dir / "uv.lock"),
    }
    for field, expected in expected_evidence.items():
        if evidence.get(field) != expected:
            raise ReleaseCandidateError(
                f"package smoke {field} must be {expected!r}, got {evidence.get(field)!r}"
            )
    provenance: dict[str, str] = {}
    for field in ("buildPython", "host"):
        value = evidence.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ReleaseCandidateError(f"package smoke {field} must be a non-empty string")
        provenance[field] = value

    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    section = _release_section(changelog, version)
    notes = (
        f"{section}\n\n"
        "### Provenance\n\n"
        f"- Commit: `{commit}`\n"
        f"- CI run: `{run_id}`\n"
        f"- Retained artifact: `distribution-{commit}`\n"
        f"- Wheel: `{wheel.name}`\n"
        f"- SHA-256: `{digest}`\n"
        f"- Build Python: `{provenance['buildPython']}`\n"
        f"- Build host: `{provenance['host']}`\n"
        "- Verified support: CPython 3.11-3.13 on current GitHub-hosted Ubuntu "
        "and macOS runners.\n"
        "- Excluded: source distribution, CPython 3.14, Windows, and stable "
        "Appium/mobile support.\n"
    )
    notes_output.write_text(notes, encoding="utf-8")
    github_output.write_text(
        f"version={version}\ntag=v{version}\nwheel={wheel.name}\nsha256={digest}\n",
        encoding="utf-8",
    )


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--run-json", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--notes-output", type=Path, required=True)
    parser.add_argument("--github-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        prepare(
            args.root.resolve(),
            args.artifact_dir.resolve(),
            args.run_json.resolve(),
            args.commit,
            args.run_id,
            args.notes_output.resolve(),
            args.github_output.resolve(),
        )
    except (
        OSError,
        UnicodeError,
        KeyError,
        tomllib.TOMLDecodeError,
        ReleaseCandidateError,
    ) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
