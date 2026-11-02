from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator, FormatChecker

from tests.e2e.cross_client_normalizer import (
    canonical_json_bytes,
    normalize_event,
    normalize_request,
    request_projection,
    valid_request_projection,
)

SECRET_OR_HOME = re.compile(
    r"/Users/|/home/|Bearer\s+[A-Za-z0-9._~-]+|"
    r"(?:api[_-]?key|token|password|secret)\s*[=:]\s*[^ ,;]+|"
    r"https?://[^ /:@]+:[^ /@]+@",
    re.IGNORECASE,
)
EXPECTED_PROCESS_ROWS = (
    "installed-startup",
    "normal-shutdown",
    "destructive-reset",
    "timeout-survives",
    "timeout-escalates",
    "runner-channel-death",
    "output-limit-drain",
    "artifact-integrity-expiry",
    "cancellation-cleanup",
)
EXPECTED_PROCESS_SEMANTICS = {
    "timeout-escalates": {
        "status": "kernel_killed",
        "kernelState": "dead",
        "runnerReplacedImplicitly": False,
    },
    "runner-channel-death": {
        "status": "kernel_killed",
        "kernelState": "dead",
        "serverState": "ready",
        "runnerReplacedImplicitly": False,
    },
    "output-limit-drain": {
        "status": "failed",
        "kernelState": "alive",
        "errorType": "OutputLimitExceeded",
        "drainCompleted": True,
        "continuationVerified": True,
    },
}


def load_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_bytes()))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_timestamp(value: Any) -> datetime:
    return datetime.fromisoformat(cast(str, value))


def _reject_private_payload(payload: bytes, label: str, excluded: set[str]) -> Any:
    text = payload.decode("utf-8", errors="ignore")
    if SECRET_OR_HOME.search(text):
        raise ValueError(f"evidence artifact contains private content: {label}")
    try:
        parsed = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    for string in _strings(parsed):
        if SECRET_OR_HOME.search(string):
            raise ValueError(f"evidence artifact contains private content: {label}")
    if _keys(parsed) & excluded:
        raise ValueError(f"evidence artifact contains excluded fields: {label}")
    return parsed


def validate_contracts(fixtures: Path) -> None:
    schema_path = fixtures / "evidence.schema.json"
    schema = load_json(schema_path)
    Draft202012Validator.check_schema(schema)

    scenario = load_json(fixtures / "scenario.json")
    steps = cast(list[dict[str, Any]], scenario["steps"])
    step_ids = [cast(str, step["id"]) for step in steps]
    if len(steps) != 13 or len(set(step_ids)) != 13:
        raise ValueError("scenario must contain exactly 13 unique steps")
    if step_ids[0] != "discover-interface" or step_ids[-1] != "reset-namespace":
        raise ValueError("scenario discovery/reset ordering differs from the contract")
    if [step["id"] for step in steps if step["action"] == "read-resources"] != [
        "read-artifact-resources"
    ]:
        raise ValueError("scenario must contain exactly one resource-read step")
    thresholds = cast(dict[str, Any], scenario["thresholds"])
    if thresholds["maximumNormalizedEventsBytes"] != 1_048_576:
        raise ValueError("normalized event ceiling must remain 1 MiB")
    if thresholds["maximumArtifactBytes"] != 16_777_216:
        raise ValueError("evidence artifact ceiling must remain 16 MiB")
    if thresholds["minimumContextReductionRatio"] != 0.8:
        raise ValueError("context reduction floor must remain 80 percent")
    bounded_output = next(step for step in steps if step["id"] == "bounded-output")
    if bounded_output["expected"] != {
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
    }:
        raise ValueError("bounded output arithmetic differs from the frozen contract")

    normalizer = load_json(fixtures / "normalizer.json")
    excluded = set(cast(list[str], normalizer["excludedFields"]))
    required_exclusions = {
        "authorization",
        "credentials",
        "environment",
        "absolutePaths",
        "modelProse",
        "chainOfThought",
        "rawCode",
        "stdoutBody",
        "stderrBody",
        "displayBytes",
        "artifactBytes",
        "clientPrivateEnvelope",
    }
    if excluded != required_exclusions:
        raise ValueError("normalizer privacy exclusions differ from the frozen contract")

    matrix = load_json(fixtures / "process-matrix.json")
    if matrix["platforms"] != ["ubuntu-latest", "macos-latest"]:
        raise ValueError("process matrix must cover Ubuntu and macOS")
    if matrix["pythonVersions"] != ["3.11", "3.13"]:
        raise ValueError("process matrix must cover oldest and newest supported Python minors")
    row_ids = [row["id"] for row in cast(list[dict[str, Any]], matrix["rows"])]
    if tuple(row_ids) != EXPECTED_PROCESS_ROWS:
        raise ValueError("process matrix rows differ from the frozen contract")
    rows = {row["id"]: row for row in cast(list[dict[str, Any]], matrix["rows"])}
    for row_id, expected in EXPECTED_PROCESS_SEMANTICS.items():
        if rows[row_id]["expected"] != expected:
            raise ValueError(f"process matrix semantics differ for {row_id}")


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [string for item in value for string in _strings(item)]
    if isinstance(value, dict):
        return [string for item in value.values() for string in _strings(item)]
    return []


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in _keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in _keys(item)}
    return set()


def validate_evidence(
    record: dict[str, Any],
    evidence_root: Path,
    fixtures: Path,
) -> None:
    validate_contracts(fixtures)
    schema = load_json(fixtures / "evidence.schema.json")
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(record),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        raise ValueError("; ".join(error.message for error in errors))

    for string in _strings(record):
        if SECRET_OR_HOME.search(string):
            raise ValueError("evidence contains a credential or absolute home path")

    scenario_path = fixtures / "scenario.json"
    normalizer_path = fixtures / "normalizer.json"
    schema_path = fixtures / "evidence.schema.json"
    normalizer_implementation_path = Path(__file__).with_name("cross_client_normalizer.py")
    scenario = load_json(scenario_path)
    normalizer = load_json(normalizer_path)
    excluded_fields = set(cast(list[str], normalizer["excludedFields"]))
    contracts = cast(dict[str, dict[str, Any]], record["contracts"])
    expected_contracts = {
        "scenario": (scenario["scenarioId"], sha256_file(scenario_path)),
        "evidenceSchema": (schema["$id"], sha256_file(schema_path)),
        "normalizer": (normalizer["normalizerId"], sha256_file(normalizer_path)),
        "normalizerImplementation": (
            "amkernel-cross-client-normalizer-v1-python",
            sha256_file(normalizer_implementation_path),
        ),
    }
    for name, (identifier, digest) in expected_contracts.items():
        if contracts[name] != {"id": identifier, "sha256": digest}:
            raise ValueError(f"{name} identity differs from the frozen contract")

    expected_steps = cast(list[dict[str, Any]], scenario["steps"])
    steps = cast(list[dict[str, Any]], record["steps"])
    observed_pairs = [(step["id"], step["action"]) for step in steps]
    expected_pairs = [(step["id"], step["action"]) for step in expected_steps]
    if observed_pairs != expected_pairs[: len(observed_pairs)]:
        raise ValueError("evidence steps are not a frozen scenario prefix")
    semantic_mismatch = False
    contract_mismatch = False
    step_intervals: list[tuple[datetime, datetime]] = []
    for definition, step in zip(expected_steps, steps, strict=False):
        expected = cast(dict[str, Any], definition["expected"])
        expected_digest = hashlib.sha256(canonical_json_bytes(expected)).hexdigest()
        expected_result_digest = (
            hashlib.sha256(canonical_json_bytes(expected["result"])).hexdigest()
            if "result" in expected
            else None
        )
        contract_mismatch = (
            contract_mismatch or step["outcome"] != "passed" or not step["contractMatched"]
        )
        semantic_mismatch = semantic_mismatch or (
            step["semantics"] != expected
            or step["semanticsSha256"] != expected_digest
            or step["status"] != expected.get("status", "unavailable")
            or step["kernelState"] != expected.get("kernelState", "unavailable")
            or step["resultSha256"] != expected_result_digest
        )
        started = _parse_timestamp(step["startedAt"])
        completed = _parse_timestamp(step["completedAt"])
        if completed < started:
            raise ValueError(f"step completed before it started: {step['id']}")
        observed_duration_ms = (completed - started).total_seconds() * 1000
        if not math.isclose(
            cast(float, step["durationMs"]), observed_duration_ms, rel_tol=0, abs_tol=0.001
        ):
            raise ValueError(f"step duration differs from timestamps: {step['id']}")
        step_intervals.append((started, completed))
    if record["outcome"] == "passed" and (semantic_mismatch or contract_mismatch):
        raise ValueError("passed evidence differs from frozen scenario semantics")

    configuration = cast(dict[str, Any], record["configuration"])
    if configuration["before"] != configuration["after"]:
        raise ValueError("persistent client configuration changed during the run")

    context = cast(dict[str, Any], record["context"])
    request_bytes = sum(cast(int, step["normalizedRequestBytes"]) for step in steps)
    result_bytes = sum(cast(int, step["normalizedResultBytes"]) for step in steps)
    resource_bytes = sum(cast(int, step["resourceBytes"]) for step in steps)
    if context["normalizedRequestBytes"] != request_bytes:
        raise ValueError("normalized request byte total differs from step evidence")
    if context["normalizedResultBytes"] != result_bytes:
        raise ValueError("normalized result byte total differs from step evidence")
    maximum_result_bytes = max(
        (cast(int, step["normalizedResultBytes"]) for step in steps), default=0
    )
    if context["maximumNormalizedResultBytes"] != maximum_result_bytes:
        raise ValueError("maximum normalized result size differs from step evidence")
    if context["rawResourceBytes"] != resource_bytes:
        raise ValueError("raw resource byte total differs from step evidence")
    expected_reduction = (
        1 - context["resourceReferenceBytes"] / resource_bytes if resource_bytes else 0
    )
    if not math.isclose(
        context["contextReductionRatio"], expected_reduction, rel_tol=0, abs_tol=1e-12
    ):
        raise ValueError("context reduction ratio differs from byte measurements")

    scenario_call_count = sum(step["action"] == "call-tool" for step in steps)
    retry_count = 0
    flattened_indexes: list[int] = []
    for step in steps:
        indexes = cast(list[int], step["toolCallIndexes"])
        flattened_indexes.extend(indexes)
        if step["action"] == "call-tool":
            if not 1 <= len(indexes) <= 3:
                raise ValueError(f"call step has invalid attempt count: {step['id']}")
            retry_count += len(indexes) - 1
        elif indexes:
            raise ValueError(f"non-call step owns tool call indexes: {step['id']}")
    if retry_count != context["schemaRetryCount"]:
        raise ValueError("schema retry count differs from step attempt indexes")
    if context["toolCallCount"] != scenario_call_count + retry_count:
        raise ValueError("tool call count differs from scenario calls and retries")
    if flattened_indexes != list(range(context["toolCallCount"])):
        raise ValueError("tool call indexes are not ordered, contiguous, and unique")
    run_started = _parse_timestamp(record["runStartedAt"])
    run_completed = _parse_timestamp(record["runCompletedAt"])
    if run_completed < run_started:
        raise ValueError("run completed before it started")
    previous_completed = run_started
    for started, completed in step_intervals:
        if started < run_started or completed > run_completed or started < previous_completed:
            raise ValueError("step chronology falls outside ordered run interval")
        previous_completed = completed
    cleanup = cast(dict[str, Any], record["cleanup"])
    cleanup_mismatch = not all(
        cleanup[name] for name in ("completed", "clientExited", "serverExited", "runnerExited")
    ) or bool(
        cleanup["managedProcessesRemaining"]
        or cleanup["managedArtifactsRemaining"]
        or cleanup["remainingExternalResources"]
    )
    if record["outcome"] == "failed" and not (semantic_mismatch or cleanup_mismatch):
        raise ValueError("failed evidence contains no concrete observed mismatch")
    run_duration_ms = (run_completed - run_started).total_seconds() * 1000
    if not math.isclose(context["durationMs"], run_duration_ms, rel_tol=0, abs_tol=0.001):
        raise ValueError("run duration differs from timestamps")

    root = evidence_root.resolve()
    artifact_payloads: dict[str, bytes] = {}
    parsed_artifacts: dict[str, Any] = {}
    artifacts = cast(list[dict[str, Any]], record["artifacts"])
    kinds: set[str] = set()
    for artifact in artifacts:
        path = (root / cast(str, artifact["path"])).resolve()
        try:
            path.relative_to(root)
        except ValueError as error:
            raise ValueError("evidence artifact escapes its root") from error
        if not path.is_file():
            raise ValueError(f"evidence artifact is missing: {artifact['path']}")
        payload = path.read_bytes()
        if len(payload) != artifact["sizeBytes"]:
            raise ValueError(f"evidence artifact size differs: {artifact['path']}")
        if hashlib.sha256(payload).hexdigest() != artifact["sha256"]:
            raise ValueError(f"evidence artifact digest differs: {artifact['path']}")
        relative_path = cast(str, artifact["path"])
        artifact_payloads[relative_path] = payload
        parsed_artifacts[relative_path] = _reject_private_payload(
            payload, relative_path, excluded_fields
        )
        kinds.add(cast(str, artifact["kind"]))
    if record["outcome"] == "blocked":
        cleanup = cast(dict[str, Any], record["cleanup"])
        if any(
            cleanup[name]
            for name in ("attempted", "completed", "clientExited", "serverExited", "runnerExited")
        ) or bool(
            cleanup["managedProcessesRemaining"]
            or cleanup["managedArtifactsRemaining"]
            or cleanup["remainingExternalResources"]
        ):
            raise ValueError("blocked evidence cleanup state is contradictory")
        return
    if not {"normalized-events", "final-summary"}.issubset(kinds):
        raise ValueError("ready run evidence lacks normalized events or final summary")

    events = next(artifact for artifact in artifacts if artifact["kind"] == "normalized-events")
    summary = next(artifact for artifact in artifacts if artifact["kind"] == "final-summary")
    if events["sizeBytes"] != context["normalizedEventsBytes"]:
        raise ValueError("normalized event byte count differs from its artifact")
    if summary["sizeBytes"] != context["finalResponseBytes"]:
        raise ValueError("final response byte count differs from its artifact")
    event_document = parsed_artifacts[cast(str, events["path"])]
    if not isinstance(event_document, dict) or set(event_document) != {
        "schemaVersion",
        "normalizerId",
        "events",
        "resources",
    }:
        raise ValueError("normalized event document shape differs from contract")
    normalized_event_list = event_document["events"]
    if (
        event_document["schemaVersion"] != 1
        or event_document["normalizerId"] != normalizer["normalizerId"]
        or not isinstance(normalized_event_list, list)
        or [event.get("index") for event in normalized_event_list]
        != list(range(context["toolCallCount"]))
    ):
        raise ValueError("normalized event document identity or ordering differs")
    retained_fields = set(cast(list[str], normalizer["retainedEventFields"]))
    if any(
        not isinstance(event, dict) or not set(event).issubset(retained_fields)
        for event in normalized_event_list
    ):
        raise ValueError("normalized event retains fields outside the frozen policy")
    normalized_resources = event_document["resources"]
    artifact_step_observed = any(step["id"] == "read-artifact-resources" for step in steps)
    expected_resource_count = 3 if record["outcome"] == "passed" or artifact_step_observed else 0
    if (
        not isinstance(normalized_resources, list)
        or len(normalized_resources) != expected_resource_count
    ):
        raise ValueError("normalized resource observation count differs")
    required_resource_fields = {
        "resourceUriSha256",
        "resourceScheme",
        "resourceMimeType",
        "resourceSizeBytes",
        "normalizedBytes",
    }
    if any(
        not isinstance(resource, dict)
        or set(resource) != required_resource_fields
        or resource["resourceScheme"] != "amkernel"
        for resource in normalized_resources
    ):
        raise ValueError("normalized resource observation differs from policy")
    required_event_fields = {
        "index",
        "direction",
        "method",
        "toolName",
        "requestId",
        "attemptKind",
        "requestProjection",
        "normalizedRequestBytes",
        "normalizedBytes",
    }
    request_ids: set[str] = set()
    for event in normalized_event_list:
        if not required_event_fields.issubset(event):
            raise ValueError("normalized event lacks required retained fields")
        if (
            event["direction"] != "response"
            or event["method"] != "tools/call"
            or event["toolName"] != "python_exec"
        ):
            raise ValueError("normalized event differs from tool response contract")
        if event["requestId"] in request_ids:
            raise ValueError("normalized event request IDs are not unique")
        request_ids.add(cast(str, event["requestId"]))
        if not valid_request_projection(event["requestProjection"]):
            raise ValueError("retained request projection contains raw or malformed values")
        if event["normalizedRequestBytes"] != len(canonical_json_bytes(event["requestProjection"])):
            raise ValueError("normalized request bytes differ from retained projection")
    call_steps = [step for step in steps if step["action"] == "call-tool"]
    for step in call_steps:
        indexes = cast(list[int], step["toolCallIndexes"])
        attempts = [normalized_event_list[index] for index in indexes]
        if any(
            event["attemptKind"] != "schema-retry" or event["normalizedBytes"] != 0
            for event in attempts[:-1]
        ):
            raise ValueError(f"retry attempt classification differs: {step['id']}")
        final_event = attempts[-1]
        if final_event["attemptKind"] != "scenario" or not {
            "status",
            "kernelState",
            "semanticsSha256",
            "startedAt",
            "completedAt",
        }.issubset(final_event):
            raise ValueError(f"final attempt lacks scenario response evidence: {step['id']}")
        definition = next(item for item in expected_steps if item["id"] == step["id"])
        expected_final_request_bytes = normalize_request(
            "python_exec", cast(dict[str, Any], definition["arguments"])
        )
        expected_final_projection = request_projection(
            "python_exec", cast(dict[str, Any], definition["arguments"])
        )
        if (
            final_event["requestProjection"] != expected_final_projection
            or final_event["normalizedRequestBytes"] != expected_final_request_bytes
            or sum(event["normalizedRequestBytes"] for event in attempts)
            != step["normalizedRequestBytes"]
            or final_event["status"] != step["status"]
            or final_event["kernelState"] != step["kernelState"]
            or final_event["semanticsSha256"] != step["semanticsSha256"]
            or final_event.get("resultSha256") != step["resultSha256"]
            or final_event["normalizedBytes"] != step["normalizedResultBytes"]
        ):
            raise ValueError(f"normalized attempts differ from step evidence: {step['id']}")

    summary_document = parsed_artifacts[cast(str, summary["path"])]
    required_summary = set(cast(list[str], scenario["finalResponse"]["requiredFields"]))
    if not isinstance(summary_document, dict) or set(summary_document) != required_summary:
        raise ValueError("final summary fields differ from frozen contract")
    expected_summary = {
        "scenarioId": scenario["scenarioId"],
        "outcome": record["outcome"],
        "completedStepIds": [step["id"] for step in steps if step["outcome"] == "passed"],
        "toolCallCount": context["toolCallCount"],
        "schemaRetryCount": context["schemaRetryCount"],
        "wrongToolSelectionCount": context["wrongToolSelectionCount"],
        "clarificationRequestCount": context["clarificationRequestCount"],
        "kernelState": steps[-1]["kernelState"],
        "cleanupCompleted": record["cleanup"]["completed"],
    }
    if any(summary_document[key] != value for key, value in expected_summary.items()):
        raise ValueError("final summary differs from structured evidence")

    resource_kinds = {"resource-manifest", "resource-part"}
    resource_proof_required = record["outcome"] == "passed" or artifact_step_observed
    if not resource_kinds.intersection(kinds):
        if resource_proof_required:
            raise ValueError("observed resource step lacks manifest and part proof")
        return
    if not resource_kinds.issubset(kinds):
        raise ValueError("resource evidence is incomplete")
    manifests = [artifact for artifact in artifacts if artifact["kind"] == "resource-manifest"]
    parts = [artifact for artifact in artifacts if artifact["kind"] == "resource-part"]
    if len(manifests) != 1 or len(parts) != 2:
        raise ValueError("passed evidence must contain one manifest and two parts")
    manifest_artifact = manifests[0]
    manifest_path = cast(str, manifest_artifact["path"])
    manifest = parsed_artifacts[manifest_path]
    if not isinstance(manifest, dict) or not isinstance(manifest.get("parts"), list):
        raise ValueError(f"resource manifest is not valid JSON: {manifest_path}")
    recovered = bytearray()
    ordered_parts: list[dict[str, Any]] = []
    expected_offset = 0
    for expected_part in manifest["parts"]:
        if expected_part.get("offset") != expected_offset:
            raise ValueError(f"resource manifest offsets are not contiguous: {manifest_path}")
        matches = [
            part
            for part in parts
            if part["sha256"] == expected_part.get("sha256")
            and part["sizeBytes"] == expected_part.get("size")
        ]
        if len(matches) != 1:
            raise ValueError(f"resource manifest part proof differs: {manifest_path}")
        ordered_parts.append(matches[0])
        recovered.extend(artifact_payloads[cast(str, matches[0]["path"])])
        expected_offset += cast(int, expected_part["size"])
    if len(recovered) != manifest.get("size") or hashlib.sha256(
        recovered
    ).hexdigest() != manifest.get("sha256"):
        raise ValueError(f"resource manifest payload proof differs: {manifest_path}")

    create_expected = next(
        step["expected"] for step in scenario["steps"] if step["id"] == "create-artifact"
    )
    read_expected = next(
        step["expected"] for step in scenario["steps"] if step["id"] == "read-artifact-resources"
    )
    read_step = next(step for step in steps if step["id"] == "read-artifact-resources")
    if (
        len(recovered) != create_expected["sizeBytes"]
        or len(recovered) != read_expected["sizeBytes"]
        or len(manifest["parts"]) != create_expected["partCount"]
        or len(manifest["parts"]) != read_expected["partCount"]
        or not read_expected["integrityVerified"]
        or manifest["declaredMimeType"] != create_expected["mimeType"]
        or read_step["resourceBytes"] != len(recovered)
        or manifest_artifact["mimeType"] != read_expected["manifestMimeType"]
        or any(part["mimeType"] != read_expected["partMimeType"] for part in parts)
    ):
        raise ValueError("resource proof differs from frozen scenario semantics")
    part_uris = [cast(str, part["uri"]) for part in manifest["parts"]]
    uri_bases = {uri.rsplit("/part/", 1)[0] for uri in part_uris if "/part/" in uri}
    if len(uri_bases) != 1:
        raise ValueError("resource part URIs do not share one artifact base URI")
    artifact_uri = uri_bases.pop()
    artifact_suffix = artifact_uri.removeprefix("amkernel://artifact/")
    identifiers = artifact_suffix.split("/")
    try:
        parsed_identifiers = [uuid.UUID(hex=value) for value in identifiers]
    except (ValueError, AttributeError) as error:
        raise ValueError("resource manifest URI identities are invalid") from error
    if any(uri != f"{artifact_uri}/part/{index}" for index, uri in enumerate(part_uris)):
        raise ValueError("resource part URI suffixes differ from production grammar")
    if (
        artifact_uri == artifact_suffix
        or len(identifiers) != 2
        or any(
            parsed.version != 4 or parsed.hex != value
            for parsed, value in zip(parsed_identifiers, identifiers, strict=True)
        )
    ):
        raise ValueError("resource manifest URI does not use production artifact shape")
    resource_uris = [artifact_uri, *part_uris]
    resource_artifacts = [manifest_artifact, *ordered_parts]
    expected_reference_bytes = 0
    for observation, uri, resource_artifact in zip(
        normalized_resources, resource_uris, resource_artifacts, strict=True
    ):
        expected_observation = normalize_event(
            {
                "resourceUri": uri,
                "mimeType": resource_artifact["mimeType"],
                "resourceSizeBytes": resource_artifact["sizeBytes"],
            },
            normalizer,
        )
        if observation != expected_observation:
            raise ValueError("normalized resource observation differs from resource proof")
        expected_reference_bytes += cast(int, observation["normalizedBytes"])
    if context["resourceReferenceBytes"] != expected_reference_bytes:
        raise ValueError("resource reference byte total differs from observed resources")
    if record["outcome"] == "passed":
        cleanup = cast(dict[str, Any], record["cleanup"])
        if not all(
            cleanup[name] for name in ("completed", "clientExited", "serverExited", "runnerExited")
        ):
            raise ValueError("passed evidence lacks observed cleanup")
        if cleanup["managedProcessesRemaining"] or cleanup["managedArtifactsRemaining"]:
            raise ValueError("passed evidence retains managed resources")
        if cleanup["remainingExternalResources"]:
            raise ValueError("passed evidence retains external resources")
