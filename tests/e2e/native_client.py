"""Reusable native Copilot experiment helper; not product code.

The existing Copilot entry point in :mod:`tests.e2e.skill_behavior` is reused
unchanged. Tool starts, completions, and result payloads are observed from the
real event stream. Only allowlisted identity, status, timestamp, and digest
evidence is retained. Raw payloads and the parsed final report are returned
transiently for the caller's domain-specific oracle and are never embedded in
the retained record.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from tests.e2e import skill_behavior as behavior
from tests.e2e.skill_behavior import (
    RuntimeContext,
    _final_json,
    _payload_from_result,
    _run_copilot,
    _terminate_owned_runners,
)

# The historical helper temporarily replaced this module-global normalization
# function. Serialize the patch and the run so two in-process experiments can
# never observe each other's observer.
_NORMALIZE_LOCK = threading.Lock()

_PROCESS_KEYS = ("exitCode", "timedOut", "durationMs", "eventCount", "malformedEventLines")
_CLEANUP_KEYS = (
    "runnerPid",
    "reason",
    "signalSent",
    "observedExit",
    "identityMismatch",
    "signal",
    "target",
    "error",
)
_FINAL_ENUMS: dict[str, frozenset[str]] = {
    "taskOutcome": frozenset({"completed", "blocked", "failed", "approval-required"}),
    "stateRestoration": frozenset({"restored", "unchanged", "not-needed", "failed", "unknown"}),
    "sessionCleanup": frozenset({"cleaned", "not-created", "failed", "unknown"}),
    "serverCleanup": frozenset({"not-owned", "preserved", "not-started", "failed", "unknown"}),
}
_SKILL_NAMES = frozenset(
    {
        "amkernel",
        "setup-mac2",
        "setup-uiautomator2",
        "setup-xcuitest",
        "xcuitest-real-device-config",
    }
)


def digest(text: str) -> str:
    """Return the SHA-256 hex digest of UTF-8 text."""
    return hashlib.sha256(text.encode()).hexdigest()


def _event_timestamp(event: Mapping[str, Any]) -> str | None:
    """Copy an observed Copilot event timestamp verbatim, or fail closed."""
    value = event.get("timestamp")
    if isinstance(value, str) and value.strip():
        return value
    return None


def _cleanup_entries(entries: object) -> list[dict[str, object]]:
    if not isinstance(entries, list):
        return []
    result: list[dict[str, object]] = []
    for item in entries:
        if not isinstance(item, Mapping):
            continue
        result.append({key: item[key] for key in _CLEANUP_KEYS if key in item})
    return result


def _process_record(process: Mapping[str, Any], final_cleanup: object) -> dict[str, Any]:
    safe: dict[str, Any] = {key: process[key] for key in _PROCESS_KEYS if key in process}
    if "runnerCleanup" in process:
        safe["runnerCleanup"] = _cleanup_entries(process.get("runnerCleanup"))
    filtered_final = _cleanup_entries(final_cleanup)
    if filtered_final:
        safe["runnerCleanupFinal"] = filtered_final
    return safe


def _final_status(parsed: Mapping[str, Any] | None) -> dict[str, str]:
    if parsed is None:
        return {}
    result: dict[str, str] = {}
    for key, allowed in _FINAL_ENUMS.items():
        value = parsed.get(key)
        if isinstance(value, str) and value in allowed:
            result[key] = value
    return result


def _call_record(
    call: Mapping[str, Any],
    *,
    call_id: str,
    started_at: str | None,
    completed_at: str | None,
    arguments_sha256: str | None,
    code_sha256: str | None,
    payload: Mapping[str, Any] | None,
) -> dict[str, Any]:
    arguments = call.get("arguments")
    arguments = arguments if isinstance(arguments, Mapping) else {}
    item: dict[str, Any] = {
        "toolName": call.get("toolName"),
        "mcpToolName": call.get("mcpToolName"),
        "mcpConfigSource": call.get("mcpConfigSource"),
        "mcpServerName": call.get("mcpServerName"),
        "mcpConfigServerName": call.get("mcpConfigServerName"),
        "mcpTransport": call.get("mcpTransport"),
        "callIdSha256": digest(call_id),
        "startedAt": started_at,
        "completedAt": completed_at,
        "argumentsSha256": arguments_sha256,
        "codeSha256": code_sha256,
        "success": call.get("success") is True,
    }
    if call.get("toolName") == "skill":
        name = arguments.get("skill")
        if isinstance(name, str) and name in _SKILL_NAMES:
            item["skill"] = name
    if payload is not None:
        item.update(
            {
                key: payload.get(key)
                for key in ("status", "kernelState", "executionCount", "durationMs")
            }
        )
        for key in ("stdout", "stderr"):
            text = payload.get(key)
            if isinstance(text, str):
                encoded = text.encode()
                item[key + "Sha256"] = hashlib.sha256(encoded).hexdigest()
                item[key + "Bytes"] = len(encoded)
        error = payload.get("error")
        if isinstance(error, Mapping):
            error_type = error.get("type")
            item["errorType"] = error_type if isinstance(error_type, str) else None
    return item


def run_native(
    project: Path,
    cli: Path,
    prompt: str,
    base: Path,
    env: dict[str, str],
    timeout: int = 420,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any] | None]:
    """Run one native Copilot prompt and return safe, transient, parsed evidence.

    The first value retains only allowlisted observations. The second value is
    the list of raw ``python_exec`` result payloads underlying those
    observations, and the third is the parsed final assistant JSON. Callers
    must not persist either transient value without their own field filtering.
    """
    options = SimpleNamespace(copilot=cli, model="gpt-6.1-sol", timeout=timeout)
    context = RuntimeContext(
        options=cast(Any, options),
        base=base,
        project=project,
        home=base / "copilot",
        env=env,
        token=env["COPILOT_GITHUB_TOKEN"],
        temp_evidence={},
        evidence={},
        commands=[],
        isolation_before={},
    )

    start_times: dict[str, str | None] = {}
    complete_times: dict[str, str | None] = {}
    argument_hashes: dict[str, str] = {}
    code_hashes: dict[str, str] = {}
    payload_by_call: dict[str, dict[str, Any]] = {}

    observed_payloads: list[dict[str, Any]] = []

    final_cleanup: object = []
    with _NORMALIZE_LOCK:
        # Capture the true original only while holding the lock, then define and
        # install the observer. A nested call therefore can never restore a
        # sibling experiment's temporary observer.
        original_normalize = behavior.normalize_copilot_events

        def observe(
            events: Sequence[Mapping[str, Any]],
        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
            calls, servers, final = original_normalize(events)
            for event in events:
                event_type = event.get("type")
                data = event.get("data")
                if not isinstance(data, Mapping):
                    continue
                call_id = data.get("toolCallId")
                if not isinstance(call_id, str):
                    continue
                if event_type == "tool.execution_start":
                    start_times[call_id] = _event_timestamp(event)
                    arguments = data.get("arguments")
                    argument_hashes[call_id] = digest(json.dumps(arguments, sort_keys=True))
                    if isinstance(arguments, Mapping):
                        code = arguments.get("code")
                        if isinstance(code, str):
                            code_hashes[call_id] = digest(code)
                elif event_type == "tool.execution_complete":
                    complete_times[call_id] = _event_timestamp(event)
                    payload = _payload_from_result(data.get("result"))
                    if isinstance(payload, dict) and "kernelState" in payload:
                        payload_by_call[call_id] = payload
            return calls, servers, final

        behavior.normalize_copilot_events = observe
        try:
            try:
                calls, _servers, final, details = _run_copilot(context, prompt)
            finally:
                behavior.normalize_copilot_events = original_normalize
        finally:
            # _run_copilot terminates its process-exit/timeout resources; this
            # second pass covers failures in observation or post-processing too.
            # It reports only Runner pids this context claimed as owned.
            final_cleanup = _terminate_owned_runners(context, "post-run")

    process = details.get("process")
    process = process if isinstance(process, Mapping) else {}
    records: list[dict[str, Any]] = []
    for call in calls:
        raw_call_id = call.get("toolCallId")
        call_id = raw_call_id if isinstance(raw_call_id, str) else ""
        payload = payload_by_call.get(call_id)
        if payload is not None:
            observed_payloads.append(payload)
        records.append(
            _call_record(
                call,
                call_id=call_id,
                started_at=start_times.get(call_id),
                completed_at=complete_times.get(call_id),
                arguments_sha256=argument_hashes.get(call_id),
                code_sha256=code_hashes.get(call_id),
                payload=payload,
            )
        )

    parsed = _final_json(final)
    safe: dict[str, Any] = {
        "process": _process_record(process, final_cleanup),
        "calls": records,
        "finalReportSha256": digest(final),
        "finalStatus": _final_status(parsed),
        "mainSkillLoaded": any(
            call.get("skill") == "amkernel" and call.get("success") is True for call in records
        ),
        "limits": (
            "Only allowlisted status, identity, timestamp, and digest evidence is "
            "retained. Absent event timestamps remain null; raw code, arguments, "
            "output, final prose, and stderr are withheld."
        ),
    }
    return safe, observed_payloads, parsed


def serialize(
    record: Mapping[str, Any],
    token: str,
    replacements: Sequence[tuple[object, str]] = (),
) -> str:
    """Serialize a record with token and experiment-specific redactions."""
    text = json.dumps(record, ensure_ascii=False, indent=2)
    if token:
        text = text.replace(token, "[REDACTED_TOKEN]")
    for old, new in replacements:
        text = text.replace(str(old), new)
    return text + "\n"
