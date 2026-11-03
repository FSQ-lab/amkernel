"""Behavioral regressions for the corrected #108 native Mac2 oracle."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.e2e.native_mac2_oracle import qualify

BASE = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


def _at(milliseconds: int) -> str:
    return (BASE + timedelta(milliseconds=milliseconds)).isoformat().replace("+00:00", "Z")


def _valid_record() -> dict[str, Any]:
    return {
        "schemaVersion": 2,
        "status": "not-qualified",
        "failedAt": None,
        "error": None,
        "before": {"calculator": [], "frontmostBundleId": "com.mitchellh.ghostty"},
        "after": {"calculator": [], "frontmostBundleId": "com.mitchellh.ghostty"},
        "cleanup": {
            "desktopRestored": True,
            "ownedServer": {
                "started": True,
                "pid": 1234,
                "pgid": 1234,
                "groupOwned": True,
                "stopAttempted": True,
                "exited": True,
                "processGroupGone": True,
                "appiumPortClosed": True,
                "wdaPortClosed": True,
            },
            "runner": {
                "entries": [{"runnerPid": 5678, "reason": "process-exit", "observedExit": True}],
                "observedGone": True,
            },
        },
        "server": {
            "pid": 1234,
            "pgid": 1234,
            "groupOwned": True,
            "endpoint": "http://127.0.0.1:63349",
            "shared": False,
            "ready": True,
        },
        "requestedIdentity": {
            "platformName": "Mac",
            "automationName": "Mac2",
            "bundleId": "com.apple.calculator",
            "noReset": True,
            "skipAppKill": True,
        },
        "native": {
            "process": {
                "exitCode": 0,
                "timedOut": False,
                "durationMs": 1000,
                "runnerCleanup": [
                    {"runnerPid": 5678, "reason": "process-exit", "observedExit": True}
                ],
            },
            "calls": [
                {
                    "toolName": "amkernel-python_exec",
                    "mcpToolName": "python_exec",
                    "success": True,
                    "status": "completed",
                    "kernelState": "alive",
                    "executionCount": 1,
                    "startedAt": _at(0),
                    "completedAt": _at(100),
                },
                {
                    "toolName": "amkernel-python_exec",
                    "mcpToolName": "python_exec",
                    "success": True,
                    "status": "failed",
                    "kernelState": "alive",
                    "executionCount": 2,
                    "startedAt": _at(200),
                    "completedAt": _at(210),
                    "errorType": "ModuleNotFoundError",
                },
                {
                    "toolName": "amkernel-python_exec",
                    "mcpToolName": "python_exec",
                    "success": True,
                    "status": "completed",
                    "kernelState": "alive",
                    "executionCount": 3,
                    "startedAt": _at(300),
                    "completedAt": _at(500),
                },
                {
                    "toolName": "amkernel-python_exec",
                    "mcpToolName": "python_exec",
                    "success": True,
                    "status": "completed",
                    "kernelState": "alive",
                    "executionCount": 4,
                    "startedAt": _at(550),
                    "completedAt": _at(650),
                },
                {"toolName": "view", "success": True},
            ],
            "finalStatus": {
                "taskOutcome": "completed",
                "stateRestoration": "restored",
                "sessionCleanup": "cleaned",
                "serverCleanup": "not-owned",
            },
            "finalReportSha256": "a" * 64,
            "mainSkillLoaded": True,
        },
        "appium": {
            "logSha256": "b" * 64,
            "logBytes": 123,
            "rawLogRemoved": True,
        },
        "protocol": {
            "parseComplete": True,
            "transactions": 8,
            "sessionIdsObservedCount": 1,
            "createSession": {
                "observed": True,
                "status": 200,
                "requestAutomationNameMac2": True,
                "requestCalculatorBundleId": True,
                "requestPlatformMac": True,
                "responseAutomationNameMac2": True,
                "responseCalculatorBundleId": True,
                "responsePlatformMac": True,
                "sessionIdSha256": "c" * 64,
                "startedAt": _at(310),
                "completedAt": _at(320),
            },
            "queryAppState": {
                "observed": True,
                "status": 200,
                "scriptOk": True,
                "bundleArgumentOk": True,
                "foregroundValue": 4,
                "foregroundOk": True,
                "startedAt": _at(330),
                "completedAt": _at(340),
            },
            "windowElements": {
                "observed": True,
                "status": 200,
                "windowQuery": True,
                "count": 1,
                "nonEmptyElementList": True,
                "startedAt": _at(350),
                "completedAt": _at(360),
            },
            "windowHandles": {
                "observed": False,
                "status": None,
                "nonEmptyHandleList": False,
                "count": None,
                "startedAt": None,
                "completedAt": None,
            },
            "restoration": {
                "observed": True,
                "startedAt": _at(600),
                "completedAt": _at(610),
                "beforeSessionDelete": True,
            },
            "sessionDelete": {
                "observed": True,
                "status": 200,
                "startedAt": _at(630),
                "completedAt": _at(640),
            },
            "singleSessionObserved": True,
            "listing": {
                "observed": True,
                "observedBeforeOwnedServerStop": True,
                "count": 0,
                "qualifyingSessionListed": False,
                "idsSha256": "d" * 64,
            },
        },
    }


def _retime_queries_before_failure(record: dict[str, Any]) -> None:
    calls = record["native"]["calls"]
    calls[0]["completedAt"] = _at(500)
    calls[1]["startedAt"] = _at(550)
    calls[1]["completedAt"] = _at(560)
    calls[2]["startedAt"] = _at(600)
    calls[2]["completedAt"] = _at(650)
    calls[3]["startedAt"] = _at(700)
    calls[3]["completedAt"] = _at(710)


@pytest.mark.parametrize(
    ("field", "value"),
    [("mcpToolName", "other_exec"), ("toolName", "unrelated-python_exec")],
)
def test_unrelated_kernel_payload_cannot_prove_recovery(field: str, value: str) -> None:
    record = _valid_record()
    record["native"]["calls"][2][field] = value
    assert qualify(record)["nativeRecoveryProven"] is False


def test_recovered_alive_failure_with_later_live_queries_qualifies() -> None:
    record = _valid_record()
    flags = qualify(record)
    assert flags["nativeRecoveryProven"] is True
    assert flags["reportTaskCompleted"] is True
    assert all(flags.values())


def test_final_noop_without_post_failure_query_fails_recovery() -> None:
    record = _valid_record()
    record["native"]["calls"][2]["status"] = "failed"
    flags = qualify(record)
    assert flags["nativeRecoveryProven"] is False
    assert all(flags.values()) is False


def test_queries_before_last_failure_do_not_prove_recovery() -> None:
    record = _valid_record()
    _retime_queries_before_failure(record)
    flags = qualify(record)
    assert flags["nativeRecoveryProven"] is False
    assert all(flags.values()) is False


def test_query_outside_successful_execution_window_fails_recovery() -> None:
    record = _valid_record()
    record["protocol"]["queryAppState"]["startedAt"] = _at(520)
    record["protocol"]["queryAppState"]["completedAt"] = _at(530)
    flags = qualify(record)
    assert flags["nativeRecoveryProven"] is False
    assert all(flags.values()) is False


def test_both_queries_must_follow_last_failure() -> None:
    record = _valid_record()
    calls = record["native"]["calls"]
    calls[1]["status"] = "completed"
    calls[1].pop("errorType", None)
    calls[2]["completedAt"] = _at(340)
    calls[3]["status"] = "failed"
    calls[3]["startedAt"] = _at(350)
    calls[3]["completedAt"] = _at(360)
    calls.insert(
        4,
        {
            "toolName": "amkernel-python_exec",
            "mcpToolName": "python_exec",
            "success": True,
            "status": "completed",
            "kernelState": "alive",
            "executionCount": 5,
            "startedAt": _at(400),
            "completedAt": _at(450),
        },
    )
    record["protocol"]["windowElements"]["startedAt"] = _at(410)
    record["protocol"]["windowElements"]["completedAt"] = _at(420)
    flags = qualify(record)
    assert flags["nativeRecoveryProven"] is False
    assert all(flags.values()) is False


def test_both_queries_may_live_in_separate_successful_windows() -> None:
    record = _valid_record()
    record["protocol"]["windowElements"]["startedAt"] = _at(560)
    record["protocol"]["windowElements"]["completedAt"] = _at(570)
    flags = qualify(record)
    assert flags["nativeRecoveryProven"] is True
    assert all(flags.values())


def test_window_handles_alternative_is_supported_with_timestamps() -> None:
    record = _valid_record()
    record["protocol"]["windowElements"] = {
        "observed": False,
        "status": None,
        "windowQuery": False,
        "count": None,
        "nonEmptyElementList": False,
        "startedAt": None,
        "completedAt": None,
    }
    record["protocol"]["windowHandles"] = {
        "observed": True,
        "status": 200,
        "nonEmptyHandleList": True,
        "count": 1,
        "startedAt": _at(350),
        "completedAt": _at(360),
    }
    flags = qualify(record)
    assert flags["actualWindowQuery"] is True
    assert flags["nativeRecoveryProven"] is True
    assert all(flags.values())


def test_stale_elements_do_not_hide_later_window_handle_recovery() -> None:
    record = _valid_record()
    record["protocol"]["windowElements"]["startedAt"] = _at(110)
    record["protocol"]["windowElements"]["completedAt"] = _at(120)
    record["protocol"]["windowHandles"] = {
        "observed": True,
        "status": 200,
        "nonEmptyHandleList": True,
        "startedAt": _at(350),
        "completedAt": _at(360),
    }
    assert qualify(record)["nativeRecoveryProven"] is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kernelState", "dead"),
        ("kernelState", "reset"),
        ("status", "reset"),
        ("executionCount", 0),
        ("executionCount", 2),
        ("success", False),
        ("success", None),
    ],
)
def test_dead_reset_or_nonmonotonic_execution_history_fails(field: str, value: object) -> None:
    record = _valid_record()
    record["native"]["calls"][2][field] = value
    flags = qualify(record)
    assert flags["nativeRecoveryProven"] is False
    assert all(flags.values()) is False


def test_reversed_or_overlapping_execution_windows_fail() -> None:
    reversed_record = _valid_record()
    reversed_record["native"]["calls"][2]["startedAt"] = _at(600)
    reversed_record["native"]["calls"][2]["completedAt"] = _at(400)
    reversed_flags = qualify(reversed_record)
    assert reversed_flags["nativeRecoveryProven"] is False
    assert all(reversed_flags.values()) is False

    overlapping_record = _valid_record()
    overlapping_record["native"]["calls"][3]["startedAt"] = _at(450)
    overlapping_flags = qualify(overlapping_record)
    assert overlapping_flags["nativeRecoveryProven"] is False
    assert all(overlapping_flags.values()) is False


@pytest.mark.parametrize("field", ["startedAt", "completedAt"])
def test_missing_execution_timestamp_fails_closed(field: str) -> None:
    record = _valid_record()
    del record["native"]["calls"][2][field]
    flags = qualify(record)
    assert flags["nativeRecoveryProven"] is False
    assert all(flags.values()) is False


@pytest.mark.parametrize(
    ("section", "field"),
    [
        ("createSession", "startedAt"),
        ("createSession", "completedAt"),
        ("queryAppState", "startedAt"),
        ("queryAppState", "completedAt"),
        ("windowElements", "startedAt"),
        ("windowElements", "completedAt"),
        ("restoration", "startedAt"),
        ("restoration", "completedAt"),
        ("sessionDelete", "startedAt"),
        ("sessionDelete", "completedAt"),
    ],
)
def test_missing_protocol_timestamp_fails_closed(section: str, field: str) -> None:
    record = _valid_record()
    del record["protocol"][section][field]
    flags = qualify(record)
    assert flags["nativeRecoveryProven"] is False
    if section in {"createSession", "restoration", "sessionDelete"}:
        assert flags["restorationBeforeSessionDelete"] is False
    assert all(flags.values()) is False


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "2026-11-03T12:00:00",
        "2026-11-03T12:00:00+01:00",
        "not-a-time",
    ],
)
def test_malformed_query_timestamp_fails_closed(value: object) -> None:
    record = _valid_record()
    record["protocol"]["queryAppState"]["completedAt"] = value
    flags = qualify(record)
    assert flags["nativeRecoveryProven"] is False
    assert all(flags.values()) is False


@pytest.mark.parametrize(
    ("section", "field"),
    [
        ("queryAppState", "foregroundOk"),
        ("queryAppState", "bundleArgumentOk"),
        ("queryAppState", "scriptOk"),
        ("windowElements", "nonEmptyElementList"),
        ("windowElements", "windowQuery"),
    ],
)
def test_missing_live_query_observation_fails_closed(section: str, field: str) -> None:
    record = _valid_record()
    record["protocol"][section][field] = False
    flags = qualify(record)
    assert flags["nativeRecoveryProven"] is False
    assert all(flags.values()) is False


@pytest.mark.parametrize(
    "section",
    [
        "createSession",
        "queryAppState",
        "windowElements",
        "restoration",
        "sessionDelete",
        "listing",
    ],
)
def test_missing_protocol_observation_fails_closed(section: str) -> None:
    record = _valid_record()
    record["protocol"].pop(section)
    flags = qualify(record)
    assert all(flags.values()) is False


@pytest.mark.parametrize(
    "section", ["createSession", "queryAppState", "windowElements", "sessionDelete"]
)
def test_non_200_protocol_status_fails_closed(section: str) -> None:
    record = _valid_record()
    record["protocol"][section]["status"] = 500
    flags = qualify(record)
    assert all(flags.values()) is False


@pytest.mark.parametrize(
    ("count", "single"),
    [(2, True), (2, False), (1, False)],
)
def test_recreated_or_ambiguous_session_fails(count: int, single: bool) -> None:
    record = _valid_record()
    record["protocol"]["sessionIdsObservedCount"] = count
    record["protocol"]["singleSessionObserved"] = single
    flags = qualify(record)
    assert flags["singleActualSession"] is False
    assert flags["nativeRecoveryProven"] is False
    assert all(flags.values()) is False


def test_restoration_must_precede_session_delete() -> None:
    record = _valid_record()
    record["protocol"]["restoration"]["startedAt"] = _at(650)
    record["protocol"]["restoration"]["completedAt"] = _at(660)
    flags = qualify(record)
    assert flags["restorationBeforeSessionDelete"] is False
    assert flags["nativeRecoveryProven"] is False
    assert flags["reportRestorationConsistent"] is False
    assert all(flags.values()) is False


def test_restoration_not_observed_before_delete_fails() -> None:
    record = _valid_record()
    record["protocol"]["restoration"]["beforeSessionDelete"] = False
    flags = qualify(record)
    assert flags["restorationBeforeSessionDelete"] is False
    assert flags["nativeRecoveryProven"] is False
    assert all(flags.values()) is False


@pytest.mark.parametrize(
    "field",
    ["taskOutcome", "stateRestoration", "sessionCleanup", "serverCleanup"],
)
def test_missing_canonical_report_field_fails_closed(field: str) -> None:
    record = _valid_record()
    del record["native"]["finalStatus"][field]
    flags = qualify(record)
    assert flags["finalReportCanonical"] is False
    assert flags["reportTaskCompleted"] is False
    assert flags["reportRestorationConsistent"] is False
    assert flags["reportSessionCleanupConsistent"] is False
    assert flags["reportServerCleanupConsistent"] is False
    assert all(flags.values()) is False


def test_invalid_canonical_report_value_fails_closed() -> None:
    record = _valid_record()
    record["native"]["finalStatus"]["taskOutcome"] = "done"
    flags = qualify(record)
    assert flags["finalReportCanonical"] is False
    assert flags["reportTaskCompleted"] is False
    assert all(flags.values()) is False


@pytest.mark.parametrize(
    ("field", "value", "flag"),
    [
        ("taskOutcome", "blocked", "reportTaskCompleted"),
        ("stateRestoration", "failed", "reportRestorationConsistent"),
        ("stateRestoration", "not-needed", "reportRestorationConsistent"),
        ("sessionCleanup", "failed", "reportSessionCleanupConsistent"),
        ("serverCleanup", "failed", "reportServerCleanupConsistent"),
    ],
)
def test_contradictory_report_value_fails(field: str, value: str, flag: str) -> None:
    record = _valid_record()
    record["native"]["finalStatus"][field] = value
    flags = qualify(record)
    assert flags[flag] is False
    assert all(flags.values()) is False


@pytest.mark.parametrize("reported", ["restored", "unchanged"])
def test_restoration_report_accepts_restored_or_unchanged(reported: str) -> None:
    record = _valid_record()
    record["native"]["finalStatus"]["stateRestoration"] = reported
    flags = qualify(record)
    assert flags["reportRestorationConsistent"] is True
    assert all(flags.values())


def test_preserved_server_report_is_consistent_with_harness_ownership() -> None:
    record = _valid_record()
    record["native"]["finalStatus"]["serverCleanup"] = "preserved"
    flags = qualify(record)
    assert flags["reportServerCleanupConsistent"] is True
    assert all(flags.values())


def test_shared_server_report_is_contradictory() -> None:
    record = _valid_record()
    record["server"]["shared"] = True
    flags = qualify(record)
    assert flags["reportServerCleanupConsistent"] is False
    assert all(flags.values()) is False


def test_harness_error_prevents_completion() -> None:
    record = _valid_record()
    record["error"] = {"type": "RuntimeError"}
    flags = qualify(record)
    assert flags["harnessCompleted"] is False
    assert flags["reportTaskCompleted"] is False
    assert all(flags.values()) is False


def test_owned_resource_cleanup_failure_prevents_completion() -> None:
    record = _valid_record()
    record["cleanup"]["ownedServer"]["exited"] = False
    flags = qualify(record)
    assert flags["ownedServerExited"] is False
    assert flags["ownedResourcesObservedGone"] is False
    assert flags["reportTaskCompleted"] is False
    assert all(flags.values()) is False


def test_desktop_restoration_failure_prevents_completion() -> None:
    record = _valid_record()
    record["cleanup"]["desktopRestored"] = False
    flags = qualify(record)
    assert flags["desktopRestored"] is False
    assert flags["reportRestorationConsistent"] is False
    assert flags["reportTaskCompleted"] is False
    assert all(flags.values()) is False


def test_session_delete_failure_prevents_completion() -> None:
    record = _valid_record()
    record["protocol"]["sessionDelete"]["status"] = 500
    flags = qualify(record)
    assert flags["sessionDeleteObserved"] is False
    assert flags["reportSessionCleanupConsistent"] is False
    assert flags["nativeRecoveryProven"] is False
    assert all(flags.values()) is False


def test_stale_session_listing_prevents_completion() -> None:
    record = _valid_record()
    record["protocol"]["listing"]["qualifyingSessionListed"] = True
    flags = qualify(record)
    assert flags["sessionGoneBeforeOwnedServerStop"] is False
    assert flags["reportSessionCleanupConsistent"] is False
    assert all(flags.values()) is False


def test_no_execution_results_fails_closed() -> None:
    record = _valid_record()
    record["native"]["calls"] = [{"toolName": "view", "success": True}]
    flags = qualify(record)
    assert flags["nativeRecoveryProven"] is False
    assert all(flags.values()) is False


def test_non_mapping_call_fails_closed() -> None:
    record = _valid_record()
    record["native"]["calls"] = ["not-a-call"]
    flags = qualify(record)
    assert flags["nativeRecoveryProven"] is False
    assert all(flags.values()) is False


def test_missing_sections_fail_closed() -> None:
    flags = qualify({})
    assert flags["nativeRecoveryProven"] is False
    assert flags["finalReportCanonical"] is False
    assert all(flags.values()) is False


def test_qualify_does_not_mutate_input() -> None:
    record = _valid_record()
    snapshot = copy.deepcopy(record)
    assert qualify(record)["reportTaskCompleted"] is True
    assert record == snapshot


def test_original_historical_record_remains_not_qualified() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "evidence"
        / "appium-skill"
        / "mac2-retry-20261103.json"
    )
    raw = path.read_bytes()
    record = json.loads(raw)
    flags = qualify(record)
    assert record["status"] == "not-qualified"
    assert flags["actualCalculatorQueryAppState"] is True
    assert flags["actualWindowQuery"] is True
    assert flags["nativeRecoveryProven"] is False
    assert flags["restorationBeforeSessionDelete"] is False
    assert flags["finalReportCanonical"] is False
    assert flags["reportTaskCompleted"] is False
    assert all(flags.values()) is False
