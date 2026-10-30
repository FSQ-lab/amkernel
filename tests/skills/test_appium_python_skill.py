from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
SKILL_ROOT = ROOT / "skills" / "appium-python"
MANIFEST_PATH = SKILL_ROOT / "references" / "official-skills.json"
VERIFIER = SKILL_ROOT / "scripts" / "verify_official_skills.py"
COMMIT = "e907024c210fe024c956ed9c74146fc27b1dd013"
SELECTED_SKILLS = {
    "setup-uiautomator2",
    "setup-xcuitest",
    "appium-troubleshooting",
}


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


def test_skill_documents_persistent_safe_appium_flow() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

    required_contracts = (
        "UiAutomator2Options",
        "XCUITestOptions",
        'webdriver.Remote("http://127.0.0.1:4723"',
        "WebDriverWait(driver, 10)",
        'display(driver.get_screenshot_as_png(), mime_type="image/png")',
        'artifact("page-source-summary.json"',
        "driver.quit()",
        "Resetting or losing the kernel does not stop or clean them",
        "npx --no-install appium",
        "verify_official_skills.py",
        "value.ready: true",
        "adb -s <serial>",
        "Automatic Android SDK/command-line-tools bootstrap is outside",
        "cleanup_blocker",
        "MAX_STATUS_BYTES = 65_536",
    )
    for contract in required_contracts:
        assert contract in skill
    assert "desired_capabilities=" not in skill
    assert "time.sleep(" not in skill


def test_manifest_pins_complete_reviewed_inputs() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    assert manifest["schemaVersion"] == 1
    assert manifest["repository"] == "https://github.com/appium/skills"
    assert manifest["commit"] == COMMIT
    assert manifest["skillsCli"] == {
        "version": "1.7.4",
        "selectedAgent": "claude-code",
        "commands": [item["installCommand"] for item in manifest["installedSkills"]],
    }
    assert len(manifest["source"]["files"]) >= 100
    assert {
        "skills/setup-uiautomator2/SKILL.md",
        "skills/setup-xcuitest/SKILL.md",
        "skills/appium-troubleshooting/SKILL.md",
        "tools/appium/setup/scripts/check-uiautomator2-env.mjs",
        "tools/appium/setup/scripts/check-xcuitest-env.mjs",
        "contexts/tools/appium/troubleshooting/references/uiautomator2-session-startup.md",
        "contexts/tools/appium/troubleshooting/references/xcuitest-troubleshooting.md",
    } <= manifest["source"]["files"].keys()

    installed = {item["name"]: item for item in manifest["installedSkills"]}
    assert installed.keys() == SELECTED_SKILLS
    for name, item in installed.items():
        command = (
            "DISABLE_TELEMETRY=1 npx -y skills@1.7.4 add "
            f"https://github.com/appium/skills/tree/{COMMIT}/skills/{name} "
            f"--skill {name} --copy -a claude-code -y"
        )
        assert item["installCommand"] == command
        assert item["generatedLocation"] == f".agents/skills/{name}"
        assert item["selectedAgent"] == "claude-code"
        assert item["selectedAgentLocation"] == f".claude/skills/{name}"
        assert item["selectedAgentMode"] == "copy"
        assert item["securityAudit"]["gen"] == "safe"
        assert item["securityAudit"]["socket"] == "0 alerts"
        assert item["securityAudit"]["snyk"] in {"low", "medium"}
        assert item["files"]["SKILL.md"] == manifest["source"]["files"][f"skills/{name}/SKILL.md"]

    every_digest = [
        *manifest["source"]["files"].values(),
        *(digest for item in installed.values() for digest in item["files"].values()),
    ]
    assert all(len(digest) == 64 for digest in every_digest)
    assert all(set(digest) <= set("0123456789abcdef") for digest in every_digest)
    assert all(COMMIT in command for command in manifest["skillsCli"]["commands"])


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
