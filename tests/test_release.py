"""Release candidate provenance and fail-closed validation."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prepare_release.py"
VERIFY_SCRIPT = ROOT / "scripts" / "verify_github_release.py"
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
WHEEL_NAME = f"amkernel-{VERSION}-py3-none-any.whl"
COMMIT = "a" * 40
RUN_ID = "12345"


def _candidate(tmp_path: Path) -> tuple[Path, Path]:
    artifact_dir = tmp_path / "candidate"
    artifact_dir.mkdir()
    (artifact_dir / "dist").mkdir()
    wheel = artifact_dir / "dist" / WHEEL_NAME
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            f"amkernel-{VERSION}.dist-info/METADATA",
            f"Metadata-Version: 2.4\nName: amkernel\nVersion: {VERSION}\n",
        )
    lock = artifact_dir / "uv.lock"
    lock.write_text("release lock\n", encoding="utf-8")
    evidence = {
        "artifact": f"dist/{wheel.name}",
        "artifactSha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "installedVersion": f"amkernel {VERSION}",
        "lockSha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
        "buildPython": "3.11.16",
        "host": "Linux-test",
    }
    (artifact_dir / "package-smoke.json").write_text(json.dumps(evidence), encoding="utf-8")
    run = {
        "head_sha": COMMIT,
        "head_branch": "main",
        "conclusion": "success",
        "event": "push",
        "path": ".github/workflows/ci.yml",
        "run_attempt": 1,
    }
    run_json = tmp_path / "run.json"
    run_json.write_text(json.dumps(run), encoding="utf-8")
    return artifact_dir, run_json


def _run(
    tmp_path: Path,
    artifact_dir: Path,
    run_json: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--root",
            str(ROOT),
            "--artifact-dir",
            str(artifact_dir),
            "--run-json",
            str(run_json),
            "--commit",
            COMMIT,
            "--run-id",
            RUN_ID,
            "--notes-output",
            str(tmp_path / "notes.md"),
            "--github-output",
            str(tmp_path / "outputs.txt"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_release_candidate_records_exact_tested_wheel(tmp_path: Path) -> None:
    artifact_dir, run_json = _candidate(tmp_path)

    completed = _run(tmp_path, artifact_dir, run_json)

    assert completed.returncode == 0, completed.stderr
    wheel = artifact_dir / "dist" / WHEEL_NAME
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    assert (tmp_path / "outputs.txt").read_text() == (
        f"version={VERSION}\ntag=v{VERSION}\nwheel={wheel.name}\nsha256={digest}\n"
    )
    notes = (tmp_path / "notes.md").read_text()
    assert f"## [{VERSION}]" in notes
    assert f"- Commit: `{COMMIT}`" in notes
    assert f"- SHA-256: `{digest}`" in notes
    assert "Excluded: source distribution" in notes


def test_release_candidate_rejects_non_main_or_failed_run(tmp_path: Path) -> None:
    artifact_dir, run_json = _candidate(tmp_path)
    run: dict[str, Any] = json.loads(run_json.read_text())
    run["conclusion"] = "failure"
    run_json.write_text(json.dumps(run), encoding="utf-8")

    completed = _run(tmp_path, artifact_dir, run_json)

    assert completed.returncode == 2
    assert "CI run conclusion must be 'success', got 'failure'" in completed.stderr


def test_release_candidate_rejects_artifact_substitution(tmp_path: Path) -> None:
    artifact_dir, run_json = _candidate(tmp_path)
    wheel = artifact_dir / "dist" / WHEEL_NAME
    with wheel.open("ab") as stream:
        stream.write(b"substituted")

    completed = _run(tmp_path, artifact_dir, run_json)

    assert completed.returncode == 2
    assert "package smoke artifactSha256 must be" in completed.stderr


def test_release_candidate_rejects_nonzero_major_version(tmp_path: Path) -> None:
    artifact_dir, run_json = _candidate(tmp_path)
    root = tmp_path / "root"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nversion = "1.0.0"\n')
    (root / "CHANGELOG.md").write_text("## [1.0.0] - 2026-11-02\n")
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--root",
            str(root),
            "--artifact-dir",
            str(artifact_dir),
            "--run-json",
            str(run_json),
            "--commit",
            COMMIT,
            "--run-id",
            RUN_ID,
            "--notes-output",
            str(tmp_path / "notes.md"),
            "--github-output",
            str(tmp_path / "outputs.txt"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "project.version must be one publishable 0.MINOR.PATCH version" in completed.stderr


def test_existing_release_must_match_metadata_asset_set_and_digest(tmp_path: Path) -> None:
    artifact_dir, _ = _candidate(tmp_path)
    wheel = artifact_dir / "dist" / WHEEL_NAME
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    notes = tmp_path / "notes.md"
    notes.write_text("release evidence\n", encoding="utf-8")
    release_json = tmp_path / "release.json"
    assets = [{"name": WHEEL_NAME}]
    release: dict[str, Any] = {
        "tagName": f"v{VERSION}",
        "name": f"AMKernel {VERSION}",
        "body": notes.read_text(encoding="utf-8"),
        "isDraft": False,
        "isPrerelease": False,
        "assets": assets,
    }
    release_json.write_text(json.dumps(release), encoding="utf-8")
    command = [
        sys.executable,
        str(VERIFY_SCRIPT),
        "--release-json",
        str(release_json),
        "--notes",
        str(notes),
        "--asset-dir",
        str(wheel.parent),
        "--tag",
        f"v{VERSION}",
        "--title",
        f"AMKernel {VERSION}",
        "--wheel",
        WHEEL_NAME,
        "--sha256",
        digest,
    ]

    assert subprocess.run(command, check=False).returncode == 0
    assets.append({"name": "unexpected.txt"})
    release_json.write_text(json.dumps(release), encoding="utf-8")
    rejected = subprocess.run(command, check=False, capture_output=True, text=True)

    assert rejected.returncode == 2
    assert "must have exactly one asset" in rejected.stderr


def test_release_workflow_uses_trusted_exact_artifact_path() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    pypi_job = workflow.split("\n  pypi:\n", 1)[1]

    assert "permissions: {}" in workflow
    assert "name: pypi\n      url: https://pypi.org/p/amkernel" in pypi_job
    assert "actions: read\n      id-token: write" in pypi_job
    assert "actions/checkout" not in pypi_job
    assert "name: distribution-${{ github.sha }}" in workflow
    assert "run-id: ${{ inputs.ci_run_id }}" in workflow
    assert "repos/$GITHUB_REPOSITORY/actions/runs/$CI_RUN_ID" in workflow
    assert '--jq \'.immutable\')" = "true"' in workflow
    assert "pypa/gh-action-pypi-publish@724590665d0d9cf2ef8e6f045d5355c6b8273d4f" in pypi_job
    assert "password:" not in workflow
    assert "uv build" not in workflow
    assert workflow.index("Create or verify immutable GitHub release") < workflow.index(
        "Publish exact tested wheel to PyPI"
    )
