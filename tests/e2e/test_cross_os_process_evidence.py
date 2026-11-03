"""Focused regression tests for evidence validation, not cross-OS observations."""

from __future__ import annotations

import unittest

from tests.e2e.cross_os_process_evidence import (
    EvidenceError,
    check_checks,
    check_expected_invocation,
)


class CheckConsistencyTests(unittest.TestCase):
    def test_contradictory_passed_check_is_rejected(self) -> None:
        row = {"id": "installed-startup", "expected": {"serverState": "ready"}}
        cell = {
            "checks": [
                {"name": "serverState", "expected": "ready", "observed": "running", "passed": True}
            ],
            "observed": {"serverState": "ready"},
            "errorType": None,
        }
        with self.assertRaises(EvidenceError):
            check_checks(cell, row, True)

    def test_missing_expected_check_is_rejected(self) -> None:
        row = {"id": "installed-startup", "expected": {"serverState": "ready"}}
        cell = {"checks": [], "observed": {"serverState": "ready"}, "errorType": None}
        with self.assertRaises(EvidenceError):
            check_checks(cell, row, True)

    def test_consistent_check_is_accepted(self) -> None:
        row = {"id": "installed-startup", "expected": {"serverState": "ready"}}
        cell = {
            "checks": [
                {"name": "serverState", "expected": "ready", "observed": "ready", "passed": True}
            ],
            "observed": {"serverState": "ready"},
            "errorType": None,
        }
        check_checks(cell, row, True)


class InvocationTests(unittest.TestCase):
    def _dispatch(self) -> dict[str, str]:
        return {
            "repository": "owner/repo",
            "workflow": "Cross-OS process evidence",
            "workflowRef": "owner/repo/.github/workflows/cross-os-process-evidence.yml@refs/heads/main",
            "runId": "123",
            "runAttempt": "1",
            "sha": "a" * 40,
        }

    def test_matching_invocation_is_accepted(self) -> None:
        record = {"dispatch": self._dispatch()}
        check_expected_invocation(record, dict(self._dispatch()))

    def test_mismatched_run_is_rejected(self) -> None:
        record = {"dispatch": self._dispatch()}
        expected = dict(self._dispatch())
        expected["runId"] = "124"
        with self.assertRaises(EvidenceError):
            check_expected_invocation(record, expected)

    def test_mismatched_commit_is_rejected(self) -> None:
        record = {"dispatch": self._dispatch()}
        expected = dict(self._dispatch())
        expected["sha"] = "b" * 40
        with self.assertRaises(EvidenceError):
            check_expected_invocation(record, expected)


if __name__ == "__main__":
    unittest.main()
