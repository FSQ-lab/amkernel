"""Regressions for synthetic approval and readiness evidence; no platform qualification."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from tests.e2e.android_setup import (
    _evaluate,
    _negative_mutations,
    _scripted_scenario,
)
from tests.e2e.android_setup_fixture import (
    _CMDLINE_COMPONENT,
    _JAVA_COMPONENT,
    _SDK_COMPONENT,
    AndroidSetupFixture,
    FixtureHost,
    build_fixture,
)


def _request(fixture: AndroidSetupFixture, components: list[str]) -> dict[str, Any]:
    plans = fixture.snapshot()["installationPlans"]
    return {
        "components": components,
        "plan": {component: copy.deepcopy(plans[component]) for component in components},
        "purpose": "Prepare only the requested synthetic Android task.",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", "unapproved-version"),
        ("source", "unknown-source"),
        ("backend", "different-manager"),
        ("path", "/shared/system/location"),
        ("license", "different-agreement"),
        ("impact", "all projects"),
        ("elevation", True),
        ("persistence", True),
        ("rollback", ""),
    ],
)
def test_approval_rejects_changed_installation_scope(
    tmp_path: Path, field: str, value: object
) -> None:
    fixture = build_fixture(tmp_path / "fixture", "missing-java-approved")
    host = FixtureHost(fixture.root)
    request = _request(fixture, [_JAVA_COMPONENT])
    request["plan"][_JAVA_COMPONENT][field] = value
    decision = host.request_approval(request)
    assert decision["granted"] is False
    assert fixture.snapshot()["state"]["java"]["installed"] is False
    assert fixture.snapshot()["grants"] == []


def test_install_grant_is_exact_and_single_use(tmp_path: Path) -> None:
    fixture = build_fixture(tmp_path / "fixture", "missing-java-approved")
    host = FixtureHost(fixture.root)
    approved = host.request_approval(_request(fixture, [_JAVA_COMPONENT]))
    grant = approved["grantId"]
    assert "error" in host.install("invented-grant", [_JAVA_COMPONENT])
    assert "error" in host.install(grant, ["platform-tools"])
    assert fixture.snapshot()["state"]["java"]["installed"] is False

    result = host.install(grant, [_JAVA_COMPONENT])
    assert "error" not in result
    assert fixture.snapshot()["state"]["java"]["installed"] is True
    assert fixture.snapshot()["grants"][0]["used"] is True
    assert "error" in host.install(grant, [_JAVA_COMPONENT])
    installs = [entry for entry in fixture.snapshot()["journal"] if entry["event"] == "install"]
    assert len(installs) == 1


def test_absent_sdk_installs_only_approved_components(tmp_path: Path) -> None:
    fixture = build_fixture(tmp_path / "fixture", "missing-sdk-approved")
    host = FixtureHost(fixture.root)
    before = host.inspect("android-sdk")
    assert before["rootPresent"] is False
    assert before["manager"] is None
    assert before["installed"] == []
    components = [_CMDLINE_COMPONENT, "platform-tools", _SDK_COMPONENT]
    approved = host.request_approval(_request(fixture, components))
    assert "error" not in host.install(approved["grantId"], components)
    after = host.inspect("android-sdk")
    assert after["rootPresent"] is True
    assert set(after["installed"]) == set(components)
    assert not any(
        item.startswith(("emulator", "system-images", "platforms;")) for item in after["installed"]
    )


@pytest.mark.parametrize("variant", ["missing-java-approved", "missing-java-unapproved"])
def test_missing_java_has_no_reusable_jdk_candidate(tmp_path: Path, variant: str) -> None:
    fixture = build_fixture(tmp_path / "fixture", variant)
    candidates = FixtureHost(fixture.root).inspect("java")["candidates"]
    assert all(not candidate["exists"] and not candidate["executed"] for candidate in candidates)


@pytest.mark.parametrize(
    ("scenario_id", "negative"),
    [
        ("missing-java-approved", "unverified-install"),
        ("missing-java-approved", "install-plan-drift"),
        ("existing-physical", "raw-doctor-pass"),
        ("existing-physical", "physical-gated-on-emulator"),
        ("existing-physical", "physical-without-evidence"),
        ("existing-physical", "session-claim"),
        ("existing-physical", "forbidden-install"),
        ("avd-configured-not-booted", "avd-entry-ready"),
        ("node-engine-mismatch", "node-major-only-accepted"),
        ("node-engine-mismatch", "incompatible-node-ready"),
    ],
)
def test_oracle_rejects_false_readiness_and_authorization(
    tmp_path: Path, scenario_id: str, negative: str
) -> None:
    run, _fixture = _scripted_scenario(tmp_path / "fixture", scenario_id)
    cases = {
        name: (mutated, check) for name, mutated, check in _negative_mutations(scenario_id, run)
    }
    mutated, check_id = cases[negative]
    evaluation = _evaluate(mutated)
    failed = {item["id"] for item in evaluation["checks"] if not item["ok"]}
    assert evaluation["status"] == "failed"
    assert check_id in failed


def test_java_version_and_executable_must_be_the_same_observed_candidate(tmp_path: Path) -> None:
    run, fixture = _scripted_scenario(tmp_path / "fixture", "existing-physical")
    bundled = next(
        candidate
        for candidate in FixtureHost(fixture.root).inspect("java")["candidates"]
        if candidate["origin"] == "Android Studio JBR"
    )
    run["final_json"]["java"]["executable"] = bundled["executable"]
    evaluation = _evaluate(run)
    assert any(item["id"] == "java-evidence" and not item["ok"] for item in evaluation["checks"])


def test_missing_java_without_approval_cannot_be_ready(tmp_path: Path) -> None:
    run, fixture = _scripted_scenario(tmp_path / "fixture", "missing-java-no-approval")
    assert _evaluate(run)["status"] == "passed"
    assert run["final_json"]["setup"]["ready"] is False
    assert run["final_json"]["target"]["ready"] is True
    assert run["final_json"]["approvalRequired"] is True
    assert run["final_json"]["java"]["present"] is False
    assert not [entry for entry in fixture.snapshot()["journal"] if entry["event"] == "install"]


def test_failed_java_probe_cannot_prove_a_usable_candidate(tmp_path: Path) -> None:
    run, _fixture = _scripted_scenario(tmp_path / "fixture", "existing-physical")
    for entry in run["fixture"]["journal"]:
        if entry.get("tool") == "java":
            entry["exitCode"] = 1
    evaluation = _evaluate(run)
    assert any(item["id"] == "java-evidence" and not item["ok"] for item in evaluation["checks"])


def test_verified_path_alias_retains_its_own_probe_version(tmp_path: Path) -> None:
    run, _fixture = _scripted_scenario(tmp_path / "fixture", "existing-physical")
    probe = next(
        entry
        for entry in run["fixture"]["journal"]
        if entry.get("tool") == "java" and entry["facts"].get("version") == "21.0.6"
    )
    run["final_json"]["java"]["executable"] = probe["argv"][0]
    assert _evaluate(run)["status"] == "passed"


def test_connected_phone_does_not_clear_missing_java_setup_blocker(tmp_path: Path) -> None:
    run, _fixture = _scripted_scenario(tmp_path / "fixture", "missing-java-no-approval")
    run["final_json"]["setup"] = {"ready": True, "blockers": []}
    run["final_json"]["taskOutcome"] = "completed"
    evaluation = _evaluate(run)
    assert any(item["id"] == "setup-readiness" and not item["ok"] for item in evaluation["checks"])


@pytest.mark.parametrize("blockers", [None, "java", [None]])
def test_malformed_setup_blockers_are_failed_evidence(tmp_path: Path, blockers: object) -> None:
    run, _fixture = _scripted_scenario(tmp_path / "fixture", "missing-java-no-approval")
    run["final_json"]["setup"]["blockers"] = blockers
    evaluation = _evaluate(run)
    assert any(item["id"] == "setup-readiness" and not item["ok"] for item in evaluation["checks"])


def test_node_blocker_still_requires_authorization_to_change_dependency(tmp_path: Path) -> None:
    run, _fixture = _scripted_scenario(tmp_path / "fixture", "node-engine-mismatch")
    run["final_json"]["approvalRequired"] = False
    evaluation = _evaluate(run)
    assert any(item["id"] == "setup-readiness" and not item["ok"] for item in evaluation["checks"])


def test_installed_emulator_tools_do_not_complete_stopped_target_setup(tmp_path: Path) -> None:
    run, _fixture = _scripted_scenario(tmp_path / "fixture", "avd-configured-not-booted")
    run["final_json"]["setup"] = {"ready": True, "blockers": []}
    evaluation = _evaluate(run)
    assert any(item["id"] == "setup-readiness" and not item["ok"] for item in evaluation["checks"])
