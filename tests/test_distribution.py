from __future__ import annotations

import json
import os
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import cast

import pytest

from amkernel.distribution import Client, CommandResult, DistributionError, DistributionManager


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
            return CommandResult(values, 0, "amkernel 0.0.0\n", "", False)
        return CommandResult(values, 0, "", "", False)

    return DistributionManager(project, runner=run, data_home=project.parent / "data")


def test_auto_client_detection_rejects_ambiguous_project_markers(
    project: Path, tmp_path: Path
) -> None:
    (project / ".omp").mkdir()
    (project / ".pi").mkdir()
    subject = manager(project, tmp_path / "bin")

    with pytest.raises(DistributionError, match="multiple Coding Agents detected"):
        subject.select_client("auto")

    assert not (project / ".agents").exists()


def test_auto_client_detection_rejects_ambiguous_installed_clients(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("amkernel.distribution.shutil.which", lambda name: f"/bin/{name}")
    subject = manager(project, tmp_path / "bin")

    with pytest.raises(DistributionError, match="multiple Coding Agents detected"):
        subject.select_client("auto")


@pytest.mark.parametrize(
    ("client", "relative"),
    (("omp", ".omp/mcp.json"), ("pi", ".pi/mcp.json"), ("codex", ".codex/config.toml")),
)
def test_configure_project_installs_shared_skill_and_native_mcp_without_losing_config(
    project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, client: str, relative: str
) -> None:
    bin_dir = tmp_path / "bin"
    executable = bin_dir / ("amkernel.exe" if os.name == "nt" else "amkernel")
    executable.parent.mkdir()
    executable.write_text("executable")
    target = project / relative
    target.parent.mkdir(parents=True)
    if client == "codex":
        target.write_text('[model_provider]\nname = "kept"\n')
    else:
        target.write_text(json.dumps({"kept": {"value": True}}))

    subject = manager(project, bin_dir)
    status = subject.configure_project(cast(Client, client), executable)
    managed_paths = (
        target,
        project / ".agents/skills/amkernel/SKILL.md",
        project / ".agents/skills/amkernel/references/official-skills.json",
        project / ".agents/skills/amkernel/.amkernel-metadata.json",
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
    assert not (project / ".amkernel.install.lock").exists()


def test_uninstall_removes_only_managed_project_entries(project: Path, tmp_path: Path) -> None:
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
    assert subject.known_projects() == {}


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


def test_status_detects_tampered_or_deleted_skill_support_files(
    project: Path, tmp_path: Path
) -> None:
    bin_dir = tmp_path / "bin"
    executable = bin_dir / "amkernel"
    executable.parent.mkdir()
    executable.write_text("executable")
    subject = manager(project, bin_dir)
    assert subject.configure_project("omp", executable).detail is None

    manifest = project / ".agents/skills/amkernel/references/official-skills.json"
    manifest.write_text(manifest.read_text() + " ")
    assert subject.status("omp").detail is not None

    assert subject.configure_project("omp", executable).detail is None
    verifier = project / ".agents/skills/amkernel/scripts/verify_official_skills.py"
    verifier.unlink()
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
    assert status.detail == "no supported Coding Agent detected; pass --client omp, pi, or codex"
