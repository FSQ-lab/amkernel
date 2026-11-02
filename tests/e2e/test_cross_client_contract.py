from __future__ import annotations

import copy
import hashlib
import io
import shutil
from pathlib import Path
from typing import Any, cast

import pytest

from tests.e2e.cross_client import codex as codex_runner
from tests.e2e.cross_client_contract import (
    load_json,
    sha256_file,
    validate_contracts,
    validate_evidence,
)
from tests.e2e.cross_client_normalizer import (
    canonical_json_bytes,
    normalize_event,
    normalize_request,
    request_projection,
)

ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "fixtures" / "cross_client"
TIMESTAMP = "2026-10-30T12:00:00Z"
RUN_COMPLETED = "2026-10-30T12:00:00.013000Z"


def artifact(path: Path, root: Path, kind: str, mime_type: str) -> dict[str, Any]:
    payload = path.read_bytes()
    return {
        "kind": kind,
        "mimeType": mime_type,
        "path": path.relative_to(root).as_posix(),
        "sizeBytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def refresh_artifact(record: dict[str, Any], path: Path) -> None:
    evidence = next(item for item in record["artifacts"] if item["path"] == path.name)
    evidence["sizeBytes"] = path.stat().st_size
    evidence["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()


def passing_record(root: Path) -> dict[str, Any]:
    scenario_path = FIXTURES / "scenario.json"
    schema_path = FIXTURES / "evidence.schema.json"
    normalizer_path = FIXTURES / "normalizer.json"
    normalizer_implementation_path = Path(__file__).with_name("cross_client_normalizer.py")
    scenario = load_json(scenario_path)
    policy = load_json(normalizer_path)
    steps: list[dict[str, Any]] = []
    next_call = 0
    for definition in cast(list[dict[str, Any]], scenario["steps"]):
        action = cast(str, definition["action"])
        call_indexes: list[int] = []
        if action == "call-tool":
            call_indexes = [next_call]
            next_call += 1
        expected = cast(dict[str, Any], definition["expected"])
        steps.append(
            {
                "id": definition["id"],
                "action": action,
                "outcome": "passed",
                "contractMatched": True,
                "semantics": expected,
                "semanticsSha256": hashlib.sha256(canonical_json_bytes(expected)).hexdigest(),
                "startedAt": TIMESTAMP,
                "completedAt": TIMESTAMP,
                "durationMs": 0.0,
                "toolCallIndexes": call_indexes,
                "normalizedRequestBytes": 10,
                "normalizedResultBytes": 20,
                "resourceBytes": 8_388_609 if action == "read-resources" else 0,
                "status": expected.get("status", "unavailable"),
                "kernelState": expected.get("kernelState", "unavailable"),
                "resultSha256": (
                    hashlib.sha256(canonical_json_bytes(expected["result"])).hexdigest()
                    if "result" in expected
                    else None
                ),
                "observation": "Frozen contract matched.",
            }
        )

    normalized_event_records: list[dict[str, Any]] = []
    call_definitions = [
        definition for definition in scenario["steps"] if definition["action"] == "call-tool"
    ]
    for index, definition in enumerate(call_definitions):
        expected = cast(dict[str, Any], definition["expected"])
        source: dict[str, Any] = {
            "index": index,
            "direction": "response",
            "method": "tools/call",
            "toolName": "python_exec",
            "requestId": f"request-{index}",
            "attemptKind": "scenario",
            "requestProjection": request_projection(
                "python_exec", cast(dict[str, Any], definition["arguments"])
            ),
            "normalizedRequestBytes": normalize_request(
                "python_exec", cast(dict[str, Any], definition["arguments"])
            ),
            "semanticsSha256": hashlib.sha256(canonical_json_bytes(expected)).hexdigest(),
            "status": expected["status"],
            "kernelState": expected["kernelState"],
            "startedAt": TIMESTAMP,
            "completedAt": TIMESTAMP,
        }
        if "result" in expected:
            source["result"] = expected["result"]
        normalized_event_records.append(normalize_event(source, policy))
    call_steps = [step for step in steps if step["action"] == "call-tool"]
    for step in steps:
        step["normalizedRequestBytes"] = 0
        step["normalizedResultBytes"] = 0
    for step, event in zip(call_steps, normalized_event_records, strict=True):
        step["normalizedRequestBytes"] = event["normalizedRequestBytes"]
        step["normalizedResultBytes"] = event["normalizedBytes"]
    final_summary = root / "final-summary.json"
    final_summary.write_bytes(
        canonical_json_bytes(
            {
                "scenarioId": scenario["scenarioId"],
                "outcome": "passed",
                "completedStepIds": [step["id"] for step in steps],
                "toolCallCount": next_call,
                "schemaRetryCount": 0,
                "wrongToolSelectionCount": 0,
                "clarificationRequestCount": 0,
                "kernelState": "alive",
                "cleanupCompleted": True,
            }
        )
    )
    part_payloads = [b"m" * 8_388_608, b"m"]
    artifact_uri = (
        "amkernel://artifact/123e4567e89b42d3a456426614174000/123e4567e89b42d3a456426614174001"
    )
    part_paths = [root / f"resource-part-{index}.bin" for index in range(2)]
    for path, payload in zip(part_paths, part_payloads, strict=True):
        path.write_bytes(payload)
    resource_payload = b"".join(part_payloads)
    resource_manifest = root / "resource-manifest.json"
    resource_manifest.write_bytes(
        canonical_json_bytes(
            {
                "version": 1,
                "name": "cross-client.bin",
                "declaredMimeType": "application/octet-stream",
                "size": len(resource_payload),
                "sha256": hashlib.sha256(resource_payload).hexdigest(),
                "parts": [
                    {
                        "uri": f"{artifact_uri}/part/{index}",
                        "offset": sum(len(payload) for payload in part_payloads[:index]),
                        "size": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    }
                    for index, payload in enumerate(part_payloads)
                ],
            }
        )
    )
    normalized_events = root / "normalized-events.json"
    normalized_resources = [
        normalize_event(
            {
                "resourceUri": artifact_uri,
                "mimeType": "application/vnd.amkernel.artifact-manifest+json",
                "resourceSizeBytes": resource_manifest.stat().st_size,
            },
            policy,
        ),
        *[
            normalize_event(
                {
                    "resourceUri": f"{artifact_uri}/part/{index}",
                    "mimeType": "application/octet-stream",
                    "resourceSizeBytes": path.stat().st_size,
                },
                policy,
            )
            for index, path in enumerate(part_paths)
        ],
    ]
    normalized_events.write_bytes(
        canonical_json_bytes(
            {
                "schemaVersion": 1,
                "normalizerId": policy["normalizerId"],
                "events": normalized_event_records,
                "resources": normalized_resources,
            }
        )
    )
    request_bytes = sum(cast(int, step["normalizedRequestBytes"]) for step in steps)
    result_bytes = sum(cast(int, step["normalizedResultBytes"]) for step in steps)
    raw_resource_bytes = sum(cast(int, step["resourceBytes"]) for step in steps)
    reference_bytes = sum(
        cast(int, resource["normalizedBytes"]) for resource in normalized_resources
    )
    config_observation = {
        "scope": "persistent-client-config",
        "existed": False,
        "sha256": None,
    }
    return {
        "schemaVersion": 1,
        "runId": "codex-reference-test",
        "generatedAt": RUN_COMPLETED,
        "runStartedAt": TIMESTAMP,
        "runCompletedAt": RUN_COMPLETED,
        "outcome": "passed",
        "client": {
            "id": "codex",
            "executable": "codex",
            "version": "0.163.0",
            "model": "reference-model",
            "invocationMode": "ephemeral-home",
            "nonInteractive": True,
        },
        "host": {
            "system": "Darwin",
            "release": "25.6.0",
            "architecture": "arm64",
            "pythonVersion": "3.11.14",
        },
        "mcp": {"clientVersion": "1.26.0", "protocolVersion": "2025-11-25"},
        "amkernel": {
            "revision": "a" * 40,
            "version": "0.0.0",
            "wheel": {
                "filename": "amkernel-0.0.0-py3-none-any.whl",
                "sizeBytes": 65_536,
                "sha256": "b" * 64,
            },
            "entryPoint": "amkernel",
            "runnerProtocolVersion": 2,
        },
        "contracts": {
            "scenario": {
                "id": scenario["scenarioId"],
                "sha256": sha256_file(scenario_path),
            },
            "evidenceSchema": {
                "id": load_json(schema_path)["$id"],
                "sha256": sha256_file(schema_path),
            },
            "normalizer": {
                "id": load_json(normalizer_path)["normalizerId"],
                "sha256": sha256_file(normalizer_path),
            },
            "normalizerImplementation": {
                "id": "amkernel-cross-client-normalizer-v1-python",
                "sha256": sha256_file(normalizer_implementation_path),
            },
        },
        "preflight": {
            "clientReady": True,
            "serverReady": True,
            "wheelVerified": True,
            "reason": None,
        },
        "configuration": {
            "workspaceIsolation": "temporary",
            "persistentMutation": False,
            "before": config_observation,
            "after": copy.deepcopy(config_observation),
            "serverCommand": ["python", "-m", "amkernel"],
        },
        "steps": steps,
        "context": {
            "publicToolCount": 1,
            "selectedTool": "python_exec",
            "toolCallCount": next_call,
            "schemaRetryCount": 0,
            "wrongToolSelectionCount": 0,
            "clarificationRequestCount": 0,
            "normalizedRequestBytes": request_bytes,
            "normalizedResultBytes": result_bytes,
            "maximumNormalizedResultBytes": max(
                cast(int, step["normalizedResultBytes"]) for step in steps
            ),
            "rawResourceBytes": raw_resource_bytes,
            "resourceReferenceBytes": reference_bytes,
            "contextReductionRatio": 1 - reference_bytes / raw_resource_bytes,
            "finalResponseBytes": final_summary.stat().st_size,
            "normalizedEventsBytes": normalized_events.stat().st_size,
            "durationMs": 13.0,
        },
        "artifacts": [
            artifact(normalized_events, root, "normalized-events", "application/json"),
            artifact(final_summary, root, "final-summary", "application/json"),
            artifact(
                resource_manifest,
                root,
                "resource-manifest",
                "application/vnd.amkernel.artifact-manifest+json",
            ),
            artifact(part_paths[0], root, "resource-part", "application/octet-stream"),
            artifact(part_paths[1], root, "resource-part", "application/octet-stream"),
        ],
        "cleanup": {
            "attempted": True,
            "completed": True,
            "clientExited": True,
            "serverExited": True,
            "runnerExited": True,
            "managedProcessesRemaining": 0,
            "managedArtifactsRemaining": 0,
            "remainingExternalResources": [],
            "observation": "All managed processes and artifacts exited.",
        },
        "review": {
            "reviewer": "CrossClientContractReviewer",
            "source": "agent://CrossClientContractReviewer",
            "blocker": 0,
            "major": 0,
            "minor": 0,
            "disposition": "accepted",
        },
        "limitations": ["Synthetic contract fixture; not a real client run."],
    }


def test_frozen_cross_client_contracts_are_valid() -> None:
    validate_contracts(FIXTURES)


def test_process_matrix_rejects_nonpublic_fatal_status(tmp_path: Path) -> None:
    fixtures = tmp_path / "cross-client"
    shutil.copytree(FIXTURES, fixtures)
    matrix_path = fixtures / "process-matrix.json"
    matrix = load_json(matrix_path)
    row = next(item for item in matrix["rows"] if item["id"] == "timeout-escalates")
    row["expected"]["status"] = "timed_out"
    matrix_path.write_bytes(canonical_json_bytes(matrix))

    with pytest.raises(ValueError, match="process matrix semantics"):
        validate_contracts(fixtures)


def test_passing_cross_client_evidence_validates(tmp_path: Path) -> None:
    validate_evidence(passing_record(tmp_path), tmp_path, FIXTURES)


def test_preflight_blocked_evidence_validates_without_scenario_steps(tmp_path: Path) -> None:
    record = passing_record(tmp_path)
    record["outcome"] = "blocked"
    record["preflight"] = {
        "clientReady": False,
        "serverReady": False,
        "wheelVerified": True,
        "reason": "Client executable is unavailable.",
    }
    record["steps"] = []
    record["context"].update(
        {
            "toolCallCount": 0,
            "normalizedRequestBytes": 0,
            "normalizedResultBytes": 0,
            "maximumNormalizedResultBytes": 0,
            "rawResourceBytes": 0,
            "resourceReferenceBytes": 0,
            "contextReductionRatio": 0,
            "finalResponseBytes": 0,
            "normalizedEventsBytes": 0,
        }
    )
    record["artifacts"] = []
    record["cleanup"].update(
        {
            "attempted": False,
            "completed": False,
            "clientExited": False,
            "serverExited": False,
            "runnerExited": False,
        }
    )
    record["review"]["disposition"] = "pending"

    validate_evidence(record, tmp_path, FIXTURES)


def test_failed_evidence_requires_a_concrete_mismatch(tmp_path: Path) -> None:
    record = passing_record(tmp_path)
    record["outcome"] = "failed"

    with pytest.raises(ValueError, match="no concrete observed mismatch"):
        validate_evidence(record, tmp_path, FIXTURES)


def test_failed_evidence_accepts_an_observed_step_mismatch(tmp_path: Path) -> None:
    record = passing_record(tmp_path)
    record["outcome"] = "failed"
    failed_step = record["steps"][3]
    failed_step["outcome"] = "failed"
    failed_step["contractMatched"] = False
    failed_step["semantics"]["errorType"] = "RuntimeError"
    failed_step["semanticsSha256"] = hashlib.sha256(
        canonical_json_bytes(failed_step["semantics"])
    ).hexdigest()
    events_path = tmp_path / "normalized-events.json"
    events = load_json(events_path)
    events["events"][2]["semanticsSha256"] = failed_step["semanticsSha256"]
    events_path.write_bytes(canonical_json_bytes(events))
    refresh_artifact(record, events_path)
    record["context"]["normalizedEventsBytes"] = events_path.stat().st_size
    path = tmp_path / "final-summary.json"
    summary = load_json(path)
    summary["outcome"] = "failed"
    summary["completedStepIds"].remove(failed_step["id"])
    path.write_bytes(canonical_json_bytes(summary))
    refresh_artifact(record, path)
    record["context"]["finalResponseBytes"] = path.stat().st_size

    validate_evidence(record, tmp_path, FIXTURES)


@pytest.mark.parametrize("raw_retry", [False, True], ids=["projected", "raw-rejected"])
def test_schema_retry_is_attributed_and_measured(tmp_path: Path, raw_retry: bool) -> None:
    record = passing_record(tmp_path)
    path = tmp_path / "normalized-events.json"
    document = load_json(path)
    for event in document["events"]:
        event["index"] += 1
    retry_projection = (
        {"arguments": {"code": "print(42)"}, "toolName": "python_exec"}
        if raw_retry
        else request_projection("python_exec", {"code": 42})
    )
    retry_request_bytes = len(canonical_json_bytes(retry_projection))
    document["events"].insert(
        0,
        {
            "index": 0,
            "direction": "response",
            "requestProjection": retry_projection,
            "method": "tools/call",
            "toolName": "python_exec",
            "requestId": "schema-retry-0",
            "attemptKind": "schema-retry",
            "normalizedRequestBytes": retry_request_bytes,
            "normalizedBytes": 0,
        },
    )
    path.write_bytes(canonical_json_bytes(document))
    refresh_artifact(record, path)
    record["context"]["normalizedEventsBytes"] = path.stat().st_size
    call_steps = [step for step in record["steps"] if step["action"] == "call-tool"]
    call_steps[0]["toolCallIndexes"] = [0, 1]
    call_steps[0]["normalizedRequestBytes"] += retry_request_bytes
    for step in call_steps[1:]:
        step["toolCallIndexes"] = [step["toolCallIndexes"][0] + 1]
    record["context"]["toolCallCount"] += 1
    record["context"]["schemaRetryCount"] += 1
    record["context"]["normalizedRequestBytes"] += retry_request_bytes
    summary_path = tmp_path / "final-summary.json"
    summary = load_json(summary_path)
    summary["toolCallCount"] += 1
    summary["schemaRetryCount"] += 1
    summary_path.write_bytes(canonical_json_bytes(summary))
    refresh_artifact(record, summary_path)
    record["context"]["finalResponseBytes"] = summary_path.stat().st_size

    if raw_retry:
        with pytest.raises(ValueError, match="raw or malformed"):
            validate_evidence(record, tmp_path, FIXTURES)
    else:
        validate_evidence(record, tmp_path, FIXTURES)


def test_executable_normalizer_excludes_private_fields_and_hashes_results() -> None:
    policy = load_json(FIXTURES / "normalizer.json")
    normalized = normalize_event(
        {
            "index": 0,
            "direction": "response",
            "method": "tools/call",
            "toolName": "python_exec",
            "requestId": "request-0",
            "rawCode": "private source",
            "result": {"answer": 42},
        },
        policy,
    )

    assert "rawCode" not in normalized
    assert (
        normalized["resultSha256"]
        == hashlib.sha256(canonical_json_bytes({"answer": 42})).hexdigest()
    )
    assert normalized["normalizedBytes"] > 0
    projected = request_projection("python_exec", {"print(private_source)": None})
    assert "private_source" not in canonical_json_bytes(projected).decode()
    resource = normalize_event(
        {
            "resourceUri": "amkernel://artifact/secret-id/part/0",
            "mimeType": "application/octet-stream",
            "resourceSizeBytes": 64,
        },
        policy,
    )
    assert "resourceUri" not in resource
    assert resource["resourceScheme"] == "amkernel"
    assert resource["resourceMimeType"] == "application/octet-stream"
    assert resource["resourceSizeBytes"] == 64


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-step",
        "reordered-steps",
        "scenario-hash",
        "secret",
        "persistent-config",
        "measurement-arithmetic",
        "timestamp-drift",
        "run-timestamp-drift",
        "wrong-step-semantics",
        "request-byte-drift",
        "step-outside-run",
        "summary-extra-field",
        "resource-observation-drift",
        "resource-reference-drift",
        "wrong-step-status",
        "wrong-result-digest",
        "duplicate-call-index",
        "coordinated-request-drift",
        "non-call-index",
        "empty-call-index",
        "event-step-mismatch",
        "summary-mismatch",
        "private-artifact",
        "missing-resource-proof",
        "manifest-link",
        "manifest-offset",
        "blocked-with-ready-preflight",
        "false-cleanup",
        "missing-review",
        "artifact-tamper",
    ],
)
def test_cross_client_evidence_rejects_invalid_contract(tmp_path: Path, mutation: str) -> None:
    record = passing_record(tmp_path)
    if mutation == "missing-step":
        cast(list[Any], record["steps"]).pop()
    elif mutation == "reordered-steps":
        steps = cast(list[Any], record["steps"])
        steps[1], steps[2] = steps[2], steps[1]
    elif mutation == "event-step-mismatch":
        path = tmp_path / "normalized-events.json"
        document = load_json(path)
        document["events"][0]["kernelState"] = "dead"
        path.write_bytes(canonical_json_bytes(document))
        evidence = next(item for item in record["artifacts"] if item["path"] == path.name)
        evidence["sizeBytes"] = path.stat().st_size
        evidence["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        record["context"]["normalizedEventsBytes"] = path.stat().st_size
    elif mutation == "summary-mismatch":
        path = tmp_path / "final-summary.json"
        document = load_json(path)
        document["toolCallCount"] += 1
        path.write_bytes(canonical_json_bytes(document))
        evidence = next(item for item in record["artifacts"] if item["path"] == path.name)
        evidence["sizeBytes"] = path.stat().st_size
        evidence["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        record["context"]["finalResponseBytes"] = path.stat().st_size
    elif mutation == "scenario-hash":
        record["contracts"]["scenario"]["sha256"] = "0" * 64
    elif mutation == "secret":
        record["limitations"] = ["token=not-retainable"]
    elif mutation == "persistent-config":
        record["configuration"]["after"]["existed"] = True
    elif mutation == "measurement-arithmetic":
        record["context"]["normalizedRequestBytes"] += 1
    elif mutation == "timestamp-drift":
        record["steps"][0]["durationMs"] = 1.0
    elif mutation == "run-timestamp-drift":
        record["context"]["durationMs"] = 12.0
    elif mutation == "resource-reference-drift":
        record["context"]["resourceReferenceBytes"] = 1
        record["context"]["contextReductionRatio"] = 1 - 1 / record["context"]["rawResourceBytes"]
    elif mutation == "wrong-step-semantics":
        record["steps"][5]["semantics"]["totalBytes"] += 1
        record["steps"][5]["semanticsSha256"] = hashlib.sha256(
            canonical_json_bytes(record["steps"][5]["semantics"])
        ).hexdigest()
    elif mutation == "request-byte-drift":
        record["steps"][1]["normalizedRequestBytes"] += 1
        record["context"]["normalizedRequestBytes"] += 1
    elif mutation == "step-outside-run":
        record["steps"][0]["startedAt"] = "2026-10-30T11:59:59Z"
        record["steps"][0]["completedAt"] = "2026-10-30T11:59:59Z"
    elif mutation == "summary-extra-field":
        path = tmp_path / "final-summary.json"
        document = load_json(path)
        document["notes"] = "undeclared retained prose"
        path.write_bytes(canonical_json_bytes(document))
        refresh_artifact(record, path)
        record["context"]["finalResponseBytes"] = path.stat().st_size
    elif mutation == "coordinated-request-drift":
        path = tmp_path / "normalized-events.json"
        document = load_json(path)
        event = document["events"][0]
        event["requestProjection"]["arguments"]["properties"].append(
            {"nameSha256": hashlib.sha256(b"extra").hexdigest(), "value": {"type": "null"}}
        )
        event["requestProjection"]["arguments"]["properties"].sort(
            key=lambda item: item["nameSha256"]
        )
        old_bytes = event["normalizedRequestBytes"]
        event["normalizedRequestBytes"] = len(canonical_json_bytes(event["requestProjection"]))
        difference = event["normalizedRequestBytes"] - old_bytes
        record["steps"][1]["normalizedRequestBytes"] += difference
        record["context"]["normalizedRequestBytes"] += difference
        path.write_bytes(canonical_json_bytes(document))
        refresh_artifact(record, path)
        record["context"]["normalizedEventsBytes"] = path.stat().st_size
    elif mutation == "resource-observation-drift":
        path = tmp_path / "normalized-events.json"
        document = load_json(path)
        document["resources"][0]["resourceMimeType"] = "application/json"
        path.write_bytes(canonical_json_bytes(document))
        refresh_artifact(record, path)
        record["context"]["normalizedEventsBytes"] = path.stat().st_size
    elif mutation == "wrong-step-status":
        record["steps"][3]["status"] = "completed"
    elif mutation == "wrong-result-digest":
        record["steps"][1]["resultSha256"] = "0" * 64
    elif mutation == "duplicate-call-index":
        record["steps"][2]["toolCallIndexes"] = [0]
    elif mutation == "non-call-index":
        record["steps"][0]["toolCallIndexes"] = [0]
    elif mutation == "empty-call-index":
        record["steps"][1]["toolCallIndexes"] = []
    elif mutation == "private-artifact":
        path = tmp_path / "normalized-events.json"
        path.write_text('{"token":"private-value"}')
        evidence = next(item for item in record["artifacts"] if item["path"] == path.name)
        evidence["sizeBytes"] = path.stat().st_size
        evidence["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        record["context"]["normalizedEventsBytes"] = path.stat().st_size
    elif mutation == "missing-resource-proof":
        record["artifacts"] = [
            item
            for item in record["artifacts"]
            if item["kind"] not in {"resource-manifest", "resource-part"}
        ]
    elif mutation == "manifest-link":
        path = tmp_path / "resource-manifest.json"
        manifest = load_json(path)
        manifest["parts"][0]["sha256"] = "0" * 64
        path.write_bytes(canonical_json_bytes(manifest))
        evidence = next(item for item in record["artifacts"] if item["path"] == path.name)
        evidence["sizeBytes"] = path.stat().st_size
        evidence["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    elif mutation == "manifest-offset":
        path = tmp_path / "resource-manifest.json"
        manifest = load_json(path)
        manifest["parts"][1]["offset"] -= 1
        path.write_bytes(canonical_json_bytes(manifest))
        refresh_artifact(record, path)
    elif mutation == "blocked-with-ready-preflight":
        record["outcome"] = "blocked"
    elif mutation == "false-cleanup":
        record["cleanup"]["completed"] = False
    elif mutation == "missing-review":
        record["review"]["disposition"] = "pending"
    elif mutation == "artifact-tamper":
        (tmp_path / "normalized-events.json").write_text("tampered")

    with pytest.raises(ValueError):
        validate_evidence(record, tmp_path, FIXTURES)


def test_codex_runner_creates_ephemeral_workspace_and_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    class FakeProcess:
        def __init__(self) -> None:
            self.stdin = io.StringIO()
            self.stdout = io.StringIO()
            self.stderr = io.StringIO()

        def wait(self, timeout: int) -> int:
            assert timeout == 600
            return 0

    def fake_popen(*args: Any, **kwargs: Any) -> FakeProcess:
        captured.update(kwargs)
        return FakeProcess()

    monkeypatch.setattr("tests.e2e.cross_client.codex.subprocess.Popen", fake_popen)
    client_dir = tmp_path / "client"
    codex_home = tmp_path / "home"

    events, _, _, stderr = codex_runner._run_codex(
        "prompt", Path("server"), tmp_path / "capture", client_dir, codex_home
    )

    assert events == []
    assert stderr == ""
    assert client_dir.is_dir()
    assert codex_home.is_dir()
    assert captured["env"]["CODEX_HOME"] == str(codex_home)


@pytest.mark.parametrize(
    ("expected", "result", "manifest"),
    [
        (
            {"status": "failed", "kernelState": "alive", "errorType": "ValueError"},
            {
                "status": "failed",
                "kernelState": "alive",
                "error": {"type": "ValueError"},
                "displays": [],
                "artifacts": [],
            },
            {"parts": []},
        ),
        (
            {
                "status": "completed",
                "kernelState": "alive",
                "result": "output-complete",
                "stdout": "stdout-marker\n",
                "stderr": "stderr-marker\n",
                "totalBytes": 28,
                "totalLines": 2,
                "discardedBytes": 0,
                "discardedLines": 0,
                "truncated": False,
                "limitExceeded": False,
            },
            {
                "status": "completed",
                "kernelState": "alive",
                "result": "output-complete",
                "stdout": "stdout-marker\n",
                "stderr": "stderr-marker\n",
                "output": {
                    "totalBytes": 28,
                    "totalLines": 2,
                    "discardedBytes": 0,
                    "discardedLines": 0,
                    "truncated": False,
                    "limitExceeded": False,
                },
                "displays": [],
                "artifacts": [],
            },
            {"parts": []},
        ),
        (
            {
                "status": "completed",
                "kernelState": "alive",
                "result": "display-complete",
                "displayKind": "image",
                "mimeType": "image/png",
                "width": 2,
                "height": 3,
            },
            {
                "status": "completed",
                "kernelState": "alive",
                "result": "display-complete",
                "displays": [{"kind": "image", "mimeType": "image/png", "width": 2, "height": 3}],
                "artifacts": [],
            },
            {"parts": []},
        ),
        (
            {
                "status": "completed",
                "kernelState": "alive",
                "result": "artifact-complete",
                "representation": "manifest",
                "mimeType": "application/octet-stream",
                "sizeBytes": 8_388_609,
                "partCount": 2,
            },
            {
                "status": "completed",
                "kernelState": "alive",
                "result": "artifact-complete",
                "displays": [],
                "artifacts": [
                    {
                        "representation": "manifest",
                        "declaredMimeType": "application/octet-stream",
                        "mimeType": "application/vnd.amkernel.artifact-manifest+json",
                        "size": 8_388_609,
                    }
                ],
            },
            {"parts": [{}, {}]},
        ),
    ],
)
def test_codex_runner_derives_semantics_from_observed_results(
    expected: dict[str, Any], result: dict[str, Any], manifest: dict[str, Any]
) -> None:
    assert codex_runner._observed_call_semantics(expected, result, manifest) == expected


def test_source_snapshot_includes_evidence_except_selected_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(codex_runner, "ROOT", tmp_path)
    tracked_evidence = tmp_path / "evidence" / "retained.json"
    tracked_evidence.parent.mkdir()
    tracked_evidence.write_text("before")
    before = codex_runner._source_snapshot()
    tracked_evidence.write_text("after")
    assert codex_runner._source_snapshot() != before

    output = tmp_path / "evidence" / "generated"
    excluded_before = codex_runner._source_snapshot(output)
    output.mkdir()
    (output / "manifest.json").write_text("generated")
    assert codex_runner._source_snapshot(output) == excluded_before
