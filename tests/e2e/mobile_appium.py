"""Run the pinned mobile scenario through AMKernel's public MCP interface."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import importlib.metadata
import json
import math
import os
import platform as host_platform
import re
import subprocess
import time
import urllib.error
import urllib.request
import uuid
import xml.etree.ElementTree as ElementTree
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from statistics import median
from typing import Any, cast

from jsonschema import Draft202012Validator
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters
from mcp.types import BlobResourceContents, CallToolResult, TextContent, TextResourceContents
from PIL import Image

APPIUM_CLIENT_DISTRIBUTION = "Appium-Python-Client"
SELENIUM_DISTRIBUTION = "selenium"
MEASUREMENT_IDS = (
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
)


class PreflightBlocked(Exception):
    def __init__(self, checks: list[dict[str, str]]) -> None:
        super().__init__("mobile experiment prerequisites are blocked")
        self.checks = checks


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def structured(result: CallToolResult) -> dict[str, Any]:
    if result.is_error:
        detail = (
            result.content[0].text
            if result.content and isinstance(result.content[0], TextContent)
            else "unknown MCP tool error"
        )
        raise RuntimeError(f"AMKernel returned an MCP tool error: {detail}")
    value = result.structured_content
    if not isinstance(value, dict):
        raise RuntimeError("AMKernel omitted structured tool output")
    if not result.content or not isinstance(result.content[0], TextContent):
        raise RuntimeError("AMKernel omitted canonical JSON text output")
    if json.loads(result.content[0].text) != value:
        raise RuntimeError("AMKernel structured and text outputs disagree")
    return cast(dict[str, Any], value)


def sanitize_text(value: str) -> str:
    sanitized = value.replace(str(Path.home()), "$HOME")
    sanitized = re.sub(r"(?i)\b(Bearer)\s+\S+", r"\1 [REDACTED]", sanitized)
    sanitized = re.sub(r"(https?://)[^/\s:@]+:[^/\s@]+@", r"\1[REDACTED]@", sanitized)
    return re.sub(
        r"(?i)\b(password|secret|credential|(?:auth)?token|private.?key)"
        r"(\s*[\"']?\s*[:=]\s*[\"']?)([^,\s\"']+)",
        r"\1\2[REDACTED]",
        sanitized,
    )


def sanitize_bytes(value: bytes) -> bytes:
    return sanitize_text(value.decode(errors="replace")).encode()


def scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if re.search(
                r"password|secret|credential|(?:auth)?token|private.?key", key, re.IGNORECASE
            )
            else scrub(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [scrub(item) for item in value]
    if isinstance(value, str):
        return sanitize_text(value)
    return value


def output_record(call: int, payload: dict[str, Any]) -> dict[str, Any]:
    output = cast(dict[str, Any], payload["output"])
    canonical = json.dumps(scrub(payload), sort_keys=True, separators=(",", ":")).encode()
    return {
        "call": call,
        "status": payload["status"],
        "durationMs": payload["durationMs"],
        "stdoutStoredBytes": len(cast(str, payload["stdout"]).encode()),
        "stderrStoredBytes": len(cast(str, payload["stderr"]).encode()),
        "totalBytes": output["totalBytes"],
        "discardedBytes": output["discardedBytes"],
        "truncated": output["truncated"],
        "limitBytes": output["limitBytes"],
        "artifactCount": len(cast(list[Any], payload["artifacts"])),
        "live": output["live"],
        "textSha256": sha256_bytes(canonical),
    }


async def read_public_artifact(client: Client, reference: dict[str, Any]) -> tuple[str, bytes]:
    async def read_one(uri: str) -> tuple[str, bytes]:
        response = await client.read_resource(uri)
        if len(response.contents) != 1:
            raise RuntimeError(f"resource {uri} returned {len(response.contents)} contents")
        content = response.contents[0]
        if content.mime_type is None:
            raise RuntimeError(f"resource {uri} omitted its MIME type")
        if isinstance(content, TextResourceContents):
            return content.mime_type, content.text.encode()
        if not isinstance(content, BlobResourceContents):
            raise RuntimeError(f"resource {uri} returned an unsupported content type")
        return content.mime_type, base64.b64decode(content.blob, validate=True)

    mime_type, payload = await read_one(cast(str, reference["uri"]))
    if reference["representation"] == "manifest":
        manifest = cast(dict[str, Any], json.loads(payload))
        chunks: list[bytes] = []
        for part in cast(list[dict[str, Any]], manifest["parts"]):
            part_mime, part_payload = await read_one(cast(str, part["uri"]))
            if part_mime != "application/octet-stream":
                raise RuntimeError(f"manifest part reported MIME type {part_mime}")
            if len(part_payload) != part["size"] or sha256_bytes(part_payload) != part["sha256"]:
                raise RuntimeError("public manifest part failed integrity validation")
            chunks.append(part_payload)
        payload = b"".join(chunks)
        mime_type = cast(str, reference["mimeType"])
    if len(payload) != reference["size"] or sha256_bytes(payload) != reference["sha256"]:
        raise RuntimeError("public artifact failed integrity validation")
    return mime_type, payload


def public_artifact_record(
    *, call: int, category: str, index: int, reference: dict[str, Any], path: Path
) -> dict[str, Any]:
    return {
        "kind": f"amkernel-{category}",
        "mimeType": reference["mimeType"],
        "path": path.name,
        "sizeBytes": path.stat().st_size,
        "sha256": sha256_bytes(path.read_bytes()),
        "call": call,
        "sourceUri": reference["uri"],
        "sequence": index,
    }


def retained_artifact(kind: str, mime_type: str, source: Path, target: Path) -> dict[str, Any]:
    payload = sanitize_bytes(source.read_bytes())
    target.write_bytes(payload)
    return {
        "kind": kind,
        "mimeType": mime_type,
        "path": target.name,
        "sizeBytes": len(payload),
        "sha256": sha256_bytes(payload),
    }


def device_observation(platform_name: str, device_id: str) -> tuple[bool, str]:
    if platform_name == "android":
        command = ["adb", "-s", device_id, "get-state"]
        try:
            completed = subprocess.run(
                command, check=False, capture_output=True, text=True, timeout=15
            )
        except (OSError, subprocess.SubprocessError) as error:
            return False, f"device probe unavailable: {type(error).__name__}: {error}"
        actual = completed.stdout.strip()
        if completed.returncode != 0:
            detail = completed.stderr.strip() or actual or f"exit status {completed.returncode}"
            return False, f"device probe reported offline: {detail}"
        return actual == "device", f"device probe returned {actual!r}"

    try:
        completed = subprocess.run(
            ["xcrun", "simctl", "list", "devices", "--json"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        devices = json.loads(completed.stdout)["devices"]
        match = next(
            device
            for runtime_devices in devices.values()
            for device in runtime_devices
            if device["udid"] == device_id
        )
    except (
        OSError,
        subprocess.SubprocessError,
        KeyError,
        StopIteration,
        json.JSONDecodeError,
    ) as error:
        return False, f"{type(error).__name__}: {error}"
    state = str(match["state"])
    return state == "Booted", f"simulator state is {state!r}"


def device_log(platform_name: str, device_id: str) -> bytes:
    command = (
        ["adb", "-s", device_id, "logcat", "-d", "-t", "2000"]
        if platform_name == "android"
        else [
            "xcrun",
            "simctl",
            "spawn",
            device_id,
            "log",
            "show",
            "--last",
            "10m",
            "--style",
            "compact",
            "--predicate",
            'process == "UIKitCatalog"',
        ]
    )
    completed = subprocess.run(command, check=True, capture_output=True, timeout=30)
    return sanitize_bytes(completed.stdout)


def platform_driver_log(platform_name: str, device_id: str) -> bytes:
    command = (
        [
            "adb",
            "-s",
            device_id,
            "logcat",
            "-d",
            "-s",
            "UiAutomator2:D",
            "io.appium.uiautomator2.server:D",
            "io.appium.uiautomator2.server.test:D",
            "*:S",
        ]
        if platform_name == "android"
        else [
            "xcrun",
            "simctl",
            "spawn",
            device_id,
            "log",
            "show",
            "--last",
            "30m",
            "--style",
            "compact",
            "--predicate",
            'process CONTAINS "WebDriverAgent"',
        ]
    )
    completed = subprocess.run(command, check=True, capture_output=True, timeout=30)
    return sanitize_bytes(completed.stdout)


def parse_args() -> argparse.Namespace:
    fixtures = Path(__file__).resolve().parents[1] / "fixtures" / "mobile_appium"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=("android", "ios"), required=True)
    parser.add_argument("--entry-point", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--amkernel-wheel", type=Path, required=True)
    parser.add_argument("--measurement-results", type=Path, required=True)
    parser.add_argument("--fixture-artifact", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--device-name", required=True)
    parser.add_argument("--os-version", required=True)
    parser.add_argument(
        "--device-kind",
        choices=("android-emulator", "android-device", "ios-simulator"),
        required=True,
    )
    parser.add_argument("--appium-server-url", default="http://127.0.0.1:4723")
    parser.add_argument("--appium-driver-version", required=True)
    parser.add_argument("--amkernel-revision", required=True)
    parser.add_argument("--appium-log", type=Path)
    parser.add_argument("--scenario", type=Path, default=fixtures / "scenario.json")
    return parser.parse_args()


def command_text(command: list[str]) -> str:
    return subprocess.run(
        command, check=True, capture_output=True, text=True, timeout=30
    ).stdout.strip()


def observe_platform_details(platform_name: str, device_id: str) -> dict[str, Any]:
    if platform_name == "android":
        prefix = ["adb", "-s", device_id]
        avd_output = command_text([*prefix, "emu", "avd", "path"])
        avd_path = Path(next(line for line in avd_output.splitlines() if line and line != "OK"))
        config: dict[str, str] = {}
        for line in (avd_path / "config.ini").read_text().splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                config[key.strip()] = value.strip()
        image_parts = [
            part for part in config["image.sysdir.1"].replace("\\", "/").split("/") if part
        ]
        return {
            "apiLevel": int(command_text([*prefix, "shell", "getprop", "ro.build.version.sdk"])),
            "abi": command_text([*prefix, "shell", "getprop", "ro.product.cpu.abi"]),
            "systemImage": ";".join(image_parts[-4:]),
            "deviceProfile": config["hw.device.name"],
            "buildFingerprint": command_text([*prefix, "shell", "getprop", "ro.build.fingerprint"]),
            "deviceName": config.get("avd.ini.displayname", avd_path.stem),
            "osVersion": command_text([*prefix, "shell", "getprop", "ro.build.version.release"]),
        }

    xcode_lines = command_text(["xcodebuild", "-version"]).splitlines()
    devices = cast(
        dict[str, list[dict[str, Any]]],
        json.loads(command_text(["xcrun", "simctl", "list", "devices", "-j"]))["devices"],
    )
    runtime_identifier, device = next(
        (runtime, candidate)
        for runtime, candidates in devices.items()
        for candidate in candidates
        if candidate["udid"] == device_id
    )
    runtimes = cast(
        list[dict[str, Any]],
        json.loads(command_text(["xcrun", "simctl", "list", "runtimes", "-j"]))["runtimes"],
    )
    runtime = next(item for item in runtimes if item["identifier"] == runtime_identifier)
    return {
        "xcodeVersion": xcode_lines[0].removeprefix("Xcode "),
        "xcodeBuild": xcode_lines[1].removeprefix("Build version "),
        "runtimeIdentifier": runtime_identifier,
        "runtimeVersion": runtime["version"],
        "runtimeBuild": runtime["buildversion"],
        "deviceTypeIdentifier": device["deviceTypeIdentifier"],
        "deviceName": device["name"],
        "osVersion": runtime["version"],
    }


def validate_inputs(arguments: argparse.Namespace, scenario: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, str]] = []

    def check(identifier: str, condition: bool, observation: str) -> None:
        checks.append(
            {
                "id": identifier,
                "status": "passed" if condition else "blocked",
                "observation": observation,
            }
        )

    expected_kind = "android-emulator" if arguments.platform == "android" else "ios-simulator"
    check(
        "device-kind",
        arguments.device_kind == expected_kind,
        f"{arguments.device_kind} selected; frozen contract requires {expected_kind}",
    )
    revision = arguments.amkernel_revision
    valid_revision = len(revision) == 40 and all(
        character in "0123456789abcdef" for character in revision
    )
    check(
        "amkernel-revision", valid_revision, "AMKernel revision is a lowercase 40-character commit"
    )
    for identifier, path in (
        ("amkernel-entry-point", arguments.entry_point),
        ("amkernel-wheel", arguments.amkernel_wheel),
        ("fixture-artifact", arguments.fixture_artifact),
        ("measurement-results", arguments.measurement_results),
        ("appium-log", arguments.appium_log),
    ):
        check(identifier, path is not None and path.is_file(), f"{identifier} is a readable file")

    fixture = cast(dict[str, Any], scenario["fixtures"][arguments.platform])
    if arguments.fixture_artifact.is_file():
        actual_size, actual_digest = hash_file(arguments.fixture_artifact)
        expected_artifact = cast(dict[str, Any], fixture["artifact"])
        check(
            "fixture-size",
            actual_size == expected_artifact["sizeBytes"],
            f"fixture size is {actual_size} bytes",
        )
        check(
            "fixture-sha256",
            actual_digest == expected_artifact["sha256"],
            f"fixture SHA-256 is {actual_digest}",
        )

    contract = cast(dict[str, Any], scenario["environmentContract"])
    platform_contract = cast(dict[str, Any], contract[arguments.platform])
    expected_python_implementation, expected_python_version = cast(str, contract["python"]).split()
    actual_python_implementation = host_platform.python_implementation()
    actual_python_version = host_platform.python_version()
    check(
        "python-runtime",
        actual_python_implementation == expected_python_implementation
        and actual_python_version.startswith(f"{expected_python_version}."),
        f"Python runtime is {actual_python_implementation} {actual_python_version}; "
        f"expected {contract['python']}",
    )
    for identifier, distribution, expected in (
        ("appium-python-client", APPIUM_CLIENT_DISTRIBUTION, contract["appiumPythonClient"]),
        ("selenium", SELENIUM_DISTRIBUTION, contract["selenium"]),
    ):
        try:
            actual = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            actual = "unavailable"
        check(
            identifier,
            actual == expected,
            f"{distribution} version is {actual}; expected {expected}",
        )
    expected_driver = cast(str, platform_contract["driverVersion"])

    check(
        "driver-version",
        arguments.appium_driver_version == expected_driver,
        f"driver version is {arguments.appium_driver_version}; expected {expected_driver}",
    )
    try:
        observed_platform = observe_platform_details(arguments.platform, arguments.device_id)
    except Exception as error:
        observed_platform = {}
        check(
            "platform-identity",
            False,
            f"platform identity is unavailable: {type(error).__name__}: {error}",
        )
    else:
        if arguments.platform == "android":
            expected_details: dict[str, Any] = {
                "apiLevel": platform_contract["apiLevel"],
                "abi": platform_contract["abi"],
                "systemImage": platform_contract["systemImage"],
            }
            for field, expected in expected_details.items():
                check(
                    f"android-{field}",
                    observed_platform[field] == expected,
                    f"observed {field} is {observed_platform[field]!r}; expected {expected!r}",
                )
            expected_profile = cast(str, platform_contract["deviceProfile"])

            def normalize(value: str) -> str:
                return "".join(character.lower() for character in value if character.isalnum())

            check(
                "android-device-profile",
                normalize(cast(str, observed_platform["deviceProfile"]))
                == normalize(expected_profile),
                f"observed device profile is {observed_platform['deviceProfile']!r}; "
                f"expected {expected_profile!r}",
            )
        else:
            expected_details = {
                "xcodeVersion": platform_contract["xcode"],
                "xcodeBuild": platform_contract["xcodeBuild"],
                "runtimeIdentifier": platform_contract["runtime"],
                "runtimeVersion": platform_contract["runtimeVersion"],
                "runtimeBuild": platform_contract["runtimeBuild"],
                "deviceTypeIdentifier": platform_contract["deviceType"],
            }
            for field, expected in expected_details.items():
                check(
                    f"ios-{field}",
                    observed_platform[field] == expected,
                    f"observed {field} is {observed_platform[field]!r}; expected {expected!r}",
                )
        check(
            "observed-os-version",
            observed_platform["osVersion"] == arguments.os_version,
            f"observed OS is {observed_platform['osVersion']!r}; "
            f"dispatch declared {arguments.os_version!r}",
        )
        if arguments.platform == "ios":
            check(
                "observed-device-name",
                observed_platform["deviceName"] == arguments.device_name,
                f"observed device name is {observed_platform['deviceName']!r}; "
                f"dispatch declared {arguments.device_name!r}",
            )
    try:
        measurement_document = cast(
            dict[str, Any], json.loads(arguments.measurement_results.read_bytes())
        )
        if set(measurement_document) != {"provenance", "measurements"}:
            raise ValueError("measurement document must contain provenance and measurements")
        provenance = cast(dict[str, Any], measurement_document["provenance"])
        measurements = cast(dict[str, Any], measurement_document["measurements"])
        protocol_path = arguments.scenario.parent / "measurement-protocol.json"
        _, wheel_sha256 = hash_file(arguments.amkernel_wheel)
        expected_provenance = {
            "platform": arguments.platform,
            "deviceId": arguments.device_id,
            "deviceBuild": observed_platform[
                "buildFingerprint" if arguments.platform == "android" else "runtimeBuild"
            ],
            "amkernelRevision": arguments.amkernel_revision,
            "amkernelWheelSha256": wheel_sha256,
            "measurementProtocolSha256": sha256_bytes(protocol_path.read_bytes()),
        }
        for field, expected in expected_provenance.items():
            if provenance.get(field) != expected:
                raise ValueError(
                    f"measurement provenance {field} is {provenance.get(field)!r}; "
                    f"expected {expected!r}"
                )
        collected_from = datetime.fromisoformat(
            cast(str, provenance["startedAt"]).replace("Z", "+00:00")
        )
        collected_to = datetime.fromisoformat(
            cast(str, provenance["completedAt"]).replace("Z", "+00:00")
        )
        now = datetime.now(UTC)
        if collected_from > collected_to or collected_to > now:
            raise ValueError("measurement collection interval is invalid")
        if (now - collected_to).total_seconds() > 86_400:
            raise ValueError("measurement results are older than 24 hours")
        evidence_schema = cast(
            dict[str, Any],
            json.loads((arguments.scenario.parent / "evidence.schema.json").read_bytes()),
        )
        measurement_schema = {
            "$schema": evidence_schema["$schema"],
            "$defs": evidence_schema["$defs"],
            "$ref": "#/$defs/measurements",
        }
        Draft202012Validator(measurement_schema).validate(measurements)
        validate_measurement_semantics(measurements, arguments.measurement_results.parent)
    except Exception as error:
        measurements = {}
        check(
            "measurement-shape",
            False,
            f"measurement results are invalid: {type(error).__name__}: {error}",
        )
    else:
        check("measurement-shape", True, "measurement results match the frozen schema")
    try:
        node_version = (
            subprocess.run(
                ["node", "--version"], check=True, capture_output=True, text=True, timeout=10
            )
            .stdout.strip()
            .removeprefix("v")
        )
    except (OSError, subprocess.SubprocessError) as error:
        node_version = f"unavailable: {type(error).__name__}"
    check(
        "node-version",
        node_version == contract["node"],
        f"Node version is {node_version}; expected {contract['node']}",
    )
    try:
        server_version = appium_version(arguments.appium_server_url)
    except Exception as error:
        server_version = f"unavailable: {type(error).__name__}: {error}"
    check(
        "appium-server",
        server_version == contract["appiumServer"],
        f"Appium Server version is {server_version}; expected {contract['appiumServer']}",
    )
    if any(item["status"] == "blocked" for item in checks):
        raise PreflightBlocked(checks)
    arguments.preflight_checks = checks
    arguments.measurements = measurements
    arguments.measurement_provenance = provenance
    arguments.observed_platform = observed_platform
    arguments.server_version = server_version
    return fixture


def measurement_artifact_bytes(root: Path, relative_path: str) -> bytes:
    if Path(relative_path).is_absolute():
        raise ValueError(f"measurement artifact path is absolute: {relative_path}")
    resolved_root = root.resolve()
    candidate = (resolved_root / relative_path).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError(f"measurement artifact escapes its root: {relative_path}") from error
    payload = candidate.read_bytes()
    if not payload or len(payload) > 16_777_216:
        raise ValueError(f"measurement artifact size is out of bounds: {relative_path}")
    return payload


def retain_measurement_artifacts(
    measurements: dict[str, Any], source_root: Path, destination: Path
) -> list[dict[str, Any]]:
    retained: list[dict[str, Any]] = []
    for identifier, mime_type in (
        ("screenshot", "image/png"),
        ("pageSource", "application/xml"),
    ):
        record = cast(dict[str, Any], measurements[identifier])
        if record["status"] != "measured":
            continue
        for observation in cast(list[dict[str, Any]], record["observations"]):
            payload = measurement_artifact_bytes(source_root, observation["artifactPath"])
            path = destination / cast(str, observation["artifactPath"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            retained.append(
                {
                    "kind": "screenshot" if identifier == "screenshot" else "page-source",
                    "mimeType": mime_type,
                    "path": path.relative_to(destination).as_posix(),
                    "sizeBytes": len(payload),
                    "sha256": sha256_bytes(payload),
                }
            )
    return retained


def validate_measurement_semantics(measurements: dict[str, Any], artifact_root: Path) -> None:
    errors: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    def same_number(actual: Any, expected: float) -> bool:
        return isinstance(actual, (int, float)) and math.isclose(
            float(actual), expected, rel_tol=1e-9, abs_tol=1e-9
        )

    def check_summary(identifier: str, samples: list[Any], summary: dict[str, Any]) -> None:
        numbers = [float(sample) for sample in samples]
        expected = {
            "minimum": min(numbers),
            "median": float(median(numbers)),
            "maximum": max(numbers),
        }
        for field, value in expected.items():
            require(
                same_number(summary[field], value),
                f"{identifier}.{field} does not match retained samples",
            )

    numeric = {
        "kernelStartup": 10_000,
        "appiumSessionStartup": 120_000,
        "timeoutToInterrupt": 5_000,
        "escalationCleanup": 15_000,
        "agentToolCallCount": 40,
    }
    for identifier, ceiling in numeric.items():
        record = cast(dict[str, Any], measurements[identifier])
        if record["status"] == "measured":
            samples = cast(list[Any], record["samples"])
            check_summary(identifier, samples, cast(dict[str, Any], record["summary"]))
            expected_pass = max(float(sample) for sample in samples) <= ceiling
            require(record["passed"] is expected_pass, f"{identifier}.passed contradicts samples")

    startup_trials = cast(list[dict[str, Any]], measurements["startupTrials"])
    for identifier, field in (
        ("kernelStartup", "kernelStartupMs"),
        ("appiumSessionStartup", "appiumSessionStartupMs"),
    ):
        record = cast(dict[str, Any], measurements[identifier])
        if record["status"] == "measured":
            samples = cast(list[Any], record["samples"])
            require(
                len(samples) == len(startup_trials)
                and all(
                    same_number(sample, trial[field])
                    for sample, trial in zip(samples, startup_trials, strict=True)
                ),
                f"{identifier}.samples do not match startupTrials",
            )
    for field in ("serverPid", "runnerPid", "sessionId"):
        identities = [trial[field] for trial in startup_trials]
        require(
            len(set(identities)) == len(identities),
            f"startupTrials.{field} values must be unique",
        )

    idle = cast(dict[str, Any], measurements["idleKernelMemory"])
    if idle["status"] == "measured":
        expected_pass = all(
            float(value) <= float(idle["ceiling"])
            for value in cast(dict[str, Any], idle["observations"]).values()
        )
        require(idle["passed"] is expected_pass, "idleKernelMemory.passed contradicts observations")

    active = cast(dict[str, Any], measurements["activeDriverMemory"])

    per_cell = cast(dict[str, Any], measurements["perCellOverhead"])
    if per_cell["status"] == "measured":
        baseline_samples = cast(list[Any], per_cell["baselineSamples"])
        require(
            same_number(per_cell["baseline"], float(median(baseline_samples))),
            "perCellOverhead.baseline is not the median of baselineSamples",
        )
        raw = cast(list[Any], per_cell["rawSamples"])
        derived = cast(list[Any], per_cell["derivedSamples"])
        expected_derived = [max(0.0, float(sample) - float(per_cell["baseline"])) for sample in raw]
        require(
            len(derived) == len(expected_derived)
            and all(
                same_number(actual, expected)
                for actual, expected in zip(derived, expected_derived, strict=True)
            ),
            "perCellOverhead.derivedSamples do not apply the frozen baseline formula",
        )
        check_summary(
            "perCellOverhead.rawSummary", raw, cast(dict[str, Any], per_cell["rawSummary"])
        )
        check_summary(
            "perCellOverhead.derivedSummary",
            derived,
            cast(dict[str, Any], per_cell["derivedSummary"]),
        )
        require(
            per_cell["passed"] is (max(expected_derived) <= float(per_cell["ceilingDerived"])),
            "perCellOverhead.passed contradicts derived samples",
        )

    output_delivery = cast(dict[str, Any], measurements["outputDeliveryLatency"])
    if output_delivery["status"] == "measured":
        samples = cast(list[Any], output_delivery["samples"])
        check_summary(
            "outputDeliveryLatency.summary",
            samples,
            cast(dict[str, Any], output_delivery["summary"]),
        )
        require(
            output_delivery["passed"] is (max(samples) <= float(output_delivery["ceiling"])),
            "outputDeliveryLatency.passed contradicts samples",
        )

    for identifier, size_field, maximum_field in (
        ("screenshot", "decodedBytes", "maximumDecodedBytes"),
        ("pageSource", "bytes", "maximumBytes"),
    ):
        record = cast(dict[str, Any], measurements[identifier])
        if record["status"] != "measured":
            continue
        observations = cast(list[dict[str, Any]], record["observations"])
        require(
            same_number(record["baseline"], float(per_cell["baseline"])),
            f"{identifier}.baseline does not match perCellOverhead.baseline",
        )
        expected_derived = [
            max(0.0, float(item["latencyMs"]) - float(record["baseline"])) for item in observations
        ]
        artifact_paths = [cast(str, item["artifactPath"]) for item in observations]
        require(
            len(set(artifact_paths)) == len(artifact_paths),
            f"{identifier}.artifactPath values must be unique",
        )
        supplied_derived = [item["derivedLatencyMs"] for item in observations]
        derivations_hold = all(
            same_number(actual, expected)
            for actual, expected in zip(supplied_derived, expected_derived, strict=True)
        )
        require(
            derivations_hold,
            f"{identifier}.derivedLatencyMs does not apply the frozen baseline formula",
        )
        check_summary(
            f"{identifier}.derivedLatencySummary",
            supplied_derived,
            cast(dict[str, Any], record["derivedLatencySummary"]),
        )
        integrity_holds = True
        for item in observations:
            payload = measurement_artifact_bytes(artifact_root, cast(str, item["artifactPath"]))
            expected_size = len(payload)
            expected_hash = sha256_bytes(payload)
            if identifier == "screenshot":
                try:
                    Image.open(BytesIO(payload)).verify()
                except Exception:
                    payload_valid = False
                else:
                    payload_valid = True
            else:
                try:
                    root = ElementTree.fromstring(payload)
                except ElementTree.ParseError:
                    payload_valid = False
                else:
                    payload_valid = sum(1 for _ in root.iter()) == item["nodeCount"]
            item_integrity = (
                payload_valid
                and item["sha256"] == expected_hash
                and item[size_field] == expected_size
                and (
                    identifier != "screenshot"
                    or item["encodedBytes"] == len(base64.b64encode(payload))
                )
            )
            require(
                item["integrityVerified"] is item_integrity,
                f"{identifier}.integrityVerified contradicts retained artifact bytes",
            )
            integrity_holds = integrity_holds and item_integrity
        expected_pass = (
            derivations_hold
            and integrity_holds
            and max(item[size_field] for item in observations) <= record[maximum_field]
            and max(expected_derived) <= record["ceilingDerivedLatency"]
        )
        require(
            record["passed"] is expected_pass,
            f"{identifier}.passed contradicts observations",
        )

    context = cast(dict[str, Any], measurements["contextReduction"])
    if context["status"] == "measured":
        observations = cast(list[dict[str, Any]], context["observations"])
        formulas_hold = all(
            same_number(item["reductionRatio"], 1.0 - item["afterBytes"] / item["beforeBytes"])
            for item in observations
        )
        require(formulas_hold, "contextReduction ratios do not match retained byte counts")
        expected_pass = formulas_hold and all(
            item["afterBytes"] <= context["maximumAfterBytes"]
            and item["reductionRatio"] >= context["minimumReductionRatio"]
            for item in observations
        )
        require(
            context["passed"] is expected_pass, "contextReduction.passed contradicts observations"
        )

    samples_by_point = {
        sample["point"]: sample
        for sample in cast(list[dict[str, Any]], measurements["resourceSamples"])
    }
    pre_session = samples_by_point["pre-session-idle"]
    baseline = samples_by_point["post-session-baseline"]
    iteration_five = samples_by_point["iteration-5"]
    iteration_ten = samples_by_point["iteration-10"]
    if active["status"] == "measured":
        same_processes = (
            baseline["amkernel"]["pid"] == pre_session["amkernel"]["pid"]
            and baseline["appiumServer"]["pid"] == pre_session["appiumServer"]["pid"]
            and iteration_ten["platformDriver"]["pid"] == baseline["platformDriver"]["pid"]
        )
        expected_deltas = {
            "amkernel": baseline["amkernel"]["rssBytes"] - pre_session["amkernel"]["rssBytes"],
            "appiumServer": baseline["appiumServer"]["rssBytes"]
            - pre_session["appiumServer"]["rssBytes"],
            "platformDriver": iteration_ten["platformDriver"]["rssBytes"]
            - baseline["platformDriver"]["rssBytes"],
        }
        require(same_processes, "activeDriverMemory compares replaced process identities")
        require(
            active["deltas"] == expected_deltas,
            "activeDriverMemory.deltas do not match resource samples",
        )
        expected_active_pass = same_processes and all(
            value <= active["ceilingDelta"] for value in expected_deltas.values()
        )
        require(
            active["passed"] is expected_active_pass,
            "activeDriverMemory.passed contradicts same-PID samples",
        )

    plateau = cast(dict[str, Any], measurements["resourcePlateau"])
    for process in ("amkernel", "appiumServer", "platformDriver"):
        five = cast(dict[str, Any], iteration_five[process])
        ten = cast(dict[str, Any], iteration_ten[process])
        decision = cast(dict[str, Any], plateau[process])
        expected = {
            "iteration5Pid": five["pid"],
            "iteration10Pid": ten["pid"],
            "samePid": five["pid"] == ten["pid"],
            "rssDeltaBytes": ten["rssBytes"] - five["rssBytes"],
            "openFileDelta": ten["openFiles"] - five["openFiles"],
            "taskDelta": ten["tasks"] - five["tasks"],
            "descendantProcessDelta": ten["descendants"] - five["descendants"],
        }
        expected_pass = (
            expected["samePid"]
            and expected["rssDeltaBytes"] <= 67_108_864
            and expected["openFileDelta"] <= 8
            and expected["taskDelta"] <= 4
            and expected["descendantProcessDelta"] <= 0
        )
        require(
            decision["passed"] is expected_pass,
            f"resourcePlateau.{process}.passed contradicts observed deltas",
        )
        require(
            all(decision[field] == value for field, value in expected.items()),
            f"resourcePlateau.{process} does not match iteration samples",
        )

    if errors:
        raise ValueError("; ".join(errors))


def appium_version(server_url: str) -> str:
    with urllib.request.urlopen(f"{server_url.rstrip('/')}/status", timeout=5) as response:
        encoded = response.read(65_537)
    if len(encoded) > 65_536:
        raise ValueError("Appium /status exceeded 65,536 bytes")
    payload = json.loads(encoded)
    if not isinstance(payload, dict):
        raise ValueError("Appium /status did not return a JSON object")
    version = payload.get("value", {}).get("build", {}).get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("Appium /status omitted value.build.version")
    return version


def appium_session_observation(server_url: str, session_id: str) -> tuple[bool, str]:
    session_url = f"{server_url.rstrip('/')}/session/{session_id}"
    try:
        with urllib.request.urlopen(session_url, timeout=5):
            pass
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return True, f"Appium session {session_id} is absent"
        return False, f"Appium session probe failed: HTTP {error.code}"
    except Exception as error:
        return False, f"Appium session probe failed: {type(error).__name__}: {error}"
    return False, f"Appium session {session_id} remains active"


async def wait_managed_processes_exited(pids: list[int], timeout: float = 10.0) -> tuple[bool, str]:
    def existing() -> list[int]:
        retained: list[int] = []
        for pid in pids:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                continue
            except PermissionError:
                retained.append(pid)
            else:
                retained.append(pid)
        return retained

    deadline = time.monotonic() + timeout
    remaining = existing()
    while remaining and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
        remaining = existing()
    return not remaining, (
        "AMKernel server and runner processes exited"
        if not remaining
        else f"managed process PIDs remain: {remaining}"
    )


def setup_code(
    *,
    platform_name: str,
    server_url: str,
    device_id: str,
    application_id: str,
    activity: str | None,
    workflow: list[dict[str, Any]],
    input_text: str,
    output_dir: Path,
    token: str,
) -> str:
    configuration = {
        "platform": platform_name,
        "serverUrl": server_url,
        "deviceId": device_id,
        "applicationId": application_id,
        "activity": activity,
        "workflow": workflow,
        "inputText": input_text,
        "outputDir": str(output_dir),
        "continuationToken": token,
    }
    return f"""import importlib.metadata as _metadata
import json as _json
import os as _os
from pathlib import Path as _Path
from appium import webdriver as _webdriver
from appium.options.android import UiAutomator2Options as _UiAutomator2Options
from appium.options.ios import XCUITestOptions as _XCUITestOptions
from selenium.webdriver.support.ui import WebDriverWait as _WebDriverWait
from selenium.webdriver.support import expected_conditions as _EC
_mobile_config = _json.loads({json.dumps(json.dumps(configuration))})
_mobile_steps = []
_mobile_artifacts = []
_mobile_output_dir = _Path(_mobile_config["outputDir"])
_mobile_output_dir.mkdir(parents=True, exist_ok=False)
if _mobile_config["platform"] == "android":
    _options = _UiAutomator2Options().load_capabilities({{
        "platformName": "Android",
        "appium:automationName": "UiAutomator2",
        "appium:udid": _mobile_config["deviceId"],
        "appium:appPackage": _mobile_config["applicationId"],
        "appium:appActivity": _mobile_config["activity"],
        "appium:noReset": True,
        "appium:newCommandTimeout": 180
    }})
else:
    _options = _XCUITestOptions().load_capabilities({{
        "platformName": "iOS",
        "appium:automationName": "XCUITest",
        "appium:udid": _mobile_config["deviceId"],
        "appium:bundleId": _mobile_config["applicationId"],
        "appium:noReset": True,
        "appium:newCommandTimeout": 180
    }})
_mobile_driver = _webdriver.Remote(_mobile_config["serverUrl"], options=_options)
try:
    _mobile_driver.terminate_app(_mobile_config["applicationId"])
    _mobile_driver.activate_app(_mobile_config["applicationId"])
except Exception:
    try:
        _mobile_driver.quit()
    finally:
        raise
{{
    "amkernelVersion": _metadata.version("amkernel"),
    "appiumPythonClientVersion": _metadata.version("Appium-Python-Client"),
    "seleniumVersion": _metadata.version("selenium"),
    "continuationToken": _mobile_config["continuationToken"],
    "sessionId": _mobile_driver.session_id,
    "runnerPid": _os.getpid(),
    "serverPid": _os.getppid()
}}
"""


def workflow_code(token: str) -> str:
    return f"""import hashlib as _hashlib
import time as _time
from datetime import UTC as _UTC, datetime as _datetime
import xml.etree.ElementTree as _ElementTree

def _mobile_now():
    return _datetime.now(_UTC).isoformat().replace("+00:00", "Z")

def _mobile_locator(step):
    locator = step["locator"]
    return locator["strategy"], locator["value"]

def _mobile_visible(step):
    return _WebDriverWait(_mobile_driver, step.get("timeoutSeconds", 10)).until(
        _EC.visibility_of_element_located(_mobile_locator(step))
    )

def _mobile_capture(step_id):
    path = _mobile_output_dir / f"{{step_id}}.png"
    if not _mobile_driver.get_screenshot_as_file(str(path)):
        raise RuntimeError(f"Appium did not write screenshot {{path}}")
    payload = path.read_bytes()
    display(payload, mime_type="image/png")
    artifact(path.name, payload, mime_type="image/png")
    artifact_record = {{
        "kind": "screenshot",
        "mimeType": "image/png",
        "path": path.name,
        "sizeBytes": len(payload),
        "sha256": _hashlib.sha256(payload).hexdigest()
    }}
    _mobile_artifacts.append(artifact_record)
    return artifact_record

def _mobile_source(step_id, minimum_nodes):
    path = _mobile_output_dir / f"{{step_id}}.xml"
    payload = _mobile_driver.page_source.encode()
    path.write_bytes(payload)
    print(payload.decode())
    artifact(path.name, payload, mime_type="application/xml")
    node_count = sum(1 for _node in _ElementTree.fromstring(payload).iter())
    if node_count < minimum_nodes:
        raise AssertionError(
            f"expected at least {{minimum_nodes}} source nodes, got {{node_count}}"
        )
    artifact_record = {{
        "kind": "page-source",
        "mimeType": "application/xml",
        "path": path.name,
        "sizeBytes": len(payload),
        "sha256": _hashlib.sha256(payload).hexdigest()
    }}
    _mobile_artifacts.append(artifact_record)
    return artifact_record, node_count

assert _mobile_config["continuationToken"] == {json.dumps(token)}
_mobile_failure = None
try:
    for _step in _mobile_config["workflow"]:
        _started_wall = _mobile_now()
        _started_clock = _time.monotonic()
        _observation = "action completed"
        _record = {{
            "id": _step["id"],
            "action": _step["action"],
            "startedAt": _started_wall
        }}
        if "locator" in _step:
            _record["locator"] = _step["locator"]
        try:
            _action = _step["action"]
            if _action == "waitVisible":
                _mobile_visible(_step)
                _observation = "element became visible"
            elif _action == "click":
                _WebDriverWait(_mobile_driver, _step.get("timeoutSeconds", 10)).until(
                    _EC.element_to_be_clickable(_mobile_locator(_step))
                ).click()
                _observation = "element clicked"
            elif _action == "type":
                _element = _mobile_visible(_step)
                _element.clear()
                _element.send_keys(_mobile_config[_step["textFrom"]])
                _observation = "text entered"
            elif _action == "assertText":
                _element = _mobile_visible(_step)
                _expected = _mobile_config[_step["textFrom"]]
                _actual = _element.text or _element.get_attribute("value")
                if _actual != _expected:
                    raise AssertionError(f"expected text {{_expected!r}}, got {{_actual!r}}")
                _observation = "text value matched"
            elif _action == "relaunch":
                _mobile_driver.terminate_app(_mobile_config["applicationId"])
                _mobile_driver.activate_app(_mobile_config["applicationId"])
                _observation = "application terminated and reactivated"
            elif _action == "waitGone":
                _WebDriverWait(_mobile_driver, _step.get("timeoutSeconds", 10)).until(
                    _EC.invisibility_of_element_located(_mobile_locator(_step))
                )
                _observation = "element became invisible"
            elif _action == "waitAttributeChange":
                _element = _mobile_visible(_step)
                _attribute = _step["attribute"]
                _initial = _element.get_attribute(_attribute)
                def _attribute_changed(_driver: object) -> str | bool:
                    _value = _driver.find_element(
                        *_mobile_locator(_step)
                    ).get_attribute(_attribute)
                    return _value if _value != _initial else False

                _changed = _WebDriverWait(
                    _mobile_driver, _step.get("timeoutSeconds", 10)
                ).until(_attribute_changed)
                _observation = f"{{_attribute}} changed from {{_initial!r}} to {{_changed!r}}"
            elif _action == "assertVisible":
                _mobile_visible(_step)
                _observation = "element was visible"
            elif _action == "scrollIntoView":
                if _mobile_config["platform"] == "android":
                    _mobile_driver.find_element(*_mobile_locator(_step))
                else:
                    for _ in range(8):
                        _matches = _mobile_driver.find_elements(*_mobile_locator(_step))
                        if _matches and _matches[0].is_displayed():
                            break
                        _mobile_driver.execute_script(
                            "mobile: swipe", {{"direction": _step["direction"]}}
                        )
                    else:
                        raise AssertionError(
                            "element did not become visible after 8 bounded swipes"
                        )
                _observation = "element was scrolled into view"
            elif _action == "captureSource":
                _record["pageSource"], _record["nodeCount"] = _mobile_source(
                    _step["id"], _step["minimumNodes"]
                )
                _observation = "bounded page source captured"
            else:
                raise ValueError(f"unsupported action {{_action!r}}")
            if _step.get("capture"):
                _record["screenshot"] = _mobile_capture(_step["id"])
            _record["outcome"] = "passed"
        except Exception as _error:
            _record["outcome"] = "failed"
            _observation = f"{{type(_error).__name__}}: {{_error}}"
            try:
                _record["screenshot"] = _mobile_capture(f"{{_step['id']}}-failure")
                _source_path = _mobile_output_dir / f"{{_step['id']}}-failure.xml"
                _source_payload = _mobile_driver.page_source.encode()
                _source_path.write_bytes(_source_payload)
                _mobile_artifacts.append({{
                    "kind": "page-source",
                    "mimeType": "application/xml",
                    "path": _source_path.name,
                    "sizeBytes": len(_source_payload),
                    "sha256": _hashlib.sha256(_source_payload).hexdigest()
                }})
            except Exception:
                pass
            _mobile_failure = {{
                "category": "scenario",
                "message": _observation,
                "lastCompletedStep": _mobile_steps[-1]["id"] if _mobile_steps else None
            }}
        finally:
            _record["completedAt"] = _mobile_now()
            _record["durationMs"] = max(0, round((_time.monotonic() - _started_clock) * 1000))
            _record["observation"] = _observation
            _mobile_steps.append(_record)
        if _mobile_failure is not None:
            break
except Exception as _error:
    _mobile_failure = {{
        "category": "scenario",
        "message": f"{{type(_error).__name__}}: {{_error}}",
        "lastCompletedStep": _mobile_steps[-1]["id"] if _mobile_steps else None
    }}
_mobile_cleanup = {{
    "attempted": True,
    "driverQuit": "not-created",
    "applicationStopped": "unknown",
    "sessionAbsent": "unknown",
    "observation": "cleanup did not run"
}}
try:
    _mobile_driver.terminate_app(_mobile_config["applicationId"])
    _mobile_cleanup["applicationStopped"] = "observed"
except Exception as _error:
    _mobile_cleanup["applicationStopped"] = "failed"
    _mobile_cleanup["observation"] = f"terminate_app failed: {{type(_error).__name__}}: {{_error}}"
try:
    _mobile_driver.quit()
    _mobile_cleanup["driverQuit"] = "observed"
    _mobile_cleanup["sessionAbsent"] = "observed"
    if _mobile_cleanup["applicationStopped"] == "observed":
        _mobile_cleanup["observation"] = "application termination and driver quit completed"
except Exception as _error:
    _mobile_cleanup["driverQuit"] = "failed"
    _mobile_cleanup["sessionAbsent"] = "unknown"
    _mobile_cleanup["observation"] = f"driver quit failed: {{type(_error).__name__}}: {{_error}}"
{{
    "continuationToken": _mobile_config["continuationToken"],
    "steps": _mobile_steps,
    "artifacts": _mobile_artifacts,
    "failure": _mobile_failure,
    "cleanup": _mobile_cleanup
}}
"""


def cleanup_code(token: str) -> str:
    return f"""_cleanup_errors = []
_mobile_steps = globals().get("_mobile_steps", [])
_mobile_artifacts = globals().get("_mobile_artifacts", [])
_mobile_failure = globals().get("_mobile_failure")
_mobile_cleanup = globals().get("_mobile_cleanup")
if not isinstance(_mobile_cleanup, dict):
    _mobile_cleanup = {{
        "attempted": True,
        "driverQuit": "not-created",
        "applicationStopped": "unknown",
        "sessionAbsent": "unknown",
        "observation": "cleanup state was unavailable"
    }}
_driver = globals().get("_mobile_driver")
if (_driver is not None and getattr(_driver, "session_id", None) is not None
        and _mobile_cleanup.get("sessionAbsent") != "observed"):
    try:
        _driver.terminate_app(_mobile_config["applicationId"])
        _mobile_cleanup["applicationStopped"] = "observed"
    except Exception as _error:
        _mobile_cleanup["applicationStopped"] = "failed"
        _cleanup_errors.append(f"terminate_app failed: {{type(_error).__name__}}: {{_error}}")
    try:
        _driver.quit()
        _mobile_cleanup["driverQuit"] = "observed"
        _mobile_cleanup["sessionAbsent"] = "observed"
    except Exception as _error:
        _mobile_cleanup["driverQuit"] = "failed"
        _mobile_cleanup["sessionAbsent"] = "unknown"
        _cleanup_errors.append(f"driver quit failed: {{type(_error).__name__}}: {{_error}}")
elif _driver is not None:
    _mobile_cleanup["driverQuit"] = "observed"
    _mobile_cleanup["sessionAbsent"] = "observed"
if _cleanup_errors:
    _mobile_cleanup["observation"] = "; ".join(_cleanup_errors)
elif _mobile_cleanup["driverQuit"] == "observed":
    _mobile_cleanup["observation"] = "application termination and driver quit completed"
{{
    "continuationToken": globals().get("_mobile_config", {{}}).get("continuationToken"),
    "expectedToken": {json.dumps(token)},
    "steps": _mobile_steps,
    "artifacts": _mobile_artifacts,
    "failure": _mobile_failure,
    "cleanup": _mobile_cleanup
}}
"""


async def run(arguments: argparse.Namespace) -> Path:
    scenario_bytes = arguments.scenario.read_bytes()
    scenario = cast(dict[str, Any], json.loads(scenario_bytes))
    fixture = validate_inputs(arguments, scenario)
    arguments.workspace.mkdir(parents=True, exist_ok=True)
    server_version = cast(str, arguments.server_version)
    timestamp = datetime.now(UTC).strftime("%Y%m%dt%H%M%Sz")
    run_id = f"{arguments.platform}-{timestamp}-{uuid.uuid4().hex[:8]}"
    run_dir = arguments.output_dir.resolve() / run_id
    token = uuid.uuid4().hex
    tool_timeout = float(scenario["toolTimeoutSeconds"])
    platform_contract = cast(dict[str, Any], scenario["platforms"][arguments.platform])
    application = cast(dict[str, str], fixture["application"])
    run_clock = time.monotonic()
    started_at = utc_now()

    parameters = StdioServerParameters(
        command=str(arguments.entry_point.resolve()), cwd=arguments.workspace.resolve()
    )
    public_artifacts: list[dict[str, Any]] = []
    async with Client(parameters, read_timeout_seconds=tool_timeout + 30.0) as client:
        tools = await client.list_tools()
        mcp_protocol_version = client.protocol_version
        if [tool.name for tool in tools.tools] != ["python_exec"]:
            raise RuntimeError("AMKernel public tool discovery did not expose exactly python_exec")
        setup = structured(
            await client.call_tool(
                "python_exec",
                {
                    "code": setup_code(
                        platform_name=arguments.platform,
                        server_url=arguments.appium_server_url,
                        device_id=arguments.device_id,
                        application_id=application["id"],
                        activity=application.get("activity"),
                        workflow=cast(list[dict[str, Any]], platform_contract["workflow"]),
                        input_text=cast(str, scenario["inputText"]),
                        output_dir=run_dir,
                        token=token,
                    ),
                    "packages": [APPIUM_CLIENT_DISTRIBUTION],
                    "timeout": tool_timeout,
                },
            )
        )
        if setup.get("status") != "completed" or setup.get("kernelState") != "alive":
            raise RuntimeError(f"AMKernel setup failed: {setup.get('error', setup)}")
        setup_result = cast(dict[str, Any], setup["result"])
        if setup_result.get("continuationToken") != token:
            raise RuntimeError("AMKernel setup returned the wrong continuation token")

        workflow: dict[str, Any] | None = None
        cleanup_output: dict[str, Any] | None = None
        tool_failure: str | None = None
        try:
            workflow = structured(
                await client.call_tool(
                    "python_exec",
                    {"code": workflow_code(token), "timeout": tool_timeout},
                )
            )
            if workflow.get("status") != "completed" or workflow.get("kernelState") != "alive":
                tool_failure = f"AMKernel workflow failed: {workflow.get('error', workflow)}"
        except Exception as error:
            tool_failure = f"workflow call failed: {type(error).__name__}: {error}"
        finally:
            try:
                cleanup_output = structured(
                    await client.call_tool(
                        "python_exec", {"code": cleanup_code(token), "timeout": tool_timeout}
                    )
                )
            except Exception as error:
                cleanup_error = f"cleanup call failed: {type(error).__name__}: {error}"
                tool_failure = f"{tool_failure}; {cleanup_error}" if tool_failure else cleanup_error

        completed_workflow = (
            workflow
            if workflow is not None and workflow.get("status") == "completed"
            else cleanup_output
        )
        if completed_workflow is None or completed_workflow.get("status") != "completed":
            workflow_result: dict[str, Any] = {
                "continuationToken": None,
                "steps": [],
                "artifacts": [],
                "failure": None,
                "cleanup": {
                    "attempted": True,
                    "driverQuit": "failed",
                    "applicationStopped": "unknown",
                    "sessionAbsent": "unknown",
                    "observation": tool_failure or "workflow and cleanup results were unavailable",
                },
            }
        else:
            workflow_result = cast(dict[str, Any], completed_workflow["result"])
        execution_outputs = [setup]
        if workflow is not None:
            execution_outputs.append(workflow)
        if cleanup_output is not None:
            execution_outputs.append(cleanup_output)
        continuation_verified = workflow_result.get("continuationToken") == token and all(
            output["executionCount"] == setup["executionCount"] + index
            for index, output in enumerate(execution_outputs[1:], start=1)
        )
        if not continuation_verified and tool_failure is None:
            tool_failure = "AMKernel did not preserve the workflow namespace across calls"
        workflow = execution_outputs[-1]
        for call_index, output in enumerate(execution_outputs, start=1):
            output_metadata = cast(dict[str, Any], output["output"])
            if output_metadata["live"] != "unavailable":
                live_failure = (
                    f"AMKernel call {call_index} reported output.live={output_metadata['live']!r}"
                )
                tool_failure = f"{tool_failure}; {live_failure}" if tool_failure else live_failure
            resources: list[tuple[str, dict[str, Any]]] = [
                ("artifact", cast(dict[str, Any], reference))
                for reference in cast(list[Any], output["artifacts"])
            ]
            resources.extend(
                (
                    "display",
                    cast(dict[str, Any], cast(dict[str, Any], display_record)["artifact"]),
                )
                for display_record in cast(list[Any], output["displays"])
                if cast(dict[str, Any], display_record)["kind"] == "image"
            )
            for resource_index, (category, reference) in enumerate(resources, start=1):
                _, payload = await read_public_artifact(client, reference)
                suffix = Path(cast(str, reference["name"])).suffix or ".bin"
                retained_path = run_dir / (
                    f"public-call-{call_index}-{category}-{resource_index}{suffix}"
                )
                retained_path.write_bytes(payload)
                public_artifacts.append(
                    public_artifact_record(
                        call=call_index,
                        category=category,
                        index=resource_index,
                        reference=reference,
                        path=retained_path,
                    )
                )

    managed_processes_exited, managed_process_observation = await wait_managed_processes_exited(
        [cast(int, setup_result["runnerPid"]), cast(int, setup_result["serverPid"])]
    )
    session_absent, session_observation = appium_session_observation(
        arguments.appium_server_url, cast(str, setup_result["sessionId"])
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    sanitized_results = scrub({"outputs": execution_outputs, "toolFailure": tool_failure})
    raw_results = (
        json.dumps(sanitized_results, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    result_path = run_dir / "amkernel-result.json"
    result_path.write_bytes(raw_results)
    result_artifact = {
        "kind": "amkernel-result",
        "mimeType": "application/json",
        "path": result_path.name,
        "sizeBytes": len(raw_results),
        "sha256": sha256_bytes(raw_results),
    }
    artifacts = list(cast(list[dict[str, Any]], workflow_result["artifacts"]))
    artifacts.extend(public_artifacts)
    expected_public_digests = {
        artifact["sha256"]
        for artifact in cast(list[dict[str, Any]], workflow_result["artifacts"])
        if artifact["kind"] in {"screenshot", "page-source"}
    }
    observed_public_digests = {artifact["sha256"] for artifact in public_artifacts}
    missing_public_digests = expected_public_digests - observed_public_digests
    if missing_public_digests:
        publication_failure = "AMKernel public resources omitted workflow artifacts: " + ", ".join(
            sorted(missing_public_digests)
        )
        tool_failure = (
            f"{tool_failure}; {publication_failure}" if tool_failure else publication_failure
        )
    artifacts.append(result_artifact)
    artifacts.extend(
        retain_measurement_artifacts(
            cast(dict[str, Any], arguments.measurements),
            arguments.measurement_results.parent,
            run_dir,
        )
    )

    appium_log = retained_artifact(
        "appium-log", "text/plain", cast(Path, arguments.appium_log), run_dir / "appium.log"
    )
    artifacts.append(appium_log)
    log_failures: list[str] = []
    try:
        driver_log_path = run_dir / "driver.log"
        driver_payload = platform_driver_log(arguments.platform, arguments.device_id)
        driver_log_path.write_bytes(
            driver_payload or b"No platform driver log messages captured.\n"
        )
        driver_log: dict[str, Any] = {
            "kind": "driver-log",
            "mimeType": "text/plain",
            "path": driver_log_path.name,
            "sizeBytes": driver_log_path.stat().st_size,
            "sha256": sha256_bytes(driver_log_path.read_bytes()),
        }
        artifacts.append(driver_log)
    except (OSError, subprocess.SubprocessError) as error:
        driver_log = {"unavailable": True, "reason": f"{type(error).__name__}: {error}"}
        log_failures.append(
            f"platform driver log collection failed: {type(error).__name__}: {error}"
        )

    try:
        device_payload = device_log(arguments.platform, arguments.device_id)
        device_log_path = run_dir / "device.log"
        device_log_path.write_bytes(device_payload or b"No device log messages captured.\n")
        device_log_record: dict[str, Any] = {
            "kind": "device-log",
            "mimeType": "text/plain",
            "path": device_log_path.name,
            "sizeBytes": device_log_path.stat().st_size,
            "sha256": sha256_bytes(device_log_path.read_bytes()),
        }
        artifacts.append(device_log_record)
    except (OSError, subprocess.SubprocessError) as error:
        device_log_record = {"unavailable": True, "reason": f"{type(error).__name__}: {error}"}
        log_failures.append(f"device log collection failed: {type(error).__name__}: {error}")
    log_failure = "; ".join(log_failures) or None

    amkernel_log_path = run_dir / "amkernel.log"
    amkernel_log_payload = "".join(
        cast(str, output["stderr"]) for output in execution_outputs
    ).encode()
    amkernel_log_path.write_bytes(
        sanitize_bytes(amkernel_log_payload) or b"No AMKernel stderr output.\n"
    )
    amkernel_log = {
        "kind": "amkernel-log",
        "mimeType": "text/plain",
        "path": amkernel_log_path.name,
        "sizeBytes": amkernel_log_path.stat().st_size,
        "sha256": sha256_bytes(amkernel_log_path.read_bytes()),
    }
    artifacts.append(amkernel_log)

    measurements = cast(dict[str, Any], arguments.measurements)
    measurement_failure = next(
        (
            f"measurement {identifier} did not pass"
            for identifier in MEASUREMENT_IDS
            if cast(dict[str, Any], measurements[identifier]).get("status") != "measured"
            or cast(dict[str, Any], measurements[identifier]).get("passed") is not True
        ),
        None,
    )
    if measurement_failure is None:
        measurement_failure = next(
            (
                f"resource plateau {process} did not pass"
                for process, decision in cast(
                    dict[str, dict[str, Any]], measurements["resourcePlateau"]
                ).items()
                if decision["passed"] is not True
            ),
            None,
        )
    device_usable, device_probe = device_observation(arguments.platform, arguments.device_id)
    workflow_cleanup = cast(dict[str, Any], workflow_result["cleanup"])
    remaining_resources: list[str] = []
    if not managed_processes_exited:
        remaining_resources.append(managed_process_observation)
    if not session_absent:
        remaining_resources.append(session_observation)
    cleanup_observation = "; ".join(
        [
            workflow_cleanup["observation"],
            managed_process_observation,
            session_observation,
            device_probe,
        ]
    )
    cleanup_completed = (
        workflow_cleanup["driverQuit"] == "observed"
        and workflow_cleanup["applicationStopped"] == "observed"
        and session_absent
        and managed_processes_exited
        and device_usable
    )
    scenario_failure = cast(dict[str, Any] | None, workflow_result.get("failure"))
    failure_message = (
        tool_failure
        or (cast(str, scenario_failure["message"]) if scenario_failure is not None else None)
        or log_failure
        or measurement_failure
        or (None if cleanup_completed else cleanup_observation)
    )
    failure_category = (
        "amkernel"
        if tool_failure is not None
        else "scenario"
        if scenario_failure is not None
        else "evidence"
        if log_failure is not None
        else "measurement"
        if measurement_failure is not None
        else "cleanup"
    )

    artifact_contract = cast(dict[str, Any], fixture["artifact"])
    environment_contract = cast(dict[str, Any], scenario["environmentContract"])
    observed_platform = cast(dict[str, Any], arguments.observed_platform)
    if arguments.platform == "android":
        platform_details = {
            "sdkRootLabel": "ANDROID_HOME",
            "apiLevel": observed_platform["apiLevel"],
            "abi": observed_platform["abi"],
            "systemImage": observed_platform["systemImage"],
            "deviceProfile": observed_platform["deviceProfile"],
        }
    else:
        platform_details = {
            field: observed_platform[field]
            for field in (
                "xcodeVersion",
                "xcodeBuild",
                "runtimeIdentifier",
                "runtimeVersion",
                "runtimeBuild",
                "deviceTypeIdentifier",
            )
        }
    wheel_size, wheel_digest = hash_file(arguments.amkernel_wheel)
    protocol_path = arguments.scenario.parent / "measurement-protocol.json"
    completed_at = utc_now()
    evidence: dict[str, Any] = {
        "schemaVersion": 1,
        "experimentId": "S3-mobile-appium",
        "runId": run_id,
        "startedAt": started_at,
        "completedAt": completed_at,
        "durationMs": max(0, round((time.monotonic() - run_clock) * 1000)),
        "outcome": "failed" if failure_message else "passed",
        "platform": arguments.platform,
        "preflight": {
            "classification": "ready",
            "checkedAt": started_at,
            "checks": arguments.preflight_checks,
        },
        "environment": {
            "host": {
                "os": host_platform.system(),
                "release": host_platform.release(),
                "architecture": host_platform.machine(),
            },
            "python": {
                "implementation": setup["runtime"]["implementation"],
                "version": setup["runtime"]["pythonVersion"],
            },
            "mcp": {
                "clientVersion": importlib.metadata.version("mcp"),
                "protocolVersion": mcp_protocol_version,
            },
            "amkernel": {
                "version": setup_result["amkernelVersion"],
                "revision": arguments.amkernel_revision,
                "wheel": {
                    "filename": arguments.amkernel_wheel.name,
                    "sizeBytes": wheel_size,
                    "sha256": wheel_digest,
                },
            },
            "nodeVersion": environment_contract["node"],
            "appium": {
                "serverVersion": server_version,
                "baseUrl": arguments.appium_server_url,
                "pythonClientVersion": setup_result["appiumPythonClientVersion"],
                "seleniumVersion": setup_result["seleniumVersion"],
                "driverName": environment_contract[arguments.platform]["driver"],
                "driverVersion": arguments.appium_driver_version,
            },
            "officialSkills": {
                "repository": "https://github.com/appium/skills",
                "commit": environment_contract["officialSkillsCommit"],
                "appiumPythonPath": "skills/appium-python",
            },
            "capabilities": {
                "platformName": "Android" if arguments.platform == "android" else "iOS",
                "automationName": "UiAutomator2" if arguments.platform == "android" else "XCUITest",
                "udid": arguments.device_id,
                "applicationId": application["id"],
                "noReset": True,
            },
        },
        "device": {
            "kind": arguments.device_kind,
            "id": arguments.device_id,
            "name": (
                observed_platform["deviceName"]
                if arguments.platform == "ios"
                else arguments.device_name
            ),
            "osVersion": observed_platform["osVersion"],
            "state": "online" if device_usable else "unavailable",
            "platformDetails": platform_details,
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
            "artifactName": artifact_contract["name"],
            "artifactSizeBytes": artifact_contract["sizeBytes"],
            "artifactSha256": artifact_contract["sha256"],
            "applicationId": application["id"],
        },
        "scenario": {
            "id": scenario["scenarioId"],
            "definitionSha256": sha256_bytes(scenario_bytes),
            "executionCount": 1,
        },
        "runState": {
            "kernelBefore": "not-started",
            "kernelAfter": "dead" if managed_processes_exited else workflow["kernelState"],
            "sessionBefore": "absent",
            "sessionAfter": "absent"
            if workflow_cleanup["sessionAbsent"] == "observed"
            else "unknown",
            "deviceBefore": "online",
            "deviceAfter": "online" if device_usable else "unavailable",
            "appBefore": "unknown",
            "appAfter": "not-running"
            if workflow_cleanup["applicationStopped"] == "observed"
            else "unknown",
        },
        "steps": workflow_result["steps"],
        "amkernel": {
            "tool": "python_exec",
            "calls": 3,
            "executionCounts": [output["executionCount"] for output in execution_outputs],
            "continuationVerified": continuation_verified,
            "kernelState": workflow["kernelState"],
            "outputs": [
                output_record(index, output)
                for index, output in enumerate(execution_outputs, start=1)
            ],
        },
        "artifacts": artifacts,
        "logs": {
            "appiumServer": appium_log,
            "platformDriver": driver_log,
            "device": device_log_record,
            "amkernel": amkernel_log,
        },
        "measurementProtocol": {
            "id": "amkernel-mobile-appium-measurement-v1",
            "definitionSha256": sha256_bytes(protocol_path.read_bytes()),
            "resultsProvenance": arguments.measurement_provenance,
        },
        "measurements": measurements,
        "cleanup": {
            "attempted": True,
            "completed": cleanup_completed,
            "driverQuit": workflow_cleanup["driverQuit"],
            "applicationStopped": workflow_cleanup["applicationStopped"],
            "sessionAbsent": "observed" if session_absent else "failed",
            "managedProcessesExited": "observed" if managed_processes_exited else "failed",
            "deviceUsable": "observed" if device_usable else "failed",
            "remainingExternalResources": remaining_resources,
            "observation": cleanup_observation,
        },
    }
    if failure_message:
        evidence["failure"] = {
            "category": failure_category,
            "message": failure_message,
            "agentObservation": failure_message,
            "kernelState": workflow["kernelState"],
            "sessionState": "absent" if session_absent else "present",
            "deviceState": "online" if device_usable else "unavailable",
            "serverState": "online" if session_absent else "unavailable",
            "recreationRequired": [] if cleanup_completed else ["session"],
            "recoverableEvidence": [artifact["path"] for artifact in artifacts],
            "cleanupAttempted": True,
            "cleanupObserved": cleanup_completed,
            "remainingExternalResources": remaining_resources,
            "lastCompletedStep": scenario_failure["lastCompletedStep"]
            if scenario_failure
            else (workflow_result["steps"][-1]["id"] if workflow_result["steps"] else None),
        }
    evidence = cast(dict[str, Any], scrub(evidence))
    schema = json.loads((arguments.scenario.parent / "evidence.schema.json").read_bytes())
    Draft202012Validator(schema).validate(evidence)
    evidence_path = run_dir / "evidence.json"
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    return cast(Path, evidence_path)


def main() -> int:
    arguments = parse_args()
    try:
        evidence_path = asyncio.run(run(arguments))
    except PreflightBlocked as error:
        arguments.output_dir.mkdir(parents=True, exist_ok=True)
        report_path = arguments.output_dir / "preflight.json"
        report_path.write_text(
            json.dumps(
                {
                    "classification": "blocked",
                    "checkedAt": utc_now(),
                    "platform": arguments.platform,
                    "checks": error.checks,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        print(report_path)
        return 2
    except Exception as error:
        arguments.output_dir.mkdir(parents=True, exist_ok=True)
        report_path = arguments.output_dir / "run-failure.json"
        report_path.write_text(
            json.dumps(
                {
                    "recordType": "pre-evidence-run-failure",
                    "recordedAt": utc_now(),
                    "platform": arguments.platform,
                    "category": "harness",
                    "message": f"{type(error).__name__}: {error}",
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        print(report_path)
        return 1
    print(evidence_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
