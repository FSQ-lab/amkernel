"""Release candidate provenance and fail-closed validation."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prepare_release.py"
VERIFY_SCRIPT = ROOT / "scripts" / "verify_github_release.py"
EVIDENCE_SCRIPT = ROOT / "scripts" / "prepare_evidence_archive.py"
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
ARCHIVE_INDEX = ROOT / "evidence" / "archive-v0.1.2.json"
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
    source_evidence = tmp_path / "source-evidence"
    source_evidence.mkdir()
    (source_evidence / "summary.json").write_text('{"result":"pass"}\n', encoding="utf-8")
    subprocess.run(
        [
            sys.executable,
            str(EVIDENCE_SCRIPT),
            "--evidence-dir",
            str(source_evidence),
            "--output-dir",
            str(artifact_dir / "evidence-dist"),
            "--version",
            VERSION,
            "--commit",
            COMMIT,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
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
    archive = artifact_dir / "evidence-dist" / f"amkernel-evidence-{VERSION}.tar.gz"
    manifest = artifact_dir / "evidence-dist" / f"amkernel-evidence-{VERSION}.manifest.json"
    archive_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    manifest_digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert (tmp_path / "outputs.txt").read_text() == (
        f"version={VERSION}\ntag=v{VERSION}\nwheel={wheel.name}\nsha256={digest}\n"
        f"evidence_archive={archive.name}\n"
        f"evidence_archive_sha256={archive_digest}\n"
        f"evidence_manifest={manifest.name}\n"
        f"evidence_manifest_sha256={manifest_digest}\n"
    )
    notes = (tmp_path / "notes.md").read_text()
    assert f"## [{VERSION}]" in notes
    assert f"- Commit: `{COMMIT}`" in notes
    assert f"- SHA-256: `{digest}`" in notes
    assert f"- Evidence archive SHA-256: `{archive_digest}`" in notes
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


def test_evidence_archive_is_deterministic_and_safe(tmp_path: Path) -> None:
    source = tmp_path / "evidence"
    (source / "nested").mkdir(parents=True)
    (source / "nested" / "report.json").write_text('{"result":"pass"}\n')
    outputs = []
    for name in ("first", "second"):
        output = tmp_path / name
        completed = subprocess.run(
            [
                sys.executable,
                str(EVIDENCE_SCRIPT),
                "--evidence-dir",
                str(source),
                "--output-dir",
                str(output),
                "--version",
                VERSION,
                "--commit",
                COMMIT,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
        outputs.append(output)

    archive_name = f"amkernel-evidence-{VERSION}.tar.gz"
    manifest_name = f"amkernel-evidence-{VERSION}.manifest.json"
    assert (outputs[0] / archive_name).read_bytes() == (outputs[1] / archive_name).read_bytes()
    assert (outputs[0] / manifest_name).read_bytes() == (outputs[1] / manifest_name).read_bytes()
    with tarfile.open(outputs[0] / archive_name, "r:gz") as archive:
        members = archive.getmembers()
    assert [member.name for member in members] == ["evidence/nested/report.json"]
    assert members[0].isfile()
    assert members[0].mtime == 0


def test_post_release_evidence_matches_immutable_archive_index() -> None:
    provenance = json.loads(ARCHIVE_INDEX.read_text(encoding="utf-8"))
    release = provenance["release"]
    assets = provenance["assets"]
    retention = provenance["retention"]

    assert release == {
        "commit": "8438198f97e0442a3869e9f32d4213adef3dc766",
        "immutable": True,
        "publishedAt": "2026-11-04T04:12:37Z",
        "tag": "v0.1.2",
        "url": "https://github.com/FSQ-lab/amkernel/releases/tag/v0.1.2",
    }
    assert assets["archive"]["sha256"] == (
        "4e03ceb4cdc9462b8960a184725290f6a202a20389c7742af0d97d4d38384c4a"
    )
    assert assets["externalManifest"]["sha256"] == (
        "2e848e0a1541a37476248ff6080fb71ec97a3d23cb29692b6463b5ca6b162c11"
    )
    assert assets["wheel"]["sha256"] == (
        "dac88ff4b36129b9b375f1abcba43342187fc9ef3b4fc54de5b6fced604c8158"
    )

    retained = {item["path"]: item for item in retention["gitAndRelease"]}
    archived = {item["path"]: item for item in retention["releaseOnly"]}
    assert len(retained) == 71
    assert len(archived) == 132
    assert retained.keys().isdisjoint(archived)
    published_manifest = {
        "archive": {key: assets["archive"][key] for key in ("name", "sha256", "sizeBytes")},
        "commit": release["commit"],
        "members": sorted([*retained.values(), *archived.values()], key=lambda item: item["path"]),
        "schemaVersion": 1,
        "version": "0.1.2",
    }
    manifest_bytes = (json.dumps(published_manifest, indent=2, sort_keys=True) + "\n").encode()
    assert hashlib.sha256(manifest_bytes).hexdigest() == assets["externalManifest"]["sha256"]

    evidence_root = ARCHIVE_INDEX.parent
    completed = subprocess.run(
        ["git", "ls-files", "-z", "--", "evidence"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    tracked = {
        Path(path).relative_to("evidence").as_posix()
        for path in completed.stdout.split("\0")
        if path and path != ARCHIVE_INDEX.relative_to(ROOT).as_posix()
    }
    present = {relative: evidence_root / relative for relative in tracked}
    assert present.keys() == retained.keys()
    assert not (present.keys() & archived.keys())
    for relative, path in present.items():
        expected = retained[relative]
        assert path.stat().st_size == expected["sizeBytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected["sha256"]


def test_raw_evidence_paths_are_ignored_without_hiding_retained_records() -> None:
    raw_paths = (
        "evidence/mobile-appium/android/run/screenshot.png",
        "evidence/stage-4/codex/attempts/events.jsonl",
        "evidence/stage-4/process/source/run/process-evidence-linux.json",
        "evidence/appium-skill/conversation-final-20990101.json",
        "evidence/appium-skill/environment-discovery-20990101.json",
        "evidence/appium-skill/mac2-m1-visible-20990101.json",
    )
    retained_paths = (
        "evidence/archive-v0.1.2.json",
        "evidence/stage-3/index.json",
        "evidence/appium-skill/final-platform-review-20261103.json",
        "evidence/stage-4/codex/validation/report.json",
    )

    for path in raw_paths:
        completed = subprocess.run(
            ["git", "check-ignore", "--no-index", "--quiet", path],
            cwd=ROOT,
            check=False,
        )
        assert completed.returncode == 0, f"raw evidence path is not ignored: {path}"
    for path in retained_paths:
        completed = subprocess.run(
            ["git", "check-ignore", "--no-index", "--quiet", path],
            cwd=ROOT,
            check=False,
        )
        assert completed.returncode == 1, f"retained evidence path is ignored: {path}"


def test_release_candidate_rejects_evidence_substitution(tmp_path: Path) -> None:
    artifact_dir, run_json = _candidate(tmp_path)
    archive = artifact_dir / "evidence-dist" / f"amkernel-evidence-{VERSION}.tar.gz"
    with archive.open("ab") as stream:
        stream.write(b"substituted")

    completed = _run(tmp_path, artifact_dir, run_json)

    assert completed.returncode == 2
    assert "evidence archive metadata or SHA-256 mismatch" in completed.stderr


def test_existing_release_must_match_metadata_asset_set_and_digest(tmp_path: Path) -> None:
    artifact_dir, _ = _candidate(tmp_path)
    wheel = artifact_dir / "dist" / WHEEL_NAME
    archive = artifact_dir / "evidence-dist" / f"amkernel-evidence-{VERSION}.tar.gz"
    manifest = artifact_dir / "evidence-dist" / f"amkernel-evidence-{VERSION}.manifest.json"
    assets_by_name = {path.name: path for path in (wheel, archive, manifest)}
    asset_dir = tmp_path / "release-assets"
    asset_dir.mkdir()
    for path in assets_by_name.values():
        shutil.copy2(path, asset_dir / path.name)
    notes = tmp_path / "notes.md"
    notes.write_text("release evidence\n", encoding="utf-8")
    release_json = tmp_path / "release.json"
    assets = [{"name": name} for name in assets_by_name]
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
        str(asset_dir),
        "--tag",
        f"v{VERSION}",
        "--title",
        f"AMKernel {VERSION}",
        "--wheel",
        WHEEL_NAME,
        "--sha256",
        hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "--evidence-archive",
        archive.name,
        "--evidence-archive-sha256",
        hashlib.sha256(archive.read_bytes()).hexdigest(),
        "--evidence-manifest",
        manifest.name,
        "--evidence-manifest-sha256",
        hashlib.sha256(manifest.read_bytes()).hexdigest(),
    ]

    assert subprocess.run(command, check=False).returncode == 0
    assets.append({"name": "unexpected.txt"})
    release_json.write_text(json.dumps(release), encoding="utf-8")
    rejected = subprocess.run(command, check=False, capture_output=True, text=True)

    assert rejected.returncode == 2
    assert "must have exactly 3 assets" in rejected.stderr


def test_release_workflow_uses_trusted_exact_artifact_path() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    ci_workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    pypi_job = workflow.split("\n  pypi:\n", 1)[1]
    github_release_job = workflow.split("\n  github-release:\n", 1)[1].split("\n  pypi:\n", 1)[0]

    assert "permissions: {}" in workflow
    assert "UV_DEFAULT_INDEX" not in ci_workflow
    assert "pypi.tuna.tsinghua.edu.cn" not in lock
    assert 'registry = "https://pypi.org/simple"' in lock
    assert "name: pypi\n      url: https://pypi.org/p/amkernel" in pypi_job
    assert "actions: read\n      id-token: write" in pypi_job
    assert "actions/checkout" not in pypi_job
    assert "name: distribution-${{ steps.release.outputs.commit }}" in workflow
    assert "commit: ${{ steps.release.outputs.commit }}" in workflow
    assert "COMMIT: ${{ needs.prepare.outputs.commit }}" in workflow
    assert 'COMMIT=$(git rev-list -n 1 "$TAG")' in workflow
    resolved_checkout = 'git checkout --detach "${{ steps.release.outputs.commit }}"'
    assert resolved_checkout in workflow
    assert workflow.index(resolved_checkout) < workflow.index("name: Set up Python")
    assert workflow.index(resolved_checkout) < workflow.index(
        "Validate candidate and prepare metadata"
    )
    release_checkout = 'git checkout --detach "${{ needs.prepare.outputs.commit }}"'
    assert release_checkout in github_release_job
    assert github_release_job.index(release_checkout) < github_release_job.index(
        "scripts/verify_github_release.py"
    )
    assert "name: distribution-${{ github.sha }}" not in workflow
    assert "run-id: ${{ inputs.ci_run_id }}" in workflow
    assert "repos/$GITHUB_REPOSITORY/actions/runs/$CI_RUN_ID" in workflow
    assert workflow.count("actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333") == 5
    assert "git -c user.name=github-actions[bot]" in workflow
    assert 'tag --annotate "$TAG"' in workflow
    assert '--jq \'.immutable\')" = "true"' in workflow
    assert "name: release-evidence-${{ github.sha }}-${{ github.run_attempt }}" in workflow
    assert '"evidence-publish/$EVIDENCE_ARCHIVE"' in github_release_job
    assert "release-evidence-" not in pypi_job
    assert "scripts/prepare_evidence_archive.py" in ci_workflow
    assert "pypa/gh-action-pypi-publish@7245906fb61fa33a13554f9d5fb856fe61758086" in pypi_job
    assert "password:" not in workflow
    assert "uv build" not in workflow
    assert workflow.index("Create or verify immutable GitHub release") < workflow.index(
        "Publish exact tested wheel to PyPI"
    )
