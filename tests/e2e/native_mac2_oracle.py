"""Pure qualification oracle for actual native Mac2 Calculator evidence (#108).

This module only evaluates retained evidence. It does not start Appium, invoke a
client, read logs, or rewrite the record it is given.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, cast

_FINAL_STATUS_VALUES: Final[dict[str, frozenset[str]]] = {
    "taskOutcome": frozenset(
        {"completed", "blocked", "failed", "ready-for-next-step", "approval-required"}
    ),
    "stateRestoration": frozenset(
        {"restored", "unchanged", "not-needed", "not-applicable", "failed", "unknown"}
    ),
    "sessionCleanup": frozenset(
        {"cleaned", "not-created", "not-needed", "not-applicable", "failed", "unknown"}
    ),
    "serverCleanup": frozenset(
        {
            "not-owned",
            "preserved",
            "not-started",
            "not-needed",
            "not-applicable",
            "failed",
            "unknown",
        }
    ),
}


@dataclass(frozen=True)
class _Execution:
    status: str
    success: bool
    window: tuple[datetime, datetime]


def _mapping(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return cast(Mapping[str, Any], value)
    return {}


def _utc(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        return None
    return parsed.astimezone(UTC)


def _window(value: object) -> tuple[datetime, datetime] | None:
    item = _mapping(value)
    started = _utc(item.get("startedAt"))
    completed = _utc(item.get("completedAt"))
    if started is None or completed is None or started > completed:
        return None
    return started, completed


def _inside(inner: tuple[datetime, datetime], outer: tuple[datetime, datetime]) -> bool:
    return outer[0] <= inner[0] and inner[1] <= outer[1]


def _status_ok(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == 200


def _count_is(value: object, expected: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == expected


def _is_execution_call(call: Mapping[str, Any]) -> bool:
    return (
        call.get("mcpToolName") == "python_exec"
        or call.get("toolName") == "amkernel-python_exec"
        or any(key in call for key in ("status", "kernelState", "executionCount"))
    )


def _parse_executions(native: Mapping[str, Any]) -> list[_Execution] | None:
    calls = native.get("calls")
    if not isinstance(calls, list):
        return None
    executions: list[_Execution] = []
    previous_count: int | None = None
    previous_end: datetime | None = None
    for raw_call in calls:
        if not isinstance(raw_call, Mapping):
            return None
        call = _mapping(raw_call)
        if not _is_execution_call(call):
            continue
        if call.get("mcpToolName") != "python_exec" or not (
            call.get("mcpConfigServerName") == "amkernel"
            or call.get("toolName") == "amkernel-python_exec"
        ):
            return None
        status = call.get("status")
        kernel_state = call.get("kernelState")
        success = call.get("success")
        count = call.get("executionCount")
        window = _window(call)
        if not isinstance(status, str) or status not in {"completed", "failed"}:
            return None
        if kernel_state != "alive":
            return None
        if not isinstance(success, bool):
            return None
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            return None
        if window is None:
            return None
        if previous_count is not None and count <= previous_count:
            return None
        if previous_end is not None and window[0] < previous_end:
            return None
        executions.append(_Execution(status=status, success=success, window=window))
        previous_count = count
        previous_end = window[1]
    return executions or None


def _query_in_windows(
    query: tuple[datetime, datetime], windows: list[tuple[datetime, datetime]]
) -> bool:
    return any(_inside(query, window) for window in windows)


def _live_foreground_query(protocol: Mapping[str, Any]) -> Mapping[str, Any] | None:
    query = _mapping(protocol.get("queryAppState"))
    if (
        query.get("observed") is True
        and _status_ok(query.get("status"))
        and query.get("scriptOk") is True
        and query.get("bundleArgumentOk") is True
        and query.get("foregroundOk") is True
    ):
        return query
    return None


def _live_window_queries(protocol: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    queries: list[Mapping[str, Any]] = []
    elements = _mapping(protocol.get("windowElements"))
    if (
        elements.get("observed") is True
        and _status_ok(elements.get("status"))
        and elements.get("windowQuery") is True
        and elements.get("nonEmptyElementList") is True
    ):
        queries.append(elements)
    handles = _mapping(protocol.get("windowHandles"))
    if (
        handles.get("observed") is True
        and _status_ok(handles.get("status"))
        and handles.get("nonEmptyHandleList") is True
    ):
        queries.append(handles)
    return queries


def _create_ok(create: Mapping[str, Any]) -> bool:
    return (
        create.get("observed") is True
        and _status_ok(create.get("status"))
        and create.get("requestAutomationNameMac2") is True
        and create.get("requestCalculatorBundleId") is True
        and create.get("requestPlatformMac") is True
        and create.get("responseAutomationNameMac2") is True
        and create.get("responseCalculatorBundleId") is True
    )


def _delete_ok(delete: Mapping[str, Any]) -> bool:
    return delete.get("observed") is True and _status_ok(delete.get("status"))


def _single_session_ok(protocol: Mapping[str, Any]) -> bool:
    return (
        protocol.get("parseComplete") is True
        and _count_is(protocol.get("sessionIdsObservedCount"), 1)
        and protocol.get("singleSessionObserved") is True
    )


def _listing_ok(protocol: Mapping[str, Any]) -> bool:
    listing = _mapping(protocol.get("listing"))
    return (
        listing.get("observed") is True
        and listing.get("observedBeforeOwnedServerStop") is True
        and _count_is(listing.get("count"), 0)
        and listing.get("qualifyingSessionListed") is False
    )


def _restoration_before_delete(protocol: Mapping[str, Any]) -> bool:
    create = _mapping(protocol.get("createSession"))
    delete = _mapping(protocol.get("sessionDelete"))
    restoration = _mapping(protocol.get("restoration"))
    create_window = _window(create)
    restoration_window = _window(restoration)
    delete_window = _window(delete)
    return (
        _create_ok(create)
        and _delete_ok(delete)
        and restoration.get("observed") is True
        and restoration.get("beforeSessionDelete") is True
        and create_window is not None
        and restoration_window is not None
        and delete_window is not None
        and create_window[1] <= restoration_window[0]
        and restoration_window[1] <= delete_window[0]
    )


def _native_recovery_proven(record: Mapping[str, Any]) -> bool:
    """Prove both live target queries postdate the last failed execution.

    Every execution must have an alive kernel and a monotonic execution count.
    The foreground and window queries must each fall inside a successful
    completed/alive execution window, and both must start after the last failed
    execution. Session creation, restoration, and deletion must also be
    timestamped in causal order.
    """
    native = _mapping(record.get("native"))
    protocol = _mapping(record.get("protocol"))
    executions = _parse_executions(native)
    if executions is None or not _single_session_ok(protocol):
        return False

    create = _mapping(protocol.get("createSession"))
    delete = _mapping(protocol.get("sessionDelete"))
    restoration = _mapping(protocol.get("restoration"))
    foreground = _live_foreground_query(protocol)
    window_queries = _live_window_queries(protocol)
    if foreground is None or not window_queries:
        return False

    create_window = _window(create)
    restoration_window = _window(restoration)
    delete_window = _window(delete)
    foreground_window = _window(foreground)
    window_query_windows = [
        window for query in window_queries if (window := _window(query)) is not None
    ]
    if (
        not _create_ok(create)
        or not _delete_ok(delete)
        or restoration.get("observed") is not True
        or restoration.get("beforeSessionDelete") is not True
        or create_window is None
        or restoration_window is None
        or delete_window is None
        or foreground_window is None
        or not window_query_windows
    ):
        return False

    successful_windows = [
        execution.window
        for execution in executions
        if execution.status == "completed" and execution.success
    ]
    if not successful_windows:
        return False
    failed_ends = [
        execution.window[1]
        for execution in executions
        if execution.status == "failed" or not execution.success
    ]
    last_failure_end = failed_ends[-1] if failed_ends else None
    if last_failure_end is not None and foreground_window[0] <= last_failure_end:
        return False
    if not (
        create_window[1] <= foreground_window[0] <= foreground_window[1] <= restoration_window[0]
    ):
        return False
    if restoration_window[1] > delete_window[0]:
        return False
    return _query_in_windows(foreground_window, successful_windows) and any(
        (last_failure_end is None or window[0] > last_failure_end)
        and create_window[1] <= window[0] <= window[1] <= restoration_window[0]
        and _query_in_windows(window, successful_windows)
        for window in window_query_windows
    )


def _final_status(record: Mapping[str, Any]) -> tuple[Mapping[str, Any], bool]:
    native = _mapping(record.get("native"))
    raw_status = native.get("finalStatus")
    if not isinstance(raw_status, Mapping):
        return {}, False
    final_status = _mapping(raw_status)
    canonical = all(
        isinstance(final_status.get(field), str) and final_status.get(field) in allowed
        for field, allowed in _FINAL_STATUS_VALUES.items()
    )
    return final_status, canonical


def _harness_owns_server(record: Mapping[str, Any]) -> bool:
    server = _mapping(record.get("server"))
    owned = _mapping(_mapping(record.get("cleanup")).get("ownedServer"))
    return (
        server.get("shared") is False
        and server.get("groupOwned") is True
        and server.get("ready") is True
        and owned.get("started") is True
        and owned.get("groupOwned") is True
    )


def qualify(record: Mapping[str, Any]) -> dict[str, bool]:
    """Return the corrected #108 qualification flags without mutating ``record``."""
    root = _mapping(record)
    native = _mapping(root.get("native"))
    process = _mapping(native.get("process"))
    cleanup = _mapping(root.get("cleanup"))
    owned = _mapping(cleanup.get("ownedServer"))
    runner = _mapping(cleanup.get("runner"))
    appium = _mapping(root.get("appium"))
    protocol = _mapping(root.get("protocol"))
    create = _mapping(protocol.get("createSession"))
    delete = _mapping(protocol.get("sessionDelete"))
    final_status, final_report_canonical = _final_status(root)

    exit_code = process.get("exitCode")
    harness_completed = root.get("error") is None and root.get("failedAt") is None
    native_client_completed = (
        isinstance(exit_code, int)
        and not isinstance(exit_code, bool)
        and exit_code == 0
        and process.get("timedOut") is False
    )
    main_skill_loaded = native.get("mainSkillLoaded") is True
    native_recovery_proven = _native_recovery_proven(root)
    actual_mac2_session_created = _create_ok(create)
    actual_calculator_query_app_state = _live_foreground_query(protocol) is not None
    actual_window_query = bool(_live_window_queries(protocol))
    single_actual_session = _single_session_ok(protocol)
    session_delete_observed = _delete_ok(delete)
    session_gone_before_owned_server_stop = _listing_ok(protocol)
    desktop_restored = cleanup.get("desktopRestored") is True
    restoration_before_session_delete = _restoration_before_delete(protocol)
    owned_server_exited = owned.get("exited") is True
    owned_process_group_gone = owned.get("processGroupGone") is True
    owned_appium_port_closed = owned.get("appiumPortClosed") is True
    owned_wda_port_closed = owned.get("wdaPortClosed") is True
    raw_appium_log_removed = appium.get("rawLogRemoved") is True
    runner_resources_observed_gone = runner.get("observedGone") is True
    owned_resources_observed_gone = all(
        (
            owned_server_exited,
            owned_process_group_gone,
            owned_appium_port_closed,
            owned_wda_port_closed,
            runner_resources_observed_gone,
        )
    )

    actual_task_succeeded = all(
        (
            harness_completed,
            native_client_completed,
            main_skill_loaded,
            native_recovery_proven,
            actual_mac2_session_created,
            actual_calculator_query_app_state,
            actual_window_query,
            single_actual_session,
            session_delete_observed,
            session_gone_before_owned_server_stop,
            desktop_restored,
            restoration_before_session_delete,
            raw_appium_log_removed,
            owned_resources_observed_gone,
        )
    )
    report_task_completed = (
        final_report_canonical
        and actual_task_succeeded
        and final_status.get("taskOutcome") == "completed"
    )
    report_restoration_consistent = (
        final_report_canonical
        and desktop_restored
        and restoration_before_session_delete
        and final_status.get("stateRestoration") in {"restored", "unchanged"}
    )
    report_session_cleanup_consistent = (
        final_report_canonical
        and actual_mac2_session_created
        and single_actual_session
        and session_delete_observed
        and session_gone_before_owned_server_stop
        and final_status.get("sessionCleanup") == "cleaned"
    )
    report_server_cleanup_consistent = (
        final_report_canonical
        and _harness_owns_server(root)
        and final_status.get("serverCleanup") in {"not-owned", "preserved"}
    )

    return {
        "harnessCompleted": harness_completed,
        "nativeClientCompleted": native_client_completed,
        "mainSkillLoaded": main_skill_loaded,
        "nativeRecoveryProven": native_recovery_proven,
        "actualMac2SessionCreated": actual_mac2_session_created,
        "actualCalculatorQueryAppState": actual_calculator_query_app_state,
        "actualWindowQuery": actual_window_query,
        "singleActualSession": single_actual_session,
        "sessionDeleteObserved": session_delete_observed,
        "sessionGoneBeforeOwnedServerStop": session_gone_before_owned_server_stop,
        "desktopRestored": desktop_restored,
        "restorationBeforeSessionDelete": restoration_before_session_delete,
        "ownedServerExited": owned_server_exited,
        "ownedProcessGroupGone": owned_process_group_gone,
        "ownedAppiumPortClosed": owned_appium_port_closed,
        "ownedWdaPortClosed": owned_wda_port_closed,
        "rawAppiumLogRemoved": raw_appium_log_removed,
        "runnerResourcesObservedGone": runner_resources_observed_gone,
        "ownedResourcesObservedGone": owned_resources_observed_gone,
        "finalReportCanonical": final_report_canonical,
        "reportTaskCompleted": report_task_completed,
        "reportRestorationConsistent": report_restoration_consistent,
        "reportSessionCleanupConsistent": report_session_cleanup_consistent,
        "reportServerCleanupConsistent": report_server_cleanup_consistent,
    }
