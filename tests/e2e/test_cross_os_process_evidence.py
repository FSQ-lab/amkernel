"""Evidence-validation regressions, not cross-OS observations."""

from __future__ import annotations

from typing import Any

import pytest

from tests.e2e.cross_os_process_evidence import (
    EvidenceError,
    check_checks,
    check_expected_invocation,
    check_transitions,
)


def test_contradictory_passed_check_is_rejected() -> None:
    row = {"id": "installed-startup", "expected": {"serverState": "ready"}}
    cell = {
        "checks": [
            {"name": "serverState", "expected": "ready", "observed": "running", "passed": True}
        ],
        "observed": {"serverState": "ready"},
        "errorType": None,
    }
    with pytest.raises(EvidenceError):
        check_checks(cell, row, True)


def test_missing_expected_check_is_rejected() -> None:
    row = {"id": "installed-startup", "expected": {"serverState": "ready"}}
    cell: dict[str, Any] = {"checks": [], "observed": {"serverState": "ready"}, "errorType": None}
    with pytest.raises(EvidenceError):
        check_checks(cell, row, True)


def test_mismatched_hosted_run_is_rejected() -> None:
    dispatch = {
        "repository": "owner/repo",
        "workflow": "Cross-OS process evidence",
        "workflowRef": "owner/repo/.github/workflows/cross-os-process-evidence.yml@refs/heads/main",
        "runId": "123",
        "runAttempt": "1",
        "sha": "a" * 40,
    }
    expected = {**dispatch, "runId": "124"}
    with pytest.raises(EvidenceError):
        check_expected_invocation({"dispatch": dispatch}, expected)


def test_timeout_transition_cannot_contradict_observed_status() -> None:
    cell = {
        "stateTransition": [
            {
                "at": "2026-11-03T00:00:00Z",
                "phase": "after-timeout",
                "serverState": "ready",
                "kernelState": "alive",
                "executionCount": 2,
                "status": "completed",
            }
        ],
        "observed": {"status": "timed_out", "kernelState": "alive"},
    }
    with pytest.raises(EvidenceError, match="status disagrees"):
        check_transitions(cell, "timeout-survives", True)


def test_startup_transition_cannot_claim_a_terminal_execution_status() -> None:
    cell = {
        "stateTransition": [
            {
                "at": "2026-11-03T00:00:00Z",
                "phase": "after-mcp-initialize",
                "serverState": "ready",
                "kernelState": "alive",
                "executionCount": 1,
                "status": "kernel_killed",
            }
        ],
        "observed": {"serverState": "ready", "kernelState": "alive"},
    }
    with pytest.raises(EvidenceError, match="status disagrees"):
        check_transitions(cell, "installed-startup", True)
