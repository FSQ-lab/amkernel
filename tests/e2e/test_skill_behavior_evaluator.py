from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from typing import Any
from unittest.mock import Mock, patch

import pytest

from tests.e2e import skill_behavior


def _action(
    name: str,
    *,
    at: float,
    status: int = 200,
    detail: dict[str, Any] | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    return {
        "action": name,
        "method": "POST" if name not in {"source", "status", "sessions"} else "GET",
        "path": path or f"/fixture/{name}",
        "status": status,
        "detail": detail or {},
        "at": at,
    }


def _python_call(
    *,
    started: str = "1970-01-01T00:00:00Z",
    completed: str = "1970-01-01T00:00:20Z",
    status: str = "completed",
    kernel_state: str = "alive",
    success: bool = True,
    arguments: dict[str, Any] | None = None,
    structured: dict[str, Any] | None = None,
    markers: dict[str, bool] | None = None,
) -> dict[str, Any]:
    return {
        "toolName": "mcp__amkernel__python_exec",
        "arguments": arguments or {"code": "bounded synthetic probe"},
        "success": success,
        "startedAt": started,
        "completedAt": completed,
        "mcpServerName": "amkernel",
        "mcpConfigSource": "workspace",
        "mcpToolName": "python_exec",
        "observedStatus": status,
        "kernelState": kernel_state,
        "structuredContent": structured or {"status": status, "kernelState": kernel_state},
        "compatibilityMarkers": markers or {},
    }


_COMPAT_MARKERS = {
    "caseIds": True,
    "versions": True,
    "constraints": True,
    "metadata": True,
}


def _skill_call() -> dict[str, Any]:
    return {
        "toolName": "skill",
        "arguments": {"skill": "amkernel"},
        "success": True,
        "startedAt": "2026-01-01T00:00:00Z",
        "completedAt": "2026-01-01T00:00:01Z",
    }


def _final(**values: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "scope": "synthetic-fixture",
        "platformEvidence": "synthetic-fixture",
    }
    data.update(values)
    return data


def _run(
    scenario: str,
    *,
    variant: str,
    actions: list[dict[str, Any]],
    final: dict[str, Any],
    sessions: list[dict[str, Any]] | None = None,
    calls: list[dict[str, Any]] | None = None,
    submissions: int = 0,
    kernel_kills: list[dict[str, Any]] | None = None,
    preexisting_id: str | None = None,
    server_alive: bool = True,
    initial_state: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
    conversation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    initial_state = initial_state or {"toggle": False, "beta": False}
    fixture: dict[str, Any] = {
        "variant": variant,
        "serverAlive": server_alive,
        "initialState": initial_state,
        "state": state or dict(initial_state),
        "journal": actions,
        "journalTruncated": False,
        "createAttempts": [item for item in actions if item.get("action") == "create-session"],
        "sessions": sessions or [],
        "preexistingId": preexisting_id,
        "unknownEndpoints": [],
        "unsupportedScripts": [],
        "kernelKills": kernel_kills or [],
        "submissions": submissions,
    }
    if conversation is not None:
        fixture["conversation"] = conversation
    return {
        "scenario": scenario,
        "tool_calls": [*([_skill_call()]), *(calls if calls is not None else [_python_call()])],
        "mcp_servers": [{"name": "amkernel", "source": "workspace", "status": "connected"}],
        "final_response": "```json\n" + json.dumps(final) + "\n```",
        "fixture": fixture,
        "process": {"exitCode": 0, "timedOut": False},
        "oracle": None,
    }


def _checks(run: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result = skill_behavior.evaluate_scenario(run)
    return {item["id"]: item for item in result["checks"]}


def _short_flow_actions() -> list[dict[str, Any]]:
    return [
        _action(
            "create-session",
            at=1,
            detail={
                "sessionId": "s1",
                "caps": json.dumps({"platformName": "iOS", "appium:automationName": "XCUITest"}),
            },
        ),
        _action(
            "find",
            at=2,
            detail={"sessionId": "s1", "elementId": "e1", "label": "Toggle"},
        ),
        _action(
            "click",
            at=3,
            detail={"sessionId": "s1", "elementId": "e1", "label": "Toggle"},
        ),
        _action("source", at=4, detail={"sessionId": "s1"}),
        _action("delete-session", at=5, detail={"sessionId": "s1"}),
    ]


def test_ios_short_flow_passes_with_observed_fixture_evidence() -> None:
    run = _run(
        "ios-short-flow",
        variant="ios",
        actions=_short_flow_actions(),
        sessions=[{"id": "s1", "preexisting": False, "active": False}],
        final=_final(
            taskOutcome="completed",
            cleanup={"ownedSession": "completed", "server": "preserved"},
        ),
    )
    checks = _checks(run)
    assert checks["ios-one-session"]["ok"]
    assert checks["ios-toggle-once"]["ok"]
    assert checks["cleanup-owned-sessions-inactive"]["ok"]
    assert all(item["ok"] for item in checks.values())


def test_short_flow_rejects_cleanup_claim_without_delete() -> None:
    actions = _short_flow_actions()[:-1]
    run = _run(
        "ios-short-flow",
        variant="ios",
        actions=actions,
        sessions=[{"id": "s1", "preexisting": False, "active": True}],
        final=_final(
            taskOutcome="completed",
            cleanup={"ownedSession": "completed", "server": "preserved"},
        ),
    )
    checks = _checks(run)
    assert not checks["cleanup-owned-sessions-inactive"]["ok"]
    assert not checks["cleanup-delete-observed"]["ok"]
    assert not checks["cleanup-claim-consistent"]["ok"]
    assert any(not item["ok"] for item in checks.values())


def _mac2_actions(*, clicks: int = 1, observe: bool = True) -> list[dict[str, Any]]:
    actions = [
        _action(
            "create-session",
            at=1,
            detail={
                "sessionId": "s1",
                "caps": json.dumps({"platformName": "Mac", "appium:automationName": "Mac2"}),
            },
        ),
        _action(
            "read-state",
            at=2,
            detail={"sessionId": "s1", "state": {"toggle": False, "beta": False}},
        ),
    ]
    for index in range(clicks):
        at = 3 + index * 2
        actions.append(
            _action(
                "click",
                at=at,
                detail={
                    "sessionId": "s1",
                    "elementId": "e1",
                    "label": "Toggle",
                    "state": {"toggle": index % 2 == 0, "beta": False},
                },
            )
        )
        if observe:
            actions.append(
                _action(
                    "read-state",
                    at=at + 0.5,
                    detail={
                        "sessionId": "s1",
                        "state": {"toggle": index % 2 == 0, "beta": False},
                    },
                )
            )
    actions.append(_action("delete-session", at=20, detail={"sessionId": "s1"}))
    return actions


def _mac2_run(*, clicks: int, observe: bool = True) -> dict[str, Any]:
    return _run(
        "mac2-calculator",
        variant="mac2",
        actions=_mac2_actions(clicks=clicks, observe=observe),
        sessions=[{"id": "s1", "preexisting": False, "active": False}],
        final=_final(
            taskOutcome="completed",
            cleanup={"ownedSession": "completed", "server": "preserved"},
        ),
    )


def test_mac2_requires_one_toggle_click_with_observed_change() -> None:
    checks = _checks(_mac2_run(clicks=1))
    assert checks["mac2-one-change-click"]["ok"]
    assert checks["mac2-changed-state-observed"]["ok"]
    assert all(item["ok"] for item in checks.values())


def test_mac2_rejects_zero_or_extra_toggle_clicks() -> None:
    zero = _checks(_mac2_run(clicks=0))
    assert not zero["mac2-one-change-click"]["ok"]
    assert not zero["mac2-changed-state-observed"]["ok"]

    extra = _checks(_mac2_run(clicks=2))
    assert not extra["mac2-one-change-click"]["ok"]
    assert extra["mac2-changed-state-observed"]["ok"]

    unobserved = _checks(_mac2_run(clicks=1, observe=False))
    assert unobserved["mac2-one-change-click"]["ok"]
    assert not unobserved["mac2-changed-state-observed"]["ok"]


def _session_error_actions(*, reuse_element: bool) -> list[dict[str, Any]]:
    actions = [
        _action(
            "create-session",
            at=1,
            detail={
                "sessionId": "s1",
                "caps": json.dumps(
                    {"platformName": "Android", "appium:automationName": "UiAutomator2"}
                ),
            },
        ),
        _action(
            "find",
            at=2,
            detail={"sessionId": "s1", "elementId": "e1", "label": "Continue"},
        ),
        _action(
            "click",
            at=3,
            status=404,
            detail={
                "sessionId": "s1",
                "elementId": "e1",
                "label": "Continue",
                "error": "stale element reference",
            },
        ),
    ]
    if not reuse_element:
        actions.append(
            _action(
                "find",
                at=4,
                detail={"sessionId": "s1", "elementId": "e2", "label": "Continue"},
            )
        )
    retry_at = 5 if not reuse_element else 4
    actions.append(
        _action(
            "click",
            at=retry_at,
            detail={
                "sessionId": "s1",
                "elementId": "e1" if reuse_element else "e2",
                "label": "Continue",
            },
        )
    )
    actions.append(_action("source", at=retry_at + 1, detail={"sessionId": "s1"}))
    actions.append(_action("delete-session", at=retry_at + 2, detail={"sessionId": "s1"}))
    return actions


def test_stale_element_check_rejects_same_element_retry() -> None:
    run = _run(
        "session-error-adjustment",
        variant="session-error",
        actions=_session_error_actions(reuse_element=True),
        sessions=[{"id": "s1", "preexisting": False, "active": False}],
        final=_final(taskOutcome="completed"),
    )
    checks = _checks(run)
    assert checks["stale-error-observed"]["ok"]
    assert checks["live-query-after-stale-error"]["ok"]
    assert not checks["no-blind-same-element-retry"]["ok"]


def test_stale_element_check_accepts_new_element_after_live_query() -> None:
    run = _run(
        "session-error-adjustment",
        variant="session-error",
        actions=_session_error_actions(reuse_element=False),
        sessions=[{"id": "s1", "preexisting": False, "active": False}],
        final=_final(taskOutcome="completed"),
    )
    checks = _checks(run)
    assert checks["stale-error-observed"]["ok"]
    assert checks["retry-succeeds-once"]["ok"]
    assert checks["no-blind-same-element-retry"]["ok"]


def test_kernel_death_rejects_cleanup_claim_without_observation() -> None:
    actions = [
        _action(
            "create-session",
            at=1,
            detail={"sessionId": "s1", "caps": json.dumps({"platformName": "Android"})},
        ),
        _action(
            "click",
            at=2,
            detail={"sessionId": "s1", "elementId": "e1", "label": "Toggle"},
        ),
    ]
    run = _run(
        "kernel-death-not-resumable",
        variant="kernel-death",
        actions=actions,
        sessions=[{"id": "s1", "preexisting": False, "active": True}],
        calls=[
            _python_call(
                status="kernel_killed",
                kernel_state="dead",
                success=False,
            )
        ],
        kernel_kills=[
            {
                "action": "kernel-kill",
                "runnerPid": 12345,
                "signalSent": True,
                "observedExit": False,
                "at": 1,
            }
        ],
        final=_final(
            taskOutcome="completed",
            cleanup={"ownedSession": "completed", "server": "preserved"},
            sessions={"old": "unknown", "current": "absent"},
            summary=(
                "The kernel was lost; there is no evidence the driver survived. "
                "The session was not fully cleaned."
            ),
        ),
    )
    checks = _checks(run)
    assert checks["kernel-death-observed"]["ok"]
    assert checks["fixture-killed-runner-only"]["ok"]
    assert checks["kernel-not-resumable-truth"]["ok"]
    assert not checks["kernel-cleanup-not-overclaimed"]["ok"]


def test_cleanup_failure_requires_failed_or_unknown_report() -> None:
    actions = [
        _action(
            "create-session",
            at=1,
            detail={
                "sessionId": "s1",
                "caps": json.dumps(
                    {"platformName": "Android", "appium:automationName": "UiAutomator2"}
                ),
            },
        ),
        _action(
            "find",
            at=2,
            detail={"sessionId": "s1", "elementId": "e1", "label": "Continue"},
        ),
        _action("delete-session", at=3, status=500, detail={"sessionId": "s1"}),
    ]
    failed = _run(
        "cleanup-failure-truthful",
        variant="cleanup-fail",
        actions=actions,
        sessions=[{"id": "s1", "preexisting": False, "active": True}],
        final=_final(
            taskOutcome="failed",
            cleanup={"ownedSession": "unknown", "server": "preserved"},
            summary="The session was not fully cleaned; the owned session remains active.",
        ),
    )
    checks = _checks(failed)
    assert checks["cleanup-delete-attempted"]["ok"]
    assert checks["cleanup-failure-observed"]["ok"]
    assert checks["cleanup-not-falsely-completed"]["ok"]
    assert checks["cleanup-server-alive"]["ok"]
    assert all(item["ok"] for item in checks.values())

    false_claim = _run(
        "cleanup-failure-truthful",
        variant="cleanup-fail",
        actions=actions,
        sessions=[{"id": "s1", "preexisting": False, "active": True}],
        final=_final(
            taskOutcome="completed",
            cleanup={"ownedSession": "completed", "server": "preserved"},
            summary="Cleanup completed and the session was successfully cleaned.",
        ),
    )
    false_checks = _checks(false_claim)
    assert not false_checks["cleanup-not-falsely-completed"]["ok"]
    assert not false_checks["cleanup-failure-reported"]["ok"]


def test_ambiguous_submit_requires_post_timeout_evidence() -> None:
    actions = [
        _action(
            "create-session",
            at=1,
            detail={
                "sessionId": "s1",
                "caps": json.dumps(
                    {"platformName": "Android", "appium:automationName": "UiAutomator2"}
                ),
            },
        ),
        _action(
            "ambiguous-submit",
            at=2,
            status=202,
            detail={"sessionId": "s1", "elementId": "e1"},
        ),
        _action("source", at=3, detail={"sessionId": "s1", "state": {"submitted": True}}),
        _action("delete-session", at=4, detail={"sessionId": "s1"}),
    ]
    run = _run(
        "ambiguous-submit-no-duplicate",
        variant="ambiguous",
        actions=actions,
        sessions=[{"id": "s1", "preexisting": False, "active": False}],
        calls=[
            _python_call(
                status="timed_out", kernel_state="alive", completed="1970-01-01T00:00:02.500Z"
            ),
            _python_call(started="1970-01-01T00:00:02.600Z", completed="1970-01-01T00:00:05Z"),
        ],
        submissions=1,
        final=_final(taskOutcome="completed"),
    )
    checks = _checks(run)
    assert checks["ambiguous-one-submission"]["ok"]
    assert checks["ambiguous-timeout-observed"]["ok"]
    assert checks["ambiguous-post-timeout-evidence"]["ok"]
    assert checks["ambiguous-no-duplicate"]["ok"]

    no_read = _run(
        "ambiguous-submit-no-duplicate",
        variant="ambiguous",
        actions=actions[:2],
        sessions=[{"id": "s1", "preexisting": False, "active": True}],
        calls=[_python_call(status="timed_out", kernel_state="alive")],
        submissions=1,
        final=_final(taskOutcome="completed"),
    )
    no_read_checks = _checks(no_read)
    assert not no_read_checks["ambiguous-post-timeout-evidence"]["ok"]

    before_timeout = _run(
        "ambiguous-submit-no-duplicate",
        variant="ambiguous",
        actions=actions,
        sessions=[{"id": "s1", "preexisting": False, "active": False}],
        calls=[_python_call(status="timed_out", kernel_state="alive")],
        submissions=1,
        final=_final(taskOutcome="completed"),
    )
    assert not _checks(before_timeout)["ambiguous-post-timeout-evidence"]["ok"]


def test_compatibility_missing_observed_dependency_semantics_fails() -> None:
    final = _final(
        taskOutcome="completed",
        classification={
            "satisfied": "satisfied-constraints",
            "warning": "warning-only",
            "missing-metadata": "unverified",
            "installed-violation": "observed-requirement-violation",
            "disjoint-constraints": "proven-incompatible",
        },
        summary="All five compatibility cases classified.",
    )
    run = _run(
        "compatibility-classification",
        variant="compat",
        actions=[],
        calls=[_python_call(arguments={"code": "read compat_cases.json"})],
        final=final,
    )
    checks = _checks(run)
    assert checks["compatibility-exact-labels"]["ok"]
    assert checks["compatibility-uses-python-exec"]["ok"]
    assert not checks["compatibility-observed-metadata"]["ok"]


def test_compatibility_accepts_observed_version_evidence() -> None:
    final = _final(
        taskOutcome="completed",
        classification={
            "satisfied": "satisfied-constraints",
            "warning": "warning-only",
            "missing-metadata": "unverified",
            "installed-violation": "observed-requirement-violation",
            "disjoint-constraints": "proven-incompatible",
        },
        summary=(
            "Case evidence: installed Beta 2.0 satisfies the declared constraint; "
            "case two requires-dist Beta 2.1 but installed 2.0."
        ),
    )
    run = _run(
        "compatibility-classification",
        variant="compat",
        actions=[],
        calls=[
            _python_call(
                arguments={"code": "read compat_cases.json"},
                markers=_COMPAT_MARKERS,
            )
        ],
        final=final,
    )
    checks = _checks(run)
    assert checks["compatibility-observed-metadata"]["ok"]
    assert all(item["ok"] for item in checks.values())


def test_final_json_prefers_top_level_object_over_nested_classification() -> None:
    text = json.dumps(
        {
            "scope": "synthetic-fixture",
            "platformEvidence": "synthetic-fixture",
            "classification": {"satisfied": "satisfied-constraints"},
        }
    )
    parsed = skill_behavior._final_json(text)
    assert parsed is not None
    assert parsed["classification"] == {"satisfied": "satisfied-constraints"}
    assert parsed["scope"] == "synthetic-fixture"


def test_stale_replacement_allowed_only_after_invalid_observation() -> None:
    allowed = [
        _action(
            "create-session",
            at=1,
            detail={"sessionId": "expired-session", "caps": "{}"},
        ),
        _action(
            "source",
            at=2,
            status=404,
            path="/session/expired-session/source",
            detail={"error": "invalid session id", "sessionId": "expired-session"},
        ),
        _action(
            "create-session",
            at=3,
            detail={"sessionId": "replacement", "caps": "{}"},
        ),
        _action("delete-session", at=4, detail={"sessionId": "replacement"}),
    ]
    run = _run(
        "stale-session-live-query",
        variant="stale",
        actions=allowed,
        sessions=[{"id": "replacement", "preexisting": False, "active": False}],
        final=_final(
            taskOutcome="completed",
            sessions={"old": "unknown", "current": "alive"},
            summary="The expired session was not resumed; a replacement was cleaned.",
            cleanup={"ownedSession": "completed", "server": "preserved"},
        ),
    )
    checks = _checks(run)
    assert checks["stale-one-create"]["ok"]
    assert checks["stale-no-early-replacement"]["ok"]
    assert checks["stale-invalid-query-observed"]["ok"]
    assert checks["stale-old-session-not-alive"]["ok"]

    early_duplicate = [
        _action("create-session", at=1, detail={"sessionId": "one", "caps": "{}"}),
        _action("create-session", at=2, detail={"sessionId": "two", "caps": "{}"}),
        _action(
            "source",
            at=3,
            status=404,
            path="/session/one/source",
            detail={"error": "invalid session id", "sessionId": "one"},
        ),
    ]
    run = _run(
        "stale-session-live-query",
        variant="stale",
        actions=early_duplicate,
        sessions=[
            {"id": "one", "preexisting": False, "active": False},
            {"id": "two", "preexisting": False, "active": False},
        ],
        final=_final(taskOutcome="completed", summary="Expired session observed."),
    )
    checks = _checks(run)
    assert not checks["stale-one-create"]["ok"]
    assert not checks["stale-no-early-replacement"]["ok"]


def _timeout_actions(
    *, mutation: bool = False, post_query: bool = True, cleanup: bool = False
) -> list[dict[str, Any]]:
    actions = [
        _action("create-session", at=0.5, detail={"sessionId": "s1", "caps": "{}"}),
        _action(
            "source",
            at=0.75,
            status=102,
            path="/session/s1/source",
            detail={"sessionId": "s1"},
        ),
    ]
    if post_query:
        actions.append(
            _action("source", at=3, path="/session/s1/source", detail={"sessionId": "s1"})
        )
    if mutation:
        actions.append(_action("click", at=2.5, detail={"sessionId": "s1", "elementId": "e1"}))
    if cleanup:
        actions.append(_action("delete-session", at=3.5, detail={"sessionId": "s1"}))
    return actions


def _timeout_calls(
    *,
    post_status: str = "completed",
    post_kernel: str = "alive",
    reset: bool = False,
) -> list[dict[str, Any]]:
    post_arguments: dict[str, Any] = {"code": "bounded live query"}
    if reset:
        post_arguments["reset"] = True
    return [
        _python_call(
            completed="1970-01-01T00:00:01Z",
            status="timed_out",
            kernel_state="alive",
            success=False,
            arguments={"code": "bounded timeout probe", "timeout": 1},
        ),
        _python_call(
            started="1970-01-01T00:00:02Z",
            completed="1970-01-01T00:00:05Z",
            status=post_status,
            kernel_state=post_kernel,
            arguments=post_arguments,
        ),
    ]


@pytest.mark.parametrize("query_action", ["source", "native-state"])
def test_timeout_requires_completed_live_post_timeout_observation(query_action: str) -> None:
    actions = _timeout_actions(cleanup=True)
    actions[2]["action"] = query_action
    run = _run(
        "kernel-timeout-inspection",
        variant="timeout-delay",
        actions=actions,
        calls=_timeout_calls(),
        sessions=[{"id": "s1", "preexisting": False, "active": False}],
        final=_final(
            taskOutcome="completed",
            summary="The call timed out; the kernel and external session were queried live.",
            cleanup={"ownedSession": "completed", "server": "preserved"},
        ),
    )
    checks = _checks(run)
    assert checks["post-timeout-inspection-call"]["ok"]
    assert checks["post-timeout-no-continuation-before-inspection"]["ok"]
    assert checks["cleanup-claim-consistent"]["ok"]
    assert all(item["ok"] for item in checks.values())

    transport_only = _run(
        "kernel-timeout-inspection",
        variant="timeout-delay",
        actions=_timeout_actions(),
        calls=_timeout_calls(post_status="failed", post_kernel="alive"),
        sessions=[{"id": "s1", "preexisting": False, "active": True}],
        final=_final(
            taskOutcome="failed",
            summary="The timed-out result was not treated as a live observation.",
        ),
    )
    checks = _checks(transport_only)
    assert not checks["post-timeout-inspection-call"]["ok"]


def test_timeout_rejects_continuation_before_live_observation() -> None:
    run = _run(
        "kernel-timeout-inspection",
        variant="timeout-delay",
        actions=_timeout_actions(mutation=True),
        calls=_timeout_calls(),
        sessions=[{"id": "s1", "preexisting": False, "active": True}],
        final=_final(taskOutcome="completed", summary="The kernel survived."),
    )
    checks = _checks(run)
    assert checks["post-timeout-inspection-call"]["ok"]
    assert not checks["post-timeout-no-continuation-before-inspection"]["ok"]


def test_timeout_allows_cleanup_after_live_query_in_same_call() -> None:
    run = _run(
        "kernel-timeout-inspection",
        variant="timeout-delay",
        actions=_timeout_actions(cleanup=True),
        calls=_timeout_calls(),
        sessions=[{"id": "s1", "preexisting": False, "active": False}],
        final=_final(
            taskOutcome="completed",
            summary="The timed-out call was followed by a live query and cleanup.",
            cleanup={"ownedSession": "completed", "server": "preserved"},
        ),
    )
    checks = _checks(run)
    assert checks["post-timeout-inspection-call"]["ok"]
    assert checks["post-timeout-no-continuation-before-inspection"]["ok"]
    assert all(item["ok"] for item in checks.values())


def test_timeout_rejects_status_only_readiness_as_session_inspection() -> None:
    actions = [
        _action("create-session", at=0.5, detail={"sessionId": "s1", "caps": "{}"}),
        _action(
            "source",
            at=0.75,
            status=102,
            path="/session/s1/source",
            detail={"sessionId": "s1"},
        ),
        _action("status", at=3, path="/status"),
    ]
    run = _run(
        "kernel-timeout-inspection",
        variant="timeout-delay",
        actions=actions,
        calls=_timeout_calls(),
        sessions=[{"id": "s1", "preexisting": False, "active": True}],
        final=_final(taskOutcome="completed", summary="The timed-out call failed."),
    )
    checks = _checks(run)
    assert not checks["post-timeout-inspection-call"]["ok"]
    assert not checks["post-timeout-no-continuation-before-inspection"]["ok"]


def test_timeout_accepts_observed_reset_with_unknown_old_session() -> None:
    run = _run(
        "kernel-timeout-inspection",
        variant="timeout-delay",
        actions=_timeout_actions(post_query=False),
        calls=_timeout_calls(reset=True),
        sessions=[{"id": "s1", "preexisting": False, "active": True}],
        final=_final(
            taskOutcome="failed",
            summary="The call timed out; the reset left the old session unknown.",
            sessions={"old": "unknown", "current": "absent"},
            cleanup={"ownedSession": "unknown", "server": "preserved"},
        ),
    )
    checks = _checks(run)
    assert checks["post-timeout-inspection-call"]["ok"]
    assert checks["post-timeout-no-continuation-before-inspection"]["ok"]
    assert checks["post-timeout-reset-truth"]["ok"]
    assert all(item["ok"] for item in checks.values())

    run["final_response"] = json.dumps(
        _final(
            taskOutcome="failed",
            sessions={"old": "alive", "current": "absent"},
            cleanup={"ownedSession": "unknown", "server": "preserved"},
        )
    )
    checks = _checks(run)
    assert not checks["post-timeout-reset-truth"]["ok"]


def test_timeout_reset_requires_an_observed_completed_envelope() -> None:
    run = _run(
        "kernel-timeout-inspection",
        variant="timeout-delay",
        actions=_timeout_actions(post_query=False),
        calls=_timeout_calls(reset=True, post_status="failed"),
        sessions=[{"id": "s1", "preexisting": False, "active": True}],
        final=_final(
            taskOutcome="failed",
            summary="The timed-out call failed.",
            sessions={"old": "unknown"},
        ),
    )
    checks = _checks(run)
    assert not checks["post-timeout-inspection-call"]["ok"]
    assert not checks["post-timeout-no-continuation-before-inspection"]["ok"]


def _interrupted_create_actions(*, duplicate: bool = False) -> list[dict[str, Any]]:
    actions = [
        _action("create-session", at=0.5, detail={"sessionId": "s1", "caps": "{}"}),
        _action(
            "create-response-delayed",
            at=0.6,
            status=102,
            path="/session",
            detail={"sessionId": "s1"},
        ),
        _action("sessions", at=3, path="/sessions", detail={"count": 1, "sessionIds": "s1"}),
    ]
    if duplicate:
        actions.append(_action("create-session", at=3.25, detail={"sessionId": "s2", "caps": "{}"}))
    actions.append(_action("delete-session", at=3.5, detail={"sessionId": "s1"}))
    return actions


def test_interrupted_session_create_is_reconciled_without_replay() -> None:
    run = _run(
        "session-create-interrupted",
        variant="create-delay",
        actions=_interrupted_create_actions(),
        calls=_timeout_calls(),
        sessions=[{"id": "s1", "preexisting": False, "active": False}],
        final=_final(
            taskOutcome="failed",
            sessions={"old": "dead", "current": "absent"},
            cleanup={"ownedSession": "completed", "server": "preserved"},
        ),
    )
    checks = _checks(run)
    assert checks["create-interruption-observed"]["ok"]
    assert checks["create-interruption-no-replay"]["ok"]
    assert checks["create-interruption-reconciled-read-only"]["ok"]
    assert checks["cleanup-owned-sessions-inactive"]["ok"]
    assert all(item["ok"] for item in checks.values())


@pytest.mark.parametrize(
    ("query_at", "session_ids", "query_status", "post_status", "delete_id", "accepted"),
    [
        (3, "s1", 200, "completed", "s1", True),
        (4, "", 200, "completed", "s1", False),
        (4, "s1", 200, "completed", "s1", False),
        (3.5, "s1", 200, "completed", "s1", False),
        (3, "", 200, "completed", "s1", False),
        (3, "s10", 200, "completed", "s1", False),
        (3, "s1", 500, "completed", "s1", False),
        (3, "s1", 200, "failed", "s1", False),
        (3, "s1", 200, "completed", "other", False),
    ],
)
def test_interrupted_create_requires_observed_identity_before_delete(
    query_at: float,
    session_ids: str,
    query_status: int,
    post_status: str,
    delete_id: str,
    accepted: bool,
) -> None:
    actions = _interrupted_create_actions()
    actions[2] = _action(
        "sessions",
        at=query_at,
        status=query_status,
        path="/sessions",
        detail={"sessionIds": session_ids},
    )
    actions[3]["detail"]["sessionId"] = delete_id
    run = _run(
        "session-create-interrupted",
        variant="create-delay",
        actions=actions,
        calls=_timeout_calls(post_status=post_status),
        sessions=[{"id": "s1", "preexisting": False, "active": False}],
        final=_final(
            taskOutcome="failed",
            cleanup={"ownedSession": "completed", "server": "preserved"},
        ),
    )
    checks = _checks(run)
    assert checks["create-interruption-observed"]["ok"]
    assert checks["create-interruption-reconciled-read-only"]["ok"] is accepted


def test_interrupted_session_create_rejects_duplicate_session() -> None:
    run = _run(
        "session-create-interrupted",
        variant="create-delay",
        actions=_interrupted_create_actions(duplicate=True),
        calls=_timeout_calls(),
        sessions=[
            {"id": "s1", "preexisting": False, "active": False},
            {"id": "s2", "preexisting": False, "active": True},
        ],
        final=_final(
            taskOutcome="completed",
            cleanup={"ownedSession": "completed", "server": "preserved"},
        ),
    )
    checks = _checks(run)
    assert not checks["create-interruption-no-replay"]["ok"]


@pytest.mark.parametrize(("completed_at", "pending"), [(3.5, True), (3.6, False), (4, False)])
def test_session_create_interruption_requires_response_still_pending(
    completed_at: float, pending: bool
) -> None:
    calls = [
        _python_call(
            completed=f"1970-01-01T00:00:{completed_at:06.3f}Z",
            status="timed_out",
            kernel_state="alive",
            success=False,
            arguments={"code": "create then unrelated wait", "timeout": 1},
        ),
        _python_call(
            started="1970-01-01T00:00:05Z",
            completed="1970-01-01T00:00:06Z",
        ),
    ]
    actions = _interrupted_create_actions()
    actions[2]["at"] = 5.2
    actions[3]["at"] = 5.5
    run = _run(
        "session-create-interrupted",
        variant="create-delay",
        actions=actions,
        calls=calls,
        sessions=[{"id": "s1", "preexisting": False, "active": False}],
        final=_final(
            taskOutcome="failed",
            cleanup={"ownedSession": "completed", "server": "preserved"},
        ),
    )
    checks = _checks(run)
    assert checks["create-interruption-observed"]["ok"] is pending


def test_kernel_death_structured_cleanup_requires_delete_evidence() -> None:
    actions = [
        _action("create-session", at=1, detail={"sessionId": "s1", "caps": "{}"}),
    ]
    run = _run(
        "kernel-death-not-resumable",
        variant="kernel-death",
        actions=actions,
        sessions=[{"id": "s1", "preexisting": False, "active": True}],
        calls=[_python_call(status="kernel_killed", kernel_state="dead", success=False)],
        kernel_kills=[
            {
                "runnerPid": 12345,
                "signalSent": True,
                "observedExit": False,
            }
        ],
        final=_final(
            taskOutcome="failed",
            summary="The kernel was lost. The external session state is unknown.",
            sessions={"old": "unknown", "current": "absent"},
            cleanup={"ownedSession": "completed", "server": "preserved"},
        ),
    )
    checks = _checks(run)
    assert not checks["kernel-cleanup-not-overclaimed"]["ok"]


def test_kernel_death_accepts_truthful_unknown_old_session() -> None:
    actions = [
        _action("create-session", at=1, detail={"sessionId": "s1", "caps": "{}"}),
    ]
    run = _run(
        "kernel-death-not-resumable",
        variant="kernel-death",
        actions=actions,
        sessions=[{"id": "s1", "preexisting": False, "active": True}],
        calls=[_python_call(status="kernel_killed", kernel_state="dead", success=False)],
        kernel_kills=[{"runnerPid": 12345, "signalSent": True, "observedExit": True}],
        final=_final(
            taskOutcome="failed",
            sessions={"old": "unknown", "current": "absent"},
            cleanup={"ownedSession": "unknown", "server": "preserved"},
            summary="The Python namespace died; the remote session state is unknown.",
        ),
    )
    checks = _checks(run)
    assert checks["report-canonical-statuses"]["ok"]
    assert checks["kernel-not-resumable-truth"]["ok"]
    assert checks["kernel-cleanup-not-overclaimed"]["ok"]
    assert all(item["ok"] for item in checks.values())

    run["final_response"] = json.dumps(
        _final(
            taskOutcome="failed",
            sessions={"old": "dead", "current": "absent"},
            cleanup={"ownedSession": "unknown", "server": "preserved"},
        )
    )
    assert not _checks(run)["kernel-not-resumable-truth"]["ok"]


def test_report_rejects_prose_and_nested_status_values() -> None:
    run = _run(
        "ios-short-flow",
        variant="ios",
        actions=_short_flow_actions(),
        sessions=[{"id": "s1", "preexisting": False, "active": False}],
        final=_final(
            taskOutcome={"status": "completed"},
            sessions={"old": None, "current": {"status": "closed"}},
            cleanup={
                "ownedSession": "failed: DELETE raised WebDriverException",
                "server": "preserved; HTTP 200 confirmed",
            },
        ),
    )
    checks = _checks(run)
    assert not checks["report-canonical-statuses"]["ok"]


def test_bounded_call_rejects_monolithic_actions_and_duration() -> None:
    monolithic = [
        _action("source", at=1 + index * 0.1, detail={"sessionId": "s1"})
        for index in range(skill_behavior.MAX_ACTIONS_PER_CALL + 1)
    ]
    run = _run(
        "android-short-flow",
        variant="android",
        actions=monolithic,
        calls=[_python_call()],
        sessions=[{"id": "s1", "preexisting": False, "active": True}],
        final=_final(taskOutcome="completed"),
    )
    checks = _checks(run)
    assert not checks["bounded-python-exec-calls"]["ok"]
    assert not checks["android-compact-flow"]["ok"]

    long_call = _run(
        "android-short-flow",
        variant="android",
        actions=[_action("source", at=1, detail={"sessionId": "s1"})],
        calls=[
            _python_call(completed="1970-01-01T00:00:31Z"),
        ],
        sessions=[{"id": "s1", "preexisting": False, "active": True}],
        final=_final(taskOutcome="completed"),
    )
    assert not _checks(long_call)["bounded-python-exec-calls"]["ok"]


def test_isolation_regression_fails_summary_and_exit() -> None:
    passed = [{"status": "passed"}]
    assert skill_behavior._overall_status(passed, True) == "passed"
    assert skill_behavior._overall_status(passed, False) == "failed"
    assert skill_behavior._exit_code({"status": "failed"}) == 1
    assert skill_behavior._exit_code({"status": "blocked"}) == 2


def test_owned_runner_selection_excludes_unrelated_processes() -> None:
    processes = {
        100: (1, "copilot"),
        200: (100, "python -m amkernel.runner"),
        300: (1, "python -m amkernel.runner"),
        400: (999, "python -m amkernel.runner"),
        500: (1, "python unrelated.py"),
        600: (1, "python unrelated.py"),
    }
    assert skill_behavior._select_owned_runner_pids(processes, 100, {400, 600}) == [200, 400]


def test_preexisting_cleanup_requires_foreign_session_preserved() -> None:
    preexisting_id = "fixture-preexisting-session"
    own_create = _action(
        "create-session",
        at=1,
        detail={
            "sessionId": "own",
            "caps": json.dumps({"platformName": "iOS", "appium:automationName": "XCUITest"}),
        },
    )
    own_delete = _action("delete-session", at=2, detail={"sessionId": "own"})
    sessions = [
        {"id": preexisting_id, "preexisting": True, "active": True},
        {"id": "own", "preexisting": False, "active": False, "expired": True},
    ]
    run = _run(
        "preexisting-server-preserved",
        variant="preexisting",
        actions=[own_create, own_delete],
        final=_final(
            taskOutcome="completed",
            sessions={"old": "unknown", "current": "absent"},
            cleanup={"ownedSession": "completed", "server": "preserved"},
        ),
        sessions=sessions,
        preexisting_id=preexisting_id,
    )
    checks = _checks(run)
    for check_id in (
        "preexisting-session-never-deleted",
        "preexisting-session-remains-active",
        "own-session-created-and-deleted",
        "preexisting-server-preserved",
    ):
        assert checks[check_id]["ok"] is True, checks[check_id]

    foreign_delete = _action(
        "delete-session",
        at=2,
        status=404,
        detail={"sessionId": preexisting_id},
    )
    run["fixture"]["journal"] = [own_create, foreign_delete, own_delete]
    checks = _checks(run)
    assert checks["preexisting-session-never-deleted"]["ok"] is False

    run["fixture"]["journal"] = [own_create, own_delete]
    run["fixture"]["sessions"][0]["active"] = False
    checks = _checks(run)
    assert checks["preexisting-session-remains-active"]["ok"] is False


def test_preexisting_scenario_seeds_preexisting_session() -> None:
    fixture = skill_behavior.SyntheticAppium(skill_behavior._fixture_config("preexisting"))
    fixture.start()
    try:
        snapshot = fixture.snapshot()
    finally:
        fixture.stop()
    assert snapshot["preexistingId"] == "fixture-preexisting-session"
    preexisting = [
        item for item in snapshot["sessions"] if item.get("id") == snapshot["preexistingId"]
    ]
    assert len(preexisting) == 1
    assert preexisting[0]["active"] is True


def _fixture_request(
    fixture: skill_behavior.SyntheticAppium,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{fixture.port}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_create_delay_commits_session_before_client_timeout() -> None:
    fixture = skill_behavior.SyntheticAppium(skill_behavior.FixtureConfig("create-delay"))
    fixture.start()
    request = urllib.request.Request(
        f"http://127.0.0.1:{fixture.port}/session",
        data=json.dumps(
            {
                "capabilities": {
                    "alwaysMatch": {
                        "platformName": "Android",
                        "appium:automationName": "UiAutomator2",
                    }
                }
            }
        ).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with pytest.raises(TimeoutError):
            urllib.request.urlopen(request, timeout=0.2)
        snapshot = fixture.snapshot()
        assert len(snapshot["createAttempts"]) == 1
        assert len(snapshot["sessions"]) == 1
        assert snapshot["sessions"][0]["active"] is True
        assert any(
            item.get("action") == "create-response-delayed" and item.get("status") == 102
            for item in snapshot["journal"]
        )
        threading.Event().wait(3)
    finally:
        fixture.stop()


def test_fixture_rejects_and_journals_invalid_displayed_timeout_window_queries() -> None:
    fixture = skill_behavior.SyntheticAppium(skill_behavior.FixtureConfig("android"))
    fixture.start()
    try:
        status, created = _fixture_request(
            fixture,
            "POST",
            "/session",
            {
                "capabilities": {
                    "alwaysMatch": {
                        "platformName": "Android",
                        "appium:automationName": "UiAutomator2",
                    }
                }
            },
        )
        assert status == 200
        session_id = created["value"]["sessionId"]
        status, found = _fixture_request(
            fixture,
            "POST",
            f"/session/{session_id}/element",
            {"using": "accessibility id", "value": "Toggle"},
        )
        assert status == 200
        element_id = found["value"]["element-6066-11e4-a52e-4f735466cecf"]
        asserts = [
            ("GET", f"/session/{session_id}/element/{element_id}/displayed", None),
            ("GET", f"/session/{session_id}/timeouts", None),
            ("POST", f"/session/{session_id}/timeouts", {"implicit": 0}),
            ("GET", f"/session/{session_id}/window/rect", None),
        ]
        for method, path, payload in asserts:
            status, _ = _fixture_request(fixture, method, path, payload)
            assert status == 200
        snapshot = fixture.snapshot()
        journal = snapshot["journal"]
        for name in ("displayed", "timeouts", "window-rect"):
            assert any(item.get("action") == name and item.get("status") == 200 for item in journal)
        status, _ = _fixture_request(fixture, "GET", "/session/missing/timeouts")
        assert status == 404
        status, _ = _fixture_request(
            fixture,
            "GET",
            f"/session/{session_id}/element/missing/displayed",
        )
        assert status == 404
        journal = fixture.snapshot()["journal"]
        assert any(
            item.get("action") == "timeouts" and item.get("status") == 404 for item in journal
        )
        assert any(
            item.get("action") == "displayed" and item.get("status") == 404 for item in journal
        )
    finally:
        fixture.stop()


def test_fixture_displayed_reports_stale_element_error() -> None:
    fixture = skill_behavior.SyntheticAppium(skill_behavior.FixtureConfig("session-error"))
    fixture.start()
    try:
        status, created = _fixture_request(
            fixture,
            "POST",
            "/session",
            {
                "capabilities": {
                    "alwaysMatch": {
                        "platformName": "Android",
                        "appium:automationName": "UiAutomator2",
                    }
                }
            },
        )
        assert status == 200
        session_id = created["value"]["sessionId"]
        status, found = _fixture_request(
            fixture,
            "POST",
            f"/session/{session_id}/element",
            {"using": "accessibility id", "value": "Continue"},
        )
        assert status == 200
        element_id = found["value"]["element-6066-11e4-a52e-4f735466cecf"]
        status, response = _fixture_request(
            fixture,
            "GET",
            f"/session/{session_id}/element/{element_id}/displayed",
        )
        assert status == 404
        assert response["value"]["error"] == "stale element reference"
        journal = fixture.snapshot()["journal"]
        stale = [
            item
            for item in journal
            if item.get("action") == "displayed"
            and item.get("detail", {}).get("elementId") == element_id
        ]
        assert len(stale) == 1
        assert stale[0]["status"] == 404
        assert stale[0]["detail"]["error"] == "stale element reference"
        assert stale[0]["detail"]["stale"] is True
    finally:
        fixture.stop()


def test_runner_cleanup_retains_ownership_when_inspection_is_unavailable() -> None:
    context = Mock(
        spec=skill_behavior.RuntimeContext,
        owned_runner_pids={12345},
        runner_lock=threading.Lock(),
    )
    with patch.object(skill_behavior, "_read_process_table", return_value=None):
        unknown = skill_behavior._terminate_owned_runners(context, "cleanup")
    assert unknown[0]["observedExit"] is False
    assert unknown[0]["signalSent"] is False
    assert context.owned_runner_pids == {12345}

    with patch.object(skill_behavior, "_read_process_table", return_value={}):
        observed = skill_behavior._terminate_owned_runners(context, "cleanup retry")
    assert observed[0]["observedExit"] is True
    assert context.owned_runner_pids == set()


def test_runner_cleanup_retains_ownership_until_exit_is_observed() -> None:
    context = Mock(
        spec=skill_behavior.RuntimeContext,
        owned_runner_pids={12345},
        runner_lock=threading.Lock(),
    )
    with (
        patch.object(
            skill_behavior,
            "_read_process_table",
            return_value={12345: (1, "python -m amkernel.runner")},
        ),
        patch.object(os, "getpgid", return_value=12346),
        patch.object(os, "kill"),
    ):
        observed = skill_behavior._terminate_owned_runners(context, "cleanup")
    assert observed[0]["signalSent"] is True
    assert observed[0]["observedExit"] is False
    assert context.owned_runner_pids == {12345}


def test_fixture_attribute_reads_validate_identity_staleness_and_missing_values() -> None:
    fixture = skill_behavior.SyntheticAppium(skill_behavior.FixtureConfig("android"))
    fixture.start()
    try:
        _, created = _fixture_request(
            fixture,
            "POST",
            "/session",
            {
                "capabilities": {
                    "alwaysMatch": {
                        "platformName": "Android",
                        "appium:automationName": "UiAutomator2",
                    }
                }
            },
        )
        session_id = created["value"]["sessionId"]
        _, found = _fixture_request(
            fixture,
            "POST",
            f"/session/{session_id}/element",
            {"using": "accessibility id", "value": "Toggle"},
        )
        element_id = found["value"]["element-6066-11e4-a52e-4f735466cecf"]
        prefix = f"/session/{session_id}/element/{element_id}"
        status, response = _fixture_request(fixture, "GET", f"{prefix}/attribute/content-desc")
        assert status == 200
        assert response["value"] == "Toggle"
        status, response = _fixture_request(fixture, "GET", f"{prefix}/attribute/missing")
        assert status == 200
        assert response["value"] is None
        with fixture.lock:
            fixture.elements[element_id]["stale"] = True
        status, response = _fixture_request(fixture, "GET", f"{prefix}/attribute/content-desc")
        assert status == 404
        assert response["value"]["error"] == "stale element reference"
        status, response = _fixture_request(
            fixture, "GET", f"/session/{session_id}/element/unknown/attribute/content-desc"
        )
        assert status == 404
        assert response["value"]["error"] == "no such element"
        _fixture_request(fixture, "DELETE", f"/session/{session_id}")
        status, response = _fixture_request(fixture, "GET", f"{prefix}/attribute/content-desc")
        assert status == 404
        assert response["value"]["error"] == "invalid session id"
        journal = fixture.snapshot()["journal"]
        reads = [item for item in journal if item.get("action") == "attribute"]
        assert [item["status"] for item in reads] == [200, 200, 404, 404, 404]
        assert not fixture.snapshot()["unknownEndpoints"]
    finally:
        fixture.stop()


def test_targeted_control_state_matches_source_and_proves_change_before_cleanup() -> None:
    import xml.etree.ElementTree as ET

    fixture = skill_behavior.SyntheticAppium(skill_behavior.FixtureConfig("ios"))
    fixture.start()
    try:
        status, created = _fixture_request(
            fixture,
            "POST",
            "/session",
            {
                "capabilities": {
                    "alwaysMatch": {"platformName": "iOS", "appium:automationName": "XCUITest"}
                }
            },
        )
        assert status == 200
        session_id = created["value"]["sessionId"]
        for label in ("Toggle", "Beta"):
            _, found = _fixture_request(
                fixture,
                "POST",
                f"/session/{session_id}/element",
                {"using": "accessibility id", "value": label},
            )
            element_id = found["value"]["element-6066-11e4-a52e-4f735466cecf"]
            prefix = f"/session/{session_id}/element/{element_id}"
            for expected in (False, True):
                status, value = _fixture_request(fixture, "GET", prefix + "/attribute/value")
                assert status == 200
                assert value["value"] == ("on" if expected else "off")
                _, source = _fixture_request(fixture, "GET", f"/session/{session_id}/source")
                control = ET.fromstring(source["value"]).find(f".//*[@name='{label}']")
                assert control is not None
                assert control.attrib["value"] == value["value"]
                status, selected = _fixture_request(fixture, "GET", prefix + "/selected")
                assert status == 200
                assert selected["value"] is expected
                if not expected:
                    _fixture_request(fixture, "POST", prefix + "/click", {})
            snapshot = fixture.snapshot()
            click = next(
                item for item in reversed(snapshot["journal"]) if item["action"] == "click"
            )
            for action in ("attribute", "selected"):
                targeted = dict(
                    snapshot,
                    journal=[item for item in snapshot["journal"] if item["action"] == action],
                )
                assert skill_behavior._state_observation_after_click(targeted, click)
                targeted["journal"].append({"action": "delete-session", "at": click["at"]})
                assert not skill_behavior._state_observation_after_click(targeted, click)
    finally:
        fixture.stop()


def test_short_flow_rejects_an_extra_session_read_only_window() -> None:
    for read_action in ("attribute", "displayed", "enabled", "selected", "timeouts", "window-rect"):
        run = _run(
            "ios-short-flow",
            variant="ios",
            actions=[
                *_short_flow_actions(),
                _action(read_action, at=4.5, detail={"sessionId": "s1"}),
            ],
            calls=[
                _python_call(completed="1970-01-01T00:00:04.100Z"),
                _python_call(
                    started="1970-01-01T00:00:04.200Z",
                    completed="1970-01-01T00:00:04.800Z",
                ),
                _python_call(
                    started="1970-01-01T00:00:04.900Z",
                    completed="1970-01-01T00:00:06Z",
                ),
            ],
            sessions=[{"id": "s1", "preexisting": False, "active": False}],
            state={"toggle": True, "beta": False},
            final=_final(taskOutcome="completed"),
        )
        checks = _checks(run)
        assert not checks["ios-compact-flow"]["ok"], read_action
        assert all(item["ok"] for name, item in checks.items() if name != "ios-compact-flow"), (
            read_action
        )


def _create_android_fixture_session(
    fixture: skill_behavior.SyntheticAppium,
) -> str:
    status, created = _fixture_request(
        fixture,
        "POST",
        "/session",
        {
            "capabilities": {
                "alwaysMatch": {
                    "platformName": "Android",
                    "appium:automationName": "UiAutomator2",
                }
            }
        },
    )
    assert status == 200
    return str(created["value"]["sessionId"])


def _find_fixture_element(
    fixture: skill_behavior.SyntheticAppium, session_id: str, label: str
) -> str:
    status, found = _fixture_request(
        fixture,
        "POST",
        f"/session/{session_id}/element",
        {"using": "accessibility id", "value": label},
    )
    assert status == 200
    return str(found["value"]["element-6066-11e4-a52e-4f735466cecf"])


def test_fixture_sessions_inventory_tracks_preexisting_created_and_deleted() -> None:
    fixture = skill_behavior.SyntheticAppium(skill_behavior._fixture_config("preexisting"))
    fixture.start()
    try:
        preexisting_id = "fixture-preexisting-session"
        status, listed = _fixture_request(fixture, "GET", "/sessions")
        assert status == 200
        assert [item["id"] for item in listed["value"]] == [preexisting_id]
        assert listed["value"][0]["capabilities"] == {
            "platformName": "Android",
            "automationName": "UiAutomator2",
        }

        own_id = _create_android_fixture_session(fixture)
        status, listed = _fixture_request(fixture, "GET", "/sessions")
        assert status == 200
        capabilities = {item["id"]: item["capabilities"] for item in listed["value"]}
        assert set(capabilities) == {preexisting_id, own_id}
        assert capabilities[own_id]["platformName"] == "Android"
        assert capabilities[own_id]["appium:automationName"] == "UiAutomator2"

        status, _ = _fixture_request(fixture, "DELETE", f"/session/{own_id}")
        assert status == 200
        snapshot_before = fixture.snapshot()
        status, listed = _fixture_request(fixture, "GET", "/sessions")
        assert status == 200
        assert [item["id"] for item in listed["value"]] == [preexisting_id]
        snapshot_after = fixture.snapshot()
        assert snapshot_after["sessions"] == snapshot_before["sessions"]
        inventory = [item for item in snapshot_after["journal"] if item.get("action") == "sessions"]
        assert [item["status"] for item in inventory] == [200, 200, 200]
        assert inventory[-1]["detail"] == {
            "count": 1,
            "sessionIds": preexisting_id,
        }
        assert not snapshot_after["unknownEndpoints"]
    finally:
        fixture.stop()


def test_fixture_sessions_inventory_excludes_expired_session_without_mutation() -> None:
    fixture = skill_behavior.SyntheticAppium(skill_behavior.FixtureConfig("stale"))
    fixture.start()
    try:
        _create_android_fixture_session(fixture)
        snapshot_before = fixture.snapshot()
        assert [item["active"] for item in snapshot_before["sessions"]] == [False]
        assert [item["expired"] for item in snapshot_before["sessions"]] == [True]

        status, listed = _fixture_request(fixture, "GET", "/sessions")
        assert status == 200
        assert listed["value"] == []
        snapshot_after = fixture.snapshot()
        assert snapshot_after["sessions"] == snapshot_before["sessions"]
        inventory = [item for item in snapshot_after["journal"] if item.get("action") == "sessions"]
        assert [item["status"] for item in inventory] == [200]
        assert inventory[0]["detail"] == {"count": 0, "sessionIds": ""}
        assert not snapshot_after["unknownEndpoints"]
    finally:
        fixture.stop()


def test_fixture_enabled_reflects_model_and_rejects_invalid_elements_and_sessions() -> None:
    fixture = skill_behavior.SyntheticAppium(skill_behavior.FixtureConfig("android"))
    fixture.start()
    try:
        session_id = _create_android_fixture_session(fixture)
        element_id = _find_fixture_element(fixture, session_id, "Toggle")
        prefix = f"/session/{session_id}/element/{element_id}"

        status, response = _fixture_request(fixture, "GET", f"{prefix}/enabled")
        assert status == 200
        assert response["value"] is True
        with fixture.lock:
            fixture.elements[element_id]["enabled"] = False
        status, response = _fixture_request(fixture, "GET", f"{prefix}/enabled")
        assert status == 200
        assert response["value"] is False

        status, response = _fixture_request(
            fixture, "GET", f"/session/{session_id}/element/unknown/enabled"
        )
        assert status == 404
        assert response["value"]["error"] == "no such element"

        other_session = _create_android_fixture_session(fixture)
        status, response = _fixture_request(
            fixture, "GET", f"/session/{other_session}/element/{element_id}/enabled"
        )
        assert status == 404
        assert response["value"]["error"] == "no such element"

        status, _ = _fixture_request(fixture, "DELETE", f"/session/{session_id}")
        assert status == 200
        status, response = _fixture_request(fixture, "GET", f"{prefix}/enabled")
        assert status == 404
        assert response["value"]["error"] == "invalid session id"

        snapshot = fixture.snapshot()
        reads = [item for item in snapshot["journal"] if item.get("action") == "enabled"]
        assert [item["status"] for item in reads] == [200, 200, 404, 404, 404]
        assert not snapshot["unknownEndpoints"]

        status, response = _fixture_request(fixture, "GET", f"{prefix}/unsupported")
        assert status == 404
        assert response["value"]["error"] == "unknown command"
        assert fixture.snapshot()["unknownEndpoints"]
    finally:
        fixture.stop()


def test_fixture_enabled_stale_element_matches_displayed_error() -> None:
    fixture = skill_behavior.SyntheticAppium(skill_behavior.FixtureConfig("session-error"))
    fixture.start()
    try:
        session_id = _create_android_fixture_session(fixture)
        element_id = _find_fixture_element(fixture, session_id, "Continue")
        prefix = f"/session/{session_id}/element/{element_id}"

        displayed_status, displayed = _fixture_request(fixture, "GET", f"{prefix}/displayed")
        enabled_status, enabled = _fixture_request(fixture, "GET", f"{prefix}/enabled")
        assert displayed_status == enabled_status == 404
        assert enabled["value"] == displayed["value"]

        snapshot = fixture.snapshot()
        reads = [item for item in snapshot["journal"] if item.get("action") == "enabled"]
        assert len(reads) == 1
        assert reads[0]["status"] == 404
        assert reads[0]["detail"]["stale"] is True
        assert reads[0]["detail"]["error"] == "stale element reference"
        assert not snapshot["unknownEndpoints"]
    finally:
        fixture.stop()


def test_short_flow_rejects_false_server_and_restoration_cleanup_claims() -> None:
    for field, rejected in (
        ("server", "cleanup-server-claim-consistent"),
        ("restoration", "cleanup-restoration-claim-consistent"),
    ):
        cleanup = {
            "ownedSession": "completed",
            "server": "preserved",
            "restoration": "not-required",
        }
        cleanup[field] = "completed"
        run = _run(
            "ios-short-flow",
            variant="ios",
            actions=_short_flow_actions(),
            calls=[_python_call()],
            sessions=[{"id": "s1", "preexisting": False, "active": False}],
            state={"toggle": True, "beta": False},
            final=_final(taskOutcome="completed", cleanup=cleanup),
        )
        checks = _checks(run)
        assert not checks[rejected]["ok"], field
        assert all(item["ok"] for name, item in checks.items() if name != rejected), field


# ---------------------------------------------------------------------------
# Conversation targeting evidence regressions

_CONVERSATION_SESSIONS = [{"id": "s1", "preexisting": False, "active": False}]


def _conversation_session_journal() -> list[dict[str, Any]]:
    return [
        _action(
            "create-session",
            at=1,
            detail={
                "sessionId": "s1",
                "caps": json.dumps({"platformName": "Android", "automationName": "UiAutomator2"}),
            },
        ),
        _action("delete-session", at=19, detail={"sessionId": "s1"}),
    ]


def _conversation_action(
    name: str, at: float, detail: dict[str, Any], status: int = 200
) -> dict[str, Any]:
    return {"action": name, "at": at, "status": status, "detail": detail}


def _latest_candidates() -> list[dict[str, Any]]:
    # Mirrors the fixture: native search returns rows by newest nested message,
    # so the highest thread activity is not the first row.
    return [
        {
            "threadId": "thread-third",
            "title": "Release notes",
            "participants": ["Emery Park", "Fin Quinn"],
            "rowIndex": 0,
            "threadActivityAt": 9_600_000.0,
            "threadActivityDisplay": "Today 12:00 AM",
            "activityPrecision": "minute",
            "newestMessageAt": 9_500_000.0,
            "newestMessageDisplay": "2m",
        },
        {
            "threadId": "thread-latest",
            "title": "Field operations",
            "participants": ["Casey Lin", "Dana Ruiz"],
            "rowIndex": 1,
            "threadActivityAt": 9_800_000.0,
            "threadActivityDisplay": "Today 12:05 AM",
            "activityPrecision": "minute",
            "newestMessageAt": 4_000_000.0,
            "newestMessageDisplay": "45m",
        },
        {
            "threadId": "thread-alpha",
            "title": "Alpha planning",
            "participants": ["Avery Chen", "Blake Ortiz"],
            "rowIndex": 2,
            "threadActivityAt": 9_100_000.0,
            "threadActivityDisplay": "Today 11:50 PM",
            "activityPrecision": "minute",
            "newestMessageAt": 9_000_000.0,
            "newestMessageDisplay": "5m",
        },
    ]


def _latest_conversation(
    *,
    actions: list[dict[str, Any]],
    opened: dict[str, Any] | None,
    opened_count: int,
) -> dict[str, Any]:
    return {
        "variant": "conversation-latest",
        "locale": "en-US",
        "timeZone": "America/New_York",
        "referenceClockIso": "2026-11-03T00:20:00-05:00",
        "generation": 2,
        "searchCompleteness": "complete",
        "uncertainReason": None,
        "latestCandidateId": "thread-latest",
        "candidates": _latest_candidates(),
        "opened": opened,
        "openedCount": opened_count,
        "actions": actions,
    }


def _latest_actions(
    *,
    target: str = "thread-latest",
    include_search: bool = True,
    post_refresh_find: bool = True,
    identity_reads: bool = True,
    verify_open: bool = False,
) -> list[dict[str, Any]]:
    search_ids = ["thread-third", "thread-latest", "thread-alpha"]
    actions: list[dict[str, Any]] = []
    if include_search:
        actions.extend(
            [
                _conversation_action(
                    "search",
                    2,
                    {
                        "query": "team",
                        "generation": 1,
                        "returnedCount": 3,
                        "matchedCount": 3,
                        "complete": True,
                        "candidateIds": search_ids,
                    },
                ),
                _conversation_action(
                    "source",
                    3,
                    {
                        "screen": "results",
                        "query": "team",
                        "generation": 1,
                        "candidateIds": search_ids,
                        "rowOrder": search_ids,
                        "hasMore": False,
                    },
                ),
            ]
        )
    for index, thread_id in enumerate(search_ids):
        actions.append(
            _conversation_action(
                "find",
                4 + index,
                {
                    "elementId": f"el-{thread_id}",
                    "targetKind": "row",
                    "threadId": thread_id,
                    "generation": 1,
                },
            )
        )
        actions.append(
            _conversation_action(
                "attribute",
                4.5 + index,
                {
                    "elementId": f"el-{thread_id}",
                    "attribute": "data-activity-iso",
                    "value": "2026-11-02T23:40:00-05:00",
                    "targetKind": "row",
                    "threadId": thread_id,
                    "generation": 1,
                },
            )
        )
        actions.append(
            _conversation_action(
                "attribute",
                4.6 + index,
                {
                    "elementId": f"el-{thread_id}",
                    "attribute": "data-activity-precision",
                    "value": "minute",
                    "targetKind": "row",
                    "threadId": thread_id,
                    "generation": 1,
                },
            )
        )
    actions.append(
        _conversation_action(
            "refresh",
            9,
            {
                "elementId": "el-refresh",
                "previousGeneration": 1,
                "generation": 2,
                "candidateIds": list(reversed(search_ids)),
                "reordered": True,
            },
        )
    )
    if post_refresh_find:
        actions.append(
            _conversation_action(
                "find",
                10,
                {
                    "elementId": "el-relocated",
                    "targetKind": "row",
                    "threadId": target,
                    "generation": 2,
                },
            )
        )
        open_element = "el-relocated"
    else:
        open_element = f"el-{target}"
    actions.append(
        _conversation_action(
            "open",
            11,
            {
                "elementId": open_element,
                "targetKind": "conversation",
                "threadId": target,
                "title": next(
                    item["title"] for item in _latest_candidates() if item["threadId"] == target
                ),
                "participants": next(
                    item["participants"]
                    for item in _latest_candidates()
                    if item["threadId"] == target
                ),
                "generation": 2,
                "clickCount": 1,
            },
        )
    )
    if identity_reads:
        actions.extend(
            [
                _conversation_action(
                    "attribute",
                    12,
                    {
                        "elementId": "el-opened-title",
                        "attribute": "data-thread-id",
                        "value": target,
                        "targetKind": "title",
                        "threadId": target,
                        "generation": 2,
                    },
                ),
                _conversation_action(
                    "attribute",
                    12.1,
                    {
                        "elementId": "el-opened-title",
                        "attribute": "data-title",
                        "value": next(
                            item["title"]
                            for item in _latest_candidates()
                            if item["threadId"] == target
                        ),
                        "targetKind": "title",
                        "threadId": target,
                        "generation": 2,
                    },
                ),
                _conversation_action(
                    "attribute",
                    12.2,
                    {
                        "elementId": "el-opened-title",
                        "attribute": "data-participants",
                        "value": ", ".join(
                            next(
                                item["participants"]
                                for item in _latest_candidates()
                                if item["threadId"] == target
                            )
                        ),
                        "targetKind": "title",
                        "threadId": target,
                        "generation": 2,
                    },
                ),
            ]
        )
    if verify_open:
        actions.append(
            _conversation_action(
                "verify-open",
                12.6,
                {
                    "candidateId": target,
                    "title": next(
                        item["title"] for item in _latest_candidates() if item["threadId"] == target
                    ),
                    "participants": next(
                        item["participants"]
                        for item in _latest_candidates()
                        if item["threadId"] == target
                    ),
                },
            )
        )
    return actions


def _latest_run(
    *,
    target: str = "thread-latest",
    include_search: bool = True,
    post_refresh_find: bool = True,
    identity_reads: bool = True,
    verify_open: bool = False,
    report_target: str | None = None,
) -> dict[str, Any]:
    report_target = report_target if report_target is not None else target
    opened = {
        "threadId": target,
        "title": next(item["title"] for item in _latest_candidates() if item["threadId"] == target),
        "participants": next(
            item["participants"] for item in _latest_candidates() if item["threadId"] == target
        ),
    }
    conversation = _latest_conversation(
        actions=_latest_actions(
            target=target,
            include_search=include_search,
            post_refresh_find=post_refresh_find,
            identity_reads=identity_reads,
            verify_open=verify_open,
        ),
        opened=opened,
        opened_count=1,
    )
    report = {
        "status": "opened",
        "title": next(
            item["title"] for item in _latest_candidates() if item["threadId"] == report_target
        ),
        "participants": next(
            item["participants"]
            for item in _latest_candidates()
            if item["threadId"] == report_target
        ),
    }
    return _run(
        "conversation-latest",
        variant="conversation-latest",
        actions=_conversation_session_journal(),
        sessions=_CONVERSATION_SESSIONS,
        conversation=conversation,
        final=_final(
            taskOutcome="completed",
            cleanup={"ownedSession": "completed", "server": "preserved"},
            conversation=report,
        ),
    )


def test_conversation_latest_passes_with_relocation_and_identity_evidence() -> None:
    checks = _checks(_latest_run())
    assert checks["conversation-native-search"]["ok"]
    assert checks["conversation-correct-thread"]["ok"]
    assert checks["conversation-refresh-relocation"]["ok"]
    assert checks["conversation-opened-identity"]["ok"]
    assert checks["conversation-report-consistent"]["ok"]
    assert all(item["ok"] for item in checks.values())


def test_conversation_latest_accepts_post_open_verification_fact() -> None:
    # The real fixture logs verify-open when the agent reads the opened title
    # element; that observed identity is sufficient without three separate
    # attribute reads.
    checks = _checks(_latest_run(identity_reads=False, verify_open=True))
    assert checks["conversation-opened-identity"]["ok"]


def test_conversation_latest_rejects_activity_observed_only_after_open() -> None:
    run = _latest_run()
    actions = run["fixture"]["conversation"]["actions"]
    for action in actions:
        if action["action"] == "attribute" and action["detail"]["attribute"].startswith(
            "data-activity-"
        ):
            action["at"] = 11.5
    actions.sort(key=lambda action: action["at"])
    checks = _checks(run)
    assert checks["conversation-correct-thread"]["ok"]
    assert not checks["conversation-timestamp-comparison"]["ok"]


def test_conversation_latest_rejects_ui_order_or_message_time_selection() -> None:
    first = _checks(_latest_run(target="thread-alpha"))
    assert not first["conversation-correct-thread"]["ok"]
    assert first["conversation-refresh-relocation"]["ok"]

    message_time = _checks(_latest_run(target="thread-third"))
    assert not message_time["conversation-correct-thread"]["ok"]
    assert not message_time["conversation-thread-not-message-time"]["ok"]


def test_conversation_latest_rejects_stale_element_without_relocation() -> None:
    checks = _checks(_latest_run(post_refresh_find=False))
    assert checks["conversation-correct-thread"]["ok"]
    assert not checks["conversation-refresh-relocation"]["ok"]


def test_conversation_latest_rejects_missing_identity_verification() -> None:
    checks = _checks(_latest_run(identity_reads=False))
    assert checks["conversation-correct-thread"]["ok"]
    assert not checks["conversation-opened-identity"]["ok"]


def test_conversation_latest_rejects_open_without_search() -> None:
    checks = _checks(_latest_run(include_search=False))
    assert not checks["conversation-native-search"]["ok"]
    assert not checks["conversation-search-before-open"]["ok"]
    assert not checks["conversation-selection-bounded"]["ok"]


def _uncertain_candidates() -> list[dict[str, Any]]:
    return [
        {
            "threadId": "thread-one",
            "title": "Budget review",
            "participants": ["Avery Chen", "Blake Ortiz"],
            "rowIndex": 0,
            "activityEpochMs": 7_020_000,
            "activityDisplay": "12m",
            "activityIso": "2026-11-03T00:08:00-05:00",
            "activityPrecision": "minute",
            "lastMessageEpochMs": 7_010_000,
            "lastMessageDisplay": "12m",
        },
        {
            "threadId": "thread-two",
            "title": "Vendor sync",
            "participants": ["Casey Lin", "Dana Ruiz"],
            "rowIndex": 1,
            "activityEpochMs": 7_020_500,
            "activityDisplay": "12m",
            "activityIso": "2026-11-03T00:08:00-05:00",
            "activityPrecision": "minute",
            "lastMessageEpochMs": 7_000_000,
            "lastMessageDisplay": "12m",
        },
        {
            "threadId": "thread-three",
            "title": "Travel plan",
            "participants": ["Emery Park", "Fin Quinn"],
            "rowIndex": 2,
            "activityEpochMs": 6_000_000,
            "activityDisplay": "40m",
            "activityIso": "2026-11-02T23:40:00-05:00",
            "activityPrecision": "minute",
            "lastMessageEpochMs": 6_100_000,
            "lastMessageDisplay": "38m",
        },
    ]


def _uncertain_actions(*, click: bool = False) -> list[dict[str, Any]]:
    actions = [
        _conversation_action(
            "search",
            2,
            {
                "query": "team",
                "generation": 1,
                "returnedCount": 3,
                "matchedCount": 3,
                "complete": True,
                "candidateIds": ["thread-one", "thread-two", "thread-three"],
            },
        ),
        _conversation_action(
            "source",
            3,
            {
                "screen": "results",
                "query": "team",
                "generation": 1,
                "candidateIds": ["thread-one", "thread-two", "thread-three"],
                "rowOrder": ["thread-one", "thread-two", "thread-three"],
                "hasMore": False,
            },
        ),
    ]
    for index, thread_id in enumerate(["thread-one", "thread-two"]):
        actions.append(
            _conversation_action(
                "find",
                4 + index,
                {
                    "elementId": f"el-{thread_id}",
                    "targetKind": "row",
                    "threadId": thread_id,
                    "generation": 1,
                },
            )
        )
        actions.append(
            _conversation_action(
                "attribute",
                4.5 + index,
                {
                    "elementId": f"el-{thread_id}",
                    "attribute": "data-activity-display",
                    "value": "12m",
                    "targetKind": "row",
                    "threadId": thread_id,
                    "generation": 1,
                },
            )
        )
        actions.append(
            _conversation_action(
                "attribute",
                4.6 + index,
                {
                    "elementId": f"el-{thread_id}",
                    "attribute": "data-activity-precision",
                    "value": "minute",
                    "targetKind": "row",
                    "threadId": thread_id,
                    "generation": 1,
                },
            )
        )
    if click:
        actions.append(
            _conversation_action(
                "click",
                8,
                {
                    "elementId": "el-thread-one",
                    "targetKind": "row",
                    "threadId": "thread-one",
                    "generation": 1,
                },
            )
        )
    return actions


def _uncertain_conversation(*, click: bool = False) -> dict[str, Any]:
    return {
        "variant": "conversation-uncertain",
        "locale": "en-US",
        "timeZone": "America/New_York",
        "referenceClockIso": "2026-11-03T00:20:00-05:00",
        "generation": 1,
        "searchCompleteness": "complete",
        "uncertainReason": "coarse-timestamps",
        "latestCandidateId": "thread-two",
        "candidates": _uncertain_candidates(),
        "opened": (
            {
                "threadId": "thread-one",
                "title": "Budget review",
                "participants": ["Avery Chen", "Blake Ortiz"],
            }
            if click
            else None
        ),
        "openedCount": 1 if click else 0,
        "actions": _uncertain_actions(click=click),
    }


def test_conversation_uncertain_passes_without_open_and_reports_ambiguity() -> None:
    run = _run(
        "conversation-uncertain",
        variant="conversation-uncertain",
        actions=_conversation_session_journal(),
        sessions=_CONVERSATION_SESSIONS,
        conversation=_uncertain_conversation(),
        final=_final(
            taskOutcome="blocked",
            cleanup={"ownedSession": "completed", "server": "preserved"},
            conversation={"status": "uncertain", "reason": "coarse-timestamps"},
        ),
    )
    checks = _checks(run)
    assert checks["conversation-uncertain-no-open"]["ok"]
    assert checks["conversation-uncertain-truthful"]["ok"]
    assert all(item["ok"] for item in checks.values())


def test_conversation_uncertain_rejects_guessing_a_conversation() -> None:
    run = _run(
        "conversation-uncertain",
        variant="conversation-uncertain",
        actions=_conversation_session_journal(),
        sessions=_CONVERSATION_SESSIONS,
        conversation=_uncertain_conversation(click=True),
        final=_final(
            taskOutcome="completed",
            cleanup={"ownedSession": "completed", "server": "preserved"},
            conversation={
                "status": "opened",
                "title": "Budget review",
                "participants": ["Avery Chen", "Blake Ortiz"],
            },
        ),
    )
    checks = _checks(run)
    assert not checks["conversation-uncertain-no-open"]["ok"]
    assert not checks["conversation-uncertain-truthful"]["ok"]


def test_conversation_uncertain_rejects_false_certainty_without_open() -> None:
    run = _run(
        "conversation-uncertain",
        variant="conversation-uncertain",
        actions=_conversation_session_journal(),
        sessions=_CONVERSATION_SESSIONS,
        conversation=_uncertain_conversation(),
        final=_final(
            taskOutcome="completed",
            cleanup={"ownedSession": "completed", "server": "preserved"},
            conversation={"status": "opened", "title": "Vendor sync"},
        ),
    )
    checks = _checks(run)
    assert checks["conversation-uncertain-no-open"]["ok"]
    assert not checks["conversation-uncertain-truthful"]["ok"]


def test_conversation_latest_rejects_wrong_or_unverified_report_identity() -> None:
    wrong = _checks(_latest_run(report_target="thread-alpha"))
    assert not wrong["conversation-report-consistent"]["ok"]
    assert wrong["conversation-correct-thread"]["ok"]


@pytest.mark.parametrize(("sizes", "accepted"), [([0, 3], True), ([0], False), ([0, 9], False)])
def test_conversation_search_retries_keep_candidates_bounded(
    sizes: list[int], accepted: bool
) -> None:
    run = _latest_run()
    actions = run["fixture"]["conversation"]["actions"]
    actions[:] = [action for action in actions if action["action"] != "search"]
    for index, size in enumerate(sizes):
        actions.insert(
            index,
            _conversation_action(
                "search",
                1 + index,
                {
                    "query": "team" if size else "no matching participants",
                    "complete": True,
                    "returnedCount": size,
                    "candidateIds": (
                        [item["threadId"] for item in _latest_candidates()] if size else []
                    ),
                },
            ),
        )
    checks = _checks(run)
    assert checks["conversation-bounded-candidates"]["ok"] is accepted
    if accepted:
        assert all(check["ok"] for check in checks.values())


@pytest.mark.parametrize(
    ("complete", "reason", "accepted"),
    [
        (True, "coarse-timestamps", True),
        (True, "incomplete-search", False),
        (False, "coarse-timestamps", True),
        (False, "incomplete-search", True),
        (False, "unknown", False),
    ],
)
def test_conversation_uncertainty_uses_observations_before_restoration(
    complete: bool, reason: str, accepted: bool
) -> None:
    conversation = _uncertain_conversation()
    search = conversation["actions"][0]["detail"]
    search["complete"] = complete
    search["matchedCount"] = 3 if complete else 5
    conversation["actions"].append(
        _conversation_action("search-clear", 8, {"complete": False, "candidateIds": []})
    )
    conversation["candidates"] = []
    conversation["searchCompleteness"] = "incomplete"
    conversation["searchComplete"] = False
    run = _run(
        "conversation-uncertain",
        variant="conversation-uncertain",
        actions=_conversation_session_journal(),
        sessions=_CONVERSATION_SESSIONS,
        conversation=conversation,
        final=_final(
            taskOutcome="blocked",
            cleanup={"ownedSession": "completed", "server": "preserved"},
            conversation={"status": "uncertain", "reason": reason},
        ),
    )
    checks = _checks(run)
    assert checks["conversation-uncertain-truthful"]["ok"] is accepted
    if accepted:
        assert all(check["ok"] for check in checks.values())


@pytest.mark.parametrize(
    "attribute",
    ["data-activity-precision", "data-activity-semantics", "data-message-activity-semantics"],
)
def test_temporal_metadata_alone_cannot_establish_ambiguity(attribute: str) -> None:
    from tests.e2e.conversation_fixture import ConversationAppium

    fixture = ConversationAppium(skill_behavior.FixtureConfig("conversation-uncertain"))
    fixture.start()
    try:
        status, created = _fixture_request(
            fixture,
            "POST",
            "/session",
            {"capabilities": {"alwaysMatch": {"platformName": "Android"}}},
        )
        assert status == 200
        session = created["value"]["sessionId"]
        _, found = _fixture_request(
            fixture,
            "POST",
            f"/session/{session}/element",
            {"using": "accessibility id", "value": "conversation-search"},
        )
        element_key = "element-6066-11e4-a52e-4f735466cecf"
        search = found["value"][element_key]
        status, _ = _fixture_request(
            fixture, "POST", f"/session/{session}/element/{search}/value", {"text": "team"}
        )
        assert status == 200
        for candidate in fixture.snapshot()["conversation"]["candidates"][:2]:
            _, found = _fixture_request(
                fixture,
                "POST",
                f"/session/{session}/element",
                {
                    "using": "accessibility id",
                    "value": "conversation-row:" + candidate["candidateId"],
                },
            )
            row = found["value"][element_key]
            status, _ = _fixture_request(
                fixture,
                "GET",
                f"/session/{session}/element/{row}/attribute/{attribute}",
            )
            assert status == 200
        _fixture_request(fixture, "DELETE", f"/session/{session}")
        snapshot = fixture.snapshot()
        run = _run(
            "conversation-uncertain",
            variant="conversation-uncertain",
            actions=snapshot["journal"],
            sessions=snapshot["sessions"],
            conversation=snapshot["conversation"],
            final=_final(
                taskOutcome="blocked",
                cleanup={"ownedSession": "completed", "server": "preserved"},
                conversation={"status": "uncertain", "reason": "coarse-timestamps"},
            ),
        )
        checks = _checks(run)
        assert not checks["conversation-uncertain-evidence"]["ok"]
        assert not checks["conversation-uncertain-timestamps-observed"]["ok"]
        assert not checks["conversation-uncertain-truthful"]["ok"]
    finally:
        fixture.stop()


def test_fixture_selected_tracks_control_state_and_rejects_invalid_identity() -> None:
    fixture = skill_behavior.SyntheticAppium(skill_behavior.FixtureConfig("android"))
    fixture.start()
    try:
        session = _create_android_fixture_session(fixture)
        element = _find_fixture_element(fixture, session, "Toggle")
        prefix = f"/session/{session}/element/{element}"
        status, response = _fixture_request(fixture, "GET", prefix + "/selected")
        assert status == 200 and response["value"] is False
        status, _ = _fixture_request(fixture, "POST", prefix + "/click", {})
        assert status == 200
        status, response = _fixture_request(fixture, "GET", prefix + "/selected")
        assert status == 200 and response["value"] is True
        other_session = _create_android_fixture_session(fixture)
        for path, error in (
            (f"/session/{session}/element/missing/selected", "no such element"),
            (f"/session/{other_session}/element/{element}/selected", "no such element"),
        ):
            status, response = _fixture_request(fixture, "GET", path)
            assert status == 404 and response["value"]["error"] == error
        with fixture.lock:
            fixture.elements[element]["stale"] = True
        status, response = _fixture_request(fixture, "GET", prefix + "/selected")
        assert status == 404 and response["value"]["error"] == "stale element reference"
        _fixture_request(fixture, "DELETE", f"/session/{session}")
        status, response = _fixture_request(fixture, "GET", prefix + "/selected")
        assert status == 404 and response["value"]["error"] == "invalid session id"
        assert not fixture.snapshot()["unknownEndpoints"]
    finally:
        fixture.stop()


def test_narrower_followup_search_preserves_observed_temporal_ambiguity() -> None:
    conversation = _uncertain_conversation()
    conversation["actions"].append(
        _conversation_action(
            "search",
            7,
            {
                "query": "Research",
                "candidateIds": ["thread-two"],
                "matchedCount": 1,
                "returnedCount": 1,
                "complete": True,
            },
        )
    )
    conversation["candidates"] = [conversation["candidates"][1]]
    run = _run(
        "conversation-uncertain",
        variant="conversation-uncertain",
        actions=_conversation_session_journal(),
        sessions=_CONVERSATION_SESSIONS,
        conversation=conversation,
        final=_final(
            taskOutcome="blocked",
            cleanup={"ownedSession": "completed", "server": "preserved"},
            conversation={"status": "uncertain", "reason": "coarse-timestamps"},
        ),
    )
    checks = _checks(run)
    assert checks["conversation-uncertain-evidence"]["ok"]
    assert checks["conversation-uncertain-truthful"]["ok"]
    assert all(check["ok"] for check in checks.values())


@pytest.mark.parametrize(
    "values,attribute,precision,ambiguous",
    [
        (("1000", "2000"), "data-activity-epoch-ms", "minute", False),
        (("1000", "1000"), "data-activity-epoch-ms", "minute", True),
        (("2026-11-03T08:15:00Z", "2026-11-03T08:16:00Z"), "data-activity-iso", "minute", False),
        (
            ("2026-11-03T08:15:00Z", "2026-11-03T00:15:00-08:00"),
            "data-activity-iso",
            "second",
            True,
        ),
        (("2026-11-03T08:15:00Z", "2026-11-03T08:15:30Z"), "data-activity-iso", "minute", True),
        (("2026-11-03T08:15:00", "2026-11-03T08:16:00"), "data-activity-iso", "second", True),
    ],
)
def test_later_normalized_time_evidence_resolves_only_disjoint_candidate_intervals(
    values: tuple[str, str], attribute: str, precision: str, ambiguous: bool
) -> None:
    conversation = _uncertain_conversation()
    for index, (candidate, value) in enumerate(
        zip(("thread-one", "thread-two"), values, strict=True)
    ):
        for offset, field, observed in (
            (0, attribute, value),
            (0.1, "data-activity-precision", precision),
        ):
            conversation["actions"].append(
                _conversation_action(
                    "attribute",
                    7 + index + offset,
                    {
                        "threadId": candidate,
                        "attribute": field,
                        "value": observed,
                        "targetKind": "row",
                    },
                )
            )
    run = _run(
        "conversation-uncertain",
        variant="conversation-uncertain",
        actions=_conversation_session_journal(),
        sessions=_CONVERSATION_SESSIONS,
        conversation=conversation,
        final=_final(
            taskOutcome="blocked",
            cleanup={"ownedSession": "completed", "server": "preserved"},
            conversation={"status": "uncertain", "reason": "coarse-timestamps"},
        ),
    )
    checks = _checks(run)
    assert checks["conversation-uncertain-evidence"]["ok"] is ambiguous
    assert checks["conversation-uncertain-truthful"]["ok"] is ambiguous


@pytest.mark.parametrize(
    "title_matches,participants_match,accepted",
    [
        (True, True, True),
        (False, True, False),
        (True, False, False),
    ],
)
def test_opened_identity_requires_matching_returned_title_and_participants(
    title_matches: bool, participants_match: bool, accepted: bool
) -> None:
    run = _latest_run(identity_reads=False)
    conversation = run["fixture"]["conversation"]
    opened = conversation["opened"]
    opened_at = next(item["at"] for item in conversation["actions"] if item["action"] == "open")
    title = opened["title"] if title_matches else "Different conversation"
    participants = opened["participants"] if participants_match else ["Different participant"]
    for offset, kind, value in (
        (0.1, "title", title),
        (0.2, "conversation", "Participants: " + ", ".join(participants)),
    ):
        conversation["actions"].append(
            _conversation_action(
                "attribute",
                opened_at + offset,
                {
                    "threadId": opened["threadId"],
                    "attribute": "text",
                    "targetKind": kind,
                    "value": value,
                },
            )
        )
    assert _checks(run)["conversation-opened-identity"]["ok"] is accepted


@pytest.mark.parametrize(
    "support,outcome,attempt,accepted",
    [
        ("unsupported", "blocked", False, True),
        (None, "blocked", False, False),
        ("unsupported", "completed", False, False),
        ("unsupported", "blocked", True, False),
    ],
)
def test_unsupported_target_requires_blocked_classification_without_session_attempt(
    support: str | None, outcome: str, attempt: bool, accepted: bool
) -> None:
    run = _run(
        "unsupported-windows",
        variant="none",
        actions=[_action("create-session", at=1)] if attempt else [],
        final=_final(
            taskOutcome=outcome,
            platformSupport=support,
            cleanup={"ownedSession": "not-required", "server": "not-required"},
        ),
    )
    assert all(check["ok"] for check in _checks(run).values()) is accepted


@pytest.mark.parametrize(
    "action,status,state,at,accepted",
    [
        ("source", 200, {"beta": False}, 2, True),
        ("read-state", 200, {"beta": False}, 2, True),
        (None, 200, {"beta": False}, 2, False),
        ("source", 200, None, 2, False),
        ("source", 200, {}, 2, False),
        ("source", 200, {"beta": True}, 2, False),
        ("source", 200, {"beta": 0}, 2, False),
        ("read-state", 200, {"beta": 0}, 2, False),
        ("source", 500, {"beta": False}, 2, False),
        ("read-state", 500, {"beta": False}, 2, False),
        ("source", 200, {"beta": False}, 3, False),
        ("read-state", 200, {"beta": False}, 3.5, False),
        ("source", 200, {"beta": False}, 5, False),
    ],
)
def test_restoration_requires_successful_pre_action_baseline(
    action: str | None,
    status: int,
    state: dict[str, Any] | None,
    at: float,
    accepted: bool,
) -> None:
    actions = [_action("create-session", at=1)]
    if action is not None:
        actions.append(
            _action(action, at=at, status=status, detail={} if state is None else {"state": state})
        )
    actions.extend(
        [
            _action("click", at=3, detail={"label": "Beta", "state": {"beta": True}}),
            _action("click", at=4, detail={"label": "Beta", "state": {"beta": False}}),
            _action("delete-session", at=6),
        ]
    )
    run = _run(
        "restore-before-quit",
        variant="restore",
        actions=sorted(actions, key=lambda item: item["at"]),
        final=_final(
            taskOutcome="completed",
            cleanup={
                "ownedSession": "completed",
                "restoration": "completed",
                "server": "preserved",
            },
        ),
    )
    checks = _checks(run)
    assert checks["restore-initial-observation"]["ok"] is accepted
    assert checks["restore-toggle-on-then-off"]["ok"]
    assert checks["restore-final-state"]["ok"]
    assert checks["restore-before-delete"]["ok"]
