from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
import tomllib
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from amkernel import __version__
from amkernel.distribution import (
    Client,
    CommandResult,
    DistributionError,
    DistributionManager,
    _validated_archive_members,
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _tar_bytes(files: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return stream.getvalue()


def _official_package(
    *, agents_as_file: bool = False, commit: str = "a" * 40
) -> tuple[dict[str, object], bytes, str]:
    source_files = {
        "LICENSE": b"official license\n",
        "skills/setup-example/SKILL.md": b"---\nname: setup-example\n---\n",
        "skills/setup-example/agents/openai.yaml": b"name: setup-example\n",
    }
    if agents_as_file:
        del source_files["skills/setup-example/agents/openai.yaml"]
        source_files["skills/setup-example/agents"] = b"standalone agent definition\n"
    skill_files = {
        name.removeprefix("skills/setup-example/"): content
        for name, content in source_files.items()
        if name.startswith("skills/setup-example/")
    }
    archive = _tar_bytes(source_files)
    manifest: dict[str, object] = {
        "schemaVersion": 1,
        "repository": "https://github.com/appium/skills",
        "commit": commit,
        "source": {
            "generatedLocation": f".agents/vendor/appium-skills/{commit}",
            "files": {name: _sha(content) for name, content in source_files.items()},
            "archive": {
                "format": "tar.gz",
                "path": "references/appium-skills-test.tar.gz",
                "sha256": _sha(archive),
            },
        },
        "installedSkills": [
            {
                "name": "setup-example",
                "sourcePath": "skills/setup-example",
                "generatedLocation": ".agents/skills/setup-example",
                "selectedAgentLocation": ".claude/skills/setup-example",
                "selectedAgentMode": "copy",
                "files": {name: _sha(content) for name, content in skill_files.items()},
            }
        ],
    }
    return manifest, archive, commit


def _alternate_official_package() -> tuple[dict[str, object], bytes, str]:
    commit = "b" * 40
    source_files = {
        "LICENSE": b"new official license\n",
        "skills/setup-new/SKILL.md": b"---\nname: setup-new\n---\n",
    }
    skill_files = {"SKILL.md": source_files["skills/setup-new/SKILL.md"]}
    archive = _tar_bytes(source_files)
    manifest: dict[str, object] = {
        "schemaVersion": 1,
        "repository": "https://github.com/appium/skills",
        "commit": commit,
        "source": {
            "generatedLocation": f".agents/vendor/appium-skills/{commit}",
            "files": {name: _sha(content) for name, content in source_files.items()},
            "archive": {
                "format": "tar.gz",
                "path": "references/appium-skills-test.tar.gz",
                "sha256": _sha(archive),
            },
        },
        "installedSkills": [
            {
                "name": "setup-new",
                "sourcePath": "skills/setup-new",
                "generatedLocation": ".agents/skills/setup-new",
                "selectedAgentLocation": ".claude/skills/setup-new",
                "selectedAgentMode": "copy",
                "files": {name: _sha(content) for name, content in skill_files.items()},
            }
        ],
    }
    return manifest, archive, commit


@pytest.fixture(autouse=True)
def official_package(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, object], bytes, str]:
    manifest, archive, commit = _official_package()
    monkeypatch.setattr(DistributionManager, "_load_official_manifest", lambda self: manifest)
    monkeypatch.setattr(DistributionManager, "_read_official_archive", lambda self, value: archive)
    return manifest, archive, commit


@pytest.fixture
def project(tmp_path: Path) -> Path:
    value = tmp_path / "project"
    value.mkdir()
    return value


def manager(project: Path, bin_dir: Path) -> DistributionManager:
    bin_dir.mkdir(exist_ok=True)

    def run(argv: Sequence[str]) -> CommandResult:
        values = tuple(argv)
        if values[-3:] == ("tool", "dir", "--bin"):
            return CommandResult(values, 0, f"{bin_dir}\n", "", False)
        if values[-1:] == ("--version",):
            return CommandResult(values, 0, f"amkernel {__version__}\n", "", False)
        return CommandResult(values, 0, "", "", False)

    return DistributionManager(project, runner=run, data_home=project.parent / "data")


def test_auto_client_detection_rejects_ambiguous_project_markers(
    project: Path, tmp_path: Path
) -> None:
    (project / ".omp").mkdir()
    (project / ".pi").mkdir()
    subject = manager(project, tmp_path / "bin")
    assert subject.client_candidates() == ("omp", "pi")

    with pytest.raises(DistributionError, match="multiple Coding Agents detected"):
        subject.select_client("auto")

    assert not (project / ".agents").exists()


def test_auto_client_detection_rejects_ambiguous_installed_clients(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("amkernel.distribution.shutil.which", lambda name: f"/bin/{name}")
    subject = manager(project, tmp_path / "bin")
    assert subject.client_candidates() == ("omp", "pi", "codex")

    with pytest.raises(DistributionError, match="multiple Coding Agents detected"):
        subject.select_client("auto")


@pytest.mark.parametrize(
    ("client", "relative"),
    (
        ("omp", ".omp/mcp.json"),
        ("pi", ".pi/mcp.json"),
        ("codex", ".codex/config.toml"),
        ("copilot", ".mcp.json"),
    ),
)
def test_configure_project_installs_shared_skill_and_native_mcp_without_losing_config(
    project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    client: str,
    relative: str,
    official_package: tuple[dict[str, object], bytes, str],
) -> None:
    _manifest, _archive, commit = official_package
    bin_dir = tmp_path / "bin"
    executable = bin_dir / ("amkernel.exe" if os.name == "nt" else "amkernel")
    executable.parent.mkdir()
    executable.write_text("executable")
    target = project / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if client == "codex":
        target.write_text('[model_provider]\nname = "kept"\n')
    else:
        target.write_text(json.dumps({"kept": {"value": True}}))

    subject = manager(project, bin_dir)
    status = subject.configure_project(cast(Client, client), executable)
    source = project / f".agents/vendor/appium-skills/{commit}"
    managed_paths = (
        target,
        project / ".agents/skills/amkernel/SKILL.md",
        project / ".agents/skills/amkernel/references/official-skills.json",
        project / ".agents/skills/amkernel/.amkernel-metadata.json",
        project / ".agents/skills/setup-example/SKILL.md",
        source / "LICENSE",
        project / ".agents/amkernel-official.json",
    )
    first_inodes = {path: path.stat().st_ino for path in managed_paths}
    repeated_status = subject.configure_project(cast(Client, client), executable)

    assert repeated_status.detail is None
    assert {path: path.stat().st_ino for path in managed_paths} == first_inodes

    assert status.runtime_installed
    assert status.skill_installed
    assert status.mcp_configured
    assert (
        (project / ".agents/skills/amkernel/SKILL.md").read_text().startswith("---\nname: amkernel")
    )
    assert (project / ".agents/skills/amkernel/references/official-skills.json").is_file()
    assert (project / ".agents/skills/amkernel/scripts/verify_official_skills.py").is_file()
    assert (project / ".agents/skills/setup-example/SKILL.md").is_file()
    assert (project / ".agents/skills/setup-example/agents/openai.yaml").is_file()
    assert (source / "skills/setup-example/SKILL.md").is_file()
    assert status.skill_provenance
    assert status.skill_content_verified
    assert status.skill_commit == commit
    assert (status.notice is not None) == (client == "copilot")
    state = json.loads((project / ".agents/amkernel-official.json").read_text())
    assert state["commit"] == commit
    assert state["runtimeVersion"] == __version__
    assert state["archive"]["sha256"] == _sha(_archive)
    assert subject.known_projects() == {str(project): client}
    if client == "codex":
        parsed = tomllib.loads(target.read_text())
        assert parsed["model_provider"] == {"name": "kept"}
        entry = parsed["mcp_servers"]["amkernel"]
    else:
        parsed = json.loads(target.read_text())
        assert parsed["kept"] == {"value": True}
        entry = parsed["mcpServers"]["amkernel"]
    assert entry["command"] == str(executable)
    assert entry["cwd"] == str(project)
    if client == "copilot":
        assert entry["type"] == "stdio"
        assert entry["args"] == []
        assert entry["tools"] == ["*"]


def test_configure_project_rolls_back_skill_when_existing_config_is_invalid(
    project: Path, tmp_path: Path
) -> None:
    target = project / ".omp/mcp.json"
    target.parent.mkdir()
    target.write_text("not json")
    executable = tmp_path / "bin/amkernel"
    executable.parent.mkdir()
    executable.write_text("executable")

    with pytest.raises(DistributionError, match="valid JSON"):
        manager(project, executable.parent).configure_project("omp", executable)

    assert target.read_text() == "not json"
    assert not (project / ".agents/skills/amkernel").exists()
    assert not (project / ".agents/skills/setup-example").exists()
    assert not (project / ".agents/amkernel-official.json").exists()
    assert not (project / ".agents/vendor").exists()
    assert not (project / ".amkernel.install.lock").exists()


def test_uninstall_removes_only_managed_project_entries(
    project: Path, tmp_path: Path, official_package: tuple[dict[str, object], bytes, str]
) -> None:
    _manifest, _archive, commit = official_package
    bin_dir = tmp_path / "bin"
    executable = bin_dir / "amkernel"
    executable.parent.mkdir()
    executable.write_text("executable")
    subject = manager(project, bin_dir)
    subject.configure_project("pi", executable)
    path = project / ".pi/mcp.json"
    value = json.loads(path.read_text())
    value["mcpServers"]["other"] = {"command": "kept"}
    path.write_text(json.dumps(value))

    status = subject.uninstall_project("pi")

    assert not status.skill_installed
    assert not status.mcp_configured
    assert json.loads(path.read_text())["mcpServers"] == {"other": {"command": "kept"}}
    assert not (project / ".agents/skills/setup-example").exists()
    assert not (project / f".agents/vendor/appium-skills/{commit}").exists()
    assert not (project / ".agents/amkernel-official.json").exists()
    assert subject.known_projects() == {}


def test_auto_client_detection_accepts_copilot_and_ignores_aws_copilot(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "amkernel.distribution.shutil.which",
        lambda name: "/usr/local/bin/copilot" if name == "copilot" else None,
    )

    def aws(argv: Sequence[str]) -> CommandResult:
        return CommandResult(tuple(argv), 0, "AWS Copilot CLI", "", False)

    aws_subject = DistributionManager(project, runner=aws, data_home=tmp_path / "data")
    assert aws_subject.client_candidates() == ()
    with pytest.raises(DistributionError, match="no supported Coding Agent"):
        aws_subject.select_client("auto")

    def github(argv: Sequence[str]) -> CommandResult:
        return CommandResult(tuple(argv), 0, "GitHub Copilot CLI", "", False)

    github_subject = DistributionManager(project, runner=github, data_home=tmp_path / "data")
    assert github_subject.client_candidates() == ("copilot",)
    assert github_subject.select_client("auto") == "copilot"

    config = project / ".mcp.json"
    config.write_text(json.dumps({"other": {"command": "other"}}))
    assert github_subject.select_client("auto") == "copilot"


def test_copilot_prefers_existing_root_config_and_leaves_native_config_inactive(
    project: Path, tmp_path: Path
) -> None:
    executable = tmp_path / "bin/amkernel"
    executable.parent.mkdir()
    executable.write_text("executable")
    config = project / ".mcp.json"
    config.write_text(json.dumps({"other": {"command": "other", "args": []}}))
    github = project / ".github/mcp.json"
    github.parent.mkdir()
    github.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "amkernel": {"command": "other"},
                    "kept": {"command": "kept"},
                }
            }
        )
    )
    original_github = github.read_text()

    subject = manager(project, executable.parent)
    status = subject.configure_project("copilot", executable)

    parsed = json.loads(config.read_text())
    assert "mcpServers" not in parsed
    assert parsed["other"] == {"command": "other", "args": []}
    assert parsed["amkernel"]["cwd"] == str(project)
    assert parsed["amkernel"]["type"] == "stdio"
    assert github.read_text() == original_github
    assert status.mcp_configured
    assert status.notice is not None

    parsed.pop("amkernel")
    config.write_text(json.dumps(parsed))
    assert not subject.status("copilot").mcp_configured

    subject.configure_project("copilot", executable)
    subject.uninstall_project("copilot")
    parsed = json.loads(config.read_text())
    assert "amkernel" not in parsed
    assert parsed["other"] == {"command": "other", "args": []}
    assert github.read_text() == original_github


def test_copilot_uses_existing_native_config_when_root_config_is_absent(
    project: Path, tmp_path: Path
) -> None:
    executable = tmp_path / "bin/amkernel"
    executable.parent.mkdir()
    executable.write_text("executable")
    github = project / ".github/mcp.json"
    github.parent.mkdir()
    github.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "amkernel": {"command": "other"},
                    "kept": {"command": "kept"},
                }
            }
        )
    )

    subject = manager(project, executable.parent)
    status = subject.configure_project("copilot", executable)

    parsed = json.loads(github.read_text())
    assert parsed["mcpServers"]["kept"] == {"command": "kept"}
    assert parsed["mcpServers"]["amkernel"]["command"] == str(executable)
    assert parsed["mcpServers"]["amkernel"]["cwd"] == str(project)
    assert parsed["mcpServers"]["amkernel"]["type"] == "stdio"
    assert not (project / ".mcp.json").exists()
    assert status.mcp_configured

    subject.uninstall_project("copilot")
    parsed = json.loads(github.read_text())
    assert parsed["mcpServers"] == {"kept": {"command": "kept"}}
    assert not (project / ".mcp.json").exists()


def test_official_source_and_skill_drift_is_repaired(
    project: Path,
    tmp_path: Path,
    official_package: tuple[dict[str, object], bytes, str],
) -> None:
    _manifest, _archive, commit = official_package
    executable = tmp_path / "bin/amkernel"
    executable.parent.mkdir()
    executable.write_text("executable")
    subject = manager(project, executable.parent)
    subject.configure_project("copilot", executable)
    source_file = project / f".agents/vendor/appium-skills/{commit}/skills/setup-example/SKILL.md"
    skill_file = project / ".agents/skills/setup-example/SKILL.md"

    source_file.write_text("tampered source\n")
    status = subject.status("copilot")
    assert status.detail is not None
    assert not status.skill_provenance
    assert not status.skill_content_verified

    subject.configure_project("copilot", executable)
    assert source_file.read_text() == "---\nname: setup-example\n---\n"
    assert subject.status("copilot").detail is None

    skill_file.write_text("tampered copy\n")
    assert subject.status("copilot").detail is not None
    subject.configure_project("copilot", executable)
    assert skill_file.read_text() == "---\nname: setup-example\n---\n"
    assert subject.status("copilot").detail is None


def test_official_receipt_mismatch_fails_status_and_is_repaired(
    project: Path,
    tmp_path: Path,
    official_package: tuple[dict[str, object], bytes, str],
) -> None:
    _manifest, _archive, commit = official_package
    executable = tmp_path / "bin/amkernel"
    executable.parent.mkdir()
    executable.write_text("executable")
    subject = manager(project, executable.parent)
    subject.configure_project("omp", executable)
    state_path = project / ".agents/amkernel-official.json"
    state = json.loads(state_path.read_text())
    state["commit"] = "b" * 40
    state_path.write_text(json.dumps(state))

    status = subject.status("omp")
    assert status.detail is not None
    assert not status.skill_provenance

    subject.configure_project("omp", executable)
    repaired = json.loads(state_path.read_text())
    assert repaired["commit"] == commit
    assert subject.status("omp").detail is None


def test_malformed_official_receipt_blocks_install_and_uninstall(
    project: Path,
    tmp_path: Path,
    official_package: tuple[dict[str, object], bytes, str],
) -> None:
    _manifest, _archive, _commit = official_package
    executable = tmp_path / "bin/amkernel"
    executable.parent.mkdir()
    executable.write_text("executable")
    subject = manager(project, executable.parent)
    subject.configure_project("omp", executable)
    state_path = project / ".agents/amkernel-official.json"
    state_path.write_text("{")

    with pytest.raises(DistributionError, match="valid JSON"):
        subject.configure_project("omp", executable)
    with pytest.raises(DistributionError, match="valid JSON"):
        subject.uninstall_project("omp")


def test_official_receipt_version_drift_is_unhealthy_until_reinstall(
    project: Path,
    tmp_path: Path,
    official_package: tuple[dict[str, object], bytes, str],
) -> None:
    _manifest, _archive, _commit = official_package
    executable = tmp_path / "bin/amkernel"
    executable.parent.mkdir()
    executable.write_text("executable")
    subject = manager(project, executable.parent)
    subject.configure_project("pi", executable)
    state_path = project / ".agents/amkernel-official.json"
    state = json.loads(state_path.read_text())
    state["runtimeVersion"] = "0.0.0"
    state_path.write_text(json.dumps(state))

    assert subject.status("pi").detail is not None
    subject.configure_project("pi", executable)
    assert json.loads(state_path.read_text())["runtimeVersion"] == __version__
    assert subject.status("pi").detail is None


def test_exact_preexisting_official_tree_is_adopted(
    project: Path,
    tmp_path: Path,
    official_package: tuple[dict[str, object], bytes, str],
) -> None:
    _manifest, _archive, _commit = official_package
    executable = tmp_path / "bin/amkernel"
    executable.parent.mkdir()
    executable.write_text("executable")
    subject = manager(project, executable.parent)
    subject.configure_project("omp", executable)
    state_path = project / ".agents/amkernel-official.json"
    state_path.unlink()

    assert subject.status("omp").detail is not None
    subject.configure_project("omp", executable)
    assert state_path.is_file()
    assert subject.status("omp").detail is None


def test_uninstall_preserves_modified_and_unowned_official_files(
    project: Path,
    tmp_path: Path,
    official_package: tuple[dict[str, object], bytes, str],
) -> None:
    _manifest, _archive, commit = official_package
    executable = tmp_path / "bin/amkernel"
    executable.parent.mkdir()
    executable.write_text("executable")
    subject = manager(project, executable.parent)
    subject.configure_project("pi", executable)
    skill_dir = project / ".agents/skills/setup-example"
    modified = skill_dir / "SKILL.md"
    modified.write_text("user edit\n")
    extra = skill_dir / "notes.txt"
    extra.write_text("user notes\n")

    subject.uninstall_project("pi")

    assert modified.read_text() == "user edit\n"
    assert extra.read_text() == "user notes\n"
    assert not (skill_dir / "agents/openai.yaml").exists()
    assert not (project / f".agents/vendor/appium-skills/{commit}").exists()
    assert not (project / ".agents/amkernel-official.json").exists()


def test_uninstall_preserves_empty_unowned_directory_under_official_skill(
    project: Path,
    tmp_path: Path,
    official_package: tuple[dict[str, object], bytes, str],
) -> None:
    _manifest, _archive, _commit = official_package
    executable = tmp_path / "bin/amkernel"
    executable.parent.mkdir()
    executable.write_text("executable")
    subject = manager(project, executable.parent)
    subject.configure_project("pi", executable)
    skill_dir = project / ".agents/skills/setup-example"
    user_dir = skill_dir / "user-notes"
    user_dir.mkdir()

    subject.uninstall_project("pi")

    assert user_dir.is_dir()
    assert not (skill_dir / "SKILL.md").exists()
    assert not (skill_dir / "agents").exists()
    assert not (project / ".agents/amkernel-official.json").exists()


@pytest.mark.parametrize("old_agents_file", [False, True])
@pytest.mark.parametrize("registration_fails", [False, True])
def test_official_upgrade_changes_file_directory_shape_transactionally(
    project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    old_agents_file: bool,
    registration_fails: bool,
) -> None:
    old_manifest, old_archive, _ = _official_package(agents_as_file=old_agents_file)
    new_manifest, new_archive, _ = _official_package(
        agents_as_file=not old_agents_file, commit="b" * 40
    )
    executable = tmp_path / "bin/amkernel"
    executable.parent.mkdir()
    executable.write_text("executable")
    subject = manager(project, executable.parent)
    monkeypatch.setattr(subject, "_load_official_manifest", lambda: old_manifest)
    monkeypatch.setattr(subject, "_read_official_archive", lambda manifest: old_archive)
    subject.configure_project("omp", executable)
    config = project / ".omp/mcp.json"
    config.chmod(0o600)
    receipt = project / ".agents/amkernel-official.json"
    original_receipt = receipt.read_bytes()
    monkeypatch.setattr(subject, "_load_official_manifest", lambda: new_manifest)
    monkeypatch.setattr(subject, "_read_official_archive", lambda manifest: new_archive)

    if registration_fails:

        def fail_registration(client: Client | None) -> None:
            raise RuntimeError("registration failed after shape replacement")

        monkeypatch.setattr(subject, "_set_project_registration", fail_registration)
        with pytest.raises(RuntimeError, match="registration failed after shape replacement"):
            subject.configure_project("omp", executable)
        assert receipt.read_bytes() == original_receipt
        monkeypatch.setattr(subject, "_load_official_manifest", lambda: old_manifest)
        monkeypatch.setattr(subject, "_read_official_archive", lambda manifest: old_archive)
    else:
        subject.configure_project("omp", executable)

    expected_file = old_agents_file if registration_fails else not old_agents_file
    agents = project / ".agents/skills/setup-example/agents"
    if expected_file:
        assert agents.is_file()
        assert agents.read_bytes() == b"standalone agent definition\n"
    else:
        assert agents.is_dir()
        assert (agents / "openai.yaml").read_bytes() == b"name: setup-example\n"
    assert subject.status("omp").detail is None
    assert config.stat().st_mode & 0o777 == 0o600


def test_upgrade_releases_only_unchanged_obsolete_official_files(
    project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_package: tuple[dict[str, object], bytes, str],
) -> None:
    _manifest, _archive, old_commit = official_package
    new_manifest, new_archive, new_commit = _alternate_official_package()
    executable = tmp_path / "bin/amkernel"
    executable.parent.mkdir()
    executable.write_text("executable")
    subject = manager(project, executable.parent)
    subject.configure_project("omp", executable)
    old_source = project / f".agents/vendor/appium-skills/{old_commit}"
    old_skill = project / ".agents/skills/setup-example"
    modified = old_source / "LICENSE"
    modified.write_text("user license\n")
    source_extra = old_source / "notes.txt"
    source_extra.write_text("user source notes\n")
    skill_extra = old_skill / "notes.txt"
    skill_extra.write_text("user skill notes\n")
    empty_user_dir = old_skill / "user-notes"
    empty_user_dir.mkdir()

    def load_manifest() -> dict[str, object]:
        return new_manifest

    def read_archive(value: object) -> bytes:
        return new_archive

    subject._load_official_manifest = load_manifest  # type: ignore[method-assign]
    monkeypatch.setattr(subject, "_read_official_archive", read_archive)

    subject.configure_project("omp", executable)

    assert modified.read_text() == "user license\n"
    assert source_extra.read_text() == "user source notes\n"
    assert skill_extra.read_text() == "user skill notes\n"
    assert empty_user_dir.is_dir()
    assert not (old_source / "skills/setup-example/SKILL.md").exists()
    assert not (old_skill / "SKILL.md").exists()
    assert not (old_skill / "agents").exists()
    assert (project / f".agents/vendor/appium-skills/{new_commit}/LICENSE").is_file()
    assert (project / ".agents/skills/setup-new/SKILL.md").is_file()
    assert (
        json.loads((project / ".agents/amkernel-official.json").read_text())["commit"] == new_commit
    )
    assert subject.status("omp").detail is None


def test_upgrade_rollback_restores_obsolete_official_files(
    project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    official_package: tuple[dict[str, object], bytes, str],
) -> None:
    old_manifest, old_archive, old_commit = official_package
    new_manifest, new_archive, new_commit = _alternate_official_package()
    executable = tmp_path / "bin/amkernel"
    executable.parent.mkdir()
    executable.write_text("executable")
    subject = manager(project, executable.parent)
    subject.configure_project("omp", executable)
    old_source = project / f".agents/vendor/appium-skills/{old_commit}"
    old_skill = project / ".agents/skills/setup-example"
    state_path = project / ".agents/amkernel-official.json"
    empty_user_dir = old_skill / "user-notes"
    empty_user_dir.mkdir()
    old_skill.joinpath("agents").chmod(0o700)

    def load_manifest() -> dict[str, object]:
        return new_manifest

    def read_archive(value: object) -> bytes:
        return new_archive

    subject._load_official_manifest = load_manifest  # type: ignore[method-assign]
    monkeypatch.setattr(subject, "_read_official_archive", read_archive)

    def fail_registration(client: Client | None) -> None:
        raise RuntimeError("simulated failure after owned-file release")

    subject._set_project_registration = fail_registration  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="simulated failure"):
        subject.configure_project("omp", executable)

    assert (old_source / "LICENSE").read_text() == "official license\n"
    assert (old_skill / "SKILL.md").read_text() == "---\nname: setup-example\n---\n"
    assert (old_skill / "agents/openai.yaml").is_file()
    assert empty_user_dir.is_dir()
    assert ((old_skill / "agents").stat().st_mode & 0o777) == 0o700
    assert json.loads(state_path.read_text())["commit"] == old_commit
    assert not (project / f".agents/vendor/appium-skills/{new_commit}").exists()
    assert not (project / ".agents/skills/setup-new").exists()

    subject._load_official_manifest = lambda: old_manifest  # type: ignore[method-assign]
    monkeypatch.setattr(subject, "_read_official_archive", lambda manifest: old_archive)
    assert subject.status("omp").detail is None


def test_uninstall_preserves_external_tree_behind_linked_official_ancestor(
    project: Path,
    tmp_path: Path,
    official_package: tuple[dict[str, object], bytes, str],
) -> None:
    _manifest, _archive, commit = official_package
    executable = tmp_path / "bin/amkernel"
    executable.parent.mkdir()
    executable.write_text("executable")
    subject = manager(project, executable.parent)
    subject.configure_project("pi", executable)
    source_parent = project / ".agents/vendor/appium-skills"
    external = tmp_path / "external-appium-skills"
    os.replace(source_parent, external)
    source_parent.symlink_to(external, target_is_directory=True)
    license_bytes = (external / commit / "LICENSE").read_bytes()

    status = subject.status("pi")
    assert not status.skill_provenance
    assert not status.skill_content_verified

    with pytest.raises(DistributionError, match="linked path component"):
        subject.uninstall_project("pi")
    assert (external / commit / "LICENSE").read_bytes() == license_bytes
    assert (external / commit / "skills/setup-example/SKILL.md").is_file()


def test_uninstall_preserves_external_main_skill_behind_linked_root(
    project: Path,
    tmp_path: Path,
    official_package: tuple[dict[str, object], bytes, str],
) -> None:
    _manifest, _archive, _commit = official_package
    executable = tmp_path / "bin/amkernel"
    executable.parent.mkdir()
    executable.write_text("executable")
    subject = manager(project, executable.parent)
    subject.configure_project("pi", executable)
    main_skill = project / ".agents/skills/amkernel"
    external = tmp_path / "external-main-skill"
    os.replace(main_skill, external)
    main_skill.symlink_to(external, target_is_directory=True)
    skill_bytes = (external / "SKILL.md").read_bytes()

    with pytest.raises(DistributionError, match="linked path component"):
        subject.uninstall_project("pi")
    assert (external / "SKILL.md").read_bytes() == skill_bytes
    assert (project / ".agents/amkernel-official.json").is_file()


def test_linked_official_receipt_is_rejected_without_touching_target(
    project: Path,
    tmp_path: Path,
    official_package: tuple[dict[str, object], bytes, str],
) -> None:
    _manifest, _archive, _commit = official_package
    executable = tmp_path / "bin/amkernel"
    executable.parent.mkdir()
    executable.write_text("executable")
    subject = manager(project, executable.parent)
    subject.configure_project("pi", executable)
    state_path = project / ".agents/amkernel-official.json"
    external = tmp_path / "external-receipt.json"
    os.replace(state_path, external)
    state_path.symlink_to(external)
    receipt_bytes = external.read_bytes()

    status = subject.status("pi")
    assert not status.skill_provenance
    assert not status.skill_content_verified
    with pytest.raises(DistributionError, match="linked path component"):
        subject.uninstall_project("pi")
    assert external.read_bytes() == receipt_bytes


def test_official_git_metadata_is_rejected_instead_of_ignored(
    project: Path,
    tmp_path: Path,
    official_package: tuple[dict[str, object], bytes, str],
) -> None:
    _manifest, _archive, commit = official_package
    executable = tmp_path / "bin/amkernel"
    executable.parent.mkdir()
    executable.write_text("executable")
    subject = manager(project, executable.parent)
    subject.configure_project("pi", executable)
    source = project / f".agents/vendor/appium-skills/{commit}"
    nested_git = source / "skills/.git"
    nested_git.mkdir()
    (nested_git / "unverified.py").write_text("unverified\n")
    external = tmp_path / "external-git"
    external.mkdir()
    (external / "held.txt").write_text("held\n")

    assert subject.status("pi").detail is not None
    with pytest.raises(DistributionError, match=r"\.git is forbidden"):
        subject.configure_project("pi", executable)
    (nested_git / "unverified.py").unlink()
    nested_git.rmdir()
    nested_git.symlink_to(external, target_is_directory=True)
    with pytest.raises(DistributionError, match=r"\.git is forbidden"):
        subject.configure_project("pi", executable)
    assert (external / "held.txt").read_text() == "held\n"
    nested_git.unlink()
    (source / ".git").mkdir()
    with pytest.raises(DistributionError, match=r"\.git is forbidden"):
        subject.configure_project("pi", executable)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("args", ["--version"]),
        ("tools", []),
        ("disabled", True),
        ("type", "http"),
    ),
)
def test_copilot_status_detects_managed_launch_field_drift(
    project: Path,
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    executable = tmp_path / "bin/amkernel"
    executable.parent.mkdir()
    executable.write_text("executable")
    subject = manager(project, executable.parent)
    assert subject.configure_project("copilot", executable).mcp_configured
    path = project / ".mcp.json"
    parsed = json.loads(path.read_text())
    parsed["mcpServers"]["amkernel"][field] = value
    path.write_text(json.dumps(parsed))

    status = subject.status("copilot")

    assert not status.mcp_configured
    assert status.detail is not None


def test_symlinked_lock_is_rejected_without_touching_external_file(
    project: Path, tmp_path: Path
) -> None:
    executable = tmp_path / "bin/amkernel"
    executable.parent.mkdir()
    executable.write_text("executable")
    subject = manager(project, executable.parent)
    lock = subject._project_lock_path()
    lock.parent.mkdir(parents=True)
    external = tmp_path / "external.lock"
    external.write_text("held\n")
    lock.symlink_to(external)

    with pytest.raises(DistributionError, match="symbolic link"):
        subject.configure_project("omp", executable)

    assert external.read_text() == "held\n"


def test_broken_linked_managed_ancestor_is_rejected_without_creation(
    project: Path, tmp_path: Path
) -> None:
    executable = tmp_path / "bin/amkernel"
    executable.parent.mkdir()
    executable.write_text("executable")
    missing = tmp_path / "missing-agents"
    (project / ".agents").symlink_to(missing, target_is_directory=True)

    with pytest.raises(DistributionError, match="not a real directory"):
        manager(project, executable.parent).configure_project("omp", executable)

    assert not missing.exists()


def test_config_symlink_is_rejected_without_touching_target(project: Path, tmp_path: Path) -> None:
    executable = tmp_path / "bin/amkernel"
    executable.parent.mkdir()
    executable.write_text("executable")
    external = tmp_path / "external-mcp.json"
    external.write_text(json.dumps({"mcpServers": {"kept": {"command": "kept"}}}))
    (project / ".omp").mkdir()
    (project / ".omp/mcp.json").symlink_to(external)

    with pytest.raises(DistributionError, match="must not be a symbolic link"):
        manager(project, executable.parent).configure_project("omp", executable)

    assert json.loads(external.read_text()) == {"mcpServers": {"kept": {"command": "kept"}}}
    assert not (project / ".agents").exists()


def test_official_archive_rejects_unsafe_or_unexpected_members() -> None:
    expected = {"ok.txt": _sha(b"ok")}
    with pytest.raises(DistributionError, match="unsafe path"):
        _validated_archive_members(_tar_bytes({"../escape": b"x"}), expected, "archive")
    with pytest.raises(DistributionError, match="unexpected member"):
        _validated_archive_members(_tar_bytes({"extra.txt": b"x"}), expected, "archive")
    with pytest.raises(DistributionError, match="sha256 mismatch"):
        _validated_archive_members(_tar_bytes({"ok.txt": b"tampered"}), expected, "archive")
    with pytest.raises(DistributionError, match="missing file"):
        _validated_archive_members(_tar_bytes({}), expected, "archive")

    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        link = tarfile.TarInfo("link")
        link.type = tarfile.SYMTYPE
        link.linkname = "ok.txt"
        archive.addfile(link)
    with pytest.raises(DistributionError, match="non-regular member"):
        _validated_archive_members(stream.getvalue(), {"link": _sha(b"")}, "archive")

    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        directory = tarfile.TarInfo("nested")
        directory.type = tarfile.DIRTYPE
        archive.addfile(directory)
        content = b"ok"
        info = tarfile.TarInfo("nested/ok.txt")
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))
    assert _validated_archive_members(
        stream.getvalue(), {"nested/ok.txt": _sha(b"ok")}, "archive"
    ) == {"nested/ok.txt": b"ok"}


def test_package_spec_reuses_local_wheel_or_uses_registry(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject = manager(project, tmp_path / "bin")
    local_wheel = "file:///tmp/amkernel-0.1.0-py3-none-any.whl"
    distribution = SimpleNamespace(read_text=lambda name: json.dumps({"url": local_wheel}))
    monkeypatch.setattr("amkernel.distribution.metadata.distribution", lambda name: distribution)
    assert subject._package_spec() == local_wheel

    distribution.read_text = lambda name: None
    assert subject._package_spec() == "amkernel"


def test_install_runtime_uses_uv_tool_and_requires_resulting_executable(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = tmp_path / "bin"
    calls: list[tuple[str, ...]] = []

    def run(argv: Sequence[str]) -> CommandResult:
        values = tuple(argv)
        calls.append(values)
        if values[-3:] == ("tool", "dir", "--bin"):
            return CommandResult(values, 0, f"{bin_dir}\n", "", False)
        if values[1:3] == ("tool", "install"):
            bin_dir.mkdir()
            (bin_dir / "amkernel").write_text("executable")
        return CommandResult(values, 0, "", "", False)

    monkeypatch.setattr("amkernel.distribution.shutil.which", lambda name: "/usr/bin/uv")
    executable = DistributionManager(project, runner=run).install_runtime()

    assert executable == bin_dir / "amkernel"
    assert calls[0][:3] == ("/usr/bin/uv", "tool", "install")


def test_status_detects_modified_or_version_drifted_skill(project: Path, tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    executable = bin_dir / "amkernel"
    executable.parent.mkdir()
    executable.write_text("executable")
    subject = manager(project, bin_dir)
    assert subject.configure_project("omp", executable).detail is None

    skill = project / ".agents/skills/amkernel/SKILL.md"
    skill.write_text(skill.read_text() + "\nmodified\n")
    status = subject.status("omp")

    assert status.detail == "run `amkernel install` to repair Runtime, Skill, or MCP drift"
    assert not status.restart_required


@pytest.mark.parametrize(
    "relative",
    (
        "references/official-skills.json",
        "references/android-setup.md",
        "references/android-execution.md",
        "references/ios-setup.md",
        "scripts/verify_official_skills.py",
    ),
)
def test_status_detects_tampered_or_deleted_skill_support_files(
    project: Path, tmp_path: Path, relative: str
) -> None:
    bin_dir = tmp_path / "bin"
    executable = bin_dir / "amkernel"
    executable.parent.mkdir()
    executable.write_text("executable")
    subject = manager(project, bin_dir)
    assert subject.configure_project("omp", executable).detail is None

    support_file = project / ".agents/skills/amkernel" / relative
    support_file.write_text(support_file.read_text() + " ")
    assert subject.status("omp").detail is not None

    assert subject.configure_project("omp", executable).detail is None
    support_file.unlink()
    assert subject.status("omp").detail is not None


@pytest.mark.parametrize(
    "existing_entry",
    (
        '[mcp_servers.amkernel]\ncommand = "old"\ncwd = "/old"\n',
        '["mcp_servers".amkernel]\ncommand = "old"\ncwd = "/old"\n',
        'mcp_servers.amkernel = { command = "old", cwd = "/old" }\n',
        (
            '[mcp_servers.amkernel]\ncommand = "old"\ncwd = "/old"\n'
            '[mcp_servers.amkernel.env]\nTOKEN = "old"\n'
        ),
    ),
)
def test_codex_existing_unmarked_entry_is_repaired_without_losing_other_tables(
    project: Path, tmp_path: Path, existing_entry: str
) -> None:
    path = project / ".codex/config.toml"
    path.parent.mkdir()
    path.write_text(existing_entry + "\n[other]\nkept = true\n")
    executable = tmp_path / "bin/amkernel"
    executable.parent.mkdir()
    executable.write_text("executable")

    status = manager(project, executable.parent).configure_project("codex", executable)

    parsed = tomllib.loads(path.read_text())
    assert status.mcp_configured
    assert parsed["other"] == {"kept": True}
    assert parsed["mcp_servers"]["amkernel"]["command"] == str(executable)
    assert "env" not in parsed["mcp_servers"]["amkernel"]


def test_codex_aggregate_inline_entry_is_repaired_without_losing_other_servers(
    project: Path, tmp_path: Path
) -> None:
    path = project / ".codex/config.toml"
    path.parent.mkdir()
    path.write_text(
        'mcp_servers = { other = { command = "x" }, '
        'amkernel = { command = "old", cwd = "/old" } }\n'
    )
    executable = tmp_path / "bin/amkernel"
    executable.parent.mkdir()
    executable.write_text("executable")

    status = manager(project, executable.parent).configure_project("codex", executable)

    parsed = tomllib.loads(path.read_text())
    assert status.mcp_configured
    assert parsed["mcp_servers"]["other"] == {"command": "x"}
    assert parsed["mcp_servers"]["amkernel"]["command"] == str(executable)


def test_codex_uninstall_removes_orphaned_amkernel_subtables(project: Path, tmp_path: Path) -> None:
    path = project / ".codex/config.toml"
    path.parent.mkdir()
    path.write_text('[mcp_servers.amkernel.env]\nTOKEN = "old"\n\n[other]\nkept = true\n')
    executable = tmp_path / "bin/amkernel"
    executable.parent.mkdir()
    executable.write_text("executable")
    subject = manager(project, executable.parent)
    assert subject.configure_project("codex", executable).mcp_configured

    subject.uninstall_project("codex")

    parsed = tomllib.loads(path.read_text())
    assert parsed == {"other": {"kept": True}}


def test_stale_lock_file_does_not_block_project_repair(project: Path, tmp_path: Path) -> None:
    executable = tmp_path / "bin/amkernel"
    executable.parent.mkdir()
    executable.write_text("executable")
    subject = manager(project, executable.parent)
    lock = subject._project_lock_path()
    lock.parent.mkdir(parents=True)
    lock.write_text("999999\n")

    status = subject.configure_project("omp", executable)

    assert status.mcp_configured


def test_update_upgrades_runtime_then_synchronizes_project_with_new_cli(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    executable = bin_dir / "amkernel"
    executable.write_text("executable")
    calls: list[tuple[str, ...]] = []

    def run(argv: Sequence[str]) -> CommandResult:
        values = tuple(argv)
        calls.append(values)
        if values[-3:] == ("tool", "dir", "--bin"):
            return CommandResult(values, 0, f"{bin_dir}\n", "", False)
        return CommandResult(values, 0, "{}", "", False)

    monkeypatch.setattr("amkernel.distribution.shutil.which", lambda name: "/usr/bin/uv")
    subject = DistributionManager(project, runner=run, data_home=tmp_path / "data")
    subject.configure_project("omp", executable)

    status = subject.update("omp")

    assert status.mcp_configured
    assert ("/usr/bin/uv", "tool", "upgrade", "amkernel") in calls
    assert (
        str(executable),
        "install",
        "--client",
        "omp",
        "--scope",
        "project",
        "--project",
        str(project),
        "--yes",
        "--json",
    ) in calls


def test_status_is_actionable_when_no_supported_client_is_detected(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("amkernel.distribution.shutil.which", lambda name: None)

    status = manager(project, tmp_path / "bin").status()

    assert not status.mcp_configured
    assert status.detail == (
        "no supported Coding Agent detected; pass --client omp, pi, codex, or copilot"
    )
