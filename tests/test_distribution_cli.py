from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from amkernel.cli import main
from amkernel.distribution import Client, ProjectStatus


def test_automated_mutation_requires_json(
    project_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = main(
        [
            "install",
            "--client",
            "omp",
            "--scope",
            "project",
            "--project",
            str(project_path),
            "--yes",
        ]
    )

    assert result == 2
    assert capsys.readouterr().err == "amkernel: automated mutations require --json\n"


def test_json_mode_returns_structured_bounded_error(
    project_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = main(
        [
            "install",
            "--scope",
            "project",
            "--project",
            str(project_path),
            "--yes",
            "--json",
        ]
    )

    output = capsys.readouterr()
    assert result == 2
    assert output.err == ""
    assert json.loads(output.out) == {
        "ok": False,
        "error": {
            "type": "DistributionError",
            "message": "automated project mutations require an explicit --client",
        },
    }
    assert len(output.out.encode()) < 4096


def test_automated_project_mutation_requires_explicit_scope(
    project_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = main(
        [
            "install",
            "--client",
            "omp",
            "--project",
            str(project_path),
            "--yes",
            "--json",
        ]
    )

    output = capsys.readouterr()
    assert result == 2
    assert json.loads(output.out)["error"]["message"] == (
        "automated project mutations require --scope project"
    )


@pytest.mark.parametrize(
    ("candidates", "answers", "expected", "prompts"),
    (
        (("omp", "codex"), ("2", "y"), "codex", True),
        ((), ("3", "y"), "codex", True),
        (("codex",), ("y",), "codex", False),
    ),
)
def test_interactive_install_selects_one_client(
    project_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    candidates: tuple[Client, ...],
    answers: tuple[str, ...],
    expected: Client,
    prompts: bool,
) -> None:
    installed: list[Client] = []

    class InteractiveInput:
        def isatty(self) -> bool:
            return True

    class FakeManager:
        def __init__(self, project: Path) -> None:
            self.project = project

        def client_candidates(self) -> tuple[Client, ...]:
            return candidates

        def planned_changes(self, client: Client) -> tuple[str, ...]:
            return (f"Project MCP ({client}): config",)

        def install(self, requested_client: Client) -> ProjectStatus:
            installed.append(requested_client)
            return ProjectStatus(
                str(self.project), requested_client, "/managed/bin/amkernel", True, True, True, True
            )

    responses = iter(answers)
    monkeypatch.setattr("amkernel.cli.DistributionManager", FakeManager)
    monkeypatch.setattr("amkernel.cli.sys.stdin", InteractiveInput())
    monkeypatch.setattr("builtins.input", lambda: next(responses))

    result = main(["install", "--project", str(project_path), "--json"])

    output = capsys.readouterr()
    assert result == 0
    assert installed == [expected]
    assert ("Select the Coding Agent" in output.err) is prompts
    assert json.loads(output.out)["client"] == expected


def test_non_interactive_install_requires_explicit_client(
    project_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    class NonInteractiveInput:
        def isatty(self) -> bool:
            return False

    monkeypatch.setattr("amkernel.cli.sys.stdin", NonInteractiveInput())

    result = main(["install", "--project", str(project_path)])

    assert result == 2
    assert capsys.readouterr().err == (
        "amkernel: non-interactive installation requires an explicit --client\n"
    )


def test_install_discloses_exact_changes_before_assumed_consent(
    project_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeManager:
        def __init__(self, project: Path) -> None:
            self.project = project

        def select_client(self, requested: str) -> Client:
            return cast(Client, requested)

        def planned_changes(self, client: Client) -> tuple[str, ...]:
            return (
                "User Runtime: /managed/bin/amkernel",
                f"Project Skill: {self.project / '.agents/skills/amkernel'}",
                f"Project MCP ({client}): {self.project / '.omp/mcp.json'}",
            )

        def install(self, requested_client: str) -> ProjectStatus:
            return ProjectStatus(
                str(self.project),
                requested_client,
                "/managed/bin/amkernel",
                True,
                True,
                True,
                True,
                None,
                "1.0.0",
                "1.0.0",
            )

    monkeypatch.setattr("amkernel.cli.DistributionManager", FakeManager)

    result = main(
        [
            "install",
            "--client",
            "omp",
            "--scope",
            "project",
            "--project",
            str(project_path),
            "--yes",
            "--json",
        ]
    )

    output = capsys.readouterr()
    assert result == 0
    assert "User Runtime: /managed/bin/amkernel" in output.err
    assert f"Project Skill: {project_path / '.agents/skills/amkernel'}" in output.err
    assert f"Project MCP (omp): {project_path / '.omp/mcp.json'}" in output.err
    assert json.loads(output.out)["mcp_configured"] is True


def test_global_uninstall_json_reports_known_project_references(
    project_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeManager:
        def __init__(self, project: Path) -> None:
            self.project = project

        def known_projects(self) -> dict[str, str]:
            return {"/projects/one": "omp", "/projects/two": "pi"}

        def uninstall_global(self) -> None:
            pass

        def status(self, client: Client | None = None) -> ProjectStatus:
            return ProjectStatus(str(self.project), client, None, False, False, False, False)

    monkeypatch.setattr("amkernel.cli.DistributionManager", FakeManager)

    result = main(
        [
            "uninstall",
            "--global",
            "--project",
            str(project_path),
            "--yes",
            "--json",
        ]
    )

    output = capsys.readouterr()
    assert result == 0
    assert json.loads(output.out)["known_project_references"] == [
        "/projects/one",
        "/projects/two",
    ]


@pytest.fixture
def project_path(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    return project
