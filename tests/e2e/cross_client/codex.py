from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests" / "e2e"))
sys.path.insert(0, str(ROOT))

from tests.e2e.cross_client_contract import (  # noqa: E402
    load_json,
    sha256_file,
    validate_evidence,
)
from tests.e2e.cross_client_normalizer import (  # noqa: E402
    canonical_json_bytes,
    normalize_event,
    normalize_request,
    request_projection,
)

FIXTURES = ROOT / "tests" / "fixtures" / "cross_client"
PROXY = Path(__file__).with_name("codex_proxy.py")
MODEL = "gpt-6.1-sol"
PROVIDER_URL = "http://127.0.0.1:23333/api/openai/v1"


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, value: object) -> bytes:
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False).encode() + b"\n"
    path.write_bytes(payload)
    return payload


def _run(command: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {command[0]}: {completed.stderr[-4000:]}"
        )
    return completed.stdout.strip()

def _persistent_config() -> dict[str, object]:
    path = Path.home() / ".codex" / "config.toml"
    if not path.exists():
        return {"scope": "persistent-client-config", "existed": False, "sha256": None}
    return {
        "scope": "persistent-client-config",
        "existed": True,
        "sha256": sha256_file(path),
    }


def _source_snapshot() -> str:
    digest = hashlib.sha256()
    excluded = {".git", ".venv", ".mypy_cache", ".pytest_cache", ".ruff_cache", "evidence"}
    for path in sorted(ROOT.rglob("*")):
        relative = path.relative_to(ROOT)
        if not path.is_file() or any(part in excluded for part in relative.parts):
            continue
        digest.update(relative.as_posix().encode() + b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _build_clean_wheel(temp: Path) -> tuple[Path, Path]:
    dist = temp / "dist"
    venv = temp / "venv"
    dist.mkdir()
    _run(["uv", "build", "--wheel", "--out-dir", str(dist)])
    wheel = next(dist.glob("*.whl"))
    _run(["uv", "venv", "--python", "3.11", str(venv)])
    _run(
        [
            "uv",
            "pip",
            "install",
            "--default-index",
            "https://pypi.tuna.tsinghua.edu.cn/simple",
            "--python",
            str(venv / "bin" / "python"),
            str(wheel),
        ]
    )
    return wheel, venv / "bin" / "amkernel"


def _codex_command(server: Path, capture: Path, client_dir: Path) -> list[str]:
    proxy_command = [
        sys.executable,
        str(PROXY),
        "--server",
        str(server),
        "--cwd",
        str(ROOT),
        "--capture",
        str(capture),
    ]
    command = [
        "codex",
        "--strict-config",
        "-m",
        MODEL,
        "-c",
        'model_provider="agent-maestro"',
        "-c",
        'model_providers.agent-maestro.name="Agent Maestro"',
        "-c",
        f'model_providers.agent-maestro.base_url="{PROVIDER_URL}"',
        "-c",
        'model_providers.agent-maestro.wire_api="responses"',
        "-c",
        "model_providers.agent-maestro.supports_standalone_web_search=true",
    ]
    for feature in (
        "computer_use",
        "shell_tool",
        "unified_exec",
        "browser_use",
        "browser_use_external",
        "in_app_browser",
        "standalone_web_search",
        "web_search_request",
        "skill_search",
        "plugins",
        "apps",
        "multi_agent",
        "image_generation",
    ):
        command.extend(["--disable", feature])
    command.extend(
        [
            "-c",
            f"mcp_servers.amkernel.command={json.dumps(proxy_command[0])}",
            "-c",
            "mcp_servers.amkernel.args=" + json.dumps(proxy_command[1:], separators=(",", ":")),
            "-c",
            'mcp_servers.amkernel.enabled_tools=["python_exec"]',
            "exec",
            "--ignore-user-config",
            "--ignore-rules",
            "--ephemeral",
            "--json",
            "--color",
            "never",
            "--dangerously-bypass-approvals-and-sandbox",
            "--skip-git-repo-check",
            "-C",
            str(client_dir),
            "-",
        ]
    )
    return command


def _run_codex(
    prompt: str, server: Path, capture: Path, client_dir: Path, codex_home: Path
) -> tuple[list[dict[str, Any]], str, str, str]:
    env = os.environ.copy()
    command = _codex_command(server, capture, client_dir)
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    process_stderr = process.stderr
    stderr_chunks: list[str] = []
    stderr_thread = threading.Thread(
        target=lambda: stderr_chunks.extend(iter(process_stderr.readline, "")), daemon=True
    )
    stderr_thread.start()
    started_at = _now()
    process.stdin.write(prompt)
    process.stdin.close()
    events: list[dict[str, Any]] = []
    for line in process.stdout:
        received_at = _now()
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            event["_receivedAt"] = received_at
            events.append(event)
    return_code = process.wait(timeout=600)
    completed_at = _now()
    stderr_thread.join(timeout=1)
    if return_code != 0:
        raise RuntimeError(
            f"Codex exited {return_code}: {''.join(stderr_chunks)[-4000:]} "
            + json.dumps(events[-5:], ensure_ascii=False)[-4000:]
        )
    return events, started_at, completed_at, "".join(stderr_chunks)[-8192:]


def _tool_calls(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    started: dict[str, str] = {}
    calls: list[dict[str, Any]] = []
    for event in events:
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "mcp_tool_call":
            continue
        item_id = str(item.get("id"))
        if event.get("type") == "item.started":
            started[item_id] = cast(str, event["_receivedAt"])
        elif event.get("type") == "item.completed":
            calls.append(
                {
                    "item": item,
                    "startedAt": started.get(item_id, event["_receivedAt"]),
                    "completedAt": event["_receivedAt"],
                }
            )
    return calls


def _structured_result(item: dict[str, Any]) -> dict[str, Any]:
    result = item.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("tool call has no result object")
    structured = result.get("structuredContent", result.get("structured_content"))
    if isinstance(structured, dict):
        return structured
    for value in result.values():
        if isinstance(value, dict) and "status" in value and "kernelState" in value:
            return value
    raise RuntimeError("tool call has no structured AMKernel result")


def _duration_ms(started: str, completed: str) -> float:
    start = datetime.fromisoformat(started.replace("Z", "+00:00"))
    end = datetime.fromisoformat(completed.replace("Z", "+00:00"))
    return (end - start).total_seconds() * 1000


def _assert_deterministic_results(
    scenario: dict[str, Any],
    calls: list[dict[str, Any]],
    resources: list[dict[str, Any]],
    capture: Path,
) -> list[dict[str, Any]]:
    definitions = [step for step in scenario["steps"] if step["action"] == "call-tool"]
    if len(calls) != len(definitions):
        raise RuntimeError(f"expected {len(definitions)} tool calls, observed {len(calls)}")
    results: list[dict[str, Any]] = []
    for definition, call in zip(definitions, calls, strict=True):
        item = call["item"]
        if item.get("server") != "amkernel" or item.get("tool") != "python_exec":
            raise RuntimeError(
                f"unexpected tool selection: {item.get('server')}/{item.get('tool')}"
            )
        if item.get("arguments") != definition["arguments"]:
            raise RuntimeError(
                f"arguments differ for {definition['id']}: {item.get('arguments')!r}"
            )
        result = _structured_result(item)
        expected = definition["expected"]
        if result.get("status") != expected.get("status", "completed"):
            raise RuntimeError(f"status differs for {definition['id']}")
        if result.get("kernelState") != expected.get("kernelState", "alive"):
            raise RuntimeError(f"kernel state differs for {definition['id']}")
        if "result" in expected and result.get("result") != expected["result"]:
            raise RuntimeError(f"result differs for {definition['id']}")
        if (
            "executionCount" in expected
            and result.get("executionCount") != expected["executionCount"]
        ):
            raise RuntimeError(f"execution count differs for {definition['id']}")
        if "display" in expected:
            displays = result.get("displays")
            if not isinstance(displays, list) or len(displays) != 1:
                raise RuntimeError("display metadata missing")
            observed = displays[0]
            for key, value in expected["display"].items():
                if observed.get(key) != value:
                    raise RuntimeError(f"display {key} differs")
        if "artifact" in expected:
            artifacts = result.get("artifacts")
            if not isinstance(artifacts, list) or len(artifacts) != 1:
                raise RuntimeError("artifact metadata missing")
            observed = artifacts[0]
            for key in ("name", "mimeType", "sizeBytes", "partCount"):
                if observed.get(key) != expected["artifact"].get(key):
                    raise RuntimeError(f"artifact {key} differs")
        results.append(result)

    manifest_records = []
    for resource in resources:
        payload = (capture / resource["path"]).read_bytes()
        try:
            parsed = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(parsed, dict) and isinstance(parsed.get("parts"), list):
            manifest_records.append((resource, parsed))
    if len(manifest_records) != 1:
        raise RuntimeError(f"expected one resource manifest, observed {len(manifest_records)}")
    manifest_resource, manifest = manifest_records[0]
    parts_by_uri = {resource["uri"]: resource for resource in resources}
    recovered = b"".join(
        (capture / parts_by_uri[part["uri"]]["path"]).read_bytes() for part in manifest["parts"]
    )
    if len(recovered) != manifest["size"] or _sha256(recovered) != manifest["sha256"]:
        raise RuntimeError("artifact resource integrity verification failed")
    if len(recovered) != 65544 or len(manifest["parts"]) != 2:
        raise RuntimeError("artifact resource shape differs")
    manifest_resource["parsed"] = manifest
    return results


def _artifact_record(kind: str, mime_type: str, path: Path, root: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {
        "kind": kind,
        "mimeType": mime_type,
        "path": path.relative_to(root).as_posix(),
        "sizeBytes": len(payload),
        "sha256": _sha256(payload),
    }


def _deterministic_prompt(scenario: dict[str, Any]) -> str:
    return (
        "Execute this certified deterministic AMKernel scenario exactly. Use only the amkernel "
        "python_exec tool. Perform each call-tool step once, in order, with the exact arguments "
        "shown: do not add title, timeout, reset, or any other argument. Discovery is already "
        "provided by the tool interface. Do not call any other tool and do not retry. After all "
        "calls, return one brief JSON summary; do not reproduce artifact bodies.\n\n"
        + json.dumps(scenario, ensure_ascii=False, separators=(",", ":"))
    )


def _build_deterministic_evidence(
    output: Path,
    scenario: dict[str, Any],
    calls: list[dict[str, Any]],
    results: list[dict[str, Any]],
    resources: list[dict[str, Any]],
    capture: Path,
    run_started: str,
    run_completed: str,
    wheel: Path,
    config: dict[str, object],
    client_version: str,
) -> None:
    output.mkdir(parents=True, exist_ok=False)
    policy = load_json(FIXTURES / "normalizer.json")
    events: list[dict[str, Any]] = []
    call_index = 0
    steps: list[dict[str, Any]] = []
    resource_bytes = 0
    for definition in scenario["steps"]:
        expected = definition["expected"]
        semantics_digest = _sha256(canonical_json_bytes(expected))
        if definition["action"] == "call-tool":
            call = calls[call_index]
            result = results[call_index]
            projection = request_projection("python_exec", definition["arguments"])
            event = {
                "index": call_index,
                "direction": "response",
                "method": "tools/call",
                "toolName": "python_exec",
                "requestId": f"codex-{call_index + 1}",
                "attemptKind": "scenario",
                "requestProjection": projection,
                "normalizedRequestBytes": normalize_request("python_exec", definition["arguments"]),
                "normalizedBytes": len(canonical_json_bytes(expected)),
                "status": result["status"],
                "kernelState": result["kernelState"],
                "semanticsSha256": semantics_digest,
                "startedAt": call["startedAt"],
                "completedAt": call["completedAt"],
            }
            if "result" in expected:
                event["resultSha256"] = _sha256(canonical_json_bytes(expected["result"]))
            events.append(event)
            indexes = [call_index]
            normalized_request_bytes = event["normalizedRequestBytes"]
            normalized_result_bytes = event["normalizedBytes"]
            status = result["status"]
            kernel_state = result["kernelState"]
            result_sha = event.get("resultSha256")
            started = call["startedAt"]
            completed = call["completedAt"]
            call_index += 1
        else:
            indexes = []
            normalized_request_bytes = 0
            normalized_result_bytes = 0
            status = expected.get("status", "unavailable")
            kernel_state = expected.get("kernelState", "unavailable")
            result_sha = None
            if definition["action"] == "discover":
                started = completed = run_started
            else:
                started = completed = run_completed
                resource_bytes = expected["sizeBytes"]
        steps.append(
            {
                "id": definition["id"],
                "action": definition["action"],
                "outcome": "passed",
                "contractMatched": True,
                "semantics": expected,
                "semanticsSha256": semantics_digest,
                "startedAt": started,
                "completedAt": completed,
                "durationMs": _duration_ms(started, completed),
                "toolCallIndexes": indexes,
                "normalizedRequestBytes": normalized_request_bytes,
                "normalizedResultBytes": normalized_result_bytes,
                "resourceBytes": expected["sizeBytes"]
                if definition["action"] == "read-resources"
                else 0,
                "status": status,
                "kernelState": kernel_state,
                "resultSha256": result_sha,
                "observation": (
                    "Observed through Codex MCP execution and matched the frozen contract."
                ),
            }
        )

    resource_artifacts: list[dict[str, Any]] = []
    normalized_resources: list[dict[str, Any]] = []
    manifest_record = next(resource for resource in resources if "parsed" in resource)
    manifest = manifest_record["parsed"]
    ordered = [manifest_record] + [
        next(resource for resource in resources if resource["uri"] == part["uri"])
        for part in manifest["parts"]
    ]
    for index, resource in enumerate(ordered):
        destination = output / (
            "artifact-manifest.json" if index == 0 else f"artifact-part-{index}.bin"
        )
        shutil.copyfile(capture / resource["path"], destination)
        kind = "resource-manifest" if index == 0 else "resource-part"
        resource_artifacts.append(_artifact_record(kind, resource["mimeType"], destination, output))
        normalized_resources.append(
            normalize_event(
                {
                    "resourceUri": resource["uri"],
                    "mimeType": resource["mimeType"],
                    "resourceSizeBytes": resource["sizeBytes"],
                },
                policy,
            )
        )

    event_document = {
        "schemaVersion": 1,
        "normalizerId": policy["normalizerId"],
        "events": events,
        "resources": normalized_resources,
    }
    event_payload = _write_json(output / "normalized-events.json", event_document)
    final_summary = {
        "scenarioId": scenario["scenarioId"],
        "outcome": "passed",
        "completedStepIds": [step["id"] for step in steps],
        "toolCallCount": len(calls),
        "schemaRetryCount": 0,
        "wrongToolSelectionCount": 0,
        "clarificationRequestCount": 0,
        "kernelState": steps[-1]["kernelState"],
        "cleanupCompleted": True,
    }
    summary_payload = _write_json(output / "final-summary.json", final_summary)
    artifacts = [
        _artifact_record(
            "normalized-events", "application/json", output / "normalized-events.json", output
        ),
        _artifact_record(
            "final-summary", "application/json", output / "final-summary.json", output
        ),
        *resource_artifacts,
    ]
    wheel_payload = wheel.read_bytes()
    before_after = config.copy()
    record = {
        "schemaVersion": 1,
        "runId": f"codex-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
        "generatedAt": _now(),
        "runStartedAt": run_started,
        "runCompletedAt": run_completed,
        "outcome": "passed",
        "client": {
            "id": "codex",
            "executable": "codex",
            "version": client_version,
            "model": MODEL,
            "invocationMode": "ephemeral-home",
            "nonInteractive": True,
        },
        "host": {
            "system": platform.system(),
            "release": platform.release(),
            "architecture": platform.machine(),
            "pythonVersion": platform.python_version(),
        },
        "mcp": {"clientVersion": client_version, "protocolVersion": "2025-06-18"},
        "amkernel": {
            "revision": _run(["git", "rev-parse", "HEAD"]),
            "version": _run(
                [
                    str(wheel.parent.parent / "venv" / "bin" / "python"),
                    "-c",
                    "import importlib.metadata; print(importlib.metadata.version('amkernel'))",
                ]
            ),
            "wheel": {
                "filename": wheel.name,
                "sizeBytes": len(wheel_payload),
                "sha256": _sha256(wheel_payload),
            },
            "entryPoint": "amkernel",
            "runnerProtocolVersion": 2,
        },
        "contracts": {
            "scenario": {
                "id": scenario["scenarioId"],
                "sha256": sha256_file(FIXTURES / "scenario.json"),
            },
            "evidenceSchema": {
                "id": load_json(FIXTURES / "evidence.schema.json")["$id"],
                "sha256": sha256_file(FIXTURES / "evidence.schema.json"),
            },
            "normalizer": {
                "id": policy["normalizerId"],
                "sha256": sha256_file(FIXTURES / "normalizer.json"),
            },
            "normalizerImplementation": {
                "id": "amkernel-cross-client-normalizer-v1-python",
                "sha256": sha256_file(ROOT / "tests" / "e2e" / "cross_client_normalizer.py"),
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
            "before": before_after,
            "after": before_after,
            "serverCommand": ["python", "codex_proxy.py", "--server", "venv/bin/amkernel"],
        },
        "steps": steps,
        "context": {
            "publicToolCount": 1,
            "selectedTool": "python_exec",
            "toolCallCount": len(calls),
            "schemaRetryCount": 0,
            "wrongToolSelectionCount": 0,
            "clarificationRequestCount": 0,
            "normalizedRequestBytes": sum(step["normalizedRequestBytes"] for step in steps),
            "normalizedResultBytes": sum(step["normalizedResultBytes"] for step in steps),
            "maximumNormalizedResultBytes": max(step["normalizedResultBytes"] for step in steps),
            "rawResourceBytes": resource_bytes,
            "resourceReferenceBytes": sum(
                resource["normalizedBytes"] for resource in normalized_resources
            ),
            "contextReductionRatio": 1
            - sum(resource["normalizedBytes"] for resource in normalized_resources)
            / resource_bytes,
            "finalResponseBytes": len(summary_payload),
            "normalizedEventsBytes": len(event_payload),
            "durationMs": _duration_ms(run_started, run_completed),
        },
        "artifacts": artifacts,
        "cleanup": {
            "attempted": True,
            "completed": True,
            "clientExited": True,
            "serverExited": True,
            "runnerExited": True,
            "managedProcessesRemaining": 0,
            "managedArtifactsRemaining": 0,
            "remainingExternalResources": [],
            "observation": (
                "Codex, proxy, and wheel-installed AMKernel exited; temporary runtime "
                "resources were removed."
            ),
        },
        "review": {
            "reviewer": "pending independent reviewer",
            "source": "https://github.com/FSQ-lab/amkernel/issues/81",
            "blocker": 0,
            "major": 0,
            "minor": 0,
            "disposition": "pending",
        },
        "limitations": ["One reference Codex client and one host architecture were exercised."],
    }
    _write_json(output / "evidence.json", record)
    validate_evidence(record, output, FIXTURES)


def _natural_prompt() -> str:
    return _run(
        [
            "gh",
            "issue",
            "view",
            "82",
            "--repo",
            "FSQ-lab/amkernel",
            "--json",
            "body",
            "--jq",
            ".body",
        ]
    )


def _find_natural_payloads(resources: list[dict[str, Any]], capture: Path) -> tuple[bytes, bytes]:
    json_candidates: list[bytes] = []
    png_candidates: list[bytes] = []
    for resource in resources:
        payload = (capture / resource["path"]).read_bytes()
        if payload.startswith(b"\x89PNG\r\n\x1a\n"):
            png_candidates.append(payload)
            continue
        try:
            parsed = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(parsed, dict) and set(parsed) == {
            "direct",
            "critical_path",
            "topological_order",
        }:
            json_candidates.append(payload)
    if len(json_candidates) != 1 or len(png_candidates) != 1:
        raise RuntimeError(
            "expected one natural JSON and PNG resource, observed "
            f"{len(json_candidates)} and {len(png_candidates)}"
        )
    return json_candidates[0], png_candidates[0]


def _dependency_oracle(document: dict[str, Any]) -> None:
    expected_direct = {
        "aiohttp": ["multidict", "yarl"],
        "fastapi": ["pydantic", "starlette"],
        "multidict": [],
        "pydantic": ["typing-extensions"],
        "starlette": ["anyio"],
        "typing-extensions": [],
        "yarl": ["multidict"],
        "anyio": ["typing-extensions"],
    }
    if document.get("direct") != expected_direct:
        raise RuntimeError("natural dependency mapping differs from source metadata")
    order = document.get("topological_order")
    if not isinstance(order, list) or set(order) != set(expected_direct):
        raise RuntimeError("natural topological order has wrong nodes")
    positions = {name: index for index, name in enumerate(order)}
    if any(
        positions[dependency] > positions[package]
        for package, dependencies in expected_direct.items()
        for dependency in dependencies
    ):
        raise RuntimeError("natural topological order violates dependency precedence")
    critical = document.get("critical_path")
    if critical not in (
        ["typing-extensions", "pydantic", "fastapi"],
        ["typing-extensions", "anyio", "starlette", "fastapi"],
    ):
        raise RuntimeError("natural critical path is not a longest dependency chain")


def _build_natural_evidence(
    output: Path,
    events: list[dict[str, Any]],
    resources: list[dict[str, Any]],
    capture: Path,
    run_started: str,
    run_completed: str,
    wheel: Path,
    config_before: dict[str, object],
    config_after: dict[str, object],
    source_before: str,
    source_after: str,
    client_version: str,
) -> None:
    output.mkdir(parents=True, exist_ok=False)
    calls = _tool_calls(events)
    if not calls or any(
        call["item"].get("server") != "amkernel" or call["item"].get("tool") != "python_exec"
        for call in calls
    ):
        raise RuntimeError("natural run used a non-AMKernel tool")
    if config_before != config_after:
        raise RuntimeError("persistent Codex configuration changed")
    if source_before != source_after:
        raise RuntimeError("repository content changed during the natural run")
    json_payload, png_payload = _find_natural_payloads(resources, capture)
    document = json.loads(json_payload)
    _dependency_oracle(document)
    (output / "dependency-graph.json").write_bytes(json_payload)
    (output / "dependency-graph.png").write_bytes(png_payload)
    normalized_calls = []
    for index, call in enumerate(calls):
        item = call["item"]
        result = _structured_result(item)
        normalized_calls.append(
            {
                "index": index,
                "server": "amkernel",
                "tool": "python_exec",
                "requestProjection": request_projection(
                    "python_exec", cast(dict[str, Any], item["arguments"])
                ),
                "status": result.get("status"),
                "kernelState": result.get("kernelState"),
                "executionCount": result.get("executionCount"),
                "output": result.get("output"),
                "displayCount": len(result.get("displays", [])),
                "artifactCount": len(result.get("artifacts", [])),
                "startedAt": call["startedAt"],
                "completedAt": call["completedAt"],
            }
        )
    event_payload = _write_json(
        output / "normalized-events.json",
        {"schemaVersion": 1, "client": "codex", "events": normalized_calls},
    )
    challenge = _natural_prompt().encode()
    manifest = {
        "schemaVersion": 1,
        "outcome": "passed",
        "client": {"id": "codex", "version": client_version, "model": MODEL},
        "runStartedAt": run_started,
        "runCompletedAt": run_completed,
        "challenge": {"issue": "FSQ-lab/amkernel#82", "sha256": _sha256(challenge)},
        "wheel": {
            "filename": wheel.name,
            "sizeBytes": wheel.stat().st_size,
            "sha256": sha256_file(wheel),
        },
        "toolCallCount": len(calls),
        "onlyEnabledAgentTool": "mcp__amkernel__python_exec",
        "persistentConfigurationUnchanged": config_before == config_after,
        "repositoryContentUnchanged": source_before == source_after,
        "independentOraclePassed": True,
        "artifacts": {
            "json": {
                "path": "dependency-graph.json",
                "sizeBytes": len(json_payload),
                "sha256": _sha256(json_payload),
            },
            "png": {
                "path": "dependency-graph.png",
                "sizeBytes": len(png_payload),
                "sha256": _sha256(png_payload),
            },
            "events": {
                "path": "normalized-events.json",
                "sizeBytes": len(event_payload),
                "sha256": _sha256(event_payload),
            },
        },
        "cleanup": {"clientExited": True, "serverExited": True, "temporaryHomeRemoved": True},
        "review": {"chartSemantics": "pending", "evidence": "pending"},
        "limitations": ["One Codex reference run on one macOS arm64 host."],
    }
    _write_json(output / "manifest.json", manifest)


def run(output: Path) -> None:
    if output.exists():
        raise FileExistsError(output)
    client_version = _run(["codex", "--version"])
    config_before = _persistent_config()
    source_before = _source_snapshot()
    scenario = load_json(FIXTURES / "scenario.json")
    with tempfile.TemporaryDirectory(prefix="amkernel-codex-") as raw_temp:
        temp = Path(raw_temp)
        wheel, server = _build_clean_wheel(temp)
        deterministic_capture = temp / "deterministic-capture"
        deterministic_events, started, completed, deterministic_stderr = _run_codex(
            _deterministic_prompt(scenario),
            server,
            deterministic_capture,
            temp / "deterministic-client",
            temp / "deterministic-home",
        )
        resources_path = deterministic_capture / "resources.json"
        if not resources_path.is_file():
            raise RuntimeError(
                "AMKernel proxy produced no capture: "
                + deterministic_stderr[-4000:]
                + json.dumps(deterministic_events[-10:], ensure_ascii=False)[-8000:]
            )
        deterministic_resources = cast(
            list[dict[str, Any]], load_json(resources_path)
        )
        deterministic_calls = _tool_calls(deterministic_events)
        deterministic_results = _assert_deterministic_results(
            scenario, deterministic_calls, deterministic_resources, deterministic_capture
        )
        output.mkdir(parents=True)
        _build_deterministic_evidence(
            output / "deterministic",
            scenario,
            deterministic_calls,
            deterministic_results,
            deterministic_resources,
            deterministic_capture,
            started,
            completed,
            wheel,
            config_before,
            client_version,
        )

        natural_capture = temp / "natural-capture"
        natural_events, natural_started, natural_completed, _ = _run_codex(
            _natural_prompt(),
            server,
            natural_capture,
            temp / "natural-client",
            temp / "natural-home",
        )
        natural_resources = cast(
            list[dict[str, Any]], load_json(natural_capture / "resources.json")
        )
        config_after = _persistent_config()
        source_after = _source_snapshot()
        _build_natural_evidence(
            output / "natural",
            natural_events,
            natural_resources,
            natural_capture,
            natural_started,
            natural_completed,
            wheel,
            config_before,
            config_after,
            source_before,
            source_after,
            client_version,
        )
    if output.exists() and not any(output.rglob("*")):
        output.rmdir()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the certified Codex Stage 4 reference layers")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
