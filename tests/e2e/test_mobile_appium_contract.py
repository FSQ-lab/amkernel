"""Contract checks for the frozen Stage 3 mobile Appium experiment."""

from __future__ import annotations

import base64
import hashlib
import json
import runpy
import shutil
import subprocess
import urllib.error
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "mobile_appium"
SCENARIO_BYTES = (FIXTURES / "scenario.json").read_bytes()
SCENARIO = cast(dict[str, Any], json.loads(SCENARIO_BYTES))
EVIDENCE_SCHEMA = cast(dict[str, Any], json.loads((FIXTURES / "evidence.schema.json").read_bytes()))
GRADUATION_SCHEMA = cast(
    dict[str, Any], json.loads((FIXTURES / "graduation-index.schema.json").read_bytes())
)
MEASUREMENT_BYTES = (FIXTURES / "measurement-protocol.json").read_bytes()
MEASUREMENT_PROTOCOL = cast(dict[str, Any], json.loads(MEASUREMENT_BYTES))
TIMESTAMP = "2026-10-30T12:00:00Z"
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
PAGE_SOURCE_BYTES = ("<root>" + "<node/>" * 19 + "</root>").encode()


def artifact(kind: str, mime_type: str, path: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "mimeType": mime_type,
        "path": path,
        "sizeBytes": 10,
        "sha256": "a" * 64,
    }


def measurement(ceiling: int, unit: str = "milliseconds") -> dict[str, Any]:
    return {
        "status": "measured",
        "unit": unit,
        "samples": [1, 2, 3],
        "summary": {"minimum": 1, "median": 2, "maximum": 3},
        "ceiling": ceiling,
        "passed": True,
    }


def process_observation(pid: int) -> dict[str, int]:
    return {"pid": pid, "rssBytes": 1024, "openFiles": 4, "tasks": 2, "descendants": 0}


def measurement_results() -> dict[str, Any]:
    process_points = (
        "pre-session-idle",
        "post-session-baseline",
        "post-warmup",
        "iteration-1",
        "iteration-5",
        "iteration-10",
    )
    resource_samples: list[dict[str, Any]] = []
    for point in process_points:
        sample: dict[str, Any] = {
            "point": point,
            "amkernel": process_observation(101),
            "appiumServer": process_observation(102),
        }
        if point != "pre-session-idle":
            sample["platformDriver"] = process_observation(103)
        resource_samples.append(sample)

    plateau = {
        "iteration5Pid": 101,
        "iteration10Pid": 101,
        "samePid": True,
        "rssDeltaBytes": 0,
        "openFileDelta": 0,
        "taskDelta": 0,
        "descendantProcessDelta": 0,
        "passed": True,
    }
    return {
        "kernelStartup": measurement(10_000),
        "appiumSessionStartup": measurement(120_000),
        "startupTrials": [
            {
                "kernelStartupMs": index,
                "appiumSessionStartupMs": index,
                "serverPid": 200 + index,
                "runnerPid": 300 + index,
                "sessionId": f"session-{index}",
                "clientClosed": True,
                "managedProcessesExited": True,
                "sessionAbsent": True,
            }
            for index in (1, 2, 3)
        ],
        "idleKernelMemory": {
            "status": "measured",
            "unit": "bytes",
            "observations": {"amkernel": 1024, "appiumServer": 1024},
            "ceiling": 1_073_741_824,
            "passed": True,
        },
        "activeDriverMemory": {
            "status": "measured",
            "unit": "bytes",
            "baselinePoint": "post-session-baseline",
            "deltas": {"amkernel": 0, "appiumServer": 0, "platformDriver": 0},
            "ceilingDelta": 1_073_741_824,
            "passed": True,
        },
        "perCellOverhead": {
            "status": "measured",
            "unit": "milliseconds",
            "baselineSamples": [1] * 10,
            "rawSamples": [2] * 10,
            "baseline": 1,
            "derivedSamples": [1] * 10,
            "rawSummary": {"minimum": 2, "median": 2, "maximum": 2},
            "derivedSummary": {"minimum": 1, "median": 1, "maximum": 1},
            "ceilingDerived": 2000,
            "passed": True,
        },
        "outputDeliveryLatency": {
            "status": "measured",
            "unit": "milliseconds",
            "samples": [2] * 10,
            "summary": {"minimum": 2, "median": 2, "maximum": 2},
            "ceiling": 10_000,
            "passed": True,
        },
        "screenshot": {
            "status": "measured",
            "observations": [
                {
                    "artifactPath": f"screenshot-{index}.png",
                    "encodedBytes": len(base64.b64encode(PNG_BYTES)),
                    "decodedBytes": len(PNG_BYTES),
                    "latencyMs": 2,
                    "derivedLatencyMs": 1,
                    "sha256": hashlib.sha256(PNG_BYTES).hexdigest(),
                    "integrityVerified": True,
                }
                for index in range(10)
            ],
            "baseline": 1,
            "derivedLatencySummary": {"minimum": 1, "median": 1, "maximum": 1},
            "maximumDecodedBytes": 16_777_216,
            "ceilingDerivedLatency": 15_000,
            "passed": True,
        },
        "pageSource": {
            "status": "measured",
            "observations": [
                {
                    "artifactPath": f"source-{index}.xml",
                    "bytes": len(PAGE_SOURCE_BYTES),
                    "latencyMs": 2,
                    "derivedLatencyMs": 1,
                    "nodeCount": 20,
                    "sha256": hashlib.sha256(PAGE_SOURCE_BYTES).hexdigest(),
                    "integrityVerified": True,
                }
                for index in range(10)
            ],
            "baseline": 1,
            "derivedLatencySummary": {"minimum": 1, "median": 1, "maximum": 1},
            "maximumBytes": 16_777_216,
            "ceilingDerivedLatency": 15_000,
            "passed": True,
        },
        "timeoutToInterrupt": measurement(5000),
        "escalationCleanup": measurement(15_000),
        "agentToolCallCount": measurement(40, "calls"),
        "contextReduction": {
            "status": "measured",
            "observations": [{"beforeBytes": 100_000, "afterBytes": 10_000, "reductionRatio": 0.9}],
            "maximumAfterBytes": 32_768,
            "minimumReductionRatio": 0.8,
            "passed": True,
        },
        "resourceSamples": resource_samples,
        "resourcePlateau": {
            "amkernel": plateau,
            "appiumServer": {**plateau, "iteration5Pid": 102, "iteration10Pid": 102},
            "platformDriver": {**plateau, "iteration5Pid": 103, "iteration10Pid": 103},
        },
    }


def evidence_record() -> dict[str, Any]:
    fixture = SCENARIO["fixtures"]["android"]
    fixture_artifact = fixture["artifact"]
    result_artifact = artifact("amkernel-result", "application/json", "amkernel-result.json")
    appium_log = artifact("appium-log", "text/plain", "appium.log")
    driver_log = artifact("driver-log", "text/plain", "driver.log")
    device_log = artifact("device-log", "text/plain", "device.log")
    amkernel_log = artifact("amkernel-log", "text/plain", "amkernel.log")
    screenshot = artifact("screenshot", "image/png", "screenshot.png")
    page_source = artifact("page-source", "application/xml", "page-source.xml")
    return {
        "schemaVersion": 1,
        "experimentId": "S3-mobile-appium",
        "runId": "android-20261030t120000z-12345678",
        "startedAt": TIMESTAMP,
        "completedAt": "2026-10-30T12:00:01Z",
        "durationMs": 1000,
        "outcome": "passed",
        "platform": "android",
        "preflight": {
            "classification": "ready",
            "checkedAt": TIMESTAMP,
            "checks": [{"id": "toolchain", "status": "passed", "observation": "pinned"}],
        },
        "environment": {
            "host": {"os": "Darwin", "release": "25.6.0", "architecture": "arm64"},
            "python": {"implementation": "CPython", "version": "3.13.9"},
            "mcp": {"clientVersion": "1.26.0", "protocolVersion": "2025-11-25"},
            "amkernel": {
                "version": "0.0.0",
                "revision": "1" * 40,
                "wheel": {
                    "filename": "amkernel-0.0.0-py3-none-any.whl",
                    "sizeBytes": 100,
                    "sha256": "2" * 64,
                },
            },
            "nodeVersion": "26.12.1",
            "appium": {
                "serverVersion": "3.7.0",
                "baseUrl": "http://127.0.0.1:4723",
                "pythonClientVersion": "5.2.5",
                "seleniumVersion": "4.52.0",
                "driverName": "uiautomator2",
                "driverVersion": "8.7.0",
            },
            "officialSkills": {
                "repository": "https://github.com/appium/skills",
                "commit": "e907024c210fe024c956ed9c74146fc27b1dd013",
                "appiumPythonPath": "skills/appium-python",
            },
            "capabilities": {
                "platformName": "Android",
                "automationName": "UiAutomator2",
                "udid": "emulator-5554",
                "applicationId": "io.appium.android.apis",
                "noReset": True,
            },
        },
        "device": {
            "kind": "android-emulator",
            "id": "emulator-5554",
            "name": "Pixel 9",
            "osVersion": "16",
            "state": "online",
            "platformDetails": {
                "sdkRootLabel": "ANDROID_HOME",
                "apiLevel": 36,
                "abi": "arm64-v8a",
                "systemImage": "system-images;android-36;google_apis;arm64-v8a",
                "deviceProfile": "pixel_9",
            },
        },
        "fixture": {
            "id": fixture["id"],
            "repository": fixture["repository"],
            "tag": fixture["tag"],
            "commit": fixture["commit"],
            "license": fixture["license"],
            "redistribution": (
                "Apache-2.0 redistribution permitted with license and notice preservation"
            ),
            "buildCommands": fixture["build"],
            "installCommand": fixture["install"],
            "artifactName": fixture_artifact["name"],
            "artifactSizeBytes": fixture_artifact["sizeBytes"],
            "artifactSha256": fixture_artifact["sha256"],
            "applicationId": fixture["application"]["id"],
        },
        "scenario": {
            "id": SCENARIO["scenarioId"],
            "definitionSha256": hashlib.sha256(SCENARIO_BYTES).hexdigest(),
            "executionCount": 1,
        },
        "runState": {
            "kernelBefore": "not-started",
            "kernelAfter": "dead",
            "sessionBefore": "absent",
            "sessionAfter": "absent",
            "deviceBefore": "online",
            "deviceAfter": "online",
            "appBefore": "unknown",
            "appAfter": "not-running",
        },
        "steps": [
            {
                "id": f"android-step-{index}",
                "action": "waitVisible",
                "startedAt": TIMESTAMP,
                "completedAt": TIMESTAMP,
                "durationMs": 0,
                "outcome": "passed",
                "locator": {"strategy": "accessibility id", "value": "Views"},
                "observation": "element became visible",
            }
            for index in range(len(SCENARIO["platforms"]["android"]["workflow"]))
        ],
        "amkernel": {
            "tool": "python_exec",
            "calls": 3,
            "executionCounts": [1, 2, 3],
            "continuationVerified": True,
            "kernelState": "alive",
            "outputs": [
                {
                    "call": call,
                    "status": "completed",
                    "durationMs": 10,
                    "stdoutStoredBytes": 0,
                    "stderrStoredBytes": 0,
                    "totalBytes": 0,
                    "discardedBytes": 0,
                    "truncated": False,
                    "limitBytes": 65536,
                    "artifactCount": 0,
                    "live": "unavailable",
                    "textSha256": "3" * 64,
                }
                for call in (1, 2, 3)
            ],
        },
        "artifacts": [
            result_artifact,
            screenshot,
            page_source,
            appium_log,
            driver_log,
            device_log,
            amkernel_log,
        ],
        "logs": {
            "appiumServer": appium_log,
            "platformDriver": driver_log,
            "device": device_log,
            "amkernel": amkernel_log,
        },
        "measurementProtocol": {
            "id": MEASUREMENT_PROTOCOL["protocolId"],
            "definitionSha256": hashlib.sha256(MEASUREMENT_BYTES).hexdigest(),
            "resultsProvenance": {
                "platform": "android",
                "deviceId": "emulator-5554",
                "deviceBuild": "google/tok*/tok*:16/build/userdebug/dev-keys",
                "amkernelRevision": "test-revision",
                "amkernelWheelSha256": "4" * 64,
                "measurementProtocolSha256": hashlib.sha256(MEASUREMENT_BYTES).hexdigest(),
                "startedAt": "2026-10-30T00:00:00Z",
                "completedAt": "2026-10-30T00:10:00Z",
            },
        },
        "measurements": measurement_results(),
        "cleanup": {
            "attempted": True,
            "completed": True,
            "driverQuit": "observed",
            "applicationStopped": "observed",
            "sessionAbsent": "observed",
            "managedProcessesExited": "observed",
            "deviceUsable": "observed",
            "remainingExternalResources": [],
            "observation": "all managed resources exited",
        },
    }


def test_evidence_schema_accepts_complete_pass() -> None:
    Draft202012Validator.check_schema(EVIDENCE_SCHEMA)
    Draft202012Validator(EVIDENCE_SCHEMA).validate(evidence_record())


def test_evidence_schema_rejects_wrong_environment_steps_paths_and_secrets() -> None:
    validator = Draft202012Validator(EVIDENCE_SCHEMA)
    mutations: list[Callable[[dict[str, Any]], None]] = [
        lambda record: record["environment"].__setitem__("nodeVersion", "26.12.0"),
        lambda record: record["steps"].pop(),
        lambda record: record["cleanup"].__setitem__("observation", "/Users/alice/private.log"),
        lambda record: record["environment"]["capabilities"].__setitem__("authToken", "secret"),
    ]
    for mutate in mutations:
        record = evidence_record()
        mutate(record)
        with pytest.raises(ValidationError):
            validator.validate(record)


def test_preflight_classification_matches_check_statuses() -> None:
    validator = Draft202012Validator(
        {
            "$schema": EVIDENCE_SCHEMA["$schema"],
            "$defs": EVIDENCE_SCHEMA["$defs"],
            "$ref": "#/$defs/preflight",
        }
    )
    ready: dict[str, Any] = {
        "classification": "ready",
        "checkedAt": TIMESTAMP,
        "checks": [{"id": "toolchain", "status": "passed", "observation": "pinned"}],
    }
    validator.validate(ready)
    ready["checks"][0]["status"] = "blocked"
    with pytest.raises(ValidationError):
        validator.validate(ready)
    blocked = {
        "classification": "blocked",
        "checkedAt": TIMESTAMP,
        "checks": [{"id": "toolchain", "status": "passed", "observation": "pinned"}],
    }
    with pytest.raises(ValidationError):
        validator.validate(blocked)


def test_lifecycle_validator_requires_exact_platform_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.syspath_prepend(str(ROOT / "e2e"))
    namespace = runpy.run_path(str(ROOT / "e2e" / "mobile_appium_failures.py"))
    cases = cast(dict[str, str], namespace["CASES"])
    artifact_record = cast(Callable[[Path, Path], dict[str, Any]], namespace["artifact_record"])
    validate = cast(
        Callable[[dict[str, Any], Path, dict[str, Any]], None],
        namespace["validate_lifecycle"],
    )
    matrix_bytes = cast(Callable[[], bytes], namespace["matrix_definition_bytes"])
    occurrences: list[dict[str, Any]] = []
    occurrence_root = tmp_path / "occurrences"
    occurrence_root.mkdir()
    for identifier, coverage in cases.items():
        platforms = ("android",) if coverage == "Shared" else ("android", "ios")
        for platform in platforms:
            transcript_path = occurrence_root / f"{identifier}-{platform}.json"
            transcript_path.write_text("{}\n")
            transcript = artifact_record(transcript_path, tmp_path)
            occurrences.append(
                {
                    "id": identifier,
                    "coverage": coverage,
                    "platform": platform,
                    "injectedAt": TIMESTAMP,
                    "injection": "injected failure",
                    "failure": {
                        "category": "driver",
                        "message": "observed failure",
                        "agentObservation": "observed failure",
                        "kernelState": "alive",
                        "sessionState": "absent",
                        "deviceState": "online",
                        "serverState": "online",
                        "recreationRequired": [],
                        "recoverableEvidence": [transcript["path"]],
                        "cleanupAttempted": True,
                        "cleanupObserved": True,
                        "remainingExternalResources": [],
                        "lastCompletedStep": "failure-injected",
                    },
                    "transcript": transcript,
                }
            )
    references: dict[str, dict[str, Any]] = {}
    for platform in ("android", "ios"):
        path = tmp_path / f"{platform}-reference.json"
        path.write_text("{}\n")
        references[platform] = artifact_record(path, tmp_path)
    record: dict[str, Any] = {
        "schemaVersion": 1,
        "experimentId": "S3-mobile-appium-lifecycle",
        "generatedAt": TIMESTAMP,
        "matrixDefinitionSha256": hashlib.sha256(matrix_bytes()).hexdigest(),
        "amkernelRevision": "a" * 40,
        "amkernelWheel": {
            "filename": "amkernel.whl",
            "sizeBytes": 1,
            "sha256": "b" * 64,
        },
        "referenceEvidence": references,
        "occurrences": occurrences,
    }

    validate(record, tmp_path, EVIDENCE_SCHEMA)
    record["occurrences"].pop()
    with pytest.raises((ValidationError, ValueError)):
        validate(record, tmp_path, EVIDENCE_SCHEMA)


def test_retained_lifecycle_evidence_satisfies_required_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(ROOT / "e2e"))
    namespace = runpy.run_path(str(ROOT / "e2e" / "mobile_appium_failures.py"))
    validate = cast(
        Callable[[dict[str, Any], Path, dict[str, Any]], None],
        namespace["validate_lifecycle"],
    )
    validate_semantics = cast(
        Callable[[dict[str, Any], Path], None], namespace["validate_required_semantics"]
    )
    root = ROOT.parent / "evidence" / "stage-3"
    record = cast(dict[str, Any], json.loads((root / "lifecycle.json").read_bytes()))

    validate(record, root, EVIDENCE_SCHEMA)
    validate_semantics(record, root)


def test_retained_graduation_index_is_evidence_derived(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(ROOT / "e2e"))
    namespace = runpy.run_path(str(ROOT / "e2e" / "mobile_appium_failures.py"))
    validate = cast(
        Callable[[dict[str, Any], Path, dict[str, Any], dict[str, Any]], None],
        namespace["validate_graduation_index"],
    )
    root = ROOT.parent / "evidence" / "stage-3"
    record = cast(dict[str, Any], json.loads((root / "index.json").read_bytes()))

    validate(record, root, GRADUATION_SCHEMA, EVIDENCE_SCHEMA)


@pytest.mark.parametrize(
    ("field", "value"),
    [("sha256", "0" * 64), ("sizeBytes", 1)],
)
def test_graduation_index_rejects_modified_evidence_identity(
    monkeypatch: pytest.MonkeyPatch, field: str, value: str | int
) -> None:
    monkeypatch.syspath_prepend(str(ROOT / "e2e"))
    namespace = runpy.run_path(str(ROOT / "e2e" / "mobile_appium_failures.py"))
    validate = cast(
        Callable[[dict[str, Any], Path, dict[str, Any], dict[str, Any]], None],
        namespace["validate_graduation_index"],
    )
    root = ROOT.parent / "evidence" / "stage-3"
    record = cast(dict[str, Any], json.loads((root / "index.json").read_bytes()))
    artifacts = cast(dict[str, dict[str, Any]], record["artifacts"])
    artifacts["androidReference"][field] = value

    with pytest.raises(ValueError, match="differs from linked evidence"):
        validate(record, root, GRADUATION_SCHEMA, EVIDENCE_SCHEMA)


@pytest.mark.parametrize("collection", ["criteria", "measurements", "failures", "reviews"])
def test_graduation_index_rejects_missing_required_mapping(
    monkeypatch: pytest.MonkeyPatch, collection: str
) -> None:
    monkeypatch.syspath_prepend(str(ROOT / "e2e"))
    namespace = runpy.run_path(str(ROOT / "e2e" / "mobile_appium_failures.py"))
    validate = cast(
        Callable[[dict[str, Any], Path, dict[str, Any], dict[str, Any]], None],
        namespace["validate_graduation_index"],
    )
    root = ROOT.parent / "evidence" / "stage-3"
    record = cast(dict[str, Any], json.loads((root / "index.json").read_bytes()))
    cast(list[Any], record[collection]).pop()

    with pytest.raises(ValueError):
        validate(record, root, GRADUATION_SCHEMA, EVIDENCE_SCHEMA)


def test_graduation_rejects_lifecycle_linked_to_another_reference(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.syspath_prepend(str(ROOT / "e2e"))
    namespace = runpy.run_path(str(ROOT / "e2e" / "mobile_appium_failures.py"))
    build = cast(Callable[..., dict[str, Any]], namespace["build_graduation_record"])
    source = ROOT.parent / "evidence" / "stage-3"
    root = tmp_path / "stage-3"
    shutil.copytree(source, root)
    original = root / "references" / "android-evidence.json"
    alternate = root / "references" / "android-alternate.json"
    shutil.copy2(original, alternate)
    lifecycle_path = root / "lifecycle.json"
    lifecycle = cast(dict[str, Any], json.loads(lifecycle_path.read_bytes()))
    references = cast(dict[str, dict[str, Any]], lifecycle["referenceEvidence"])
    references["android"]["path"] = "references/android-alternate.json"
    lifecycle_path.write_text(json.dumps(lifecycle))

    with pytest.raises(ValueError, match="differs from selected graduation evidence"):
        build(
            original,
            root / "references" / "ios-evidence.json",
            lifecycle_path,
            root,
            TIMESTAMP,
            EVIDENCE_SCHEMA,
        )


def test_required_semantics_rejects_post_cleanup_session_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(ROOT / "e2e"))
    namespace = runpy.run_path(str(ROOT / "e2e" / "mobile_appium_failures.py"))
    validate_semantics = cast(
        Callable[[dict[str, Any], Path], None], namespace["validate_required_semantics"]
    )
    root = ROOT.parent / "evidence" / "stage-3"
    record = cast(dict[str, Any], json.loads((root / "lifecycle.json").read_bytes()))
    occurrence = next(
        item
        for item in cast(list[dict[str, Any]], record["occurrences"])
        if item["id"] == "python-exception" and item["platform"] == "android"
    )
    cast(dict[str, Any], occurrence["failure"])["sessionState"] = "absent"

    with pytest.raises(ValueError, match="loses failure-time live-session state"):
        validate_semantics(record, root)


@pytest.mark.parametrize(
    ("transcript_name", "observation", "message"),
    [
        (
            "platform-driver-failure-android.json",
            "called _driver.quit()",
            "lacks driver fault or cleanup proof",
        ),
        (
            "platform-driver-failure-ios.json",
            "called _driver.quit()",
            "lacks driver fault or cleanup proof",
        ),
        (
            "device-offline-android.json",
            "device probe unavailable: TimeoutExpired",
            "lacks an observed offline injection state",
        ),
        (
            "device-offline-ios.json",
            "device probe unavailable: TimeoutExpired",
            "lacks an observed offline injection state",
        ),
    ],
)
def test_required_semantics_rejects_unobserved_injections(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    transcript_name: str,
    observation: str,
    message: str,
) -> None:
    monkeypatch.syspath_prepend(str(ROOT / "e2e"))
    namespace = runpy.run_path(str(ROOT / "e2e" / "mobile_appium_failures.py"))
    validate_semantics = cast(
        Callable[[dict[str, Any], Path], None], namespace["validate_required_semantics"]
    )
    source = ROOT.parent / "evidence" / "stage-3"
    shutil.copytree(source / "occurrences", tmp_path / "occurrences")
    record = cast(dict[str, Any], json.loads((source / "lifecycle.json").read_bytes()))
    transcript_path = tmp_path / "occurrences" / transcript_name
    transcript = cast(dict[str, Any], json.loads(transcript_path.read_bytes()))
    observations = cast(dict[str, Any], transcript["observations"])
    if transcript_name.startswith("platform-driver"):
        observations["platformDriverFault"] = observation
    else:
        observations["deviceBeforeInjection"] = observation
    transcript_path.write_text(json.dumps(transcript))

    with pytest.raises(ValueError, match=message):
        validate_semantics(record, tmp_path)


@pytest.mark.parametrize(
    ("state", "expected"),
    [("Shutdown", False), ("Booted", True)],
)
def test_device_observation_uses_simulator_power_state(
    monkeypatch: pytest.MonkeyPatch, state: str, expected: bool
) -> None:
    namespace = runpy.run_path(str(ROOT / "e2e" / "mobile_appium.py"))
    observe = cast(Callable[[str, str], tuple[bool, str]], namespace["device_observation"])
    device_id = "fixture-device"

    def fake_run(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        assert command == ["xcrun", "simctl", "list", "devices", "--json"]
        payload = {"devices": {"runtime": [{"udid": device_id, "state": state}]}}
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert observe("ios", device_id) == (expected, f"simulator state is {state!r}")


def test_retain_measurement_artifacts_preserves_observation_paths(tmp_path: Path) -> None:
    namespace = runpy.run_path(str(ROOT / "e2e" / "mobile_appium.py"))
    retain = cast(
        Callable[[dict[str, Any], Path, Path], list[dict[str, Any]]],
        namespace["retain_measurement_artifacts"],
    )
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    for index in range(10):
        (source / f"screenshot-{index}.png").write_bytes(PNG_BYTES)
        (source / f"source-{index}.xml").write_bytes(PAGE_SOURCE_BYTES)

    retained = retain(measurement_results(), source, destination)

    assert (destination / "screenshot-0.png").read_bytes() == PNG_BYTES
    assert (destination / "source-0.xml").read_bytes() == PAGE_SOURCE_BYTES
    assert {record["path"] for record in retained} == {
        *(f"screenshot-{index}.png" for index in range(10)),
        *(f"source-{index}.xml" for index in range(10)),
    }


def test_measurement_semantics_reject_derived_contradictions(tmp_path: Path) -> None:
    namespace = runpy.run_path(str(ROOT / "e2e" / "mobile_appium.py"))
    validate = cast(
        Callable[[dict[str, Any], Path], None], namespace["validate_measurement_semantics"]
    )
    for index in range(10):
        (tmp_path / f"screenshot-{index}.png").write_bytes(PNG_BYTES)
        (tmp_path / f"source-{index}.xml").write_bytes(PAGE_SOURCE_BYTES)
    validate(measurement_results(), tmp_path)

    contradictions: list[Callable[[dict[str, Any]], None]] = [
        lambda results: results["kernelStartup"]["summary"].__setitem__("maximum", 4),
        lambda results: results["perCellOverhead"]["derivedSamples"].__setitem__(0, 0),
        lambda results: results["perCellOverhead"].__setitem__("baseline", 0),
        lambda results: results["startupTrials"][1].__setitem__(
            "serverPid", results["startupTrials"][0]["serverPid"]
        ),
        lambda results: results["startupTrials"][0].__setitem__("kernelStartupMs", 9),
        lambda results: results["screenshot"]["observations"][0].__setitem__("sha256", "0" * 64),
        lambda results: results["resourcePlateau"]["amkernel"].__setitem__("rssDeltaBytes", 1),
    ]
    for contradict in contradictions:
        results = measurement_results()
        contradict(results)
        with pytest.raises(ValueError):
            validate(results, tmp_path)


def test_retained_text_redacts_supported_secret_forms() -> None:
    namespace = runpy.run_path(str(ROOT / "e2e" / "mobile_appium.py"))
    sanitize = cast(Callable[[bytes], bytes], namespace["sanitize_bytes"])
    retained = sanitize(
        b"Bearer abc token=def password:ghi https://alice:hunter2@example.test/path"
    )
    assert b"abc" not in retained
    assert b"def" not in retained
    assert b"ghi" not in retained
    assert b"hunter2" not in retained
    assert retained.count(b"[REDACTED]") == 4


@pytest.mark.parametrize(
    "path",
    [
        ("environment", "amkernel", "wheel", "sha256"),
        ("fixture", "artifactSha256"),
        ("runState", "sessionAfter"),
        ("cleanup", "remainingExternalResources"),
        ("measurements", "outputDeliveryLatency"),
        ("logs", "device"),
        ("amkernel", "outputs"),
    ],
)
def test_evidence_schema_rejects_missing_required_fact(path: tuple[str, ...]) -> None:
    record = evidence_record()
    target = record
    for key in path[:-1]:
        target = cast(dict[str, Any], target[key])
    del target[path[-1]]
    with pytest.raises(ValidationError):
        Draft202012Validator(EVIDENCE_SCHEMA).validate(record)


def test_pass_rejects_unavailable_measurement_or_incomplete_cleanup() -> None:
    validator = Draft202012Validator(EVIDENCE_SCHEMA)
    unavailable = evidence_record()
    unavailable["measurements"]["outputDeliveryLatency"] = {
        "status": "unavailable",
        "passed": False,
        "unavailableReason": "public MCP completion could not be observed",
        "substituteObservation": "none",
    }
    with pytest.raises(ValidationError):
        validator.validate(unavailable)

    leaked = evidence_record()
    leaked["cleanup"]["remainingExternalResources"] = ["Appium session abc remains"]
    with pytest.raises(ValidationError):
        validator.validate(leaked)


def test_failure_requires_complete_state_and_cleanup_context() -> None:
    validator = Draft202012Validator(EVIDENCE_SCHEMA)
    failed = evidence_record()
    failed["outcome"] = "failed"
    with pytest.raises(ValidationError):
        validator.validate(failed)
    failed["failure"] = {
        "category": "scenario",
        "message": "expected failure",
        "agentObservation": "python_exec returned the failed step",
        "kernelState": "alive",
        "sessionState": "absent",
        "deviceState": "online",
        "serverState": "online",
        "recreationRequired": ["application"],
        "recoverableEvidence": ["amkernel-result.json"],
        "cleanupAttempted": True,
        "cleanupObserved": True,
        "remainingExternalResources": [],
        "lastCompletedStep": None,
    }
    failed["steps"] = failed["steps"][:1]
    validator.validate(failed)


def test_measurement_protocol_freezes_required_schedule_and_gates() -> None:
    Draft202012Validator.check_schema({"$schema": MEASUREMENT_PROTOCOL["$schema"]})
    assert MEASUREMENT_PROTOCOL["status"] == "frozen-before-platform-runs"
    assert MEASUREMENT_PROTOCOL["schedule"] == {
        "freshProcessStartupTrials": 3,
        "warmupIterations": 1,
        "steadyStateIterations": 10,
        "processSamplePoints": [
            "pre-session-idle",
            "post-session-baseline",
            "post-warmup",
            "iteration-1",
            "iteration-5",
            "iteration-10",
        ],
        "latencySummary": ["minimum", "median", "maximum"],
        "freshProcessDefinition": MEASUREMENT_PROTOCOL["schedule"]["freshProcessDefinition"],
        "warmupDefinition": MEASUREMENT_PROTOCOL["schedule"]["warmupDefinition"],
        "steadyStateDefinition": MEASUREMENT_PROTOCOL["schedule"]["steadyStateDefinition"],
    }
    assert len(MEASUREMENT_PROTOCOL["measurements"]) == 12
    assert {item["id"] for item in MEASUREMENT_PROTOCOL["measurements"]} == {
        "kernelStartup",
        "appiumSessionStartup",
        "idleKernelMemory",
        "activeDriverMemory",
        "perCellOverhead",
        "outputDeliveryLatency",
        "screenshot",
        "pageSource",
        "timeoutToInterrupt",
        "escalationCleanup",
        "agentToolCallCount",
        "contextReduction",
    }
    plateau = MEASUREMENT_PROTOCOL["plateau"]
    assert plateau["maximumRssDeltaBytes"] > 0
    assert plateau["maximumOpenFileDelta"] >= 0
    assert plateau["maximumTaskDelta"] >= 0
    assert plateau["maximumDescendantProcessDelta"] == 0
    assert MEASUREMENT_PROTOCOL["passFail"]["unavailable"].startswith("fail")
    assert (
        "max(0, raw minus baseline)"
        in MEASUREMENT_PROTOCOL["baselineSubtraction"]["derivedLatency"]
    )


def test_fixture_sources_artifacts_and_builds_are_immutable() -> None:
    assert isinstance(SCENARIO["toolTimeoutSeconds"], int)
    assert 1 <= SCENARIO["toolTimeoutSeconds"] <= 300
    expected = {
        "android": (
            "3e716ee04ef3390284bfab761e28da8c15c08143",
            "a9eecf37b26cd084855c530db81c2bb1b91f4c1b095a04f47aa7c20e2791f686",
        ),
        "ios": (
            "9981bc4c9441f00e77064d85e5552dba72a37bea",
            "6708c9cbdf28bf69b45b10b2cfd53e98c998ad011315bb21b1815399f6a8387e",
        ),
    }
    for platform_name, (commit, digest) in expected.items():
        fixture = SCENARIO["fixtures"][platform_name]
        assert fixture["commit"] == commit
        assert fixture["artifact"]["sha256"] == digest
        assert fixture["tag"] in fixture["artifact"]["url"]
        assert fixture["license"] == "Apache-2.0"
        assert commit in "\n".join(fixture["build"])
        assert digest in "\n".join(fixture["acquire"])
        assert fixture["install"]


def test_platform_workflows_cover_equivalent_observable_behavior() -> None:
    required = {
        "waitVisible",
        "click",
        "type",
        "assertText",
        "assertVisible",
        "relaunch",
        "scrollIntoView",
        "captureSource",
    }
    all_ids: set[str] = set()
    for platform_name, contract in SCENARIO["platforms"].items():
        workflow = contract["workflow"]
        actions = {step["action"] for step in workflow}
        assert required <= actions
        assert actions & {"waitGone", "waitAttributeChange"}
        assert sum(bool(step.get("capture")) for step in workflow) >= 3
        large_tree = next(step for step in workflow if step["action"] == "captureSource")
        assert large_tree["minimumNodes"] >= 20
        for step in workflow:
            assert step["id"].startswith(f"{platform_name}-")
            assert step["id"] not in all_ids
            all_ids.add(step["id"])


def test_appium_session_probe_treats_not_found_as_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    namespace = runpy.run_path(str(ROOT / "e2e" / "mobile_appium.py"))
    observe = cast(Callable[[str, str], tuple[bool, str]], namespace["appium_session_observation"])

    def not_found(*args: object, **kwargs: object) -> None:
        raise urllib.error.HTTPError(
            "http://appium/session/gone", 404, "not found", cast(Any, {}), None
        )

    monkeypatch.setattr("urllib.request.urlopen", not_found)
    absent, observation = observe("http://appium", "gone")

    assert absent is True
    assert observation == "Appium session gone is absent"


def test_harness_emits_syntactically_valid_kernel_programs(tmp_path: Path) -> None:
    namespace = runpy.run_path(str(ROOT / "e2e" / "mobile_appium.py"))
    build_setup = cast(Callable[..., str], namespace["setup_code"])
    build_workflow = cast(Callable[[str], str], namespace["workflow_code"])
    token = "c" * 32
    setup = build_setup(
        platform_name="android",
        server_url="http://127.0.0.1:4723",
        device_id="emulator-5554",
        application_id="io.appium.android.apis",
        activity=".ApiDemos",
        workflow=SCENARIO["platforms"]["android"]["workflow"],
        input_text=SCENARIO["inputText"],
        output_dir=tmp_path / "evidence",
        token=token,
    )
    compile(setup, "<mobile-appium-setup>", "exec")
    compile(build_workflow(token), "<mobile-appium-workflow>", "exec")
