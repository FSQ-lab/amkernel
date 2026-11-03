from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[2]
SKILL_ROOT = ROOT / "src" / "amkernel" / "skill"
VERIFIER = SKILL_ROOT / "scripts" / "verify_official_skills.py"
ARCHIVE = {
    "format": "tar.gz",
    "path": "references/source.tar.gz",
    "sha256": "f" * 64,
}


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _run_verifier(project_root: Path, manifest_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            "--manifest",
            str(manifest_path),
            "--project-root",
            str(project_root),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def _write_manifest(tmp_path: Path, manifest: dict[str, Any]) -> Path:
    path = tmp_path / "manifest.json"
    _write_json(path, manifest)
    return path


def _install_receipt(
    project_root: Path, manifest: dict[str, Any], runtime_version: str = "0.1.0"
) -> Path:
    source = manifest["source"]
    skills = {
        item["name"]: {"path": item["generatedLocation"], "files": item["files"]}
        for item in manifest["installedSkills"]
    }
    state = {
        "schemaVersion": 1,
        "runtimeVersion": runtime_version,
        "repository": manifest["repository"],
        "commit": manifest["commit"],
        "archive": source["archive"],
        "source": {"path": source["generatedLocation"], "files": source["files"]},
        "skills": skills,
    }
    state_path = project_root / ".agents" / "amkernel-official.json"
    _write_json(state_path, state)
    metadata_path = project_root / ".agents" / "skills" / "amkernel" / ".amkernel-metadata.json"
    _write_json(
        metadata_path,
        {
            "runtimeVersion": runtime_version,
            "files": {"SKILL.md": _sha256(b"main skill\n")},
        },
    )
    (metadata_path.parent / "SKILL.md").write_bytes(b"main skill\n")
    return state_path


def test_verifier_accepts_receipt_and_rejects_source_or_runtime_tampering(
    tmp_path: Path,
) -> None:
    source_content = b"pinned source\n"
    installed_content = b"installed copy\n"
    source = tmp_path / "vendor"
    runtime = tmp_path / "runtime" / "example"
    source.mkdir()
    runtime.mkdir(parents=True)
    (source / "source.md").write_bytes(source_content)
    (runtime / "SKILL.md").write_bytes(installed_content)
    manifest: dict[str, Any] = {
        "schemaVersion": 1,
        "repository": "https://example.invalid/official",
        "commit": "a" * 40,
        "source": {
            "generatedLocation": "vendor",
            "files": {"source.md": _sha256(source_content)},
            "archive": ARCHIVE,
        },
        "installedSkills": [
            {
                "name": "example",
                "generatedLocation": "runtime/example",
                "files": {"SKILL.md": _sha256(installed_content)},
            }
        ],
    }
    manifest_path = _write_manifest(tmp_path, manifest)
    state_path = _install_receipt(tmp_path, manifest)

    accepted = _run_verifier(tmp_path, manifest_path)
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    assert "verified" in accepted.stdout

    (source / "source.md").write_text("tampered\n", encoding="utf-8")
    source_rejected = _run_verifier(tmp_path, manifest_path)
    assert source_rejected.returncode == 1
    assert "official source: sha256 mismatch" in source_rejected.stdout
    (source / "source.md").write_bytes(source_content)

    (runtime / "SKILL.md").write_text("tampered\n", encoding="utf-8")
    runtime_rejected = _run_verifier(tmp_path, manifest_path)
    assert runtime_rejected.returncode == 1
    assert "runtime skill example: sha256 mismatch" in runtime_rejected.stdout
    (runtime / "SKILL.md").write_bytes(installed_content)

    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["repository"] = "https://evil.invalid/source"
    _write_json(state_path, state)
    repository_rejected = _run_verifier(tmp_path, manifest_path)
    assert repository_rejected.returncode == 1
    assert "official source receipt: repository mismatch" in repository_rejected.stdout

    state_path.unlink()
    missing = _run_verifier(tmp_path, manifest_path)
    assert missing.returncode == 1
    assert "official source receipt: missing" in missing.stdout


def test_verifier_rejects_git_metadata_and_linked_receipt(tmp_path: Path) -> None:
    source_content = b"pinned source\n"
    installed_content = b"installed copy\n"
    source = tmp_path / "vendor"
    runtime = tmp_path / "runtime" / "example"
    source.mkdir()
    runtime.mkdir(parents=True)
    (source / "source.md").write_bytes(source_content)
    (runtime / "SKILL.md").write_bytes(installed_content)
    manifest: dict[str, Any] = {
        "schemaVersion": 1,
        "repository": "https://example.invalid/official",
        "commit": "a" * 40,
        "source": {
            "generatedLocation": "vendor",
            "files": {"source.md": _sha256(source_content)},
            "archive": ARCHIVE,
        },
        "installedSkills": [
            {
                "name": "example",
                "generatedLocation": "runtime/example",
                "files": {"SKILL.md": _sha256(installed_content)},
            }
        ],
    }
    manifest_path = _write_manifest(tmp_path, manifest)
    state_path = _install_receipt(tmp_path, manifest)
    accepted = _run_verifier(tmp_path, manifest_path)
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr

    git_dir = source / "nested" / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "unverified.py").write_text("unverified\n", encoding="utf-8")
    rejected = _run_verifier(tmp_path, manifest_path)
    assert rejected.returncode == 1
    assert ".git" in rejected.stdout
    (git_dir / "unverified.py").unlink()
    git_dir.rmdir()
    (source / "nested").rmdir()

    external_git = tmp_path / "external-git"
    external_git.mkdir()
    (external_git / "held.txt").write_text("held\n", encoding="utf-8")
    (source / ".git").symlink_to(external_git, target_is_directory=True)
    linked_git = _run_verifier(tmp_path, manifest_path)
    assert linked_git.returncode == 1
    assert ".git" in linked_git.stdout
    assert (external_git / "held.txt").read_text(encoding="utf-8") == "held\n"
    (source / ".git").unlink()

    external_receipt = tmp_path / "external-receipt.json"
    os.replace(state_path, external_receipt)
    state_path.symlink_to(external_receipt)
    linked_receipt = _run_verifier(tmp_path, manifest_path)
    assert linked_receipt.returncode == 1
    assert "official source receipt: linked file is forbidden" in linked_receipt.stdout
    state_path.unlink()

    agents = tmp_path / ".agents"
    external_agents = tmp_path / "external-agents"
    os.replace(agents, external_agents)
    agents.symlink_to(external_agents, target_is_directory=True)
    linked_receipt_parent = _run_verifier(tmp_path, manifest_path)
    assert linked_receipt_parent.returncode == 1
    assert "linked location component is forbidden" in linked_receipt_parent.stdout


def test_verifier_rejects_linked_location_ancestor(tmp_path: Path) -> None:
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    (project / "vendor").symlink_to(outside, target_is_directory=True)

    manifest: dict[str, Any] = {
        "schemaVersion": 1,
        "repository": "https://example.invalid/official",
        "commit": "0" * 40,
        "source": {"generatedLocation": "vendor", "files": {}, "archive": ARCHIVE},
        "installedSkills": [
            {
                "name": "example",
                "generatedLocation": "vendor",
                "files": {},
            }
        ],
    }
    manifest_path = _write_manifest(tmp_path, manifest)
    _install_receipt(project, manifest)

    rejected = _run_verifier(project, manifest_path)
    assert rejected.returncode == 1
    assert "linked location component is forbidden" in rejected.stdout


def test_verifier_binds_receipt_to_installed_main_metadata_version(
    tmp_path: Path,
) -> None:
    source_content = b"pinned source\n"
    installed_content = b"installed copy\n"
    commit = "a" * 40
    source = tmp_path / ".agents" / "vendor" / "appium-skills" / commit
    runtime = tmp_path / ".agents" / "skills" / "example"
    source.mkdir(parents=True)
    runtime.mkdir(parents=True)
    (source / "source.md").write_bytes(source_content)
    (runtime / "SKILL.md").write_bytes(installed_content)

    manifest: dict[str, Any] = {
        "schemaVersion": 1,
        "repository": "https://example.invalid/official",
        "commit": commit,
        "source": {
            "generatedLocation": f".agents/vendor/appium-skills/{commit}",
            "files": {"source.md": _sha256(source_content)},
            "archive": ARCHIVE,
        },
        "installedSkills": [
            {
                "name": "example",
                "generatedLocation": ".agents/skills/example",
                "files": {"SKILL.md": _sha256(installed_content)},
            }
        ],
    }
    manifest_path = _write_manifest(tmp_path, manifest)
    state_path = _install_receipt(tmp_path, manifest)
    metadata_path = tmp_path / ".agents" / "skills" / "amkernel" / ".amkernel-metadata.json"

    accepted = _run_verifier(tmp_path, manifest_path)
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    assert "verified" in accepted.stdout
    assert not (tmp_path / ".claude").exists()

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["runtimeVersion"] = "0.2.0"
    _write_json(metadata_path, metadata)
    version_rejected = _run_verifier(tmp_path, manifest_path)
    assert version_rejected.returncode == 1
    assert "official source receipt: runtimeVersion mismatch" in version_rejected.stdout

    metadata["runtimeVersion"] = "0.1.0"
    metadata["files"] = []
    _write_json(metadata_path, metadata)
    shape_rejected = _run_verifier(tmp_path, manifest_path)
    assert shape_rejected.returncode == 1
    assert "main Skill metadata: invalid" in shape_rejected.stdout

    metadata["files"] = {"SKILL.md": _sha256(b"main skill\n")}
    _write_json(metadata_path, metadata)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["commit"] = "b" * 40
    _write_json(state_path, state)
    mismatched = _run_verifier(tmp_path, manifest_path)
    assert mismatched.returncode == 1
    assert "official source receipt: commit mismatch" in mismatched.stdout

    state["commit"] = commit
    _write_json(state_path, state)
    (runtime / "SKILL.md").write_text("tampered\n", encoding="utf-8")
    tampered = _run_verifier(tmp_path, manifest_path)
    assert tampered.returncode == 1
    assert "runtime skill example: sha256 mismatch" in tampered.stdout


def test_verifier_rejects_missing_unexpected_and_linked_files(tmp_path: Path) -> None:
    source = tmp_path / "vendor"
    runtime = tmp_path / "runtime" / "example"
    source.mkdir()
    runtime.mkdir(parents=True)
    (source / "unexpected.md").write_text("unexpected\n", encoding="utf-8")
    (source / "linked.md").symlink_to("unexpected.md")

    manifest: dict[str, Any] = {
        "schemaVersion": 1,
        "repository": "https://example.invalid/official",
        "commit": "a" * 40,
        "source": {
            "generatedLocation": "vendor",
            "files": {"required.md": _sha256(b"required\n")},
            "archive": ARCHIVE,
        },
        "installedSkills": [
            {
                "name": "example",
                "generatedLocation": "runtime/example",
                "files": {"SKILL.md": _sha256(b"skill\n")},
            }
        ],
    }
    manifest_path = _write_manifest(tmp_path, manifest)
    _install_receipt(tmp_path, manifest)

    rejected = _run_verifier(tmp_path, manifest_path)
    assert rejected.returncode == 1
    assert "missing file: required.md" in rejected.stdout
    assert "unexpected file: unexpected.md" in rejected.stdout
    assert "symbolic links are forbidden: linked.md" in rejected.stdout
    assert "runtime skill example: missing file: SKILL.md" in rejected.stdout
