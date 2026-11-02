"""Capture and validate Stage 3 Mobile/Appium lifecycle failures."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import signal
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator, FormatChecker
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

from tests.e2e.mobile_appium import (
    appium_session_observation,
    device_observation,
    sanitize_text,
    sha256_bytes,
    structured,
)

BOTH = "Both"
SHARED = "Shared"
CASES: dict[str, str] = {
    "appium-endpoint-unavailable": BOTH,
    "incompatible-client-selenium": SHARED,
    "missing-appium-driver": BOTH,
    "device-offline": BOTH,
    "session-creation-failure": BOTH,
    "invalid-app-target": BOTH,
    "missing-ambiguous-element": BOTH,
    "stale-element": BOTH,
    "appium-command-timeout": BOTH,
    "app-crash": BOTH,
    "appium-server-restart": BOTH,
    "platform-driver-failure": BOTH,
    "python-exception": BOTH,
    "python-timeout-surviving-kernel": BOTH,
    "kernel-hard-kill": SHARED,
    "oversized-output": SHARED,
    "artifact-write-failure": SHARED,
    "module-changed-after-import": SHARED,
    "driver-quit-during-kernel-shutdown": BOTH,
}
SHARED_CASES = {identifier for identifier, coverage in CASES.items() if coverage == SHARED}
ARTIFACT_KIND = "amkernel-result"


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def hash_file(path: Path) -> tuple[int, str]:
    payload = path.read_bytes()
    return len(payload), sha256_bytes(payload)


def artifact_record(path: Path, root: Path) -> dict[str, Any]:
    size, digest = hash_file(path)
    return {
        "kind": ARTIFACT_KIND,
        "mimeType": "application/json",
        "path": path.relative_to(root).as_posix(),
        "sizeBytes": size,
        "sha256": digest,
    }


def redact_paths(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, str):
        for source, replacement in replacements.items():
            value = value.replace(source, replacement)
        return value
    if isinstance(value, list):
        return [redact_paths(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: redact_paths(item, replacements) for key, item in value.items()}
    return value


def matrix_definition_bytes() -> bytes:
    return json.dumps(CASES, sort_keys=True, separators=(",", ":")).encode()


def lifecycle_validator(schema: dict[str, Any]) -> Draft202012Validator:
    return Draft202012Validator(
        {
            "$schema": schema["$schema"],
            "$defs": schema["$defs"],
            "$ref": "#/$defs/lifecycleRecord",
        }
    )


def validate_lifecycle(record: dict[str, Any], root: Path, schema: dict[str, Any]) -> None:
    lifecycle_validator(schema).validate(record)
    errors: list[str] = []
    expected = {
        (identifier, platform)
        for identifier, coverage in CASES.items()
        for platform in (("android",) if coverage == SHARED else ("android", "ios"))
    }
    occurrences = cast(list[dict[str, Any]], record["occurrences"])
    observed = {(item["id"], item["platform"]) for item in occurrences}
    if observed != expected or len(occurrences) != len(expected):
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        errors.append(f"coverage mismatch: missing={missing!r} extra={extra!r}")
    if record["matrixDefinitionSha256"] != sha256_bytes(matrix_definition_bytes()):
        errors.append("matrix definition digest mismatch")
    for occurrence in occurrences:
        expected_coverage = CASES[cast(str, occurrence["id"])]
        if occurrence["coverage"] != expected_coverage:
            errors.append(f"{occurrence['id']}/{occurrence['platform']} coverage mismatch")
        transcript = cast(dict[str, Any], occurrence["transcript"])
        candidate = (root / cast(str, transcript["path"])).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            errors.append(f"{transcript['path']} escapes lifecycle root")
            continue
        if not candidate.is_file():
            errors.append(f"{transcript['path']} is missing")
            continue
        size, digest = hash_file(candidate)
        if size != transcript["sizeBytes"] or digest != transcript["sha256"]:
            errors.append(f"{transcript['path']} size/hash mismatch")
        recoverable = cast(
            list[str], cast(dict[str, Any], occurrence["failure"])["recoverableEvidence"]
        )
        if transcript["path"] not in recoverable:
            errors.append(f"{occurrence['id']}/{occurrence['platform']} omits its transcript")
    for platform, reference in cast(dict[str, dict[str, Any]], record["referenceEvidence"]).items():
        candidate = (root / cast(str, reference["path"])).resolve()
        if not candidate.is_file():
            errors.append(f"{platform} reference evidence is missing")
            continue
        size, digest = hash_file(candidate)
        if size != reference["sizeBytes"] or digest != reference["sha256"]:
            errors.append(f"{platform} reference evidence size/hash mismatch")
    if errors:
        raise ValueError("; ".join(errors))


def validate_required_semantics(record: dict[str, Any], root: Path) -> None:
    indexed: dict[tuple[str, str], tuple[dict[str, Any], dict[str, Any]]] = {}
    for occurrence in cast(list[dict[str, Any]], record["occurrences"]):
        transcript_ref = cast(dict[str, Any], occurrence["transcript"])
        transcript = cast(
            dict[str, Any], json.loads((root / cast(str, transcript_ref["path"])).read_bytes())
        )
        indexed[(cast(str, occurrence["id"]), cast(str, occurrence["platform"]))] = (
            occurrence,
            transcript,
        )

    errors: list[str] = []

    def error_types(transcript: dict[str, Any]) -> set[str]:
        return {
            cast(str, error["type"])
            for call in cast(list[dict[str, Any]], transcript["calls"])
            if (error := cast(dict[str, Any] | None, call.get("error"))) is not None
        }

    hard_kill, hard_kill_transcript = indexed[("kernel-hard-kill", "android")]
    hard_failure = cast(dict[str, Any], hard_kill["failure"])
    hard_observations = cast(dict[str, Any], hard_kill_transcript["observations"])
    hard_calls = cast(list[dict[str, Any]], hard_kill_transcript["calls"])
    if (
        hard_failure["kernelState"] != "dead"
        or hard_failure["sessionState"] != "present"
        or hard_failure["remainingExternalResources"]
        or "KernelExited" not in error_types(hard_kill_transcript)
        or "KernelUnavailable" not in error_types(hard_kill_transcript)
        or hard_calls[-1].get("result") != {"driverPresent": False}
        or "remains active" not in cast(str, hard_observations["sessionAtFailure"])
        or "is absent" not in cast(str, hard_observations["sessionAfterCleanup"])
    ):
        errors.append("kernel-hard-kill does not prove live-session death, reset, and cleanup")

    for platform in ("android", "ios"):
        stale, stale_transcript = indexed[("stale-element", platform)]
        if (
            cast(dict[str, Any], stale["failure"])["sessionState"] != "present"
            or "selenium.common.exceptions.StaleElementReferenceException"
            not in error_types(stale_transcript)
        ):
            errors.append(f"stale-element/{platform} is not a genuine stale-element failure")

        driver, driver_transcript = indexed[("platform-driver-failure", platform)]
        driver_observations = cast(dict[str, Any], driver_transcript["observations"])
        expected_driver_fault = {
            "android": (
                "force-stopped io.appium.uiautomator2.server; "
                "force-stopped io.appium.uiautomator2.server.test"
            ),
            "ios": "terminated the installed WebDriverAgentRunner bundle",
        }[platform]
        if (
            driver_observations.get("platformDriverFault") != expected_driver_fault
            or "selenium.common.exceptions.WebDriverException" not in error_types(driver_transcript)
            or cast(dict[str, Any], driver["failure"])["remainingExternalResources"]
        ):
            errors.append(f"platform-driver-failure/{platform} lacks driver fault or cleanup proof")

        endpoint, endpoint_transcript = indexed[("appium-endpoint-unavailable", platform)]
        endpoint_observations = cast(dict[str, Any], endpoint_transcript["observations"])
        if (
            cast(dict[str, Any], endpoint["failure"])["serverState"] != "offline"
            or endpoint_observations["controlServerState"] != "online"
        ):
            errors.append(
                f"appium-endpoint-unavailable/{platform} records the wrong endpoint state"
            )

        offline, offline_transcript = indexed[("device-offline", platform)]
        offline_observations = cast(dict[str, Any], offline_transcript["observations"])
        before = cast(str, offline_observations["deviceBeforeInjection"])
        offline_observed = (
            before.startswith("device probe reported offline:")
            if platform == "android"
            else before == "simulator state is 'Shutdown'"
        )
        if (
            cast(dict[str, Any], offline["failure"])["deviceState"] != "offline"
            or not offline_observed
        ):
            errors.append(f"device-offline/{platform} lacks an observed offline injection state")

    for identifier in (
        "invalid-app-target",
        "missing-ambiguous-element",
        "stale-element",
        "appium-command-timeout",
        "app-crash",
        "platform-driver-failure",
        "python-exception",
        "python-timeout-surviving-kernel",
        "driver-quit-during-kernel-shutdown",
    ):
        for platform in ("android", "ios"):
            occurrence, _ = indexed[(identifier, platform)]
            if cast(dict[str, Any], occurrence["failure"])["sessionState"] != "present":
                errors.append(f"{identifier}/{platform} loses failure-time live-session state")

    if errors:
        raise ValueError("; ".join(errors))


def server_online(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/status", timeout=timeout) as response:
            return cast(int, response.status) == 200
    except (OSError, urllib.error.URLError):
        return False


def wait_server(url: str, expected: bool, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server_online(url) is expected:
            return True
        time.sleep(0.1)
    return False


def stop_platform_driver(platform: str, device_id: str) -> str:
    if platform == "android":
        observations = []
        for package in (
            "io.appium.uiautomator2.server",
            "io.appium.uiautomator2.server.test",
        ):
            result = subprocess.run(
                ["adb", "-s", device_id, "shell", "am", "force-stop", package],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"failed to stop {package}: {result.stderr.strip() or result.stdout.strip()}"
                )
            observations.append(f"force-stopped {package}")
        return "; ".join(observations)

    listed = subprocess.run(
        ["xcrun", "simctl", "listapps", device_id],
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    matches = sorted(set(re.findall(r'"([^"]*WebDriverAgentRunner[^\"]*)" =', listed.stdout)))
    if len(matches) != 1:
        raise RuntimeError(f"expected one WebDriverAgent bundle, got {matches!r}")
    bundle_id = matches[0]
    stopped = subprocess.run(
        ["xcrun", "simctl", "terminate", device_id, bundle_id],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if stopped.returncode != 0:
        raise RuntimeError(
            f"failed to stop {bundle_id}: {stopped.stderr.strip() or stopped.stdout.strip()}"
        )
    return "terminated the installed WebDriverAgentRunner bundle"


def delete_session(url: str, session_id: str) -> tuple[bool, str]:
    request = urllib.request.Request(f"{url.rstrip('/')}/session/{session_id}", method="DELETE")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status == 200, f"DELETE session returned HTTP {response.status}"
    except (OSError, urllib.error.URLError) as error:
        return False, f"{type(error).__name__}: {error}"


def options_code(
    platform: str,
    server_url: str,
    device_id: str,
    application_id: str,
    activity: str | None,
    *,
    automation_name: str | None = None,
    impossible_version: bool = False,
) -> str:
    if platform == "android":
        options_import = "from appium.options.android import UiAutomator2Options as _Options"
        assignments = [
            "_options.platform_name = 'Android'",
            f"_options.automation_name = {automation_name or 'UiAutomator2'!r}",
            f"_options.udid = {device_id!r}",
            f"_options.app_package = {application_id!r}",
            f"_options.app_activity = {activity!r}",
            "_options.no_reset = True",
        ]
    else:
        options_import = "from appium.options.ios import XCUITestOptions as _Options"
        assignments = [
            "_options.platform_name = 'iOS'",
            f"_options.automation_name = {automation_name or 'XCUITest'!r}",
            f"_options.udid = {device_id!r}",
            f"_options.bundle_id = {application_id!r}",
            "_options.no_reset = True",
        ]
    if impossible_version:
        assignments.append("_options.set_capability('appium:newCommandTimeout', 'invalid')")
    return "\n".join(
        [
            "from appium import webdriver",
            options_import,
            "_options = _Options()",
            *assignments,
            f"_driver = webdriver.Remote({server_url!r}, options=_options)",
            "_session_id = _driver.session_id",
        ]
    )


def failure_action_code(case: str, platform: str, invalid_target: str) -> str:
    if case == "invalid-app-target":
        return f"_driver.activate_app({invalid_target!r})"
    if case == "missing-ambiguous-element":
        return "_driver.find_element('accessibility id', 'amkernel-definitely-missing')"
    if case == "stale-element":
        target = "Views" if platform == "android" else "Text Fields"
        return (
            "_driver.terminate_app(_mobile_application)\n"
            "_driver.activate_app(_mobile_application)\n"
            f"_element = _driver.find_element('accessibility id', {target!r})\n"
            "_driver.terminate_app(_mobile_application)\n"
            "_driver.activate_app(_mobile_application)\n"
            "_element.is_displayed()"
        )
    if case == "appium-command-timeout":
        return "_driver.command_executor._client_config.timeout = 0.000001\n_driver.page_source"
    if case == "app-crash":
        return (
            "_driver.terminate_app(_mobile_application)\n"
            "_state = _driver.query_app_state(_mobile_application)\n"
            "raise RuntimeError(f'fixture app terminated; observed state={_state}')"
        )
    if case == "platform-driver-failure":
        return "_driver.page_source"
    if case == "python-exception":
        return "raise ValueError('injected lifecycle Python exception')"
    if case == "python-timeout-surviving-kernel":
        return "import time\ntime.sleep(30)"
    if case == "appium-server-restart":
        return "_driver.page_source"
    raise ValueError(f"unsupported session action case: {case}")


def call_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": payload.get("status"),
        "kernelState": payload.get("kernelState"),
        "executionCount": payload.get("executionCount"),
        "error": payload.get("error"),
        "result": payload.get("result"),
        "output": payload.get("output"),
    }


def failure_category(case: str) -> str:
    if case in {
        "appium-endpoint-unavailable",
        "incompatible-client-selenium",
        "missing-appium-driver",
        "device-offline",
    }:
        return "prerequisite"
    if case in {
        "kernel-hard-kill",
        "oversized-output",
        "artifact-write-failure",
        "module-changed-after-import",
    }:
        return "amkernel"
    if case == "driver-quit-during-kernel-shutdown":
        return "cleanup"
    if case in {"python-exception", "python-timeout-surviving-kernel"}:
        return "scenario"
    return "driver"


def recreation(case: str) -> list[str]:
    mapping = {
        "appium-endpoint-unavailable": ["server"],
        "incompatible-client-selenium": ["kernel"],
        "missing-appium-driver": ["server"],
        "device-offline": ["device"],
        "session-creation-failure": ["session"],
        "invalid-app-target": ["application"],
        "missing-ambiguous-element": [],
        "stale-element": ["application"],
        "appium-command-timeout": ["driver", "session"],
        "app-crash": ["application"],
        "appium-server-restart": ["server", "driver", "session"],
        "platform-driver-failure": ["driver", "session"],
        "python-exception": [],
        "python-timeout-surviving-kernel": [],
        "kernel-hard-kill": ["kernel"],
        "oversized-output": [],
        "artifact-write-failure": [],
        "module-changed-after-import": [],
        "driver-quit-during-kernel-shutdown": ["session"],
    }
    return mapping[case]


async def capture(arguments: argparse.Namespace) -> dict[str, Any]:
    case = cast(str, arguments.case)
    platform = cast(str, arguments.platform)
    server_url = cast(str, arguments.appium_server_url)
    output_root = cast(Path, arguments.output_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    case_workspace = cast(Path, arguments.workspace).resolve() / f"{case}-{platform}"
    shutil.rmtree(case_workspace, ignore_errors=True)
    case_workspace.mkdir(parents=True)
    environment: dict[str, str] = {}
    temporary_root: Path | None = None
    if case == "artifact-write-failure":
        temporary_root = case_workspace / "tmp"
        temporary_root.mkdir()
        environment["TMPDIR"] = str(temporary_root)

    effective_url = "http://127.0.0.1:1" if case == "appium-endpoint-unavailable" else server_url
    dedicated_server: subprocess.Popen[bytes] | None = None
    server_restarted = False
    if case == "appium-server-restart":
        effective_url = f"http://127.0.0.1:{arguments.restart_port}"
        appium = shutil.which("appium")
        if appium is None:
            raise RuntimeError("appium executable is unavailable")
        log_path = output_root / f"{case}-{platform}-appium.log"
        log = log_path.open("wb")
        dedicated_server = subprocess.Popen(
            [appium, "--address", "127.0.0.1", "--port", str(arguments.restart_port)],
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        if not wait_server(effective_url, True, 30):
            dedicated_server.terminate()
            raise RuntimeError("dedicated Appium Server did not start")

    parameters = StdioServerParameters(
        command=str(cast(Path, arguments.entry_point).resolve()),
        cwd=case_workspace,
        env=environment or None,
    )
    calls: list[dict[str, Any]] = []
    session_id: str | None = None
    injection = ""
    cleanup_attempted = False
    cleanup_observed = False
    kernel_state = "unavailable"
    failure_kernel_state = "unavailable"
    session_state = "absent"
    failure_session_state = "absent"
    failure_session_observation = "session was not created"
    cleanup_session_observation = "session was not created"
    message = ""
    last_step: str | None = None
    managed_pids: list[int] = []
    platform_fault_observation: str | None = None
    device_before_online, device_before_probe = device_observation(platform, arguments.device_id)
    if case == "device-offline" and device_before_online:
        raise RuntimeError("device-offline injection requires an observed offline device")
    try:
        async with Client(parameters, read_timeout_seconds=45.0) as client:
            await client.list_tools()
            if case == "artifact-write-failure":
                identity = structured(
                    await client.call_tool(
                        "python_exec", {"code": "import os\n[os.getppid(), os.getpid()]"}
                    )
                )
                calls.append(call_summary(identity))
                managed_pids = list(cast(tuple[int, int], identity["result"]))
                assert temporary_root is not None
                roots = list(temporary_root.glob("amkernel-*"))
                if len(roots) != 1:
                    raise RuntimeError(f"expected one Artifact Store root, got {roots!r}")
                roots[0].chmod(0)
                injection = "removed write permission from the isolated Artifact Store root"
                try:
                    result = structured(
                        await client.call_tool(
                            "python_exec", {"code": "artifact('failure.txt', b'injected')"}
                        )
                    )
                except RuntimeError as error:
                    calls.append(
                        {
                            "status": "adapter-error",
                            "kernelState": "alive",
                            "executionCount": None,
                            "error": {"type": type(error).__name__, "message": str(error)},
                            "result": None,
                            "output": None,
                        }
                    )
                else:
                    raise RuntimeError("artifact write unexpectedly succeeded")
                roots[0].chmod(0o700)
                probe = structured(await client.call_tool("python_exec", {"code": "42"}))
                calls.append(call_summary(probe))
            elif case == "module-changed-after-import":
                module = case_workspace / "mutable_probe.py"
                module.write_text("VALUE = 'before'\n")
                module_path = str(module)
                load_code = (
                    "import importlib.util, sys\n"
                    "_spec=importlib.util.spec_from_file_location("
                    f"'mutable_probe', {module_path!r})\n"
                    "mutable_probe=importlib.util.module_from_spec(_spec)\n"
                    "sys.modules['mutable_probe']=mutable_probe\n"
                    "_spec.loader.exec_module(mutable_probe)\n"
                    "mutable_probe.VALUE"
                )
                first = structured(await client.call_tool("python_exec", {"code": load_code}))
                calls.append(call_summary(first))
                module.write_text("VALUE = 'after-reload'\n")
                shutil.rmtree(case_workspace / "__pycache__", ignore_errors=True)
                injection = "changed a workspace module after importing it in the persistent kernel"
                stale = structured(
                    await client.call_tool("python_exec", {"code": "mutable_probe.VALUE"})
                )
                calls.append(call_summary(stale))
                reloaded = structured(
                    await client.call_tool(
                        "python_exec",
                        {"code": "_spec.loader.exec_module(mutable_probe)\nmutable_probe.VALUE"},
                    )
                )
                calls.append(call_summary(reloaded))
                if (
                    first["result"] != "before"
                    or stale["result"] != "before"
                    or reloaded["result"] != "after-reload"
                ):
                    raise RuntimeError("module mutation behavior was not observed")
            elif case == "kernel-hard-kill":
                setup = options_code(
                    platform,
                    server_url,
                    arguments.device_id,
                    arguments.application_id,
                    arguments.activity,
                )
                setup += (
                    f"\n_mobile_application={arguments.application_id!r}"
                    f"\n_mobile_device={arguments.device_id!r}\n_session_id"
                )
                setup_result = structured(
                    await client.call_tool(
                        "python_exec",
                        {"code": setup, "packages": ["Appium-Python-Client"], "timeout": 30.0},
                    )
                )
                calls.append(call_summary(setup_result))
                if setup_result["status"] != "completed":
                    raise RuntimeError(f"hard-kill session setup failed: {setup_result!r}")
                session_id = cast(str, setup_result["result"])
                session_state = "present"
                failure_session_state = "present"
                last_step = "session-created"
                injection = "sent SIGKILL to the isolated Runner while an Appium session was live"
                killed = structured(
                    await client.call_tool(
                        "python_exec",
                        {"code": "import os, signal\nos.kill(os.getpid(), signal.SIGKILL)"},
                    )
                )
                calls.append(call_summary(killed))
                failure_kernel_state = "dead"
                unavailable = structured(await client.call_tool("python_exec", {"code": "42"}))
                calls.append(call_summary(unavailable))
                recovered = structured(
                    await client.call_tool(
                        "python_exec",
                        {"code": "{'driverPresent': '_driver' in globals()}", "reset": True},
                    )
                )
                calls.append(call_summary(recovered))
                if recovered["status"] != "completed" or recovered["result"] != {
                    "driverPresent": False
                }:
                    raise RuntimeError("replacement kernel did not start with a clean namespace")
                last_step = "replacement-kernel-verified"
            elif case == "oversized-output":
                injection = "wrote beyond the frozen per-execution output limit"
                code = "import os\n_chunk=b'x'*(1024*1024)\nfor _ in range(300): os.write(1,_chunk)"
                result = structured(
                    await client.call_tool("python_exec", {"code": code, "timeout": 30.0})
                )
                calls.append(call_summary(result))
                probe = structured(await client.call_tool("python_exec", {"code": "42"}))
                calls.append(call_summary(probe))
            elif case == "incompatible-client-selenium":
                injection = "injected a client requirement of selenium<4"
                code = (
                    "import importlib.metadata\n"
                    "from packaging.specifiers import SpecifierSet\n"
                    "from packaging.version import Version\n"
                    "_selenium=importlib.metadata.version('selenium')\n"
                    "_required=SpecifierSet('<4')\n"
                    "assert Version(_selenium) in _required, "
                    "f'injected client requires selenium{_required}; '"
                    "f'installed selenium is {_selenium}'"
                )
                result = structured(
                    await client.call_tool(
                        "python_exec",
                        {"code": code, "packages": ["Appium-Python-Client", "selenium"]},
                    )
                )
                calls.append(call_summary(result))
                probe = structured(await client.call_tool("python_exec", {"code": "42"}))
                calls.append(call_summary(probe))
            else:
                automation = "MissingDriver" if case == "missing-appium-driver" else None
                impossible = case == "session-creation-failure"
                setup = options_code(
                    platform,
                    effective_url,
                    arguments.device_id,
                    arguments.application_id,
                    arguments.activity,
                    automation_name=automation,
                    impossible_version=impossible,
                )
                setup += (
                    f"\n_mobile_application={arguments.application_id!r}"
                    f"\n_mobile_device={arguments.device_id!r}\n_session_id"
                )
                injection = {
                    "appium-endpoint-unavailable": (
                        "connected to an unused loopback Appium endpoint"
                    ),
                    "missing-appium-driver": "requested an uninstalled Appium automation driver",
                    "device-offline": "requested the isolated target while it was powered off",
                    "session-creation-failure": "requested an impossible platform version",
                    "driver-quit-during-kernel-shutdown": (
                        "closed MCP transport while the Appium driver remained live"
                    ),
                }.get(case, f"executed {case} against a live Appium session")
                setup_result = structured(
                    await client.call_tool(
                        "python_exec",
                        {"code": setup, "packages": ["Appium-Python-Client"], "timeout": 30.0},
                    )
                )
                calls.append(call_summary(setup_result))
                if setup_result["status"] == "completed":
                    session_id = cast(str, setup_result["result"])
                    session_state = "present"
                    failure_session_state = "present"
                    last_step = "session-created"
                if case in {
                    "appium-endpoint-unavailable",
                    "missing-appium-driver",
                    "device-offline",
                    "session-creation-failure",
                }:
                    pass
                elif case == "driver-quit-during-kernel-shutdown":
                    last_step = "transport-closed-with-live-session"
                else:
                    if case == "appium-server-restart":
                        assert dedicated_server is not None
                        os.killpg(dedicated_server.pid, signal.SIGTERM)
                        dedicated_server.wait(timeout=15)
                        if not wait_server(effective_url, False, 10):
                            raise RuntimeError("dedicated Appium Server did not stop")
                        appium = shutil.which("appium")
                        assert appium is not None
                        log = (output_root / f"{case}-{platform}-appium-restart.log").open("wb")
                        dedicated_server = subprocess.Popen(
                            [
                                appium,
                                "--address",
                                "127.0.0.1",
                                "--port",
                                str(arguments.restart_port),
                            ],
                            stdout=log,
                            stderr=subprocess.STDOUT,
                            start_new_session=True,
                        )
                        if not wait_server(effective_url, True, 30):
                            raise RuntimeError("dedicated Appium Server did not restart")
                        server_restarted = True
                    if case == "platform-driver-failure":
                        platform_fault_observation = stop_platform_driver(
                            platform, cast(str, arguments.device_id)
                        )
                        injection = (
                            f"stopped the actual platform driver: {platform_fault_observation}"
                        )
                    action = failure_action_code(case, platform, arguments.invalid_application_id)
                    timeout = 0.05 if case == "python-timeout-surviving-kernel" else 30.0
                    action_result = structured(
                        await client.call_tool("python_exec", {"code": action, "timeout": timeout})
                    )
                    calls.append(call_summary(action_result))
                    failure_kernel_state = cast(
                        str, action_result.get("kernelState") or "unavailable"
                    )
                    if server_restarted:
                        failure_session_state = "absent"
                        failure_session_observation = (
                            "Appium Server restart invalidated the old session"
                        )
                    elif session_id is not None:
                        absent_at_failure, failure_session_observation = appium_session_observation(
                            effective_url, session_id
                        )
                        failure_session_state = "absent" if absent_at_failure else "present"
                    last_step = "failure-injected"
                    probe = structured(
                        await client.call_tool(
                            "python_exec",
                            {
                                "code": (
                                    "{'kernel': 'alive', 'sessionId': globals().get('_session_id')}"
                                )
                            },
                        )
                    )
                    calls.append(call_summary(probe))
                    if case != "driver-quit-during-kernel-shutdown":
                        cleanup_attempted = True
                        cleanup = structured(
                            await client.call_tool(
                                "python_exec",
                                {
                                    "code": (
                                        "\ntry:\n _driver.quit()\n"
                                        " _cleanup='quit observed'\n"
                                        "except Exception as _error:\n"
                                        " _cleanup=f'{type(_error).__name__}: {_error}'\n"
                                        "_cleanup"
                                    )
                                },
                            )
                        )
                        calls.append(call_summary(cleanup))
                        cleanup_observed = cleanup["status"] == "completed"
            kernel_state = cast(str, calls[-1].get("kernelState") or "unavailable")
            if failure_kernel_state == "unavailable":
                failure_kernel_state = kernel_state
    finally:
        if temporary_root is not None:
            for root in temporary_root.glob("amkernel-*"):
                root.chmod(0o700)
        if dedicated_server is not None and dedicated_server.poll() is None:
            os.killpg(dedicated_server.pid, signal.SIGTERM)
            dedicated_server.wait(timeout=15)

    if case == "driver-quit-during-kernel-shutdown":
        kernel_state = "dead"
        failure_kernel_state = "dead"
    if session_id is not None and failure_session_observation == "session was not created":
        absent_at_failure, failure_session_observation = appium_session_observation(
            effective_url, session_id
        )
        failure_session_state = "absent" if absent_at_failure else "present"
    if session_id is not None and server_restarted:
        session_state = "absent"
        cleanup_session_observation = "Appium Server restart invalidated the old session"
        cleanup_attempted = True
        cleanup_observed = True
    elif session_id is not None:
        absent, cleanup_session_observation = appium_session_observation(effective_url, session_id)
        session_state = "absent" if absent else "present"
        if not absent:
            cleanup_attempted = True
            deleted, delete_observation = delete_session(effective_url, session_id)
            cleanup_observed = deleted
            absent, after_delete = appium_session_observation(effective_url, session_id)
            session_state = "absent" if absent else "present"
            cleanup_session_observation = (
                f"{cleanup_session_observation}; {delete_observation}; {after_delete}"
            )
        else:
            cleanup_observed = True
    else:
        cleanup_observed = True
    device_online, device_probe = device_observation(platform, arguments.device_id)
    server_state = (
        "restarted"
        if server_restarted
        else ("online" if server_online(effective_url) else "offline")
    )

    failed_calls = [item for item in calls if item.get("status") != "completed"]

    if case in {"module-changed-after-import", "driver-quit-during-kernel-shutdown"}:
        message = injection
    elif case == "app-crash":
        message = "fixture application termination was observed as an explicit failed call"
    elif failed_calls:
        failure_error = cast(dict[str, Any] | None, failed_calls[0].get("error"))
        message = str(failure_error or failed_calls[0]["status"])
    else:
        message = f"{case} injection produced no failed AMKernel call"
        if case != "artifact-write-failure":
            raise RuntimeError(message)

    entry_point = cast(Path, arguments.entry_point)
    redactions = {
        str(entry_point.absolute().parents[1]): "<venv>",
        str(entry_point.resolve().parents[1]): "<venv>",
        str(case_workspace): "<workspace>",
        str(Path.home()): "<home>",
        str(arguments.device_id): "<device>",
    }
    message = cast(str, redact_paths(message, redactions))
    transcript_payload = redact_paths(
        {
            "case": case,
            "platform": platform,
            "injection": injection,
            "calls": calls,
            "observations": {
                "kernelAtFailure": failure_kernel_state,
                "kernelAfterRecovery": kernel_state,
                "sessionAtFailure": failure_session_observation,
                "sessionAfterCleanup": cleanup_session_observation,
                "deviceBeforeInjection": device_before_probe,
                "deviceAfterFailure": device_probe,
                "serverAtFailure": server_state,
                "controlServerState": "online" if server_online(server_url) else "offline",
                "platformDriverFault": platform_fault_observation,
                "managedPids": managed_pids,
            },
        },
        redactions,
    )
    transcript_path = output_root / "occurrences" / f"{case}-{platform}.json"
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text(json.dumps(transcript_payload, indent=2, sort_keys=True) + "\n")
    transcript = artifact_record(transcript_path, output_root)
    remaining = [] if session_state == "absent" else [f"Appium session {session_id} remains"]
    if not device_online:
        remaining.append(f"device {arguments.device_id} remains offline")
    required_recreation = recreation(case)
    if case == "device-offline" and device_online:
        required_recreation = []
    return {
        "id": case,
        "coverage": CASES[case],
        "platform": platform,
        "injectedAt": utc_now(),
        "injection": injection,
        "failure": {
            "category": failure_category(case),
            "message": sanitize_text(message),
            "agentObservation": sanitize_text(message),
            "kernelState": failure_kernel_state,
            "sessionState": failure_session_state,
            "deviceState": (
                "offline"
                if case == "device-offline" and not device_before_online
                else ("online" if device_online else "offline")
            ),
            "serverState": server_state,
            "recreationRequired": required_recreation,
            "recoverableEvidence": [transcript["path"]],
            "cleanupAttempted": cleanup_attempted,
            "cleanupObserved": cleanup_observed,
            "remainingExternalResources": remaining,
            "lastCompletedStep": last_step,
        },
        "transcript": transcript,
    }


def parse_capture(subparsers: Any) -> None:
    parser = subparsers.add_parser("capture")
    parser.add_argument("--case", action="append", choices=tuple(CASES))
    parser.add_argument("--coverage", choices=(BOTH, SHARED))
    parser.add_argument("--platform", required=True, choices=("android", "ios"))
    parser.add_argument("--entry-point", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--application-id", required=True)
    parser.add_argument("--invalid-application-id", required=True)
    parser.add_argument("--activity")
    parser.add_argument("--appium-server-url", default="http://127.0.0.1:4723")
    parser.add_argument("--restart-port", type=int, default=4725)


def finalize_device_recovery(arguments: argparse.Namespace) -> None:
    occurrence_path = cast(Path, arguments.occurrence).resolve()
    output_root = cast(Path, arguments.output_dir).resolve()
    occurrence = cast(dict[str, Any], json.loads(occurrence_path.read_bytes()))
    if occurrence["id"] != "device-offline" or occurrence["platform"] != arguments.platform:
        raise ValueError("occurrence is not the requested device-offline record")
    online, observation = device_observation(arguments.platform, arguments.device_id)
    if not online:
        raise RuntimeError(observation)
    transcript_path = output_root / cast(str, occurrence["transcript"]["path"])
    transcript = cast(
        dict[str, Any],
        redact_paths(
            json.loads(transcript_path.read_bytes()),
            {str(arguments.device_id): "<device>"},
        ),
    )
    transcript["cleanup"] = {
        "observedAt": utc_now(),
        "deviceOnline": True,
        "observation": cast(str, redact_paths(observation, {str(arguments.device_id): "<device>"})),
    }
    transcript_path.write_text(json.dumps(transcript, indent=2, sort_keys=True) + "\n")
    occurrence["transcript"] = artifact_record(transcript_path, output_root)
    failure = cast(dict[str, Any], occurrence["failure"])
    failure["cleanupAttempted"] = True
    failure["cleanupObserved"] = True
    failure["remainingExternalResources"] = []
    failure["recreationRequired"] = []
    failure["recoverableEvidence"] = [occurrence["transcript"]["path"]]
    occurrence_path.write_text(json.dumps(occurrence, indent=2, sort_keys=True) + "\n")


def parse_finalize_device(subparsers: Any) -> None:
    parser = subparsers.add_parser("finalize-device")
    parser.add_argument("--occurrence", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--platform", required=True, choices=("android", "ios"))
    parser.add_argument("--device-id", required=True)


def parse_assemble(subparsers: Any) -> None:
    parser = subparsers.add_parser("assemble")
    parser.add_argument("--occurrence-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--schema", required=True, type=Path)
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--android-reference", required=True, type=Path)
    parser.add_argument("--ios-reference", required=True, type=Path)


def assemble(arguments: argparse.Namespace) -> None:
    output = cast(Path, arguments.output).resolve()
    root = output.parent
    root.mkdir(parents=True, exist_ok=True)
    occurrences = [
        cast(dict[str, Any], json.loads(path.read_bytes()))
        for path in sorted(cast(Path, arguments.occurrence_dir).glob("*.occurrence.json"))
    ]
    wheel_size, wheel_digest = hash_file(cast(Path, arguments.wheel))
    references: dict[str, Any] = {}
    for platform, source in (
        ("android", cast(Path, arguments.android_reference)),
        ("ios", cast(Path, arguments.ios_reference)),
    ):
        source = source.resolve()
        size, digest = hash_file(source)
        references[platform] = {
            "kind": ARTIFACT_KIND,
            "mimeType": "application/json",
            "path": Path(os.path.relpath(source, root)).as_posix(),
            "sizeBytes": size,
            "sha256": digest,
        }
    record = {
        "schemaVersion": 1,
        "experimentId": "S3-mobile-appium-lifecycle",
        "generatedAt": utc_now(),
        "matrixDefinitionSha256": sha256_bytes(matrix_definition_bytes()),
        "amkernelRevision": arguments.revision,
        "amkernelWheel": {
            "filename": cast(Path, arguments.wheel).name,
            "sizeBytes": wheel_size,
            "sha256": wheel_digest,
        },
        "referenceEvidence": references,
        "occurrences": occurrences,
    }
    schema = cast(dict[str, Any], json.loads(cast(Path, arguments.schema).read_bytes()))
    validate_lifecycle(record, root, schema)
    validate_required_semantics(record, root)
    output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")


GRADUATION_CRITERIA = (
    "retain-appium-driver",
    "control-android-and-ios",
    "inspect-and-interact",
    "deliver-screenshots",
    "reduce-page-source-locally",
    "continue-after-ordinary-errors",
    "distinguish-kernel-lifecycle",
    "execute-project-automation",
    "retain-diagnostic-artifacts",
    "clean-managed-resources",
)

GRADUATION_MEASUREMENTS = (
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

GRADUATION_REVIEWS: tuple[dict[str, Any], ...] = (
    {
        "id": "skill",
        "reviewer": "independent reviewer",
        "recordedBy": "houlianpi",
        "source": "https://github.com/FSQ-lab/amkernel/issues/73#issuecomment-6517212394",
        "scope": "Official-skill trust, project-local procedure, security, and workflow",
        "severity": {"blocker": 0, "major": 0, "minor": 0},
        "disposition": "accepted",
    },
    {
        "id": "fixture-contract",
        "reviewer": "independent reviewer",
        "recordedBy": "houlianpi",
        "source": "https://github.com/FSQ-lab/amkernel/issues/74#issuecomment-6514737289",
        "scope": "Fixtures, schemas, scenario, measurement protocol, and evidence ownership",
        "severity": {"blocker": 0, "major": 0, "minor": 0},
        "disposition": "accepted",
    },
    {
        "id": "android-reference",
        "reviewer": "independent reviewer",
        "recordedBy": "houlianpi",
        "source": "https://github.com/FSQ-lab/amkernel/issues/72#issuecomment-6517212387",
        "scope": "Android reference run, provenance, measurements, state, and cleanup",
        "severity": {"blocker": 0, "major": 0, "minor": 0},
        "disposition": "accepted",
    },
    {
        "id": "ios-reference",
        "reviewer": "independent reviewer",
        "recordedBy": "houlianpi",
        "source": "https://github.com/FSQ-lab/amkernel/issues/70#issuecomment-6517212420",
        "scope": "iOS reference run, provenance, measurements, state, and cleanup",
        "severity": {"blocker": 0, "major": 0, "minor": 0},
        "disposition": "accepted",
    },
    {
        "id": "lifecycle",
        "reviewer": "LifecycleFinalReviewer",
        "recordedBy": "houlianpi",
        "source": "https://github.com/FSQ-lab/amkernel/issues/71#issuecomment-6518419963",
        "scope": "All 19 failure cases, 33 occurrences, state transitions, and cleanup",
        "severity": {"blocker": 0, "major": 0, "minor": 0},
        "disposition": "accepted",
    },
    {
        "id": "graduation",
        "reviewer": "GraduationFinalReview",
        "recordedBy": "Main",
        "source": "https://github.com/FSQ-lab/amkernel/issues/69#issuecomment-6518659573",
        "scope": "Complete Stage 3 index, decision, support claim, and Stage 4 recommendation",
        "severity": {"blocker": 0, "major": 0, "minor": 0},
        "disposition": "accepted",
    },
)


def graduation_artifact(path: Path, root: Path) -> dict[str, Any]:
    resolved = path.resolve()
    relative = resolved.relative_to(root.resolve()).as_posix()
    size, digest = hash_file(resolved)
    return {"path": relative, "sizeBytes": size, "sha256": digest}


def platform_graduation_result(reference: dict[str, Any]) -> dict[str, Any]:
    measurements = cast(dict[str, Any], reference["measurements"])
    reduction = cast(dict[str, Any], measurements["contextReduction"])
    reduction_observations = cast(list[dict[str, Any]], reduction["observations"])
    page_source = cast(dict[str, Any], measurements["pageSource"])
    screenshots = cast(dict[str, Any], measurements["screenshot"])
    cleanup = cast(dict[str, Any], reference["cleanup"])
    amkernel = cast(dict[str, Any], reference["amkernel"])
    return {
        "outcome": reference["outcome"],
        "timing": {
            "kernelStartupMs": measurements["kernelStartup"]["summary"],
            "appiumSessionStartupMs": measurements["appiumSessionStartup"]["summary"],
            "perCellOverheadMs": measurements["perCellOverhead"]["derivedSummary"],
            "outputDeliveryLatencyMs": measurements["outputDeliveryLatency"]["summary"],
            "timeoutToInterruptMs": measurements["timeoutToInterrupt"]["summary"],
        },
        "size": {
            "maximumPageSourceBytes": max(
                cast(int, observation["bytes"])
                for observation in cast(list[dict[str, Any]], page_source["observations"])
            ),
            "maximumScreenshotDecodedBytes": max(
                cast(int, observation["decodedBytes"])
                for observation in cast(list[dict[str, Any]], screenshots["observations"])
            ),
        },
        "localReduction": {
            "minimumRequiredRatio": reduction["minimumReductionRatio"],
            "observedMinimumRatio": min(
                cast(float, observation["reductionRatio"]) for observation in reduction_observations
            ),
            "maximumAfterBytes": reduction["maximumAfterBytes"],
        },
        "errorRecovery": {
            "continuationVerified": amkernel["continuationVerified"],
            "kernelState": amkernel["kernelState"],
        },
        "cleanup": {
            "completed": cleanup["completed"],
            "driverQuit": cleanup["driverQuit"],
            "sessionAbsent": cleanup["sessionAbsent"],
            "deviceUsable": cleanup["deviceUsable"],
            "managedProcessesExited": cleanup["managedProcessesExited"],
            "remainingExternalResources": cleanup["remainingExternalResources"],
        },
    }


def build_graduation_record(
    android_path: Path,
    ios_path: Path,
    lifecycle_path: Path,
    root: Path,
    generated_at: str,
    evidence_schema: dict[str, Any],
) -> dict[str, Any]:
    android = cast(dict[str, Any], json.loads(android_path.read_bytes()))
    ios = cast(dict[str, Any], json.loads(ios_path.read_bytes()))
    lifecycle = cast(dict[str, Any], json.loads(lifecycle_path.read_bytes()))
    reference_validator = Draft202012Validator(evidence_schema)
    reference_validator.validate(android)
    reference_validator.validate(ios)
    validate_lifecycle(lifecycle, lifecycle_path.parent, evidence_schema)
    validate_required_semantics(lifecycle, lifecycle_path.parent)

    references = {"android": android, "ios": ios}
    common: dict[str, Any] = {}
    for platform, reference in references.items():
        environment = cast(dict[str, Any], reference["environment"])
        amkernel = cast(dict[str, Any], environment["amkernel"])
        scenario = cast(dict[str, Any], reference["scenario"])
        protocol = cast(dict[str, Any], reference["measurementProtocol"])
        skills = cast(dict[str, Any], environment["officialSkills"])
        identity = {
            "amkernelRevision": amkernel["revision"],
            "wheel": amkernel["wheel"],
            "scenario": {
                "id": scenario["id"],
                "sha256": scenario["definitionSha256"],
            },
            "measurementProtocol": {
                "id": protocol["id"],
                "sha256": protocol["definitionSha256"],
            },
            "officialSkill": {
                "repository": skills["repository"],
                "commit": skills["commit"],
                "path": skills["appiumPythonPath"],
            },
        }
        if not common:
            common = identity
        elif identity != common:
            raise ValueError(f"{platform} reference identity differs from the shared identity")

    artifact_paths = {
        "androidReference": graduation_artifact(android_path, root),
        "iosReference": graduation_artifact(ios_path, root),
        "lifecycle": graduation_artifact(lifecycle_path, root),
    }
    lifecycle_references = cast(dict[str, dict[str, Any]], lifecycle["referenceEvidence"])
    for platform in references:
        selected = artifact_paths[f"{platform}Reference"]
        if any(lifecycle_references[platform][key] != value for key, value in selected.items()):
            raise ValueError(
                f"lifecycle {platform} reference differs from selected graduation evidence"
            )

    if lifecycle["amkernelRevision"] != common["amkernelRevision"]:
        raise ValueError("lifecycle AMKernel revision differs from reference evidence")
    if lifecycle["amkernelWheel"] != common["wheel"]:
        raise ValueError("lifecycle wheel differs from reference evidence")

    required_measurements = GRADUATION_MEASUREMENTS
    for platform, reference in references.items():
        measurements = cast(dict[str, Any], reference["measurements"])
        cleanup = cast(dict[str, Any], reference["cleanup"])
        if reference["outcome"] != "passed":
            raise ValueError(f"{platform} reference did not pass")
        if any(
            not cast(dict[str, Any], measurements[name])["passed"] for name in required_measurements
        ):
            raise ValueError(f"{platform} reference has a failed graduation measurement")
        if (
            not cleanup["completed"]
            or cleanup["remainingExternalResources"]
            or not cast(dict[str, Any], reference["amkernel"])["continuationVerified"]
        ):
            raise ValueError(f"{platform} reference lacks recovery or cleanup proof")

    occurrences = cast(list[dict[str, Any]], lifecycle["occurrences"])
    remaining = [
        resource
        for occurrence in occurrences
        for resource in cast(dict[str, Any], occurrence["failure"])["remainingExternalResources"]
    ]
    both_ids = {item["id"] for item in occurrences if item["coverage"] == BOTH}
    shared_ids = {item["id"] for item in occurrences if item["coverage"] == SHARED}
    all_cleanup = all(
        cast(bool, cast(dict[str, Any], occurrence["failure"])["cleanupObserved"])
        for occurrence in occurrences
    )
    if len(occurrences) != 33 or len(both_ids) != 14 or len(shared_ids) != 5:
        raise ValueError("lifecycle evidence does not cover the frozen matrix")
    if not all_cleanup or remaining:
        raise ValueError("lifecycle evidence retains incomplete cleanup")

    fixture_identities = {
        platform: {
            "id": reference["fixture"]["id"],
            "commit": reference["fixture"]["commit"],
            "tag": reference["fixture"]["tag"],
            "artifactSha256": reference["fixture"]["artifactSha256"],
        }
        for platform, reference in references.items()
    }
    evidence_by_criterion = {
        "retain-appium-driver": [
            artifact_paths["androidReference"]["path"],
            artifact_paths["iosReference"]["path"],
        ],
        "control-android-and-ios": [
            artifact_paths["androidReference"]["path"],
            artifact_paths["iosReference"]["path"],
        ],
        "inspect-and-interact": [
            artifact_paths["androidReference"]["path"],
            artifact_paths["iosReference"]["path"],
        ],
        "deliver-screenshots": [
            artifact_paths["androidReference"]["path"],
            artifact_paths["iosReference"]["path"],
        ],
        "reduce-page-source-locally": [
            artifact_paths["androidReference"]["path"],
            artifact_paths["iosReference"]["path"],
        ],
        "continue-after-ordinary-errors": [artifact_paths["lifecycle"]["path"]],
        "distinguish-kernel-lifecycle": [artifact_paths["lifecycle"]["path"]],
        "execute-project-automation": [
            artifact_paths["androidReference"]["path"],
            artifact_paths["iosReference"]["path"],
        ],
        "retain-diagnostic-artifacts": [artifact_paths["lifecycle"]["path"]],
        "clean-managed-resources": [
            artifact_paths["androidReference"]["path"],
            artifact_paths["iosReference"]["path"],
            artifact_paths["lifecycle"]["path"],
        ],
    }
    reviews_by_criterion = {
        "retain-appium-driver": ["skill", "android-reference", "ios-reference"],
        "control-android-and-ios": ["android-reference", "ios-reference"],
        "inspect-and-interact": ["android-reference", "ios-reference"],
        "deliver-screenshots": ["android-reference", "ios-reference"],
        "reduce-page-source-locally": ["android-reference", "ios-reference"],
        "continue-after-ordinary-errors": ["lifecycle"],
        "distinguish-kernel-lifecycle": ["lifecycle"],
        "execute-project-automation": [
            "fixture-contract",
            "android-reference",
            "ios-reference",
        ],
        "retain-diagnostic-artifacts": ["lifecycle"],
        "clean-managed-resources": [
            "android-reference",
            "ios-reference",
            "lifecycle",
        ],
    }
    measurements_index = [
        {
            "id": identifier,
            "platforms": {
                platform: {
                    "evidence": artifact_paths[f"{platform}Reference"]["path"],
                    "runOutcome": reference["outcome"],
                    "cleanupCompleted": reference["cleanup"]["completed"],
                    "remainingExternalResources": reference["cleanup"][
                        "remainingExternalResources"
                    ],
                    "value": reference["measurements"][identifier],
                }
                for platform, reference in references.items()
            },
            "reviews": [
                "fixture-contract",
                "android-reference",
                "ios-reference",
                "graduation",
            ],
        }
        for identifier in GRADUATION_MEASUREMENTS
    ]
    failures_index = [
        {
            "id": identifier,
            "coverage": coverage,
            "occurrences": [
                {
                    "platform": occurrence["platform"],
                    "injectedAt": occurrence["injectedAt"],
                    "injection": occurrence["injection"],
                    "failure": occurrence["failure"],
                    "transcript": occurrence["transcript"],
                }
                for occurrence in occurrences
                if occurrence["id"] == identifier
            ],
            "reviews": ["lifecycle", "graduation"],
        }
        for identifier, coverage in CASES.items()
    ]
    return {
        "schemaVersion": 1,
        "experimentId": "S3-mobile-appium-graduation",
        "generatedAt": generated_at,
        "decision": {
            "outcome": "advance-to-stage-4-cross-client-validation",
            "supportStatus": "experimental-not-supported",
            "coreChangeRecommended": False,
            "mobileSpecificInterfaceRecommended": False,
        },
        "artifacts": artifact_paths,
        "identities": {**common, "fixtures": fixture_identities},
        "results": {
            "android": platform_graduation_result(android),
            "ios": platform_graduation_result(ios),
            "lifecycle": {
                "occurrenceCount": len(occurrences),
                "bothCaseCount": len(both_ids),
                "sharedCaseCount": len(shared_ids),
                "allCleanupObserved": all_cleanup,
                "remainingExternalResources": remaining,
            },
        },
        "criteria": [
            {
                "id": identifier,
                "passed": True,
                "evidence": evidence_by_criterion[identifier],
                "reviews": [*reviews_by_criterion[identifier], "graduation"],
            }
            for identifier in GRADUATION_CRITERIA
        ],
        "measurements": measurements_index,
        "failures": failures_index,
        "reviews": list(GRADUATION_REVIEWS),
        "limitations": [
            "Evidence comes from one reference Coding Agent host.",
            "Device coverage is limited to one local Android emulator and one local iOS simulator.",
            "The result is experimental evidence and does not establish supported "
            "mobile automation.",
            "Appium Server and device lifecycle supervision remain external to AMKernel.",
        ],
    }


def validate_graduation_index(
    record: dict[str, Any],
    root: Path,
    schema: dict[str, Any],
    evidence_schema: dict[str, Any],
) -> None:
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(record),
        key=lambda error: list(error.path),
    )
    if errors:
        raise ValueError("; ".join(error.message for error in errors))
    artifacts = cast(dict[str, dict[str, Any]], record["artifacts"])
    expected = build_graduation_record(
        root / artifacts["androidReference"]["path"],
        root / artifacts["iosReference"]["path"],
        root / artifacts["lifecycle"]["path"],
        root,
        cast(str, record["generatedAt"]),
        evidence_schema,
    )
    if record != expected:
        raise ValueError("graduation index differs from linked evidence")


def parse_graduate(subparsers: Any) -> None:
    parser = subparsers.add_parser("graduate")
    parser.add_argument("--android-reference", required=True, type=Path)
    parser.add_argument("--ios-reference", required=True, type=Path)
    parser.add_argument("--lifecycle", required=True, type=Path)
    parser.add_argument("--schema", required=True, type=Path)
    parser.add_argument("--evidence-schema", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)


def graduate(arguments: argparse.Namespace) -> None:
    output = cast(Path, arguments.output).resolve()
    root = output.parent
    evidence_schema = cast(
        dict[str, Any], json.loads(cast(Path, arguments.evidence_schema).read_bytes())
    )
    record = build_graduation_record(
        cast(Path, arguments.android_reference).resolve(),
        cast(Path, arguments.ios_reference).resolve(),
        cast(Path, arguments.lifecycle).resolve(),
        root,
        utc_now(),
        evidence_schema,
    )
    schema = cast(dict[str, Any], json.loads(cast(Path, arguments.schema).read_bytes()))
    validate_graduation_index(record, root, schema, evidence_schema)
    output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    parse_capture(subparsers)
    parse_assemble(subparsers)
    parse_finalize_device(subparsers)
    parse_graduate(subparsers)
    arguments = parser.parse_args(argv)
    if arguments.command == "capture":
        requested = cast(list[str] | None, arguments.case)
        if requested is not None and arguments.coverage is not None:
            parser.error("--case and --coverage are mutually exclusive")
        cases = requested or [
            identifier
            for identifier, coverage in CASES.items()
            if arguments.coverage is None or coverage == arguments.coverage
        ]
        if arguments.platform != "android" and any(case in SHARED_CASES for case in cases):
            parser.error("Shared cases are captured on Android only")
        for case in cases:
            arguments.case = case
            occurrence = asyncio.run(capture(arguments))
            path = (
                arguments.output_dir
                / "occurrences"
                / f"{case}-{arguments.platform}.occurrence.json"
            )
            path.write_text(json.dumps(occurrence, indent=2, sort_keys=True) + "\n")
            print(path)
        return 0
    if arguments.command == "finalize-device":
        finalize_device_recovery(arguments)
        print(arguments.occurrence)
        return 0
    if arguments.command == "graduate":
        graduate(arguments)
        print(arguments.output)
        return 0
    assemble(arguments)
    print(arguments.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
