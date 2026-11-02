from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.e2e.discovery_fixture import build_fixture
from tests.e2e.skill_behavior import Evaluation
from tests.e2e.skill_discovery import _check_synthetic_selection, _evaluate_synthetic


@pytest.mark.parametrize("arguments", [["-invalid-option"], ["-jar", "application.jar"], []])
def test_java_rejects_non_version_invocations(tmp_path: Path, arguments: list[str]) -> None:
    fixture = build_fixture(tmp_path / "fixture", "prefer-explicit")
    assert fixture.expected_java is not None
    result = subprocess.run(
        [str(fixture.expected_java), *arguments],
        env=fixture.environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0


@pytest.mark.parametrize("destination_kind", ["absolute", "relative", "symlink"])
def test_devicectl_cannot_overwrite_outside_fixture(
    tmp_path: Path, destination_kind: str
) -> None:
    fixture = build_fixture(tmp_path / "fixture", "prefer-explicit")
    outside = tmp_path / "outside"
    outside.mkdir()
    protected = outside / "result.json"
    protected.write_text("existing unrelated data", encoding="utf-8")
    if destination_kind == "absolute":
        destination = str(protected)
    elif destination_kind == "relative":
        destination = "../outside/result.json"
    else:
        (fixture.root / "escape").symlink_to(outside, target_is_directory=True)
        destination = str(fixture.root / "escape" / "result.json")
    command = fixture.contract["physical"]["argv"][:3]
    result = subprocess.run(
        [*command, "--json-output", destination],
        cwd=fixture.root,
        env=fixture.environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert protected.read_text(encoding="utf-8") == "existing unrelated data"


@pytest.mark.parametrize(
    "arguments",
    [
        ["list", "devices", "booted", "--json"],
        ["list", "devices", "--unsupported", "--json"],
        ["list", "runtimes", "--unsupported", "--json"],
    ],
)
def test_simctl_rejects_unimplemented_filters_and_options(
    tmp_path: Path, arguments: list[str]
) -> None:
    fixture = build_fixture(tmp_path / "fixture", "prefer-explicit")
    executable = fixture.contract["simulators"]["argv"][0]
    result = subprocess.run(
        [executable, *arguments],
        env=fixture.environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0


@pytest.mark.parametrize("arguments", [["-v", "21"], ["--unsupported"], []])
def test_java_inventory_rejects_unimplemented_selection_options(
    tmp_path: Path, arguments: list[str]
) -> None:
    fixture = build_fixture(tmp_path / "fixture", "fallback-bundled")
    executable = fixture.contract["javaInventory"]["argv"][0]
    result = subprocess.run(
        [executable, *arguments],
        env=fixture.environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0


@pytest.mark.parametrize(
    ("field", "incorrect"),
    [("major", 11), ("version", "11.0.27"), ("javaHome", "/unobserved/jdk")],
)
def test_java_facts_must_match_execution_even_when_selection_is_unchanged(
    tmp_path: Path, field: str, incorrect: object
) -> None:
    fixture = build_fixture(tmp_path / "fixture", "fallback-bundled")
    for command in fixture.contract["commands"]:
        if command["kind"].startswith("java-") and command["kind"] != "java-inventory":
            subprocess.run(
                command["argv"],
                env=fixture.environment,
                capture_output=True,
                text=True,
                check=False,
            )
    journal = fixture.snapshot()["commands"]
    reported: dict[str, dict[str, Any]] = {}
    for candidate in fixture.contract["javaCandidates"]:
        if not candidate["exists"]:
            continue
        observed = next(item for item in journal if item["kind"] == candidate["kind"])
        major = observed["major"]
        reported[candidate["executable"]] = {
            "exists": True,
            "executed": True,
            "exitCode": observed["exitCode"],
            "version": observed["version"],
            "major": major,
            "javaHome": observed["javaHome"],
            "eligible": observed["exitCode"] == 0 and major is not None and major >= 21,
        }
    final = {"selectedJava": {"executable": str(fixture.expected_java)}}
    truthful = Evaluation("truthful")
    _check_synthetic_selection(truthful, fixture.contract, fixture, final, journal, reported)
    assert all(check["ok"] for check in truthful.checks)

    registered = next(
        item for item in fixture.contract["javaCandidates"] if item["id"] == "registered"
    )
    reported[registered["executable"]][field] = incorrect
    misstated = Evaluation("misstated")
    _check_synthetic_selection(misstated, fixture.contract, fixture, final, journal, reported)
    checks = {check["id"]: check["ok"] for check in misstated.checks}
    assert checks["selected-java-expected"] is True
    assert checks["selection-rejects-earlier-or-ineligible-candidates"] is False


@pytest.mark.parametrize("surface", ["final", "output"])
@pytest.mark.parametrize("false_claim", ["present", "version", "extra"])
def test_missing_java_cannot_be_reported_as_observed(
    tmp_path: Path, surface: str, false_claim: str
) -> None:
    fixture = build_fixture(tmp_path / "fixture", "missing")
    candidates = [
        {
            "executable": item["executable"],
            "exists": False,
            "executed": False,
            "eligible": False,
            "exitCode": None,
            "version": None,
            "major": None,
            "javaHome": None,
        }
        for item in fixture.contract["javaCandidates"]
    ]
    physical = {
        "discovered": 0, "discoveredUnknown": False,
        "connected": 0, "connectedUnknown": False,
        "usableForDevelopment": None, "usableForDevelopmentUnknown": True,
        "readyForXcuitest": None, "readyForXcuitestUnknown": True,
    }
    simulators = {
        "discovered": 0, "discoveredUnknown": False,
        "runtimeCount": 0, "runtimeCountUnknown": False,
    }
    final = {
        "selectedJava": {"executable": None},
        "javaCandidates": [dict(item) for item in candidates],
        "physical": physical,
        "simulators": simulators,
    }
    output = {"javaCandidates": candidates, "physical": physical, "simulators": simulators}
    observations = [{"factObjects": [output]}]
    check_id = (
        "candidate-facts-present" if surface == "final" else "python-output-candidate-execution"
    )
    truthful = Evaluation("truthful-missing")
    _evaluate_synthetic(truthful, fixture, [], final, observations)
    assert next(check["ok"] for check in truthful.checks if check["id"] == check_id) is True

    claimed = final["javaCandidates"] if surface == "final" else candidates
    assert isinstance(claimed, list)
    if false_claim == "present":
        claimed[0].update(exists=True, executed=True, eligible=True, exitCode=0, major=21)
    elif false_claim == "version":
        claimed[0]["version"] = "21.0.6"
    else:
        claimed.append({**candidates[0], "executable": "/invented/bin/java"})
    misstated = Evaluation("misstated-missing")
    _evaluate_synthetic(misstated, fixture, [], final, observations)
    assert next(check["ok"] for check in misstated.checks if check["id"] == check_id) is False


@pytest.mark.parametrize(
    ("variant", "query_succeeds", "readiness", "accepted"),
    [
        ("missing", True, 0, True),
        ("missing", False, 0, False),
        ("prefer-explicit", True, 0, False),
        ("missing", True, None, True),
        ("prefer-explicit", True, None, True),
    ],
)
def test_zero_readiness_requires_a_successfully_observed_empty_inventory(
    tmp_path: Path, variant: str, query_succeeds: bool,
    readiness: int | None, accepted: bool,
) -> None:
    fixture = build_fixture(tmp_path / "fixture", variant)
    argv = fixture.contract["physical"]["argv"]
    result = subprocess.run(
        argv if query_succeeds else [*argv, "--unsupported"],
        env=fixture.environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is query_succeeds
    population = 0 if variant == "missing" else 1
    final = {
        "selectedJava": {"executable": None},
        "physical": {
            "discovered": population, "discoveredUnknown": False,
            "connected": population, "connectedUnknown": False,
            "usableForDevelopment": readiness,
            "usableForDevelopmentUnknown": readiness is None,
            "readyForXcuitest": readiness,
            "readyForXcuitestUnknown": readiness is None,
        },
    }
    evaluation = Evaluation("physical-population")
    _evaluate_synthetic(evaluation, fixture, [], final, [])
    assert next(
        check["ok"] for check in evaluation.checks if check["id"] == "physical-layers-truthful"
    ) is accepted
