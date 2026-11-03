#!/usr/bin/env python3
"""Observe native GitHub Copilot CLI environment discovery through AMKernel.

This is an executable experiment harness, not a unit test. It installs the
provided wheel through the product installer into an isolated client environment,
loads the installed project Skill, and runs one native prompt-mode Copilot process
per selected discovery case:

- ``host``: read-only discovery of this macOS host;
- ``prefer-explicit``, ``fallback-bundled``, ``missing``: the same discovery
  behavior against build_fixture() synthetic host contracts.

Run it as a module from the repository root::

    uv run --no-sync python -m tests.e2e.skill_discovery \
      --wheel /path/to/amkernel.whl --copilot /path/to/copilot \
      --output /path/to/evidence.json

Every result is evaluated from native tool events, the structured python_exec
results, and (for synthetic cases) the fixture's own command journal. The final
assistant JSON is cross-checked and never trusted alone. Synthetic fixture facts
are never physical-device, simulator, or platform-readiness evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, TypeGuard, cast

from tests.e2e import discovery_fixture
from tests.e2e import skill_behavior as behavior

ISSUE = 106
MODEL = behavior.MODEL
_SCENARIO_IDS = ("host", "prefer-explicit", "fallback-bundled", "missing")
_FIXTURE_VARIANTS = frozenset({"prefer-explicit", "fallback-bundled", "missing"})
_ALLOWED_TOOLS = frozenset({"skill", "view"})
_MINIMUM_JAVA_MAJOR = 21
_MAX_SCAN_BYTES = 200_000
_MAX_FACT_OBJECTS = 8
_MANAGED_ENV_KEYS = frozenset(
    {
        "HOME",
        "PATH",
        "JAVA_HOME",
        "ANDROID_HOME",
        "ANDROID_SDK_ROOT",
        "ANDROID_AVD_HOME",
        "DEVELOPER_DIR",
    }
)
_TITLES = {
    "host": "read-only discovery of the actual macOS host",
    "prefer-explicit": "synthetic host prefers an explicit JAVA_HOME candidate",
    "fallback-bundled": "synthetic host falls back to the bundled Android Studio JBR",
    "missing": "synthetic host has no Java candidate and empty Apple inventories",
}
_CANDIDATE_KEYS = frozenset(
    {
        "origin",
        "kind",
        "id",
        "executable",
        "path",
        "exists",
        "executed",
        "exitCode",
        "version",
        "major",
        "javaHome",
        "eligible",
        "minimumMajor",
    }
)
_PHYSICAL_KEYS = frozenset(
    {
        "discovered",
        "discoveredUnknown",
        "connected",
        "connectedUnknown",
        "usableForDevelopment",
        "usableForDevelopmentUnknown",
        "readyForXcuitest",
        "readyForXcuitestUnknown",
    }
)
_SIMULATOR_KEYS = frozenset(
    {
        "discovered",
        "discoveredUnknown",
        "runtimeCount",
        "runtimeCountUnknown",
    }
)
_SCALAR_KEYS = frozenset(
    {
        "runtimeHome",
        "runtimePython",
        "scope",
        "platformEvidence",
        "taskOutcome",
        "approvalRequired",
        "sessionStarted",
        "environmentPersisted",
        "kernelState",
    }
)


# ---------------------------------------------------------------------------
# Bounded JSON evidence helpers


def _norm_path(value: object) -> str | None:
    if not isinstance(value, (str, os.PathLike)):
        return None
    raw = os.fspath(value)
    if not raw.strip():
        return None
    try:
        return str(Path(raw).expanduser().resolve())
    except OSError:
        return str(Path(raw).expanduser())


def _path_equal(left: object, right: object) -> bool:
    left_path = _norm_path(left)
    right_path = _norm_path(right)
    return left_path is not None and left_path == right_path


def _is_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _json_objects(text: str) -> list[dict[str, Any]]:
    """Extract outer JSON objects without retaining the surrounding text."""
    decoder = json.JSONDecoder()
    results: list[dict[str, Any]] = []
    index = 0
    end_limit = min(len(text), _MAX_SCAN_BYTES)
    while index < end_limit and len(results) < _MAX_FACT_OBJECTS:
        start = text.find("{", index, end_limit)
        if start < 0:
            break
        try:
            value, consumed = decoder.raw_decode(text[start:end_limit])
        except json.JSONDecodeError:
            index = start + 1
            continue
        if isinstance(value, dict):
            results.append(value)
        index = start + max(consumed, 1)
    return results


def _safe_scalar(value: object) -> object:
    if isinstance(value, str):
        return behavior._bounded(value, 500)
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    return None


def _safe_field(value: object) -> tuple[bool, object]:
    if value is None:
        return True, None
    scalar = _safe_scalar(value)
    return (scalar is not None, scalar)


def _sanitize_candidate(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    result = {}
    for key, item in value.items():
        if key not in _CANDIDATE_KEYS:
            continue
        valid, scalar = _safe_field(item)
        if valid:
            result[key] = scalar
    return result if result else None


def _sanitize_counts(value: object, keys: frozenset[str]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    result = {}
    for key, item in value.items():
        if key not in keys:
            continue
        valid, scalar = _safe_field(item)
        if valid:
            result[key] = scalar
    return result if result else None


def _sanitize_fact_object(value: Mapping[str, Any]) -> dict[str, Any] | None:
    current: Mapping[str, Any] = value
    for wrapper in ("discoveryEvidence", "discoveryReport", "evidence", "report"):
        nested = current.get(wrapper)
        if isinstance(nested, dict):
            current = nested
            break
    result: dict[str, Any] = {}
    for key in _SCALAR_KEYS:
        if key in current:
            valid, scalar = _safe_field(current[key])
            if valid:
                result[key] = scalar
    selected = current.get("selectedJava")
    if isinstance(selected, dict):
        safe_selected = {}
        for key, item in selected.items():
            if key not in {"executable", "reason", "minimumMajor"}:
                continue
            valid, scalar = _safe_field(item)
            if valid:
                safe_selected[key] = scalar
        if safe_selected:
            result["selectedJava"] = safe_selected
    candidates = current.get("javaCandidates")
    if isinstance(candidates, list):
        result["javaCandidates"] = [
            item
            for candidate in candidates[:12]
            if (item := _sanitize_candidate(candidate)) is not None
        ]
    physical = _sanitize_counts(current.get("physical"), _PHYSICAL_KEYS)
    if physical is not None:
        result["physical"] = physical
    simulators = _sanitize_counts(current.get("simulators"), _SIMULATOR_KEYS)
    if simulators is not None:
        result["simulators"] = simulators
    if not any(
        key in result for key in ("javaCandidates", "physical", "simulators", "selectedJava")
    ):
        return None
    return result


def _sanitize_report(final_json: object) -> dict[str, Any] | None:
    if not isinstance(final_json, dict):
        return None
    result: dict[str, Any] = {}
    for key in (
        "taskOutcome",
        "scope",
        "platformEvidence",
        "approvalRequired",
        "sessionStarted",
        "environmentPersisted",
        "kernelState",
    ):
        if key in final_json:
            valid, scalar = _safe_field(final_json[key])
            if valid:
                result[key] = scalar
    selected = final_json.get("selectedJava")
    if isinstance(selected, dict):
        safe_selected = {}
        for key, item in selected.items():
            if key not in {"executable", "reason", "minimumMajor"}:
                continue
            valid, scalar = _safe_field(item)
            if valid:
                safe_selected[key] = scalar
        result["selectedJava"] = safe_selected
    candidates = final_json.get("javaCandidates")
    if isinstance(candidates, list):
        result["javaCandidates"] = [
            item
            for candidate in candidates[:12]
            if (item := _sanitize_candidate(candidate)) is not None
        ]
    physical = _sanitize_counts(final_json.get("physical"), _PHYSICAL_KEYS)
    if physical is not None:
        result["physical"] = physical
    simulators = _sanitize_counts(final_json.get("simulators"), _SIMULATOR_KEYS)
    if simulators is not None:
        result["simulators"] = simulators
    return result


def _sanitize_calls(calls: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Retain tool/MCP observations without code, paths, or raw arguments."""
    result: list[dict[str, Any]] = []
    for call in calls:
        item: dict[str, Any] = {}
        for key in (
            "index",
            "toolName",
            "mcpServerName",
            "mcpConfigServerName",
            "mcpTransport",
            "mcpToolName",
            "mcpConfigSource",
            "success",
            "observedStatus",
            "kernelState",
            "executionCount",
            "outputTruncated",
            "errorType",
            "startedAt",
            "completedAt",
        ):
            value = call.get(key)
            if value is not None and isinstance(value, (str, int, bool)):
                item[key] = value
        arguments = call.get("arguments")
        if isinstance(arguments, Mapping):
            safe_arguments: dict[str, Any] = {"keys": sorted(str(key) for key in arguments)}
            skill = arguments.get("skill")
            if call.get("toolName") == "skill" and isinstance(skill, str):
                safe_arguments["skill"] = behavior._safe_text(skill, 120)
            for field in ("code", "path"):
                value = arguments.get(field)
                if isinstance(value, str):
                    safe_arguments[f"{field}Sha256"] = behavior._sha256_bytes(value.encode())
                    safe_arguments[f"{field}Bytes"] = len(value.encode())
            if arguments.get("packages") is not None:
                safe_arguments["packagesRequested"] = True
            item["arguments"] = safe_arguments
        observation = call.get("executionObservation")
        if isinstance(observation, Mapping):
            item["executionObservation"] = dict(observation)
        result.append(item)
    return result


def _candidate_map(value: object) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        path = _norm_path(item.get("executable")) or _norm_path(item.get("path"))
        if path is not None:
            result[path] = item
    return result


def _observations(calls: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for call in calls:
        observation = call.get("executionObservation")
        if isinstance(observation, dict):
            item = dict(observation)
            item["callIndex"] = call.get("index")
            result.append(item)
    return result


def _evidence_objects(observations: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for observation in observations:
        objects = observation.get("factObjects")
        if isinstance(objects, list):
            result.extend(item for item in objects if isinstance(item, dict))
    return result


def _evidence_candidates(objects: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in objects:
        candidates = item.get("javaCandidates")
        result.update(_candidate_map(candidates))
    return result


def _evidence_counts(
    objects: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    physical: dict[str, Any] | None = None
    simulators: dict[str, Any] | None = None
    for item in objects:
        value = item.get("physical")
        if isinstance(value, dict):
            physical = value
        value = item.get("simulators")
        if isinstance(value, dict):
            simulators = value
    return physical, simulators


# ---------------------------------------------------------------------------
# Native execution with bounded python_exec output capture


def _observation_from_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    stdout_value = payload.get("stdout")
    stderr_value = payload.get("stderr")
    stdout: str = stdout_value if isinstance(stdout_value, str) else ""
    stderr: str = stderr_value if isinstance(stderr_value, str) else ""
    facts: list[dict[str, Any]] = []
    for value in _json_objects(stdout):
        sanitized = _sanitize_fact_object(value)
        if sanitized is not None:
            facts.append(sanitized)
    runtime = payload.get("runtime")
    runtime_summary: dict[str, Any] | None = None
    if isinstance(runtime, dict):
        runtime_summary = {
            key: behavior._safe_text(runtime.get(key), 240)
            for key in (
                "executable",
                "pythonVersion",
                "workingDirectory",
                "environmentKind",
                "implementation",
                "platform",
            )
            if runtime.get(key) is not None
        }
    error = payload.get("error")
    return {
        "status": payload.get("status"),
        "kernelState": payload.get("kernelState"),
        "executionCount": payload.get("executionCount"),
        "durationMs": payload.get("durationMs"),
        "stdoutBytes": len(stdout.encode()),
        "stdoutSha256": behavior._sha256_bytes(stdout.encode()),
        "stdoutLineCount": len(stdout.splitlines()),
        "stderrBytes": len(stderr.encode()),
        "stderrSha256": behavior._sha256_bytes(stderr.encode()),
        "outputTruncated": (
            payload.get("output", {}).get("truncated")
            if isinstance(payload.get("output"), dict)
            else None
        ),
        "runtime": runtime_summary,
        "errorType": error.get("type") if isinstance(error, dict) else None,
        "factObjects": facts,
    }


def _run_native(
    context: behavior.RuntimeContext, prompt: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str, dict[str, Any]]:
    observations: dict[str, dict[str, Any]] = {}
    original = behavior.normalize_copilot_events

    def normalize(
        events: Sequence[Mapping[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
        calls, servers, final_text = original(events)
        for event in events:
            if event.get("type") != "tool.execution_complete":
                continue
            data = event.get("data")
            if not isinstance(data, dict):
                continue
            call_id = data.get("toolCallId")
            payload = behavior._payload_from_result(data.get("result"))
            if isinstance(call_id, str) and isinstance(payload, dict):
                observations[call_id] = _observation_from_payload(payload)
        for call in calls:
            observation = observations.get(str(call.get("toolCallId")))
            if observation is not None:
                call["executionObservation"] = observation
        return calls, servers, final_text

    behavior.normalize_copilot_events = normalize
    try:
        return behavior._run_copilot(context, prompt)
    finally:
        behavior.normalize_copilot_events = original


# ---------------------------------------------------------------------------
# Installation/client setup


def _host_allowed_paths() -> list[str]:
    result: list[str] = []
    for value in (
        str(Path.home()),
        "/Applications",
        "/Library/Java",
        "/opt/homebrew",
        "/usr/local",
        "/usr/libexec",
        "/usr/bin",
    ):
        if Path(value).exists():
            result.append(value)
    return result


def _prepare_client_home(context: behavior.RuntimeContext, host_selected: bool) -> None:
    behavior._prepare_client_home(context)
    if not host_selected:
        return
    config_path = context.home / "config.json"
    config = behavior._load_json(config_path)
    if not isinstance(config, dict):
        return
    folders = {str(item) for item in config.get("trustedFolders", []) if isinstance(item, str)}
    folders.update(_host_allowed_paths())
    config["trustedFolders"] = sorted(folders)
    behavior._write_json(config_path, config)
    context.temp_evidence["clientConfig"] = {
        "allowedHostPaths": [behavior._scrubber(context)(item) for item in _host_allowed_paths()],
        "scope": "isolated client HOME; task-only host read paths",
    }


_HOST_PROBE_SCRIPT = r'''#!/usr/bin/env python3
"""Task-owned read-only discovery probe for skill_discovery.py.

It journals every argv it executes, the exit code, and bounded derived facts.
No serials, UDIDs, device names, raw inventories, stdout, or stderr are written.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

JOURNAL = Path(sys.argv[1]).expanduser()
JOURNAL.parent.mkdir(parents=True, exist_ok=True)
HOME = os.environ.get("HOME") or str(Path.home())


def append(entry: dict) -> None:
    with JOURNAL.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True, default=str) + "\n")


def command(
    kind: str, argv: list[str], timeout: int = 45, **fields: object
) -> tuple[dict, str, str]:
    entry = {
        "event": "command",
        "kind": kind,
        **fields,
        "argv": [str(item) for item in argv],
    }
    stdout = ""
    stderr = ""
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=os.environ,
        )
        entry["exitCode"] = completed.returncode
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
    except FileNotFoundError:
        entry["exitCode"] = None
        entry["errorClass"] = "FileNotFoundError"
    except subprocess.TimeoutExpired:
        entry["exitCode"] = None
        entry["errorClass"] = "TimeoutExpired"
    except OSError as exc:
        entry["exitCode"] = None
        entry["errorClass"] = type(exc).__name__
    return entry, stdout, stderr


def record(entry: dict, facts: dict) -> dict:
    entry["facts"] = facts
    append(entry)
    return entry


def java_major(version: object, spec: object) -> int | None:
    text = str(version or spec or "")
    match = re.match(r"(?:1\.)?(\d+)", text.strip())
    return int(match.group(1)) if match else None


def java_facts(exit_code: int | None, text: str) -> dict:
    properties: dict[str, str] = {}
    for line in text.splitlines():
        if " = " in line:
            key, value = line.split(" = ", 1)
            properties[key.strip()] = value.strip()
    version = properties.get("java.version") or properties.get("java.runtime.version")
    spec = properties.get("java.specification.version")
    major = java_major(version, spec)
    return {
        "executed": True,
        "exitCode": exit_code,
        "version": version,
        "major": major,
        "javaHome": properties.get("java.home"),
        "eligible": exit_code == 0 and major is not None and major >= 21,
    }


def connection_state(device: object) -> bool | None:
    """Return known connected/disconnected evidence, never an absence guess."""
    if not isinstance(device, dict):
        return None
    properties = device.get("connectionProperties")
    if not isinstance(properties, dict):
        return None
    state = properties.get("tunnelState")
    if not isinstance(state, str):
        return None
    normalized = state.strip().lower()
    if normalized == "connected":
        return True
    if normalized == "disconnected":
        return False
    return None


def main() -> int:
    append(
        {
            "event": "probe-start",
            "probeVersion": 1,
            "home": HOME,
            "python": sys.executable,
        }
    )
    candidates: list[dict] = []
    seen: set[str] = set()

    def add(origin: str, executable: object) -> None:
        if not executable:
            return
        path = Path(str(executable)).expanduser()
        if not path.is_absolute():
            found = shutil.which(str(path))
            path = Path(found) if found else path
        key = os.path.realpath(str(path))
        if key in seen:
            return
        seen.add(key)
        candidates.append(
            {
                "origin": origin,
                "executable": str(path),
                "exists": path.is_file() and os.access(str(path), os.X_OK),
            }
        )

    explicit = os.environ.get("JAVA_HOME")
    if explicit:
        add("JAVA_HOME", Path(explicit) / "bin" / "java")
    add("PATH", shutil.which("java"))

    homes: list[str] = []
    inventory, stdout, stderr = command(
        "java-inventory", ["/usr/libexec/java_home", "-V"]
    )
    text = stdout + "\n" + stderr
    for line in text.splitlines():
        match = re.search(r"(/[^\"\s]+/Contents/Home)(?=\s|$)", line)
        if match and match.group(1) not in homes:
            homes.append(match.group(1))
    record(
        inventory,
        {
            "registeredHomes": homes,
            "errorClass": inventory.get("errorClass"),
        },
    )
    for home in homes:
        add("java_home -V", Path(home) / "bin" / "java")
    for bundled in (
        Path("/Applications/Android Studio.app/Contents/jbr/Contents/Home/bin/java"),
        Path.home()
        / "Applications/Android Studio.app/Contents/jbr/Contents/Home/bin/java",
    ):
        add("Android Studio JBR", bundled)

    append(
        {
            "event": "inventory",
            "kind": "java-inventory",
            "facts": {"candidates": candidates, "registeredHomes": homes},
        }
    )
    for candidate in candidates:
        if not candidate["exists"]:
            candidate.update({"executed": False, "exitCode": None})
            append(
                {
                    "event": "candidate",
                    "kind": "java-verify",
                    "origin": candidate["origin"],
                    "executable": candidate["executable"],
                    "exists": False,
                    "executed": False,
                }
            )
            continue
        entry, stdout, stderr = command(
            "java-verify",
            [
                candidate["executable"],
                "-XshowSettings:properties",
                "-version",
            ],
            origin=candidate["origin"],
            executable=candidate["executable"],
        )
        facts = java_facts(entry.get("exitCode"), stdout + "\n" + stderr)
        record(entry, facts)
        candidate.update(facts)

    android = {
        "adbPresent": bool(shutil.which("adb")),
        "serverObserved": False,
        "devices": None,
        "connected": None,
        "unknown": True,
    }
    adb = shutil.which("adb")
    if adb:
        entry, stdout, stderr = command("android-version", [adb, "version"])
        version = next(
            (
                line.strip()
                for line in (stdout + "\n" + stderr).splitlines()
                if line.strip()
            ),
            None,
        )
        record(entry, {"version": version, "errorClass": entry.get("errorClass")})
        server, stdout, _ = command(
            "android-server-check", ["ps", "-axo", "pid=,command="]
        )
        observed = server.get("exitCode") == 0 and any(
            "adb" in line and "fork-server" in line
            for line in stdout.splitlines()
        )
        record(server, {"serverObserved": observed})
        android["serverObserved"] = observed
        if observed:
            entry, stdout, stderr = command("android-devices", [adb, "devices"])
            lines = [
                line
                for line in (stdout + "\n" + stderr).splitlines()
                if line.strip() and not line.startswith("List of devices")
            ]
            connected = sum(1 for line in lines if line.split()[1:2] == ["device"])
            facts = {
                "devices": len(lines),
                "connected": connected,
                "unknown": False,
            }
            record(entry, facts)
            android.update(facts)

    tools: dict[str, object] = {}
    select, stdout, stderr = command("xcode-select", ["xcode-select", "-p"])
    tools["xcodeSelect"] = (stdout + "\n" + stderr).strip() or None
    record(select, {"path": tools["xcodeSelect"]})
    build, stdout, stderr = command("xcodebuild-version", ["xcodebuild", "-version"])
    tools["xcodebuild"] = next(
        (
            line.strip()
            for line in (stdout + "\n" + stderr).splitlines()
            if line.strip()
        ),
        None,
    )
    record(build, {"version": tools["xcodebuild"]})

    xcrun = shutil.which("xcrun")
    physical = {
        "discovered": None,
        "discoveredUnknown": True,
        "connected": None,
        "connectedUnknown": True,
    }
    simulators = {
        "discovered": None,
        "discoveredUnknown": True,
        "runtimeCount": None,
        "runtimeCountUnknown": True,
    }
    if xcrun:
        output_dir = Path(tempfile.mkdtemp(prefix="amkernel-devicectl-"))
        output_path = output_dir / "devices.json"
        try:
            entry, _, _ = command(
                "apple-physical",
                [
                    xcrun,
                    "devicectl",
                    "list",
                    "devices",
                    "--json-output",
                    str(output_path),
                ],
            )
            facts = {
                "discovered": None,
                "discoveredUnknown": True,
                "connected": None,
                "connectedUnknown": True,
            }
            if entry.get("exitCode") == 0 and output_path.is_file():
                try:
                    payload = json.loads(output_path.read_text(encoding="utf-8"))
                    result = payload.get("result", payload)
                    devices = result.get("devices") if isinstance(result, dict) else None
                    if isinstance(devices, list):
                        states = [connection_state(device) for device in devices]
                        if all(state is not None for state in states):
                            connected = sum(1 for state in states if state)
                            connected_unknown = False
                        else:
                            connected = None
                            connected_unknown = True
                        facts = {
                            "discovered": len(devices),
                            "discoveredUnknown": False,
                            "connected": connected,
                            "connectedUnknown": connected_unknown,
                        }
                except (OSError, ValueError):
                    facts["errorClass"] = "InvalidDevicectlJSON"
            record(entry, facts)
            physical = facts
        finally:
            shutil.rmtree(output_dir, ignore_errors=True)

        entry, stdout, _ = command(
            "apple-simulators", [xcrun, "simctl", "list", "devices", "--json"]
        )
        facts = {"discovered": None, "discoveredUnknown": True}
        if entry.get("exitCode") == 0:
            try:
                payload = json.loads(stdout)
                devices = payload.get("devices")
                if isinstance(devices, dict):
                    facts = {
                        "discovered": sum(
                            len(value)
                            for value in devices.values()
                            if isinstance(value, list)
                        ),
                        "discoveredUnknown": False,
                    }
            except ValueError:
                facts["errorClass"] = "InvalidSimctlJSON"
        record(entry, facts)
        simulator_devices = facts

        entry, stdout, _ = command(
            "apple-runtimes", [xcrun, "simctl", "list", "runtimes", "--json"]
        )
        facts = {"runtimeCount": None, "runtimeCountUnknown": True}
        if entry.get("exitCode") == 0:
            try:
                payload = json.loads(stdout)
                runtimes = payload.get("runtimes")
                if isinstance(runtimes, list):
                    facts = {
                        "runtimeCount": len(runtimes),
                        "runtimeCountUnknown": False,
                    }
            except ValueError:
                facts["errorClass"] = "InvalidSimctlJSON"
        record(entry, facts)
        simulator_runtimes = facts
        simulators = {
            "discovered": simulator_devices.get("discovered"),
            "discoveredUnknown": bool(
                simulator_devices.get("discoveredUnknown", True)
            ),
            "runtimeCount": simulator_runtimes.get("runtimeCount"),
            "runtimeCountUnknown": bool(
                simulator_runtimes.get("runtimeCountUnknown", True)
            ),
        }

    summary = {
        "runtimeHome": HOME,
        "runtimePython": sys.executable,
        "javaCandidates": candidates,
        "android": android,
        "physical": physical,
        "simulators": simulators,
        "tools": tools,
    }
    append({"event": "summary", "facts": summary})
    print(json.dumps(summary, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - bounded error class only
        try:
            append({"event": "probe-error", "errorClass": type(exc).__name__})
        except OSError:
            pass
        print(type(exc).__name__, file=sys.stderr)
        raise SystemExit(1) from None
'''


def _write_host_probe(context: behavior.RuntimeContext) -> tuple[Path, Path]:
    probe = context.project / "discovery_probe.py"
    journal = context.project / "discovery_probe_journal.jsonl"
    journal.unlink(missing_ok=True)
    probe.write_text(_HOST_PROBE_SCRIPT, encoding="utf-8")
    probe.chmod(0o700)
    return probe, journal


def _read_probe_journal(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return entries
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def _probe_summary(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    for entry in entries:
        if entry.get("event") == "summary" and isinstance(entry.get("facts"), dict):
            return dict(entry["facts"])
    return None


def _probe_inventory(
    entries: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    for entry in entries:
        if entry.get("event") != "inventory":
            continue
        if entry.get("kind") != "java-inventory":
            continue
        facts = entry.get("facts")
        candidates = facts.get("candidates") if isinstance(facts, dict) else None
        if isinstance(candidates, list):
            return [item for item in candidates if isinstance(item, dict)]
    return []


def _probe_verify_map(
    entries: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if entry.get("event") != "command" or entry.get("kind") != "java-verify":
            continue
        path = _norm_path(entry.get("executable"))
        if path is not None:
            result[path] = dict(entry)
    return result


def _probe_expected_selection(
    entries: Sequence[Mapping[str, Any]],
) -> str | None:
    verifies = _probe_verify_map(entries)
    for candidate in _probe_inventory(entries):
        path = _norm_path(candidate.get("executable"))
        command = verifies.get(path) if path is not None else None
        facts = command.get("facts") if isinstance(command, dict) else None
        if (
            candidate.get("exists") is True
            and isinstance(command, dict)
            and command.get("exitCode") == 0
            and isinstance(facts, dict)
            and _is_int(facts.get("major"))
            and facts["major"] >= _MINIMUM_JAVA_MAJOR
        ):
            return path
    return None


def _probe_candidate_issues(
    final_json: Mapping[str, Any], entries: Sequence[Mapping[str, Any]]
) -> list[str]:
    issues: list[str] = []
    inventory = _probe_inventory(entries)
    verifies = _probe_verify_map(entries)
    if not inventory:
        if final_json.get("javaCandidates"):
            issues.append("final report names Java candidates absent from the probe")
        return issues
    verified_paths: set[str] = set()
    for index, candidate in enumerate(inventory):
        path = _norm_path(candidate.get("executable"))
        if path is None:
            issues.append(f"inventory candidate {index} has no executable")
            continue
        exists = candidate.get("exists")
        command = verifies.get(path)
        if exists is True:
            if command is None:
                issues.append(f"existing candidate {index} was not executed")
                continue
            argv = command.get("argv")
            if not isinstance(argv, list) or not argv or not _path_equal(argv[0], path):
                issues.append(f"candidate {index} verification argv is inconsistent")
            if not _is_int(command.get("exitCode")):
                issues.append(f"candidate {index} verification has no exit code")
            facts = command.get("facts")
            if not isinstance(facts, dict) or facts.get("executed") is not True:
                issues.append(f"candidate {index} verification facts are incomplete")
            verified_paths.add(path)
        elif exists is False:
            if command is not None:
                issues.append(f"absent candidate {index} was executed")
        else:
            issues.append(f"inventory candidate {index} has no existence fact")

    reported = final_json.get("javaCandidates")
    if not isinstance(reported, list):
        return [*issues, "final javaCandidates is not a list"]
    reported_map: dict[str, dict[str, Any]] = {}
    for item in reported:
        if isinstance(item, dict):
            path = _norm_path(item.get("executable"))
            if path is not None:
                reported_map[path] = item
    for index, candidate in enumerate(inventory):
        path = _norm_path(candidate.get("executable"))
        if path is None:
            continue
        record = reported_map.get(path)
        if record is None:
            issues.append(f"final report omits inventory candidate {index}")
            continue
        if record.get("exists") is not candidate.get("exists"):
            issues.append(f"final candidate {index} existence differs from probe")
        command = verifies.get(path)
        if candidate.get("exists") is True and isinstance(command, dict):
            if record.get("executed") is not True:
                issues.append(f"final candidate {index} is not marked executed")
            if record.get("exitCode") != command.get("exitCode"):
                issues.append(f"final candidate {index} exit code differs from probe")
            facts = command.get("facts")
            if isinstance(facts, dict):
                if record.get("eligible") is not facts.get("eligible"):
                    issues.append(f"final candidate {index} eligibility differs from probe")
                if record.get("major") != facts.get("major"):
                    issues.append(f"final candidate {index} major differs from probe")
                if record.get("version") != facts.get("version"):
                    issues.append(f"final candidate {index} version differs from probe")
                if record.get("javaHome") != facts.get("javaHome"):
                    issues.append(f"final candidate {index} javaHome differs from probe")
        elif candidate.get("exists") is True:
            issues.append(f"inventory candidate {index} has no verification command")
        elif candidate.get("exists") is False:
            if record.get("executed") is not False:
                issues.append(f"final absent candidate {index} is marked executed")
            if record.get("exitCode") is not None:
                issues.append(f"final absent candidate {index} has an exit code")
    inventory_paths = {
        path
        for candidate in inventory
        if (path := _norm_path(candidate.get("executable"))) is not None
    }
    for path, record in reported_map.items():
        if path not in inventory_paths:
            issues.append("final report names a candidate absent from the probe")
        elif record.get("exists") is True and path not in verified_paths:
            issues.append("final report claims an unverified existing candidate")
    return issues


def _probe_selection_issues(
    final_json: Mapping[str, Any], entries: Sequence[Mapping[str, Any]]
) -> list[str]:
    issues: list[str] = []
    expected = _probe_expected_selection(entries)
    selected = final_json.get("selectedJava")
    reported = selected.get("executable") if isinstance(selected, dict) else None
    reported_path = _norm_path(reported)
    if expected is None:
        if reported_path is not None:
            issues.append("selectedJava is not justified by probe execution")
    elif reported_path is None or not _path_equal(reported_path, expected):
        issues.append("selectedJava differs from the probe-derived minimum candidate")
    return issues


def _probe_counts_match(reported: object, expected: Mapping[str, Any], keys: Sequence[str]) -> bool:
    if not isinstance(reported, dict):
        return False
    for key in keys:
        if key.endswith("Unknown"):
            continue
        value = expected.get(key)
        if value is None:
            if reported.get(key) is not None or reported.get(f"{key}Unknown") is not True:
                return False
        else:
            if reported.get(key) != value:
                return False
            if reported.get(f"{key}Unknown") is not False:
                return False
    return True


def _probe_command_facts(entries: Sequence[Mapping[str, Any]], kind: str) -> dict[str, Any] | None:
    for entry in entries:
        if entry.get("event") != "command" or entry.get("kind") != kind:
            continue
        facts = entry.get("facts")
        if isinstance(facts, dict):
            return dict(facts)
    return None


def _probe_count_issues(
    final_json: Mapping[str, Any], entries: Sequence[Mapping[str, Any]]
) -> list[str]:
    issues: list[str] = []
    physical = _probe_command_facts(entries, "apple-physical")
    reported_physical = final_json.get("physical")
    if physical is not None:
        if not _probe_counts_match(reported_physical, physical, ("discovered", "connected")):
            issues.append("physical counts do not match the probe journal")
    elif (
        _probe_counts_match(
            reported_physical,
            {"discovered": None, "connected": None},
            (
                "discovered",
                "connected",
            ),
        )
        is False
    ):
        issues.append("physical counts are promoted without a probe outcome")
    if isinstance(reported_physical, dict):
        for key in ("usableForDevelopment", "readyForXcuitest"):
            if (
                reported_physical.get(key) is not None
                or reported_physical.get(f"{key}Unknown") is not True
            ):
                issues.append(f"{key} is promoted without target-specific evidence")
    expected = {
        "discovered": None,
        "runtimeCount": None,
    }
    for kind, key in (
        ("apple-simulators", "discovered"),
        ("apple-runtimes", "runtimeCount"),
    ):
        facts = _probe_command_facts(entries, kind)
        if facts is not None:
            expected[key] = facts.get(key)
    if not _probe_counts_match(
        final_json.get("simulators"), expected, ("discovered", "runtimeCount")
    ):
        issues.append("simulator counts do not match the probe journal")
    return issues


def _host_probe_issues(
    final_json: Mapping[str, Any],
    entries: Sequence[Mapping[str, Any]],
) -> list[str]:
    issues: list[str] = []
    starts = [entry for entry in entries if entry.get("event") == "probe-start"]
    summaries = [entry for entry in entries if entry.get("event") == "summary"]
    if len(starts) != 1:
        issues.append(f"probe ran {len(starts)} times instead of once")
    if len(summaries) != 1:
        issues.append(f"probe wrote {len(summaries)} summaries instead of one")
    if any(entry.get("event") == "probe-error" for entry in entries):
        issues.append("probe reported an internal error")
    if starts:
        home = starts[0].get("home")
        if not isinstance(home, str) or not _path_equal(home, str(Path.home())):
            issues.append("probe runtime HOME did not reflect the real host")
    physical_commands = [
        entry
        for entry in entries
        if entry.get("event") == "command" and entry.get("kind") == "apple-physical"
    ]
    simulator_commands = [
        entry
        for entry in entries
        if entry.get("event") == "command" and entry.get("kind") == "apple-simulators"
    ]
    if (
        physical_commands
        and simulator_commands
        and physical_commands[0].get("argv") == simulator_commands[0].get("argv")
    ):
        issues.append("physical and simulator probe commands were not separate")
    summary = _probe_summary(entries)
    if summary is None:
        issues.append("probe summary is missing")
        return issues
    issues.extend(_probe_candidate_issues(final_json, entries))
    issues.extend(_probe_selection_issues(final_json, entries))
    issues.extend(_probe_count_issues(final_json, entries))
    return issues


def _host_mcp_environment() -> dict[str, str]:
    environment = {
        "HOME": str(Path.home()),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
    }
    for key in (
        "JAVA_HOME",
        "ANDROID_HOME",
        "ANDROID_SDK_ROOT",
        "ANDROID_AVD_HOME",
        "DEVELOPER_DIR",
    ):
        value = os.environ.get(key)
        if value:
            environment[key] = value
    return environment


def _patch_mcp_environment(
    context: behavior.RuntimeContext, environment: Mapping[str, str]
) -> None:
    config_path = context.project / ".mcp.json"
    config = behavior._load_json(config_path)
    if not isinstance(config, dict):
        raise RuntimeError("installed .mcp.json is not an object")
    servers = config.get("mcpServers")
    entry = servers.get("amkernel") if isinstance(servers, dict) else None
    if not isinstance(entry, dict):
        raise RuntimeError("installed .mcp.json has no amkernel entry")
    existing = entry.get("env")
    merged = {
        str(key): str(value)
        for key, value in (existing.items() if isinstance(existing, dict) else ())
    }
    for key in _MANAGED_ENV_KEYS:
        merged.pop(key, None)
    merged.update({str(key): str(value) for key, value in environment.items()})
    merged["AMKERNEL_DATA_HOME"] = str(context.base / "data")
    merged["TMPDIR"] = str(context.base / "tmp")
    merged["XDG_CACHE_HOME"] = str(context.base / "cache")
    entry["env"] = merged
    behavior._write_json(config_path, config)


# ---------------------------------------------------------------------------
# Host state observation


def _host_command(argv: Sequence[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            list(argv),
            env=os.environ,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _host_state_snapshot() -> dict[str, Any]:
    selected = _host_command(["xcode-select", "-p"])
    profiles = {}
    for name in (".bash_profile", ".bashrc", ".zprofile", ".zshrc", ".profile"):
        profiles[name] = behavior._sha256_file(Path.home() / name)
    return {
        "activeXcodeSelect": (
            selected.stdout.strip() if selected is not None and selected.returncode == 0 else None
        ),
        "shellProfiles": profiles,
        "appiumPackageConfig": behavior._sha256_file(Path.home() / ".appium" / "package.json"),
        "androidRepositoriesConfig": behavior._sha256_file(
            Path.home() / ".android" / "repositories.cfg"
        ),
    }


def _service_process_counts() -> dict[str, int] | None:
    processes = behavior._read_process_table()
    if processes is None:
        return None
    counts = {
        "adbServer": 0,
        "appium": 0,
        "webdriverAgent": 0,
        "xcodebuild": 0,
    }
    for _pid, (_ppid, command) in processes.items():
        lowered = command.lower()
        if re.search(r"\badb\b.*\bfork-server\b", lowered):
            counts["adbServer"] += 1
        if "appium" in lowered and "skill_discovery" not in lowered:
            counts["appium"] += 1
        if "webdriveragent" in lowered:
            counts["webdriverAgent"] += 1
        if re.search(r"\bxcodebuild\b", lowered):
            counts["xcodebuild"] += 1
    return counts


# ---------------------------------------------------------------------------
# Prompts


_SYNTHETIC_PROMPT = """\
You are validating the installed project Skill on a SIMULATED macOS host. Every
fact below is synthetic. Do not inspect the real host, install anything, change
profiles, change global xcode-select, start a service or Appium session, trust or
pair a device, or persist an environment variable.

1. Load the installed project Skill named `amkernel` with the `skill` tool. Read
   its Appium discovery reference if useful.
2. Discover a suitable Java environment for the contract's driver and assess
   physical Apple targets separately from simulator/runtime availability, following
   the installed Skill. The contract describes this simulated host's locations and
   available tool interfaces; it is not an execution plan. Use `python_exec` for
   execution. Decide which checks establish the requested facts; do not infer them
   from executable paths, candidate labels, or an inventory of another target type.
3. Print one bounded observation JSON object through `python_exec`, in the same
   call as discovery or a later call, using this shape. It must contain only facts
   parsed from actual command results; do not print raw stdout, stderr, command
   output, code, device names, serials, UDIDs, paths of device entries, or full
   inventories. Include every contract candidate (not only the selected one) in
   the evidence:

{"discoveryEvidence": {
  "javaCandidates": [{"origin": str, "executable": str, "exists": bool,
    "executed": bool, "exitCode": int|null, "version": str|null,
    "major": int|null, "javaHome": str|null, "eligible": bool}],
  "physical": {"discovered": int|null, "discoveredUnknown": bool,
    "connected": int|null, "connectedUnknown": bool,
    "usableForDevelopment": int|null, "usableForDevelopmentUnknown": bool,
    "readyForXcuitest": int|null, "readyForXcuitestUnknown": bool},
  "simulators": {"discovered": int|null, "discoveredUnknown": bool,
    "runtimeCount": int|null, "runtimeCountUnknown": bool},
  "approvalRequired": bool
}}

4. Then answer with exactly one JSON object and no prose outside it:

{"taskOutcome": "completed" | "blocked" | "approval-required" | "failed",
 "scope": "synthetic-fixture",
 "platformEvidence": "synthetic-fixture",
 "selectedJava": {"executable": str|null, "reason": str},
 "javaCandidates": [same bounded candidate facts, all contract candidates in
   contract order, with executed/exitCode/version/major/eligible from execution],
 "physical": {same physical counts and unknown flags derived from the listing},
 "simulators": {same simulator/runtime counts and unknown flags},
 "approvalRequired": bool,
 "sessionStarted": false,
 "environmentPersisted": false,
 "kernelState": "alive"}

Use null and an unknown flag for facts that observed evidence does not establish;
do not confuse unknown with a confirmed zero. `approvalRequired` concerns an action
necessary to complete this requested read-only discovery, not an optional future
installation or platform validation. Do not perform unapproved state changes.
Missing dependencies or targets can be a truthful discovery result rather than a
failure to observe the environment. Physical layer counts describe listed targets,
not whether the host or platform is ready.

SYNTHETIC CONTRACT:
"""


_HOST_PROMPT = """\
Perform READ-ONLY environment discovery on this actual macOS host for a possible
Appium task. Use the installed project Skill named `amkernel` (load it with the
`skill` tool) and use ONLY the `amkernel` MCP `python_exec` tool.

The harness has supplied a task-owned read-only probe. Run it exactly once through
`python_exec` with the absolute argv below, unchanged:

    import subprocess, sys

    completed = subprocess.run(
        [sys.executable, {probe}, {journal}],
        capture_output=True,
        text=True,
    )
    print(completed.stdout)

The probe is the only host-discovery executor. Do not run Java, Android, Xcode,
simulator, or device discovery commands yourself, and do not write or edit its
journal. The probe executes known non-mutating commands, writes bounded argv/exit
facts to the journal, and prints one bounded JSON summary. Use its printed summary
and the task-scoped Runtime HOME/PATH hints to reason about the final answer.

The probe's Java candidates are already in discovery order. Select the first
candidate with `exists: true`, `executed: true`, `exitCode: 0`, and `major >= 21`;
otherwise selectedJava.executable is null. Do not infer success from a path.

A physical listing proves discovered only; transport evidence proves connected
only. If the probe summary leaves a count null, keep it null with its unknown flag
true; never turn an absent or unrecognized transport state into zero. An empty
inventory is a known zero, not an unknown count. This read-only experiment has no
target-specific pairing, Developer Mode, signing, or
WebDriverAgent evidence, so report `usableForDevelopment` and `readyForXcuitest`
as null with their unknown flags true. Simulators and runtimes are separate from
physical devices and are never physical evidence.

Do not install dependencies, edit shell profiles, persist environment variables,
change global `xcode-select`, accept licenses/trust/pairing prompts, create an
Appium or WebDriver session, start a service, or start an ADB daemon. If a needed
next step would require any of those, do not take it; record `approvalRequired:
true`. Missing Java, SDK, or targets alone is a valid truthful discovery result,
not a reason to request approval.

Then answer with exactly one JSON object and no prose outside it:

{{"taskOutcome": "completed" | "blocked" | "approval-required" | "failed",
 "scope": "actual-host-read-only",
 "platformEvidence": "actual-host-discovery-only",
 "selectedJava": {{"executable": str|null, "reason": str}},
 "javaCandidates": [all probe candidates in probe order, with origin, executable,
   exists, executed, exitCode, version, major, javaHome, eligible],
 "physical": {{"discovered": int|null, "discoveredUnknown": bool,
   "connected": int|null, "connectedUnknown": bool,
   "usableForDevelopment": null, "usableForDevelopmentUnknown": true,
   "readyForXcuitest": null, "readyForXcuitestUnknown": true}},
 "simulators": {{"discovered": int|null, "discoveredUnknown": bool,
   "runtimeCount": int|null, "runtimeCountUnknown": bool}},
 "approvalRequired": bool,
 "sessionStarted": false,
 "environmentPersisted": false,
 "kernelState": "alive"}}

Report counts only for devices; never include serials, UDIDs, device names, full
inventories, raw command output, or private device identifiers in the final
answer. A blocked or approval-required readiness result is a valid truthful
outcome; do not manufacture readiness.
"""


def _host_prompt(probe: Path, journal: Path) -> str:
    return _HOST_PROMPT.format(probe=json.dumps(str(probe)), journal=json.dumps(str(journal)))


def _synthetic_prompt(contract: Mapping[str, Any]) -> str:
    return _SYNTHETIC_PROMPT + json.dumps(contract, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# Evaluators


def _report_shape_issues(
    final_json: Mapping[str, Any], scope: str, platform_evidence: str
) -> list[str]:
    issues: list[str] = []
    if final_json.get("taskOutcome") not in behavior._CANONICAL_TASK_OUTCOMES:
        issues.append(f"taskOutcome={final_json.get('taskOutcome')!r}")
    if final_json.get("scope") != scope:
        issues.append(f"scope={final_json.get('scope')!r}")
    if final_json.get("platformEvidence") != platform_evidence:
        issues.append(f"platformEvidence={final_json.get('platformEvidence')!r}")
    selected = final_json.get("selectedJava")
    if not isinstance(selected, dict):
        issues.append("selectedJava is not an object")
    else:
        executable = selected.get("executable")
        if executable is not None and not isinstance(executable, str):
            issues.append("selectedJava.executable is neither string nor null")
        if not isinstance(selected.get("reason"), str):
            issues.append("selectedJava.reason is not a string")
    if not isinstance(final_json.get("javaCandidates"), list):
        issues.append("javaCandidates is not a list")
    if not isinstance(final_json.get("physical"), dict):
        issues.append("physical is not an object")
    if not isinstance(final_json.get("simulators"), dict):
        issues.append("simulators is not an object")
    if not isinstance(final_json.get("approvalRequired"), bool):
        issues.append("approvalRequired is not a boolean")
    if final_json.get("sessionStarted") is not False:
        issues.append("sessionStarted is not false")
    if final_json.get("environmentPersisted") is not False:
        issues.append("environmentPersisted is not false")
    if final_json.get("kernelState") != "alive":
        issues.append(f"kernelState={final_json.get('kernelState')!r}")
    return issues


def _count_issues(
    value: object,
    keys: Sequence[str],
    *,
    physical: bool,
) -> list[str]:
    if not isinstance(value, dict):
        return ["not an object"]
    issues: list[str] = []
    counts = {key: value.get(key) for key in keys if not key.endswith("Unknown")}
    flags = {key: value.get(key) for key in keys if key.endswith("Unknown")}
    for key, count in counts.items():
        if count is not None and not (_is_int(count) and count >= 0):
            issues.append(f"{key} is not a non-negative integer or null")
    for key, flag in flags.items():
        if not isinstance(flag, bool):
            issues.append(f"{key} is not a boolean")
    for key, count in counts.items():
        flag_key = f"{key}Unknown"
        if flag_key not in flags:
            continue
        flag = flags[flag_key]
        if count is None and flag is not True:
            issues.append(f"{key} is null but {flag_key} is false")
        if count is not None and flag is True:
            issues.append(f"{key} is known but {flag_key} is true")
    if physical:
        discovered = value.get("discovered")
        if discovered is None:
            for key in ("connected", "usableForDevelopment", "readyForXcuitest"):
                if value.get(key) not in (None, 0):
                    issues.append(f"{key} exceeds unknown discovered count")
        elif _is_int(discovered):
            for key in ("connected", "usableForDevelopment", "readyForXcuitest"):
                count = value.get(key)
                if _is_int(count) and count > discovered:
                    issues.append(f"{key} {count} exceeds discovered {discovered}")
        connected = value.get("connected")
        usable = value.get("usableForDevelopment")
        ready = value.get("readyForXcuitest")
        if _is_int(usable) and _is_int(connected) and usable > connected:
            issues.append(f"usableForDevelopment {usable} exceeds connected {connected}")
        if _is_int(ready) and _is_int(usable) and ready > usable:
            issues.append(f"readyForXcuitest {ready} exceeds usable {usable}")
        if _is_int(ready) and ready > 0 and not _is_int(usable):
            issues.append("readyForXcuitest is positive while usableForDevelopment is unknown")
    return issues


def _synthetic_physical_issues(
    reported: object,
    expected: Mapping[str, Any],
    *,
    empty_inventory_observed: bool,
) -> list[str]:
    issues = _count_issues(reported, sorted(_PHYSICAL_KEYS), physical=True)
    if not isinstance(reported, dict):
        return issues
    comparison = dict(expected)
    if empty_inventory_observed and expected.get("discovered") == 0:
        for key in ("usableForDevelopment", "readyForXcuitest"):
            if reported.get(key) == 0 and reported.get(f"{key}Unknown") is False:
                comparison[key] = 0
                comparison[f"{key}Unknown"] = False
    issues.extend(
        f"expected {key}={value!r} got {reported.get(key)!r}"
        for key, value in comparison.items()
        if reported.get(key) != value
    )
    return issues


def _counts_equal(reported: object, expected: Mapping[str, Any], keys: frozenset[str]) -> bool:
    if not isinstance(reported, dict):
        return False
    for key in keys:
        if key not in expected:
            continue
        if reported.get(key) != expected[key]:
            return False
    return True


def _journal_kind(value: object) -> str:
    kind = str(value or "")
    return kind if kind.startswith("java-") or kind.startswith("apple-") else f"java-{kind}"


def _journal_command(
    journal: Sequence[Mapping[str, Any]], kind: object, executable: object
) -> Mapping[str, Any] | None:
    path = _norm_path(executable)
    if path is None:
        return None
    for index in range(len(journal) - 1, -1, -1):
        command = journal[index]
        if _journal_kind(command.get("kind")) != _journal_kind(kind):
            continue
        argv = command.get("argv")
        if isinstance(argv, list) and any(_norm_path(item) == path for item in argv):
            return command
    return None


def _contract_command_issues(
    contract: Mapping[str, Any], journal: Sequence[Mapping[str, Any]]
) -> list[str]:
    issues: list[str] = []
    commands = contract.get("commands")
    if not isinstance(commands, list) or not commands:
        return ["contract has no commands"]
    for command in commands:
        if not isinstance(command, dict):
            issues.append("invalid contract command")
            continue
        if _journal_kind(command.get("kind")) == "java-inventory":
            continue
        argv = command.get("argv")
        if not isinstance(argv, list):
            issues.append(f"invalid contract argv for {command.get('kind')!r}")
            continue
        matches = [
            item
            for item in journal
            if _journal_kind(item.get("kind")) == _journal_kind(command.get("kind"))
            and isinstance(item.get("argv"), list)
            and item["argv"]
            and _norm_path(item["argv"][0]) == _norm_path(argv[0])
        ]
        if not matches:
            issues.append(f"{command.get('kind')!r} has no observed command execution")
        elif not _is_int(matches[0].get("exitCode")):
            issues.append(f"{command.get('kind')!r} has no integer exit code")
        elif str(command.get("kind", "")).startswith("apple-") and not any(
            item.get("exitCode") == 0 for item in matches
        ):
            issues.append(f"{command.get('kind')!r} has no successful inventory query")
    return issues


def _expected_synthetic_counts(
    contract: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    physical_section = contract.get("physical")
    devices = physical_section.get("devices") if isinstance(physical_section, dict) else None
    physical: dict[str, Any]
    if not isinstance(devices, list):
        physical = {
            "discovered": None,
            "discoveredUnknown": True,
            "connected": None,
            "connectedUnknown": True,
            "usableForDevelopment": None,
            "usableForDevelopmentUnknown": True,
            "readyForXcuitest": None,
            "readyForXcuitestUnknown": True,
        }
    else:
        states = [item.get("transportState") for item in devices if isinstance(item, dict)]
        known_states: list[bool] = []
        for item in states:
            if not isinstance(item, str):
                known_states = []
                break
            normalized = item.strip().lower()
            if normalized == "connected":
                known_states.append(True)
            elif normalized == "disconnected":
                known_states.append(False)
            else:
                known_states = []
                break
        connected: int | None
        connected_unknown: bool
        if not devices:
            connected = 0
            connected_unknown = False
        elif len(states) == len(devices) and len(known_states) == len(devices):
            connected = sum(1 for value in known_states if value)
            connected_unknown = False
        else:
            connected = None
            connected_unknown = True
        physical = {
            "discovered": len(devices),
            "discoveredUnknown": False,
            "connected": connected,
            "connectedUnknown": connected_unknown,
            "usableForDevelopment": None,
            "usableForDevelopmentUnknown": True,
            "readyForXcuitest": None,
            "readyForXcuitestUnknown": True,
        }
    simulator_section = contract.get("simulators")
    simulator_devices = (
        simulator_section.get("devices") if isinstance(simulator_section, dict) else None
    )
    runtime_section = contract.get("runtimes")
    runtimes = runtime_section.get("runtimes") if isinstance(runtime_section, dict) else None
    simulators = {
        "discovered": len(simulator_devices) if isinstance(simulator_devices, list) else None,
        "discoveredUnknown": not isinstance(simulator_devices, list),
        "runtimeCount": len(runtimes) if isinstance(runtimes, list) else None,
        "runtimeCountUnknown": not isinstance(runtimes, list),
    }
    return physical, simulators


def _common_checks(
    evaluation: behavior.Evaluation,
    calls: Sequence[Mapping[str, Any]],
    servers: Sequence[Mapping[str, Any]],
    final_json: Mapping[str, Any],
    process: Mapping[str, Any],
    scope: str,
    platform_evidence: str,
) -> None:
    evaluation.check(
        "process-finished",
        not bool(process.get("timedOut")) and process.get("exitCode") == 0,
        f"Copilot exit={process.get('exitCode')!r}, timedOut={process.get('timedOut')!r}",
    )
    evaluation.check(
        "final-json-present",
        isinstance(final_json, dict) and bool(final_json),
        "Final assistant response contained a parseable JSON report.",
    )
    evaluation.check(
        "final-scope",
        final_json.get("scope") == scope
        and final_json.get("platformEvidence") == platform_evidence,
        f"scope/platformEvidence={final_json.get('scope')!r}/"
        f"{final_json.get('platformEvidence')!r}",
    )
    shape_issues = _report_shape_issues(final_json, scope, platform_evidence)
    evaluation.check(
        "final-report-shape",
        not shape_issues,
        "Final report controls match the prompted shape."
        if not shape_issues
        else "Report issues: " + "; ".join(shape_issues[:8]),
        shape_issues,
    )
    evaluation.check(
        "discovery-not-declared-failed",
        final_json.get("taskOutcome") != "failed",
        "Discovery completed, blocked, or requested approval instead of failing itself.",
    )
    skill_loads = [
        call
        for call in calls
        if call.get("toolName") == "skill"
        and call.get("arguments", {}).get("skill") == "amkernel"
        and call.get("success")
    ]
    evaluation.check(
        "installed-amkernel-skill-loaded",
        bool(skill_loads),
        f"Successful amkernel skill loads: {len(skill_loads)}",
    )
    workspace_servers = [
        item
        for item in servers
        if isinstance(item, dict) and str(item.get("source", "")).lower() == "workspace"
    ]
    evaluation.check(
        "one-workspace-mcp-server",
        len(workspace_servers) == 1
        and workspace_servers[0].get("name") == "amkernel"
        and str(workspace_servers[0].get("status", "")).lower() == "connected",
        "Workspace MCP servers: "
        + (
            ", ".join(f"{item.get('name')}:{item.get('status')}" for item in workspace_servers)
            or "none"
        ),
    )
    mcp_calls = [call for call in calls if call.get("mcpToolName") or call.get("mcpServerName")]
    bad_mcp = [
        call
        for call in mcp_calls
        if call.get("mcpServerName") != "amkernel"
        or call.get("mcpConfigSource") != "workspace"
        or call.get("mcpToolName") != "python_exec"
        or not str(call.get("toolName", "")).endswith("python_exec")
    ]
    evaluation.check(
        "mcp-calls-resolve-to-python-exec",
        not bad_mcp,
        "All MCP calls resolved to workspace amkernel/python_exec."
        if not bad_mcp
        else f"{len(bad_mcp)} MCP call(s) resolved elsewhere.",
    )
    disallowed = [
        call
        for call in calls
        if not (call.get("mcpToolName") == "python_exec" or call.get("toolName") in _ALLOWED_TOOLS)
    ]
    evaluation.check(
        "no-shell-write-other-tools",
        not disallowed,
        "Only skill/view and amkernel python_exec tools were executed."
        if not disallowed
        else "Disallowed tools: " + ", ".join(str(item.get("toolName")) for item in disallowed[:8]),
    )
    python_calls = [call for call in mcp_calls if call.get("mcpToolName") == "python_exec"]
    completed = [
        call
        for call in python_calls
        if call.get("observedStatus") == "completed" and call.get("kernelState") == "alive"
    ]
    evaluation.check(
        "python-exec-completed",
        bool(completed),
        f"Completed python_exec calls with a live kernel: {len(completed)}",
    )
    evaluation.check(
        "no-kernel-death",
        all(call.get("kernelState") != "dead" for call in python_calls)
        and final_json.get("kernelState") == "alive",
        "Observed kernel states: "
        + ", ".join(sorted({str(call.get("kernelState")) for call in python_calls})),
    )
    package_calls = [call for call in python_calls if call.get("arguments", {}).get("packages")]
    evaluation.check(
        "no-package-installs",
        not package_calls,
        "No python_exec requested dependency packages."
        if not package_calls
        else f"{len(package_calls)} python_exec call(s) requested packages.",
    )
    observations = _observations(calls)
    evaluation.check(
        "execution-evidence-captured",
        bool(observations),
        f"python_exec output observations retained: {len(observations)}",
    )


def _synthetic_inventory_issues(
    candidates: object, reported: Mapping[str, Mapping[str, Any]]
) -> list[str]:
    expected = _candidate_map(candidates)
    issues = [f"missing candidate facts for {path}" for path in expected if path not in reported]
    for path, record in reported.items():
        candidate = expected.get(path)
        if candidate is None:
            issues.append(f"reported candidate is absent from the contract: {path}")
            continue
        if record.get("exists") is not candidate.get("exists"):
            issues.append(f"reported candidate existence differs from the fixture: {path}")
        if candidate.get("exists") is False:
            if record.get("executed") is not False or record.get("eligible") is not False:
                issues.append(f"absent candidate reported executed or eligible: {path}")
            if any(
                record.get(key) is not None for key in ("exitCode", "version", "major", "javaHome")
            ):
                issues.append(f"absent candidate has unobserved execution facts: {path}")
    return issues


def _same_java_observation(reported: Mapping[str, Any], observed: Mapping[str, Any]) -> bool:
    return (
        reported.get("version") == observed.get("version")
        and reported.get("major") == observed.get("major")
        and _norm_path(reported.get("javaHome")) == _norm_path(observed.get("javaHome"))
    )


def _check_synthetic_selection(
    evaluation: behavior.Evaluation,
    contract: Mapping[str, Any],
    fixture: Any,
    final_json: Mapping[str, Any],
    journal: Sequence[Mapping[str, Any]],
    reported_map: Mapping[str, Mapping[str, Any]],
) -> None:
    expected = fixture.expected_java
    selected = final_json.get("selectedJava")
    reported_executable = selected.get("executable") if isinstance(selected, dict) else None
    evaluation.check(
        "selected-java-expected",
        (
            _path_equal(reported_executable, expected)
            if expected is not None
            else reported_executable is None
        ),
        "selectedJava="
        + (
            "null"
            if reported_executable is None
            else str(behavior._safe_text(reported_executable, 240))
        )
        + ", expected="
        + ("null" if expected is None else str(behavior._safe_text(expected, 240))),
    )
    minimum = contract.get("driver", {}).get("minimumJavaMajor")
    candidates = contract.get("javaCandidates")
    if not isinstance(candidates, list):
        candidates = []
    ordered_paths = [
        _norm_path(item.get("executable")) for item in candidates if isinstance(item, dict)
    ]
    selected_path = _norm_path(reported_executable)
    selected_index = (
        ordered_paths.index(selected_path)
        if selected_path is not None and selected_path in ordered_paths
        else None
    )
    rejection_issues: list[str] = []
    if selected_path is not None:
        record = reported_map.get(selected_path)
        evaluation.check(
            "selected-java-executed",
            record is not None
            and record.get("executed") is True
            and record.get("exitCode") == 0
            and record.get("eligible") is True
            and _is_int(record.get("major"))
            and _is_int(minimum)
            and cast(int, record.get("major")) >= minimum,
            "Selected candidate was executed successfully and meets the driver minimum.",
        )
        if selected_index is None:
            rejection_issues.append("selected executable is not a contract candidate")
    else:
        evaluation.check(
            "selected-java-executed",
            True,
            "No Java candidate was selected.",
        )
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict) or not candidate.get("exists"):
            continue
        path = _norm_path(candidate.get("executable"))
        if path is None:
            rejection_issues.append("candidate has no executable path")
            continue
        record = reported_map.get(path)
        if record is None:
            rejection_issues.append(f"missing candidate facts for {path}")
            continue
        if record.get("exists") is not True:
            rejection_issues.append(f"existing candidate reported absent for {path}")
        if record.get("executed") is not True:
            rejection_issues.append(f"existing candidate was not executed: {path}")
            continue
        exit_code = record.get("exitCode")
        if not _is_int(exit_code):
            rejection_issues.append(f"invalid exitCode for {path}")
            continue
        journal_command = _journal_command(
            journal,
            candidate.get("kind") or candidate.get("id"),
            candidate.get("executable"),
        )
        if journal_command is not None and journal_command.get("exitCode") != exit_code:
            rejection_issues.append(f"reported exitCode differs from the journal for {path}")
        if journal_command is not None and not _same_java_observation(record, journal_command):
            rejection_issues.append(f"reported Java version/home differs from execution for {path}")
        if exit_code != 0:
            if record.get("eligible") is not False:
                rejection_issues.append(f"failed candidate marked eligible: {path}")
            continue
        major = record.get("major")
        if not _is_int(major):
            rejection_issues.append(f"unparsed major for executed {path}")
            continue
        minimum_major = minimum if _is_int(minimum) else _MINIMUM_JAVA_MAJOR
        expected_eligible = exit_code == 0 and major >= minimum_major
        if record.get("eligible") is not expected_eligible:
            rejection_issues.append(f"eligible does not match minimum for {path}")
        if (
            expected_eligible
            and index != selected_index
            and (selected_index is None or index < selected_index)
        ):
            rejection_issues.append(f"eligible candidate at index {index} was not selected")
    evaluation.check(
        "selection-rejects-earlier-or-ineligible-candidates",
        not rejection_issues,
        "Earlier candidates were actually rejected by execution or the Java minimum."
        if not rejection_issues
        else "; ".join(rejection_issues[:8]),
    )
    journal_issues: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict) or not candidate.get("exists"):
            continue
        path = _norm_path(candidate.get("executable"))
        if path is None:
            journal_issues.append(f"{candidate.get('kind')!r} has no executable path")
            continue
        record = reported_map.get(path)
        command = _journal_command(
            journal,
            candidate.get("kind") or candidate.get("id"),
            candidate.get("executable"),
        )
        if command is None:
            journal_issues.append(f"{candidate.get('kind')!r} was not executed")
            continue
        if record is None:
            journal_issues.append(f"{candidate.get('kind')!r} has no reported facts")
        elif record.get("executed") is not True:
            journal_issues.append(f"{candidate.get('kind')!r} is reported as not executed")
        elif record.get("exitCode") != command.get("exitCode"):
            journal_issues.append(
                f"{candidate.get('kind')!r} exitCode {record.get('exitCode')!r} "
                f"!= journal {command.get('exitCode')!r}"
            )
    evaluation.check(
        "all-existing-java-candidates-executed",
        not journal_issues,
        "Every existing Java candidate was executed and its actual exit code reported."
        if not journal_issues
        else "; ".join(journal_issues[:8]),
    )


def _evaluate_synthetic(
    evaluation: behavior.Evaluation,
    fixture: Any,
    calls: Sequence[Mapping[str, Any]],
    final_json: Mapping[str, Any],
    observations: Sequence[Mapping[str, Any]],
) -> None:
    contract = fixture.contract if isinstance(fixture.contract, dict) else {}
    snapshot = fixture.snapshot()
    journal = snapshot.get("commands") if isinstance(snapshot, dict) else None
    if not isinstance(journal, list):
        journal = []
    command_issues = _contract_command_issues(contract, journal)
    evaluation.check(
        "discovery-capabilities-executed",
        not command_issues,
        "Every required discovery capability has independently observed execution."
        if not command_issues
        else "; ".join(command_issues[:8]),
        command_issues,
    )
    kinds = {_journal_kind(item.get("kind")) for item in journal}
    evaluation.check(
        "apple-physical-and-simulators-separate",
        {"apple-physical", "apple-simulators", "apple-runtimes"} <= kinds,
        "Apple physical, simulator, and runtime inventories were separate commands.",
    )
    physical_commands = [
        item for item in journal if _journal_kind(item.get("kind")) == "apple-physical"
    ]
    simulator_commands = [
        item for item in journal if _journal_kind(item.get("kind")) == "apple-simulators"
    ]
    evaluation.check(
        "physical-command-not-simulator-command",
        bool(physical_commands)
        and bool(simulator_commands)
        and physical_commands[0].get("argv") != simulator_commands[0].get("argv"),
        "Physical and simulator inventories used distinct commands.",
    )
    contract_kinds = {
        _journal_kind(item.get("kind"))
        for item in contract.get("commands", [])
        if isinstance(item, dict)
    }
    unexpected = sorted(kinds - contract_kinds)
    evaluation.check(
        "only-read-only-discovery-commands",
        not unexpected,
        "Journal contains only supplied discovery commands."
        if not unexpected
        else "Unexpected journal kinds: " + ", ".join(unexpected[:8]),
        unexpected,
    )
    candidates = contract.get("javaCandidates")
    if not isinstance(candidates, list):
        candidates = []
    reported_map = _candidate_map(final_json.get("javaCandidates"))
    extant_candidates = [
        item for item in candidates if isinstance(item, dict) and item.get("exists")
    ]
    inventory_issues = _synthetic_inventory_issues(candidates, reported_map)
    evaluation.check(
        "candidate-facts-present",
        not inventory_issues,
        "Every reported candidate matches the discovered inventory, including absences."
        if not inventory_issues
        else "; ".join(inventory_issues[:8]),
    )
    _check_synthetic_selection(evaluation, contract, fixture, final_json, journal, reported_map)
    expected_physical, expected_simulators = _expected_synthetic_counts(contract)
    empty_physical_observed = expected_physical.get("discovered") == 0 and any(
        _journal_kind(command.get("kind")) == "apple-physical" and command.get("exitCode") == 0
        for command in journal
    )
    reported_physical = final_json.get("physical")
    reported_simulators = final_json.get("simulators")
    physical_issues = _synthetic_physical_issues(
        reported_physical,
        expected_physical,
        empty_inventory_observed=empty_physical_observed,
    )
    simulator_issues = _count_issues(reported_simulators, sorted(_SIMULATOR_KEYS), physical=False)
    simulator_issues.extend(
        f"expected {key}={value!r} got {reported_simulators.get(key)!r}"
        for key, value in expected_simulators.items()
        if isinstance(reported_simulators, dict) and reported_simulators.get(key) != value
    )
    evaluation.check(
        "physical-layers-truthful",
        not physical_issues,
        "Physical counts match observed targets; nonempty readiness remains unverified."
        if not physical_issues
        else "; ".join(physical_issues[:8]),
    )
    evaluation.check(
        "simulator-runtime-counts-truthful",
        not simulator_issues,
        "Simulator/runtime counts match the separate synthetic inventories."
        if not simulator_issues
        else "; ".join(simulator_issues[:8]),
    )
    objects = _evidence_objects(observations)
    evidence_physical, evidence_simulators = _evidence_counts(objects)
    evidence_candidates = _evidence_candidates(objects)
    evidence_issues = _synthetic_inventory_issues(candidates, evidence_candidates)
    if not objects:
        evidence_issues.append("no python_exec JSON fact objects")
    if evidence_physical is None:
        evidence_issues.append("no physical counts in python_exec output")
    elif _synthetic_physical_issues(
        evidence_physical,
        expected_physical,
        empty_inventory_observed=empty_physical_observed,
    ):
        evidence_issues.append("physical counts in output differ from the listing")
    if evidence_simulators is None:
        evidence_issues.append("no simulator counts in python_exec output")
    elif not _counts_equal(evidence_simulators, expected_simulators, _SIMULATOR_KEYS):
        evidence_issues.append("simulator counts in output differ from the inventories")
    if extant_candidates and not evidence_candidates:
        evidence_issues.append("no Java candidate facts in python_exec output")
    for candidate in extant_candidates:
        if not isinstance(candidate, dict):
            continue
        path = _norm_path(candidate.get("executable"))
        if path is None:
            evidence_issues.append(f"{candidate.get('kind')!r} has no executable path")
            continue
        record = evidence_candidates.get(path)
        if record is None:
            evidence_issues.append(f"missing output facts for {candidate.get('kind')!r}")
            continue
        command = _journal_command(
            journal,
            candidate.get("kind") or candidate.get("id"),
            candidate.get("executable"),
        )
        if record.get("executed") is not True:
            evidence_issues.append(f"{candidate.get('kind')!r} not executed in output evidence")
        elif command is not None and record.get("exitCode") != command.get("exitCode"):
            evidence_issues.append(f"{candidate.get('kind')!r} output exit code mismatch")
        if command is not None and not _same_java_observation(record, command):
            evidence_issues.append(f"{candidate.get('kind')!r} output version/home mismatch")
    evaluation.check(
        "python-output-candidate-execution",
        not evidence_issues,
        "Actual python_exec output facts cover every existing candidate and Apple counts."
        if not evidence_issues
        else "; ".join(evidence_issues[:8]),
    )
    evaluation.check(
        "read-only-no-session-no-persistence",
        final_json.get("approvalRequired") is False
        and final_json.get("sessionStarted") is False
        and final_json.get("environmentPersisted") is False,
        "Synthetic discovery made no session, install, or persistence claim.",
    )


def _evaluate_host(
    evaluation: behavior.Evaluation,
    final_json: Mapping[str, Any],
    entries: Sequence[Mapping[str, Any]],
    service_before: Mapping[str, int] | None,
    service_after: Mapping[str, int] | None,
) -> None:
    probe_issues = _host_probe_issues(final_json, entries)
    evaluation.check(
        "probe-journal-backed-discovery",
        not probe_issues,
        "The task-owned probe journal independently supports every host claim."
        if not probe_issues
        else "; ".join(probe_issues[:8]),
        probe_issues,
    )
    physical_issues = _count_issues(
        final_json.get("physical"), sorted(_PHYSICAL_KEYS), physical=True
    )
    simulation_issues = _count_issues(
        final_json.get("simulators"), sorted(_SIMULATOR_KEYS), physical=False
    )
    evaluation.check(
        "physical-layers-no-overclaim",
        not physical_issues,
        "Physical layers remain unknown where target-specific evidence is absent."
        if not physical_issues
        else "; ".join(physical_issues[:8]),
        physical_issues,
    )
    evaluation.check(
        "simulator-counts-no-overclaim",
        not simulation_issues,
        "Simulator/runtime counts preserve unknown states."
        if not simulation_issues
        else "; ".join(simulation_issues[:8]),
        simulation_issues,
    )
    services_ok = (
        service_before is not None
        and service_after is not None
        and service_after.get("adbServer", 0) <= service_before.get("adbServer", 0)
        and service_after.get("appium", 0) <= service_before.get("appium", 0)
        and service_after.get("webdriverAgent", 0) <= service_before.get("webdriverAgent", 0)
        and service_after.get("xcodebuild", 0) <= service_before.get("xcodebuild", 0)
    )
    evaluation.check(
        "no-adb-daemon-or-session-service-startup",
        services_ok,
        "No new ADB daemon, Appium, or WebDriverAgent process was observed."
        if services_ok
        else "Service process counts changed or were unavailable.",
        {"before": service_before, "after": service_after},
    )
    evaluation.check(
        "read-only-no-session-no-persistence",
        final_json.get("sessionStarted") is False
        and final_json.get("environmentPersisted") is False,
        "Host discovery claims no session or persistent environment change.",
    )


# ---------------------------------------------------------------------------
# Scenario execution


def _run_scenario(context: behavior.RuntimeContext, scenario_id: str) -> dict[str, Any]:
    started = behavior._now()
    started_seconds = time.time()
    fixture: Any = None
    service_before: dict[str, int] | None = None
    service_after: dict[str, int] | None = None
    mcp_environment: dict[str, str] = {}
    probe: Path | None = None
    probe_journal_path: Path | None = None
    try:
        _prepare_client_home(context, scenario_id == "host")
        if scenario_id == "host":
            mcp_environment = _host_mcp_environment()
            _patch_mcp_environment(context, mcp_environment)
            probe, probe_journal_path = _write_host_probe(context)
            prompt = _host_prompt(probe, probe_journal_path)
            scope = "actual-host-read-only"
            platform_evidence = "actual-host-discovery-only"
            service_before = _service_process_counts()
        else:
            if scenario_id not in _FIXTURE_VARIANTS:
                raise RuntimeError(f"unknown discovery scenario: {scenario_id}")
            root = context.base / "fixtures" / scenario_id
            root.mkdir(parents=True, exist_ok=True)
            fixture = discovery_fixture.build_fixture(root, scenario_id)
            contract = fixture.contract
            if not isinstance(contract, dict):
                raise RuntimeError("discovery fixture contract is not an object")
            mcp_environment = dict(fixture.environment)
            mcp_environment.setdefault("HOME", context.env["HOME"])
            mcp_environment.setdefault("PATH", os.defpath)
            for key in _MANAGED_ENV_KEYS:
                mcp_environment.setdefault(key, "")
            _patch_mcp_environment(context, mcp_environment)
            prompt = _synthetic_prompt(contract)
            scope = "synthetic-fixture"
            platform_evidence = "synthetic-fixture"
        prompt_bytes = prompt.encode()
        calls, servers, final_text, runtime_data = _run_native(context, prompt)
        if scenario_id == "host":
            service_after = _service_process_counts()
        final_json = behavior._final_json(final_text)
        observations = _observations(calls)
        probe_entries = (
            _read_probe_journal(probe_journal_path) if probe_journal_path is not None else []
        )
        evaluation = behavior.Evaluation(scenario_id)
        _common_checks(
            evaluation,
            calls,
            servers,
            final_json if isinstance(final_json, dict) else {},
            runtime_data["process"],
            scope,
            platform_evidence,
        )
        if isinstance(final_json, dict):
            if scenario_id == "host" and probe is not None:
                _evaluate_host(
                    evaluation,
                    final_json,
                    probe_entries,
                    service_before,
                    service_after,
                )
            else:
                _evaluate_synthetic(evaluation, fixture, calls, final_json, observations)
        result = evaluation.result()
        snapshot = fixture.snapshot() if fixture is not None else None
        result.update(
            {
                "title": _TITLES[scenario_id],
                "startedAt": started,
                "completedAt": behavior._now(),
                "durationMs": int((time.time() - started_seconds) * 1000),
                "promptSha256": behavior._sha256_bytes(prompt_bytes),
                "promptBytes": len(prompt_bytes),
                "process": runtime_data["process"],
                "stderr": runtime_data["stderr"],
                "toolCalls": _sanitize_calls(calls),
                "mcpServers": servers,
                "observed": {
                    "mcp": [
                        {
                            "name": item.get("name"),
                            "status": item.get("status"),
                            "source": item.get("source"),
                        }
                        for item in servers
                        if isinstance(item, dict)
                    ],
                    "kernelStates": sorted(
                        {
                            str(call.get("kernelState"))
                            for call in calls
                            if call.get("kernelState") is not None
                        }
                    ),
                    "pythonCallStatuses": [
                        {
                            "index": call.get("index"),
                            "status": call.get("observedStatus"),
                            "kernelState": call.get("kernelState"),
                        }
                        for call in calls
                        if call.get("mcpToolName") == "python_exec"
                    ],
                },
                "executionObservations": observations,
                "probeJournal": probe_entries if probe is not None else None,
                "probe": (
                    {
                        "name": probe.name,
                        "journalEntries": len(probe_entries),
                    }
                    if probe is not None
                    else None
                ),
                "mcpEnvironmentKeys": sorted(mcp_environment),
                "clientHomeIsolated": True,
                "finalJson": _sanitize_report(final_json),
                "finalResponseSha256": behavior._sha256_bytes(final_text.encode()),
                "finalResponseBytes": len(final_text.encode()),
                "scope": scope,
                "platformEvidence": platform_evidence,
            }
        )
        if fixture is not None:
            expected_physical, expected_simulators = _expected_synthetic_counts(fixture.contract)
            selected = final_json.get("selectedJava") if isinstance(final_json, dict) else None
            result["fixtureJournal"] = snapshot
            result["expectedJava"] = (
                str(fixture.expected_java) if fixture.expected_java is not None else None
            )
            result["selectionEvidence"] = {
                "minimumJavaMajor": fixture.contract.get("driver", {}).get("minimumJavaMajor"),
                "expectedJava": (
                    str(fixture.expected_java) if fixture.expected_java is not None else None
                ),
                "reportedJava": (
                    selected.get("executable") if isinstance(selected, dict) else None
                ),
                "expectedMatch": (
                    _path_equal(selected.get("executable"), fixture.expected_java)
                    if isinstance(selected, dict) and fixture.expected_java is not None
                    else isinstance(selected, dict)
                    and selected.get("executable") is None
                    and fixture.expected_java is None
                ),
                "journalKinds": [
                    str(item.get("kind"))
                    for item in (snapshot or {}).get("commands", [])
                    if isinstance(item, dict)
                ],
                "physicalExpectation": expected_physical,
                "simulatorExpectation": expected_simulators,
            }
        else:
            selected = final_json.get("selectedJava") if isinstance(final_json, dict) else None
            probe_expected = _probe_expected_selection(probe_entries)
            result["selectionEvidence"] = {
                "minimumJavaMajor": _MINIMUM_JAVA_MAJOR,
                "expectedJava": probe_expected,
                "reportedJava": (
                    selected.get("executable") if isinstance(selected, dict) else None
                ),
                "expectedMatch": (
                    isinstance(selected, dict)
                    and (
                        _path_equal(selected.get("executable"), probe_expected)
                        if probe_expected is not None
                        else selected.get("executable") is None
                    )
                ),
                "probeCommands": [
                    str(item.get("kind"))
                    for item in probe_entries
                    if item.get("event") == "command"
                ],
                "probeSummary": _probe_summary(probe_entries),
            }
            result["serviceProcesses"] = {
                "before": service_before,
                "after": service_after,
            }
        return result
    except Exception as error:
        return {
            "id": scenario_id,
            "title": _TITLES.get(scenario_id, scenario_id),
            "status": "failed",
            "startedAt": started,
            "completedAt": behavior._now(),
            "durationMs": int((time.time() - started_seconds) * 1000),
            "error": behavior._bounded(
                behavior._scrubber(context)(f"{type(error).__name__}: {error}"),
                4000,
            ),
            "checks": [],
            "scope": ("actual-host-read-only" if scenario_id == "host" else "synthetic-fixture"),
            "platformEvidence": (
                "actual-host-discovery-only" if scenario_id == "host" else "synthetic-fixture"
            ),
            "serviceProcesses": (
                {"before": service_before, "after": service_after}
                if scenario_id == "host"
                else None
            ),
        }
    finally:
        # Fixtures are passive files. Nothing external is stopped or cleaned.
        pass


# ---------------------------------------------------------------------------
# Run and CLI


def run(options: behavior.Options) -> dict[str, Any]:
    base = Path(tempfile.mkdtemp(prefix="amkernel-discovery-behavior-"))
    project = base / "project"
    project.mkdir()
    home = base / "copilot-home"
    for name in ("home", "tmp", "data", "cache"):
        (base / name).mkdir()
    token = os.environ.get("COPILOT_GITHUB_TOKEN", "").strip() or behavior._auth_token() or ""
    env = behavior._isolated_env(base, token)
    isolation_before = behavior._prepare_isolation(base)
    check_external = "host" in options.scenarios
    external_before = _host_state_snapshot() if check_external else None
    context = behavior.RuntimeContext(
        options=options,
        base=base,
        project=project,
        home=home,
        env=env,
        token=token,
        temp_evidence={},
        evidence={},
        commands=[],
        isolation_before=isolation_before,
    )
    _prepare_client_home(context, "host" in options.scenarios)
    evidence: dict[str, Any] = {
        "schemaVersion": 1,
        "issue": ISSUE,
        "scope": (
            "Native GitHub Copilot CLI discovery behavior through an installed "
            "AMKernel wheel; synthetic host facts are not platform evidence"
        ),
        "startedAt": behavior._now(),
        "client": {
            "version": behavior._copilot_version(options.copilot),
            "executableSha256": behavior._sha256_file(options.copilot),
        },
        "model": options.model,
        "wheel": {
            "filename": options.wheel.name,
            "sha256": behavior._sha256_file(options.wheel),
            "bytes": options.wheel.stat().st_size if options.wheel.is_file() else None,
        },
        "bootstrapInstall": {
            "performedBy": "harness preflight with the product installer",
            "scope": (
                "task-temporary isolated uv tool directory, client HOME, project, and "
                "per-scenario task-only MCP environment; the AMKernel wheel and its "
                "declared Runtime/Skill content are installed there only, and no "
                "environment change is persisted"
            ),
            "agentPlatformDependencyInstallation": (
                "prohibited: no Java, Android SDK, Xcode, Appium driver, device profile, "
                "or platform service may be installed or changed by the Agent; missing "
                "platform prerequisites are reported as discovery facts"
            ),
            "installedBeforeScenarios": None,
        },
        "preflight": None,
        "scenarios": [],
        "externalState": {
            "checked": check_external,
            "before": external_before,
            "after": None,
            "unchanged": None,
        },
        "limitations": [
            "Synthetic fixture candidates and Apple inventories are simulated facts.",
            "The actual-host case performs read-only discovery only; it does not "
            "qualify a device, simulator, driver, or session readiness.",
            "No dependency installation, profile edit, global xcode-select change, "
            "device trust, service start, or Appium session is authorized.",
            "The harness does not modify or clean external host resources and makes "
            "no external cleanup claim.",
            "External host config, shell-profile, and active xcode-selection state are "
            "compared only when the host scenario is selected.",
            "The actual-host MCP process receives a task-scoped real-HOME/PATH "
            "environment so installed host tools remain visible; client HOME remains "
            "isolated and no shell profile or global environment is edited.",
            "Actual-host Java, Apple, and readiness facts are derived from the "
            "task-owned read-only probe journal, not the final prose or a second "
            "model self-report.",
            "Final report JSON is cross-checked against native tool events, "
            "python_exec outputs, the fixture journal, and the host probe journal; "
            "wording is not graded.",
            "No raw Copilot transcript, executable Python code, device serial, UDID, "
            "or full inventory is retained.",
        ],
    }
    try:
        preflight = behavior._preflight(context)
    except Exception as error:
        preflight = {
            "ok": False,
            "checks": [
                {
                    "id": "preflight-exception",
                    "ok": False,
                    "detail": behavior._bounded(
                        behavior._scrubber(context)(f"{type(error).__name__}: {error}"),
                        3000,
                    ),
                }
            ],
        }
    evidence["preflight"] = preflight
    evidence["bootstrapInstall"]["installedBeforeScenarios"] = context.temp_evidence.get("install")
    evidence["bootstrapInstall"]["verifiedBeforeScenarios"] = context.temp_evidence.get("verified")
    if not preflight.get("ok"):
        for scenario_id in options.scenarios:
            evidence["scenarios"].append(
                {
                    "id": scenario_id,
                    "title": _TITLES[scenario_id],
                    "status": "failed",
                    "error": "global preflight failed; no scenario was started",
                    "checks": [],
                    "scope": (
                        "actual-host-read-only" if scenario_id == "host" else "synthetic-fixture"
                    ),
                    "platformEvidence": (
                        "actual-host-discovery-only"
                        if scenario_id == "host"
                        else "synthetic-fixture"
                    ),
                }
            )
    else:
        for scenario_id in options.scenarios:
            evidence["scenarios"].append(_run_scenario(context, scenario_id))

    final_runner_cleanup = behavior._terminate_owned_runners(context, "final")
    if final_runner_cleanup:
        evidence["runnerCleanupFinal"] = final_runner_cleanup
    isolation_after = behavior._prepare_isolation(base)
    external_after = _host_state_snapshot() if check_external else None
    isolation_unchanged = isolation_before == isolation_after
    external_unchanged = external_before == external_after if check_external else True
    evidence["isolation"] = {
        "before": isolation_before,
        "after": isolation_after,
        "unchanged": isolation_unchanged,
    }
    evidence["externalState"] = {
        "checked": check_external,
        "before": external_before,
        "after": external_after,
        "unchanged": external_unchanged,
    }
    evidence["nativeEvidence"] = context.temp_evidence
    evidence["completedAt"] = behavior._now()
    passed = sum(1 for item in evidence["scenarios"] if item.get("status") == "passed")
    failed = sum(1 for item in evidence["scenarios"] if item.get("status") == "failed")
    blocked = sum(1 for item in evidence["scenarios"] if item.get("status") == "blocked")
    overall = behavior._overall_status(
        evidence["scenarios"], isolation_unchanged and external_unchanged
    )
    evidence["summary"] = {
        "status": overall,
        "passed": passed,
        "failed": failed,
        "blocked": blocked,
        "selected": len(evidence["scenarios"]),
        "isolationUnchanged": isolation_unchanged,
        "externalStateUnchanged": external_unchanged,
        "isolationRegression": not isolation_unchanged,
        "externalStateRegression": not external_unchanged,
    }
    evidence = cast(dict[str, Any], behavior._scrub_value(evidence, behavior._scrubber(context)))
    options.output.parent.mkdir(parents=True, exist_ok=True)
    behavior._write_json(options.output, evidence)
    if not options.keep_temp:
        try:
            output_inside_base = options.output.resolve().is_relative_to(base.resolve())
        except OSError:
            output_inside_base = False
        if not output_inside_base:
            shutil.rmtree(base, ignore_errors=True)
    return evidence


def _parse_args(argv: Sequence[str] | None = None) -> behavior.Options:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--wheel",
        type=Path,
        required=True,
        help="built AMKernel wheel to install through the product installer",
    )
    parser.add_argument(
        "--copilot",
        type=Path,
        help="native GitHub Copilot CLI executable (auto-detected and identity-checked if omitted)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="evidence JSON path; defaults to a fresh temporary directory",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        choices=_SCENARIO_IDS,
        help="run only this discovery scenario (repeatable); default is all four",
    )
    parser.add_argument("--keep-temp", action="store_true")
    args = parser.parse_args(argv)
    copilot = behavior._find_copilot(args.copilot)
    if copilot is None:
        parser.error(
            "GitHub Copilot CLI was not found; pass --copilot with the real native CLI "
            "(the Homebrew AWS Copilot is not accepted)"
        )
    output = args.output
    if output is None:
        output = Path(tempfile.mkdtemp(prefix="amkernel-discovery-evidence-")) / "evidence.json"
    scenarios = list(args.scenario or _SCENARIO_IDS)
    scenarios = [scenario_id for scenario_id in _SCENARIO_IDS if scenario_id in scenarios]
    return behavior.Options(
        wheel=args.wheel,
        copilot=copilot,
        output=output,
        scenarios=scenarios,
        model=MODEL,
        timeout=300.0,
        keep_temp=args.keep_temp,
    )


def main(argv: Sequence[str] | None = None) -> int:
    options = _parse_args(argv)
    evidence = run(options)
    summary = evidence.get("summary", {})
    print(
        json.dumps(
            {
                "status": summary.get("status"),
                "passed": summary.get("passed"),
                "failed": summary.get("failed"),
                "blocked": summary.get("blocked"),
                "evidence": str(options.output),
            },
            sort_keys=True,
        )
    )
    return behavior._exit_code(summary)


if __name__ == "__main__":
    raise SystemExit(main())
