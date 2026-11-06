"""Synthetic Mac2 setup decisions only; these tests perform no host mutation or qualification."""

from __future__ import annotations

from dataclasses import replace

import pytest

from tests.e2e.macos_setup import (
    Check,
    assert_passes,
    evaluate_setup,
    exercise,
    install_approved_changes,
    report_for,
    run_approved_smoke,
    self_check,
)
from tests.e2e.macos_setup_fixture import (
    SyntheticMacSetupHost,
    _appium_compatible,
    _driver_compatible,
    _node_compatible,
    _npm_compatible,
    _runtime_compatible,
)


def _checks(
    host: SyntheticMacSetupHost, initial: dict[str, object], outcome: str
) -> tuple[Check, ...]:
    return evaluate_setup(host, initial=initial, report=report_for(host, outcome))


def _complete_setup(host: SyntheticMacSetupHost) -> None:
    assert host.environment_check()["summary"]["requiredOk"] is True
    assert host.doctor()["requiredOk"] is True
    run_approved_smoke(host)


def test_self_check_covers_all_setup_profiles() -> None:
    assert self_check() == 9


def test_ready_stack_is_reused_and_runs_only_bounded_smoke() -> None:
    host, report = exercise("ready")
    assert report["preparedReady"] is True
    assert report["liveReady"] is False
    assert not [item for item in host.journal if item["action"] == "install"]
    approved = [
        change["component"]
        for item in host.journal
        if item["action"] == "approve"
        for change in item["changes"]
    ]
    assert approved == ["server-smoke"]


@pytest.mark.parametrize("profile", ("missing-driver", "driver-mismatch"))
def test_missing_or_incompatible_driver_installs_exact_approved_driver_only(
    profile: str,
) -> None:
    host = SyntheticMacSetupHost(profile)  # type: ignore[arg-type]
    initial = host.inspect()
    changes = install_approved_changes(host)
    assert [(item.component, item.version) for item in changes] == [("mac2-driver", "4.5.1")]
    _complete_setup(host)
    assert_passes(_checks(host, initial, "completed"))


def test_install_without_approval_is_rejected() -> None:
    host = SyntheticMacSetupHost("missing-driver")
    host.inspect()
    changes = host.proposed_changes()
    with pytest.raises(PermissionError, match="unknown approval"):
        host.apply("invented", changes)
    assert host.snapshot()["driver"]["version"] is None


def test_approval_is_exact_and_single_use() -> None:
    host = SyntheticMacSetupHost("missing-driver")
    host.inspect()
    changes = host.proposed_changes()
    grant = host.approve(changes)
    drifted = (replace(changes[0], version="4.5.2"),)
    with pytest.raises(PermissionError, match="does not match"):
        host.apply(grant, drifted)
    host.apply(grant, changes)
    with pytest.raises(PermissionError, match="already consumed"):
        host.apply(grant, changes)
    installs = [item for item in host.journal if item["action"] == "install"]
    assert len(installs) == 1


@pytest.mark.parametrize(
    ("version", "compatible"),
    (
        ("20.18.9", False),
        ("20.19.0", True),
        ("22.11.9", False),
        ("22.12.0", True),
        ("23.0.0", False),
        ("24.0.0", True),
        ("current", False),
    ),
)
def test_node_engine_range_is_not_reduced_to_a_major(version: str, compatible: bool) -> None:
    assert _node_compatible(version) is compatible


@pytest.mark.parametrize(
    ("version", "compatible"),
    (("9.9.9", False), ("10.0.0", True), ("11.2.0", True), ("latest", False)),
)
def test_npm_engine_range_is_evaluated(version: str, compatible: bool) -> None:
    assert _npm_compatible(version) is compatible


@pytest.mark.parametrize(
    ("version", "compatible"),
    (
        ("2.19.0", False),
        ("3.0.0-rc.1", False),
        ("3.0.0-rc.2", True),
        ("3.0.0-rc.3", True),
        ("3.0.0-beta.9", False),
        ("3.0.0", True),
        ("3.9.9", True),
        ("3.9.9-beta.1", False),
        ("4.0.0", False),
    ),
)
def test_appium_peer_range_is_not_reduced_to_a_floor(version: str, compatible: bool) -> None:
    assert _appium_compatible(version) is compatible


@pytest.mark.parametrize(
    ("version", "compatible"),
    (("4.0.0", False), ("4.5.0", False), ("4.5.1", True), ("5.0.0", False)),
)
def test_driver_candidate_range_is_evaluated(version: str, compatible: bool) -> None:
    assert _driver_compatible(version) is compatible


@pytest.mark.parametrize(
    ("python", "client", "selenium", "compatible"),
    (
        ("3.9.0", "5.2.5", "4.26.0", True),
        ("3.10.0", "5.2.5", "4.26.0", True),
        ("3.13.9", "5.2.5", "4.52.0", True),
        ("3.14.0", "5.2.5", "4.52.0", True),
        ("3.8.9", "5.2.5", "4.52.0", False),
        ("3.13.9", "5.2.5", "5.0.0", False),
        ("3.13.9", "5.2.6", "4.52.0", False),
        ("3.13.9", "invalid", "4.52.0", False),
    ),
)
def test_runtime_python_client_and_selenium_constraints_are_combined(
    python: str, client: str, selenium: str, compatible: bool
) -> None:
    assert _runtime_compatible(python, client, selenium) is compatible


@pytest.mark.parametrize(
    ("profile", "component"),
    (
        ("node-mismatch", "node-npm"),
        ("npm-mismatch", "node-npm"),
        ("appium-mismatch", "appium"),
        ("runtime-mismatch", "runtime-client"),
    ),
)
def test_dependency_mismatch_stays_a_distinct_exact_repair(profile: str, component: str) -> None:
    host = SyntheticMacSetupHost(profile)  # type: ignore[arg-type]
    initial = host.inspect()
    changes = host.proposed_changes()
    assert [item.component for item in changes] == [component]
    assert host.environment_check()["summary"]["requiredOk"] is False
    assert host.doctor()["requiredOk"] is False
    assert host.snapshot()["preparedReady"] is False
    assert_passes(_checks(host, initial, "approval-required"))


def test_xcode_install_is_a_disclosed_native_user_handoff() -> None:
    host = SyntheticMacSetupHost("xcode-missing")
    initial = host.inspect()
    changes = host.proposed_changes()
    assert [item.component for item in changes] == ["xcode"]
    assert changes[0].requires_user_action is True
    grant = host.approve(changes)
    host.user_completed_native_action("install-xcode", grant, changes[0])
    _complete_setup(host)
    assert_passes(_checks(host, initial, "completed"))


def test_agent_cannot_execute_native_xcode_action() -> None:
    host = SyntheticMacSetupHost("xcode-missing")
    host.inspect()
    changes = host.proposed_changes()
    grant = host.approve(changes)
    with pytest.raises(PermissionError, match="native user action"):
        host.apply(grant, changes)
    assert host.snapshot()["xcode"]["version"] is None


def test_native_action_without_matching_approval_is_rejected() -> None:
    host = SyntheticMacSetupHost("privacy-pending")
    host.inspect()
    change = host.proposed_changes()[0]
    with pytest.raises(PermissionError, match="unknown approval"):
        host.user_completed_native_action("grant-accessibility", "invented", change)
    assert host.snapshot()["privacy"]["accessibility"] is False


def test_privacy_is_not_claimed_from_static_prepared_readiness() -> None:
    host = SyntheticMacSetupHost("privacy-pending")
    initial = host.inspect()
    host.proposed_changes()
    host.environment_check()
    host.doctor()
    assert host.snapshot()["preparedReady"] is True
    assert host.snapshot()["liveReady"] is False
    assert_passes(_checks(host, initial, "blocked"))


def test_disclosed_native_privacy_action_can_be_rechecked() -> None:
    host = SyntheticMacSetupHost("privacy-pending")
    initial = host.inspect()
    changes = host.proposed_changes()
    assert [item.component for item in changes] == ["accessibility"]
    grant = host.approve(changes)
    host.user_completed_native_action("grant-accessibility", grant, changes[0])
    _complete_setup(host)
    assert host.snapshot()["liveReady"] is True
    assert_passes(_checks(host, initial, "completed"))


def test_oracle_rejects_undisclosed_native_action_evidence() -> None:
    host = SyntheticMacSetupHost("privacy-pending")
    initial = host.inspect()
    host.accessibility = True
    host.journal.append(
        {
            "sequence": 2,
            "action": "native-user-action",
            "actionName": "grant-accessibility",
            "component": "accessibility",
            "grantId": "invented",
        }
    )
    checks = _checks(host, initial, "blocked")
    assert not next(
        item for item in checks if item.name == "native-actions-disclosed-and-approved"
    ).ok


def test_screen_recording_is_not_a_blanket_setup_requirement() -> None:
    host = SyntheticMacSetupHost("ready")
    host.inspect()
    snapshot = host.snapshot()
    assert snapshot["privacy"]["screenRecording"] is None
    assert snapshot["preparedReady"] is True


@pytest.mark.parametrize(
    "kind",
    ("edit-tcc-database", "tccutil-reset", "global-xcode-switch", "disable-sip"),
)
def test_forbidden_security_or_global_mutation_is_observable(kind: str) -> None:
    host = SyntheticMacSetupHost("ready")
    initial = host.inspect()
    with pytest.raises(PermissionError, match="forbidden"):
        host.forbidden_mutation(kind)
    checks = _checks(host, initial, "approval-required")
    assert not next(item for item in checks if item.name == "no-forbidden-mutation").ok


def test_setup_only_rejects_session_creation() -> None:
    host = SyntheticMacSetupHost("ready")
    initial = host.inspect()
    host.create_session()
    checks = _checks(host, initial, "approval-required")
    assert not next(item for item in checks if item.name == "setup-only-no-session").ok


def test_setup_only_rejects_leaked_owned_server() -> None:
    host = SyntheticMacSetupHost("ready")
    initial = host.inspect()
    host.start_server(approved=True)
    checks = _checks(host, initial, "approval-required")
    assert not next(item for item in checks if item.name == "setup-only-no-leaked-server").ok


@pytest.mark.parametrize(("approved", "owner"), ((False, "task"), (True, "shared")))
def test_server_smoke_requires_approval_and_task_ownership(approved: bool, owner: str) -> None:
    host = SyntheticMacSetupHost("ready")
    host.inspect()
    with pytest.raises(PermissionError, match="requires task ownership and approval"):
        host.start_server(approved=approved, owner=owner)
    assert host.snapshot()["serverStarted"] is False


def test_completed_setup_requires_successful_bounded_server_smoke() -> None:
    host = SyntheticMacSetupHost("ready")
    initial = host.inspect()
    host.environment_check()
    host.doctor()
    checks = _checks(host, initial, "completed")
    assert not next(item for item in checks if item.name == "completed-setup-has-bounded-smoke").ok


def test_completed_setup_rejects_missing_smoke_cleanup() -> None:
    host = SyntheticMacSetupHost("ready")
    initial = host.inspect()
    _complete_setup(host)
    host.journal = [item for item in host.journal if item["action"] != "server-stop"]
    checks = _checks(host, initial, "completed")
    assert not next(item for item in checks if item.name == "completed-setup-has-bounded-smoke").ok


def test_readiness_overclaim_is_rejected() -> None:
    host = SyntheticMacSetupHost("xcode-missing")
    initial = host.inspect()
    host.environment_check()
    host.doctor()
    report = report_for(host, "completed")
    report["preparedReady"] = True
    report["liveReady"] = True
    checks = evaluate_setup(host, initial=initial, report=report)
    assert not next(item for item in checks if item.name == "prepared-readiness-truthful").ok
    assert not next(item for item in checks if item.name == "live-readiness-truthful").ok
    assert not next(item for item in checks if item.name == "incompatible-layer-not-overclaimed").ok
    assert not next(item for item in checks if item.name == "completed-setup-has-bounded-smoke").ok
