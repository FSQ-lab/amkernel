from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
SKILL_ROOT = ROOT / "src" / "amkernel" / "skill"
VERIFIER = SKILL_ROOT / "scripts" / "verify_official_skills.py"


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


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


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )


def _initialize_source(source: Path) -> str:
    _git(source, "init", "-q")
    _git(source, "config", "user.email", "tests@example.invalid")
    _git(source, "config", "user.name", "AMKernel Tests")
    _git(source, "remote", "add", "origin", "https://example.invalid/official")
    _git(source, "add", ".")
    _git(source, "commit", "-q", "-m", "pinned fixture")
    commit = _git(source, "rev-parse", "HEAD").stdout.strip()
    _git(source, "checkout", "-q", "--detach", commit)
    return commit


def test_verifier_accepts_exact_trees_and_rejects_tampering(tmp_path: Path) -> None:
    source_content = b"pinned source\n"
    installed_content = b"installed copy\n"
    source = tmp_path / "vendor"
    runtime = tmp_path / "runtime" / "example"
    agent = tmp_path / "agent" / "example"
    source.mkdir()
    runtime.mkdir(parents=True)
    agent.mkdir(parents=True)
    (source / "source.md").write_bytes(source_content)
    (runtime / "SKILL.md").write_bytes(installed_content)
    (agent / "SKILL.md").write_bytes(installed_content)
    commit = _initialize_source(source)

    manifest = {
        "schemaVersion": 1,
        "repository": "https://example.invalid/official",
        "commit": commit,
        "source": {
            "generatedLocation": "vendor",
            "files": {"source.md": _sha256(source_content)},
        },
        "installedSkills": [
            {
                "name": "example",
                "generatedLocation": "runtime/example",
                "selectedAgentLocation": "agent/example",
                "selectedAgentMode": "copy",
                "files": {"SKILL.md": _sha256(installed_content)},
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    accepted = _run_verifier(tmp_path, manifest_path)
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    assert "verified" in accepted.stdout

    _git(source, "remote", "set-url", "origin", "https://evil.invalid/source")
    wrong_origin = _run_verifier(tmp_path, manifest_path)
    assert wrong_origin.returncode == 1
    assert "origin mismatch" in wrong_origin.stdout
    _git(source, "remote", "set-url", "origin", "https://example.invalid/official")

    (agent / "SKILL.md").write_text("tampered\n", encoding="utf-8")
    rejected = _run_verifier(tmp_path, manifest_path)
    assert rejected.returncode == 1
    assert "selected-agent skill example: sha256 mismatch" in rejected.stdout


def test_verifier_rejects_linked_location_ancestor(tmp_path: Path) -> None:
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    (project / "vendor").symlink_to(outside, target_is_directory=True)

    manifest = {
        "schemaVersion": 1,
        "repository": "https://example.invalid/official",
        "commit": "0" * 40,
        "source": {"generatedLocation": "vendor", "files": {}},
        "installedSkills": [
            {
                "name": "example",
                "generatedLocation": "vendor",
                "selectedAgentLocation": "vendor",
                "selectedAgentMode": "copy",
                "files": {},
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    rejected = _run_verifier(project, manifest_path)
    assert rejected.returncode == 1
    assert "linked location component is forbidden" in rejected.stdout


def test_verifier_rejects_missing_unexpected_and_linked_files(tmp_path: Path) -> None:
    source = tmp_path / "vendor"
    runtime = tmp_path / "runtime" / "example"
    agent = tmp_path / "agent" / "example"
    source.mkdir()
    runtime.mkdir(parents=True)
    agent.mkdir(parents=True)
    (source / "unexpected.md").write_text("unexpected\n", encoding="utf-8")
    (source / "linked.md").symlink_to("unexpected.md")
    commit = _initialize_source(source)

    manifest = {
        "schemaVersion": 1,
        "repository": "https://example.invalid/official",
        "commit": commit,
        "source": {
            "generatedLocation": "vendor",
            "files": {"required.md": _sha256(b"required\n")},
        },
        "installedSkills": [
            {
                "name": "example",
                "generatedLocation": "runtime/example",
                "selectedAgentLocation": "agent/example",
                "selectedAgentMode": "copy",
                "files": {"SKILL.md": _sha256(b"skill\n")},
            }
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    rejected = _run_verifier(tmp_path, manifest_path)
    assert rejected.returncode == 1
    assert "missing file: required.md" in rejected.stdout
    assert "unexpected file: unexpected.md" in rejected.stdout
    assert "symbolic links are forbidden: linked.md" in rejected.stdout
    assert "runtime skill example: missing file: SKILL.md" in rejected.stdout
    assert "selected-agent skill example: missing file: SKILL.md" in rejected.stdout
