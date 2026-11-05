"""Regressions for the synthetic iPhone setup decision experiment; no device qualification."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.e2e import ios_setup_fixture
from tests.e2e.ios_setup import (
    SetupOptions,
    _evaluate,
    _negative_mutations,
    _scripted_scenario,
)
from tests.e2e.ios_setup_fixture import (
    _DRIVER_COMPONENT,
    FixtureHost,
    IosSetupFixture,
    build_fixture,
)


def _driver_request(fixture: IosSetupFixture) -> dict[str, Any]:
    plan = copy.deepcopy(fixture.snapshot()["driverPlans"][_DRIVER_COMPONENT])
    return {
        "components": [_DRIVER_COMPONENT],
        "plan": {_DRIVER_COMPONENT: plan},
        "purpose": "Install only the requested synthetic XCUITest driver.",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", "unapproved-version"),
        ("source", "unknown-source"),
        ("backend", "different-manager"),
        ("appiumHome", "/shared/appium/home"),
        ("path", "/shared/system/location"),
        ("license", "different-license"),
        ("impact", "all projects"),
        ("elevation", True),
        ("persistence", True),
        ("rollback", ""),
    ],
)
def test_installation_approval_rejects_changed_scope(
    tmp_path: Path, field: str, value: Any
) -> None:
    fixture = build_fixture(tmp_path / "fixture", "missing-driver-approved")
    host = FixtureHost(fixture.root)
    request = _driver_request(fixture)
    request["plan"][_DRIVER_COMPONENT][field] = value
    decision = host.request_approval(request)
    assert decision["granted"] is False
    assert fixture.snapshot()["state"]["driver"]["installed"] is False
    assert fixture.snapshot()["grants"] == []


def test_installation_grant_is_exact_and_single_use(tmp_path: Path) -> None:
    fixture = build_fixture(tmp_path / "fixture", "missing-driver-approved")
    host = FixtureHost(fixture.root)
    approved = host.request_approval(_driver_request(fixture))
    grant = approved["grantId"]
    assert "error" in host.install("invented-grant", [_DRIVER_COMPONENT])
    assert "error" in host.install(grant, ["unapproved-component"])
    assert "error" in host.install(grant, [_DRIVER_COMPONENT, _DRIVER_COMPONENT])
    assert fixture.snapshot()["grants"][0]["used"] is False
    assert fixture.snapshot()["state"]["driver"]["installed"] is False

    assert "error" not in host.install(grant, [_DRIVER_COMPONENT])
    assert fixture.snapshot()["state"]["driver"]["installed"] is True
    assert fixture.snapshot()["grants"][0]["used"] is True
    assert "error" in host.install(grant, [_DRIVER_COMPONENT])
    installs = [entry for entry in fixture.snapshot()["journal"] if entry["event"] == "install"]
    assert len(installs) == 1


@pytest.mark.parametrize("kind", ["runtime", "signing"])
def test_repair_binds_effects_not_purpose_wording_and_refuses_incomplete_scope(
    tmp_path: Path, kind: str
) -> None:
    variant = "runtime-client-repair" if kind == "runtime" else "wda-expired-profile"
    fixture = build_fixture(tmp_path / "fixture", variant)
    host = FixtureHost(fixture.root)
    plan = host.inspect(kind)["repairPlan"]
    request = host.request_runtime_repair if kind == "runtime" else host.request_signing_repair
    apply = host.apply_runtime_repair if kind == "runtime" else host.apply_signing_repair
    refused_disclosure = request(
        {
            "plan": plan,
            "purpose": "Authorize the disclosed repair",
            "persistence": True,
        }
    )
    assert refused_disclosure["recoverable"] is False
    assert fixture.snapshot()["grants"] == []
    grant = request({"plan": plan, "purpose": "Authorize the disclosed repair"})["grantId"]
    partial = dict(plan)
    del partial[next(iter(partial))]
    refused = apply(grant, {"plan": partial, "purpose": "Apply the approved repair"})
    assert refused["recoverable"] is True
    for supplied in (plan, partial, {"plan": plan}):
        extra = apply(
            grant,
            {
                "plan": supplied,
                "purpose": "Apply the approved repair",
                "persistence": True,
            },
        )
        assert extra["recoverable"] is False
        assert fixture.snapshot()["grants"][0]["used"] is False
    wrapped = apply(grant, {"plan": {"plan": plan}, "purpose": "Apply the approved repair"})
    assert wrapped["recoverable"] is True
    assert fixture.snapshot()["grants"][0]["used"] is False
    changed = dict(plan)
    changed[next(iter(changed))] = "unapproved-effect"
    unsafe = apply(grant, {"plan": changed, "purpose": "Apply the approved repair"})
    assert unsafe["recoverable"] is False
    assert fixture.snapshot()["grants"][0]["used"] is False
    result = apply(grant, {"plan": plan, "purpose": "Apply the approved repair"})
    assert result["repaired"] is True
    assert fixture.snapshot()["grants"][0]["used"] is True
    assert "error" in apply(grant, {"plan": plan, "purpose": "Try again"})


def test_native_action_refusal_is_bounded_and_wrong_device_remains_unsafe(tmp_path: Path) -> None:
    inactive = FixtureHost(build_fixture(tmp_path / "inactive", "existing-physical").root)
    wrong_inactive = inactive.request_native_action(
        {
            "action": "unlock-and-trust",
            "device": "other-device",
        }
    )
    assert wrong_inactive["recoverable"] is False
    assert inactive.request_native_action({"action": "unlock-and-trust"})["recoverable"] is True
    assert inactive.recheck_native_action()["recoverable"] is True
    assert inactive.request_native_action({"action": "unlock-and-trust"})["recoverable"] is False
    active_fixture = build_fixture(tmp_path / "active", "pin-blocked-recheck")
    active = FixtureHost(active_fixture.root)
    refused = active.request_native_action({"action": "unlock-and-trust", "device": "other-device"})
    assert refused["recoverable"] is False
    assert not any(
        entry["event"] == "native-action" for entry in active_fixture.snapshot()["journal"]
    )


def test_doctor_rechecks_required_tooling_after_approved_driver_install(tmp_path: Path) -> None:
    fixture = build_fixture(tmp_path / "fixture", "missing-driver-approved")
    host = FixtureHost(fixture.root)
    assert host.inspect("doctor")["passed"] is False
    grant = host.request_approval(_driver_request(fixture))["grantId"]
    host.install(grant, [_DRIVER_COMPONENT])
    assert host.inspect("doctor")["passed"] is True


@pytest.mark.parametrize("version", ["v22.11.0", "v23.0.0", "not-a-version"])
def test_doctor_rejects_node_outside_selected_appium_declaration(
    tmp_path: Path, version: str
) -> None:
    fixture = build_fixture(tmp_path / "fixture", "existing-physical")
    fixture.state["appium"]["nodeVersion"] = version
    assert ios_setup_fixture._inspect_doctor(fixture)["passed"] is False


@pytest.mark.parametrize("version", ["v22.12.0", "v22.13.4", "v22.99.0"])
def test_doctor_accepts_node_within_selected_appium_declaration(
    tmp_path: Path, version: str
) -> None:
    fixture = build_fixture(tmp_path / "fixture", "existing-physical")
    fixture.state["appium"]["nodeVersion"] = version
    assert ios_setup_fixture._inspect_doctor(fixture)["passed"] is True


@pytest.mark.parametrize("kind", ["installation", "runtime", "signing"])
def test_secret_bearing_approval_is_refused_without_retaining_payload(
    tmp_path: Path, kind: str
) -> None:
    fixture = build_fixture(tmp_path / "fixture", "missing-driver-approved")
    host = FixtureHost(fixture.root)
    request: dict[str, Any] = {
        "plan": {"nested": [{"password": "fixture-secret-do-not-retain"}]},
        "purpose": "Prepare the fixture",
    }
    if kind == "installation":
        request["components"] = [_DRIVER_COMPONENT]
        decision = host.request_approval(request)
    elif kind == "runtime":
        decision = host.request_runtime_repair(request)
    else:
        decision = host.request_signing_repair(request)
    assert decision["granted"] is False
    assert fixture.snapshot()["grants"] == []
    assert "fixture-secret-do-not-retain" not in json.dumps(fixture.snapshot())
    assert "fixture-secret-do-not-retain" not in fixture.journal_path.read_text()


@pytest.mark.parametrize("pending", [False, True])
def test_native_recheck_rejects_wrong_device_without_changing_target(
    tmp_path: Path, pending: bool
) -> None:
    variant = "pin-blocked-recheck" if pending else "existing-physical"
    fixture = build_fixture(tmp_path / "fixture", variant)
    if pending:
        FixtureHost(fixture.root).request_native_action({"action": "unlock-and-trust"})
    before = fixture.snapshot()["state"]["target"]
    refused = ios_setup_fixture._call_tool(
        fixture, "recheck_native_action", {"device": "other-device"}
    )
    assert refused["recoverable"] is False
    assert fixture.snapshot()["state"]["target"] == before
    assert not any(
        entry.get("event") == "native-action" and entry.get("phase") == "completed"
        for entry in fixture.snapshot()["journal"]
    )
    if pending:
        result = ios_setup_fixture._call_tool(fixture, "recheck_native_action", {})
        assert result["target"]["locked"] is False
        assert result["target"]["trusted"] is True


def test_malformed_runtime_method_is_refused_and_mcp_host_keeps_serving(tmp_path: Path) -> None:
    fixture = build_fixture(tmp_path / "fixture", "runtime-client-repair")
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "request_runtime_repair",
                "arguments": {"plan": {"method": []}, "purpose": "Repair the fixture Runtime"},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "inspect_host", "arguments": {"area": "runtime"}},
        },
    ]
    process = subprocess.run(
        [sys.executable, "-S", ios_setup_fixture.__file__, "serve", "--root", str(fixture.root)],
        input="".join(json.dumps(message) + "\n" for message in messages),
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    responses = [json.loads(line) for line in process.stdout.splitlines()]
    assert [response["id"] for response in responses] == [1, 2]
    refusal = json.loads(responses[0]["result"]["content"][0]["text"])
    assert refusal["granted"] is False
    runtime = json.loads(responses[1]["result"]["content"][0]["text"])
    assert runtime["client"]["installed"] is False
    assert fixture.snapshot()["grants"] == []


@pytest.mark.parametrize(
    "scenario_id",
    [
        "existing-physical",
        "historical-unavailable",
        "missing-driver-approved",
        "missing-driver-unapproved",
        "runtime-client-repair",
        "compatibility-warning",
        "compatibility-violation",
        "wda-reusable-candidate",
        "wda-expired-profile",
        "pin-wait-recheck",
        "transport-timeout",
        "shared-resource",
        "explicit-live-validation",
    ],
)
def test_oracle_rejects_every_negative_mutation(tmp_path: Path, scenario_id: str) -> None:
    run = _scripted_scenario(tmp_path / "fixture", scenario_id)
    assert _evaluate(run)["status"] == "passed"
    mutations = _negative_mutations(scenario_id, run)
    for mutation in mutations:
        if not mutation.get("expectFailure", True):
            continue
        evaluation = _evaluate(mutation["run"])
        failed = {item["id"] for item in evaluation["checks"] if not item["ok"]}
        assert evaluation["status"] == "failed", mutation["name"]
        assert mutation["expected"] in failed, mutation["name"]


@pytest.mark.parametrize(
    "scenario_id",
    [
        "existing-physical",
        "missing-driver-approved",
        "runtime-client-repair",
        "shared-resource",
        "explicit-live-validation",
    ],
)
def test_oracle_accepts_normalized_mutations(tmp_path: Path, scenario_id: str) -> None:
    run = _scripted_scenario(tmp_path / "fixture", scenario_id)
    accepted = [
        mutation
        for mutation in _negative_mutations(scenario_id, run)
        if not mutation.get("expectFailure", True)
    ]
    assert accepted
    for mutation in accepted:
        evaluation = _evaluate(mutation["run"])
        failed = {item["id"] for item in evaluation["checks"] if not item["ok"]}
        assert evaluation["status"] == "passed", mutation["name"]
        assert mutation["expected"] not in failed, mutation["name"]


def test_native_exception_after_preflight_is_failed_and_evidence_is_scoped_and_sanitized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from tests.e2e import ios_setup
    from tests.e2e import skill_behavior as behavior

    wheel = tmp_path / "amkernel.whl"
    wheel.write_bytes(b"synthetic wheel placeholder")
    copilot = tmp_path / "copilot"
    copilot.write_text("#!/bin/sh\nexit 0\n")
    context = SimpleNamespace(
        base=tmp_path / "base",
        project=tmp_path / "project",
        home=tmp_path / "home",
        env={},
        token="secret-copilot-token",
        options=SimpleNamespace(model="test-model"),
        commands=[],
        isolation_before={"captured": "yes"},
        runtime_python=None,
    )
    (tmp_path / "base").mkdir()
    context.project.mkdir()
    monkeypatch.setattr(ios_setup, "_base_context", lambda _options: context)
    monkeypatch.setattr(behavior, "_preflight", lambda _context: {"ok": True, "checks": []})
    monkeypatch.setattr(behavior, "_copilot_version", lambda _path: "GitHub Copilot CLI test")
    monkeypatch.setattr(behavior, "_terminate_owned_runners", lambda _context, _phase: [])
    monkeypatch.setattr(behavior, "_prepare_isolation", lambda _base: {"captured": "yes"})

    def fail(_context: Any, _scenario_id: str) -> None:
        raise RuntimeError(f"native boom {_context.token}")

    monkeypatch.setattr(ios_setup, "_run_native_scenario", fail)
    options = SetupOptions(
        wheel=wheel,
        copilot=copilot,
        output=tmp_path / "evidence.json",
        scenarios=["existing-physical"],
        model="test-model",
        timeout=30.0,
        keep_temp=True,
        self_check=False,
        list_scenarios=False,
    )
    evidence = ios_setup.run_native(options)

    assert evidence["preflight"]["ok"] is True
    assert evidence["scope"].startswith("Real native GitHub Copilot CLI decisions")
    assert "not real workstation, device, simulator, or session qualification" in evidence["scope"]
    assert any("No real Xcode tool" in item for item in evidence["limitations"])
    assert evidence["summary"]["status"] == "failed"
    assert evidence["summary"]["failed"] == 1
    assert evidence["scenarios"][0]["status"] == "failed"
    assert evidence["scenarios"][0]["checks"][0]["id"] == "scenario-exception"
    serialized = (tmp_path / "evidence.json").read_text()
    assert "secret-copilot-token" not in serialized
    assert "$COPILOT_TOKEN" in serialized
    assert "native boom" in serialized
