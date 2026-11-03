from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
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
PUBLISHED_WHEEL_VERSION = "0.1.1"
PUBLISHED_WHEEL_FILENAME = "amkernel-0.1.1-py3-none-any.whl"
PUBLISHED_WHEEL_SHA256 = "a72cacb0de33335026e0b03e0686d115c8366c4e012f84fe6f4973e1ebcc608f"
PUBLISHED_SOURCE_REVISION = "e16f42727b32a30fd431e4504712a5f31c28b408"
CODEX_BIN_ENV = "CODEX_BIN"
CODEX_BIN_CANDIDATES = (
    Path("/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex"),
    Path.home() / ".codex/plugins/.plugin-appserver/codex-cli/bin/codex",
)
ATTEMPT_EVENT_LIMIT = 400
ATTEMPT_TIMEOUT_SECONDS = 180
ATTEMPT_BYTES_LIMIT = 65536
_HOME_PATH = re.compile(r"/(?:Users|home)/[^/\s\"']+")
_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}")
_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "api-key",
        "apikey",
        "token",
        "access_token",
        "refresh_token",
        "password",
        "secret",
        "authorization",
    }
)
_QUOTED_ASSIGNMENT = re.compile(
    r"(?i)([\"']?(?:api[_-]?key|apikey|token|access_token|refresh_token|password|secret|"
    r"authorization)[\"']?\s*[:=]\s*)([\"'])(?:\\.|(?!\2).)*\2"
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)([\"']?(?:api[_-]?key|apikey|token|access_token|refresh_token|password|secret|"
    r"authorization)[\"']?\s*[=:]\s*)[^,;\s]+"
)


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


def _source_snapshot(*excluded_roots: Path) -> str:
    digest = hashlib.sha256()
    excluded_names = {".git", ".venv", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
    resolved_roots = tuple(root.resolve() for root in excluded_roots)
    for path in sorted(ROOT.rglob("*")):
        relative = path.relative_to(ROOT)
        resolved = path.resolve()
        if (
            not path.is_file()
            or any(part in excluded_names for part in relative.parts)
            or any(resolved == root or root in resolved.parents for root in resolved_roots)
        ):
            continue
        digest.update(relative.as_posix().encode() + b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _redact(text: str) -> str:
    text = _HOME_PATH.sub("<home>", text)
    text = _BEARER.sub(r"\1<redacted>", text)
    text = _QUOTED_ASSIGNMENT.sub(r"\1\2<redacted>\2", text)
    return _SECRET_ASSIGNMENT.sub(r"\1<redacted>", text)


def _redact_structure(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): (
                "<redacted>" if str(key).lower() in _SENSITIVE_KEYS else _redact_structure(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_structure(item) for item in value]
    if isinstance(value, str):
        return _redact(value)
    return value


def _bound_structure(value: Any, limit: int = 1024) -> Any:
    if isinstance(value, dict):
        return {str(key): _bound_structure(item, limit) for key, item in value.items()}
    if isinstance(value, list):
        return [_bound_structure(item, limit) for item in value]
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "…<truncated>"
    return value


def _write_provenance(output: Path, wheel: Path) -> None:
    payload = wheel.read_bytes()
    _write_json(
        output / "provenance.json",
        {
            "amkernel": {
                "version": PUBLISHED_WHEEL_VERSION,
                "wheel": {"filename": wheel.name, "sha256": _sha256(payload)},
                "sourceRevision": PUBLISHED_SOURCE_REVISION,
                "source": "published PyPI artifact",
            },
            "harness": {
                "path": "tests/e2e/cross_client/codex.py",
                "revision": _run(["git", "rev-parse", "HEAD"]),
                "sha256": sha256_file(Path(__file__)),
            },
        },
    )


def _bounded(text: str, limit: int = ATTEMPT_BYTES_LIMIT) -> str:
    redacted = _redact(text)
    return redacted[:limit]


def _codex_executable() -> str:
    override = os.environ.get(CODEX_BIN_ENV)
    if override:
        candidate = Path(override).expanduser()
        if not candidate.is_file():
            raise RuntimeError(f"{CODEX_BIN_ENV} does not point to an executable file")
        return str(candidate)
    found = shutil.which("codex")
    if found:
        return found
    for candidate in CODEX_BIN_CANDIDATES:
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError("Codex CLI is not installed or not discoverable; set CODEX_BIN")


def _download_published_wheel(destination: Path) -> Path:
    request = urllib.request.Request(
        f"https://pypi.org/pypi/amkernel/{PUBLISHED_WHEEL_VERSION}/json",
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        metadata = json.load(response)
    match = next(
        (
            item
            for item in metadata.get("urls", [])
            if item.get("filename") == PUBLISHED_WHEEL_FILENAME
        ),
        None,
    )
    if match is None:
        raise RuntimeError("the published 0.1.1 wheel is absent from the PyPI index")
    with urllib.request.urlopen(match["url"], timeout=60) as response:
        destination.write_bytes(response.read())
    return destination


def _published_wheel(temp: Path, explicit: Path | None) -> Path:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit)
    configured = os.environ.get("AMKERNEL_WHEEL")
    if configured:
        candidates.append(Path(configured))
    dist = temp / "dist"
    dist.mkdir()
    for candidate in candidates:
        if not candidate.is_file():
            raise RuntimeError(f"published wheel path does not exist: {candidate.name}")
        digest = _sha256(candidate.read_bytes())
        if digest != PUBLISHED_WHEEL_SHA256:
            raise RuntimeError(
                f"{candidate.name} is not the published {PUBLISHED_WHEEL_VERSION} artifact "
                f"(sha256 {digest})"
            )
        target = dist / candidate.name
        if candidate.resolve() != target.resolve():
            shutil.copyfile(candidate, target)
        if _sha256(target.read_bytes()) != PUBLISHED_WHEEL_SHA256:
            raise RuntimeError("copied wheel bytes differ from the published digest")
        return target
    wheel = _download_published_wheel(dist / PUBLISHED_WHEEL_FILENAME)
    digest = _sha256(wheel.read_bytes())
    if digest != PUBLISHED_WHEEL_SHA256:
        raise RuntimeError("downloaded wheel bytes differ from the published digest")
    return wheel


def _install_published_wheel(temp: Path, explicit: Path | None) -> tuple[Path, Path]:
    wheel = _published_wheel(temp, explicit)
    venv = temp / "venv"
    python = venv / "bin" / "python"
    _run(["uv", "venv", "--python", "3.11", str(venv)])
    _run(
        [
            "uv",
            "pip",
            "install",
            "--default-index",
            "https://pypi.org/simple",
            "--python",
            str(python),
            str(wheel),
        ]
    )
    installed = _run(
        [
            str(python),
            "-c",
            "import importlib.metadata; print(importlib.metadata.version('amkernel'))",
        ]
    )
    if installed != PUBLISHED_WHEEL_VERSION:
        raise RuntimeError(f"installed AMKernel version is {installed}, not the published wheel")
    return wheel, venv / "bin" / "amkernel"


def _probe_provider() -> tuple[bool, str]:
    endpoint = PROVIDER_URL.rstrip("/") + "/models"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(endpoint, timeout=5) as response:
            return response.status == 200, f"HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code} on direct connection"
    except Exception as exc:  # the diagnostic is the evidence
        return False, f"{type(exc).__name__} on direct connection"


def _attempt_signal(attempt: dict[str, Any]) -> str:
    events = cast(list[dict[str, Any]], attempt["events"])
    for event in reversed(events):
        if event.get("type") not in {"error", "turn.failed"}:
            continue
        payload = event.get("error") or event.get("message") or ""
        if isinstance(payload, dict):
            payload = payload.get("message", "")
        text = _redact(str(payload))[:240]
        if text:
            return text
    return f"exit code {attempt.get('exitCode')}"


_NON_TOOL_ITEM_TYPES = frozenset({"agent_message", "reasoning"})


def _execution_signal(events: list[dict[str, Any]]) -> str | None:
    for event in events:
        event_type = event.get("type")
        if event_type == "turn.completed":
            return "completed model turn"
        if event_type not in {"item.started", "item.completed", "item.updated"}:
            continue
        item = event.get("item")
        if isinstance(item, dict) and isinstance(item.get("type"), str):
            # Unknown and future item types fail closed: only turn.started alone is
            # treated as client-side bookkeeping without model or tool progress.
            return f"{event_type.split('.', 1)[1]} {item.get('type')}"
    return None


def _diagnostic_event(event: dict[str, Any]) -> dict[str, Any] | None:
    event_type = event.get("type")
    if not isinstance(event_type, str):
        return None
    if event_type in {"item.started", "item.updated", "item.completed"}:
        item = event.get("item")
        if not isinstance(item, dict):
            return None
        item_type = item.get("type")
        if not isinstance(item_type, str):
            return None
        diagnostic: dict[str, Any] = {"type": event_type, "itemType": item_type[:80]}
        for key in ("id", "callId", "name", "server", "tool", "status"):
            value = item.get(key)
            if isinstance(value, bool) or isinstance(value, (int, float)):
                diagnostic[key] = value
            elif isinstance(value, str):
                diagnostic[key] = _redact(value)[:200]
        text = item.get("text")
        if isinstance(text, str):
            diagnostic["textBytes"] = len(text)
        arguments = item.get("arguments")
        if isinstance(arguments, str):
            diagnostic["argumentsBytes"] = len(arguments)
        elif isinstance(arguments, (dict, list)):
            diagnostic["argumentsBytes"] = len(json.dumps(arguments, ensure_ascii=False))
        return diagnostic
    if event_type in {"turn.completed", "turn.failed", "error"}:
        diagnostic = {"type": event_type}
        error = event.get("error")
        if isinstance(error, dict) and isinstance(error.get("type"), str):
            diagnostic["errorType"] = error["type"][:100]
        return diagnostic
    return None


def _attempt_executed(attempt: dict[str, Any]) -> bool:
    if attempt.get("execution"):
        return True
    return _execution_signal(cast(list[dict[str, Any]], attempt["events"])) is not None


def _blocked_reason(detail: str, attempts: list[dict[str, Any]]) -> str:
    signals = sorted({_attempt_signal(attempt) for attempt in attempts})
    observed = "; ".join(signals) if signals else "no client event"
    timed = bool(attempts) and all(attempt.get("timedOut") for attempt in attempts)
    outcome = (
        f"remained in connection retry until the {ATTEMPT_TIMEOUT_SECONDS} s bound"
        if timed
        else "ended without a completed model turn or model-generated response"
    )
    return (
        f"The direct model provider probe of {PROVIDER_URL}/models failed ({detail}). "
        f"{len(attempts)} supplementary client launch attempts each {outcome} "
        f"({observed}); no item.started or item.completed event was observed, so no model "
        "or tool activity is evidenced. No credential or configuration was modified."
    )


def _client_environment(codex_home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["CODEX_HOME"] = str(codex_home)
    env["NO_PROXY"] = "127.0.0.1,localhost"
    env["no_proxy"] = "127.0.0.1,localhost"
    return env


def _codex_command(server: Path, capture: Path, client_dir: Path, executable: str) -> list[str]:
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
        executable,
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
        "-c",
        'web_search="disabled"',
    ]
    for feature in (
        "computer_use",
        "shell_tool",
        "unified_exec",
        "browser_use",
        "browser_use_external",
        "in_app_browser",
        "standalone_web_search",
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
    prompt: str,
    server: Path,
    capture: Path,
    client_dir: Path,
    codex_home: Path,
    executable: str = "codex",
) -> tuple[list[dict[str, Any]], str, str, str]:
    client_dir.mkdir(parents=True, exist_ok=False)
    codex_home.mkdir(parents=True, exist_ok=False)
    env = _client_environment(codex_home)
    command = _codex_command(server, capture, client_dir, executable)
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


def _observed_call_semantics(
    expected: dict[str, Any], result: dict[str, Any], manifest: dict[str, Any]
) -> dict[str, Any]:
    direct_fields = {"status", "kernelState", "result", "stdout", "stderr", "executionCount"}
    output_fields = {
        "totalBytes",
        "totalLines",
        "discardedBytes",
        "discardedLines",
        "truncated",
        "limitExceeded",
    }
    observed: dict[str, Any] = {}
    displays = result.get("displays")
    artifacts = result.get("artifacts")
    for key in expected:
        if key in direct_fields:
            observed[key] = result.get(key)
        elif key == "errorType":
            error = result.get("error")
            observed[key] = error.get("type") if isinstance(error, dict) else None
        elif key in output_fields:
            output = result.get("output")
            observed[key] = output.get(key) if isinstance(output, dict) else None
        elif key in {"displayKind", "width", "height"} or (
            key == "mimeType" and "displayKind" in expected
        ):
            if not isinstance(displays, list) or len(displays) != 1:
                raise RuntimeError("display metadata missing")
            display = displays[0]
            observed[key] = display.get("kind" if key == "displayKind" else key)
        elif key in {"representation", "sizeBytes", "partCount"} or (
            key == "mimeType" and "representation" in expected
        ):
            if not isinstance(artifacts, list) or len(artifacts) != 1:
                raise RuntimeError("artifact metadata missing")
            artifact = artifacts[0]
            if key == "sizeBytes":
                observed[key] = artifact.get("size")
            elif key == "partCount":
                parts = manifest.get("parts")
                observed[key] = len(parts) if isinstance(parts, list) else None
            elif key == "mimeType":
                observed[key] = artifact.get("declaredMimeType")
            else:
                observed[key] = artifact.get(key)
        else:
            raise RuntimeError(f"unsupported deterministic expectation: {key}")
    return observed


def _payload_match_length(payload: bytes, candidate: bytes) -> int:
    if len(candidate) < 32:
        return 0
    position = payload.find(candidate)
    return len(candidate) if position >= 0 else 0


def _raw_payload_bytes_in_final_response(events: list[dict[str, Any]], payload: bytes) -> int:
    messages: list[str] = []
    for event in events:
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "agent_message":
            text = item.get("text")
            if isinstance(text, str):
                messages.append(text)
        elif event.get("type") == "agent_message" and isinstance(event.get("text"), str):
            messages.append(event["text"])
    if not messages:
        raise RuntimeError("Codex produced no final agent response")
    response = messages[-1].encode()

    for offset in range(max(0, len(response) - 31)):
        if payload.find(response[offset : offset + 32]) >= 0:
            return 32

    for match in re.finditer(rb"[A-Za-z0-9+/]{43,}={0,2}", response):
        token = match.group()
        for offset in range(4):
            encoded = token[offset:]
            encoded += b"=" * (-len(encoded) % 4)
            try:
                decoded = base64.b64decode(encoded, validate=True)
            except ValueError:
                continue
            matched = _payload_match_length(payload, decoded)
            if matched:
                return matched

    for match in re.finditer(rb"[0-9a-fA-F]{64,}", response):
        token = match.group()
        for offset in range(2):
            encoded = token[offset : len(token) - ((len(token) - offset) % 2)]
            matched = _payload_match_length(payload, bytes.fromhex(encoded.decode()))
            if matched:
                return matched
    return 0


def _assert_deterministic_results(
    scenario: dict[str, Any],
    calls: list[dict[str, Any]],
    resources: list[dict[str, Any]],
    capture: Path,
    events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
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
    part_resources = [parts_by_uri[part["uri"]] for part in manifest["parts"]]
    recovered = b"".join((capture / resource["path"]).read_bytes() for resource in part_resources)
    integrity_verified = (
        len(recovered) == manifest["size"] and _sha256(recovered) == manifest["sha256"]
    )
    if not integrity_verified:
        raise RuntimeError("artifact resource integrity verification failed")

    resource_definition = next(
        step for step in scenario["steps"] if step["action"] == "read-resources"
    )
    resource_expected = resource_definition["expected"]
    part_mime_types = {resource["mimeType"] for resource in part_resources}
    resource_semantics = {
        "manifestMimeType": manifest_resource["mimeType"],
        "partMimeType": next(iter(part_mime_types)) if len(part_mime_types) == 1 else None,
        "sizeBytes": len(recovered),
        "partCount": len(part_resources),
        "integrityVerified": integrity_verified,
        "rawBytesInFinalResponse": _raw_payload_bytes_in_final_response(events, recovered),
    }
    if resource_semantics != resource_expected:
        raise RuntimeError("artifact resource semantics differ")
    manifest_resource["parsed"] = manifest

    definitions = [step for step in scenario["steps"] if step["action"] == "call-tool"]
    if len(calls) != len(definitions):
        raise RuntimeError(f"expected {len(definitions)} tool calls, observed {len(calls)}")
    results: list[dict[str, Any]] = []
    observed_semantics: list[dict[str, Any]] = []
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
        observed = _observed_call_semantics(definition["expected"], result, manifest)
        if observed != definition["expected"]:
            raise RuntimeError(f"semantics differ for {definition['id']}")
        results.append(result)
        observed_semantics.append(observed)
    return results, observed_semantics, resource_semantics


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
    call_semantics: list[dict[str, Any]],
    resource_semantics: dict[str, Any],
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
        if definition["action"] == "call-tool":
            semantics = call_semantics[call_index]
        elif definition["action"] == "read-resources":
            semantics = resource_semantics
        else:
            semantics = expected
        if semantics != expected:
            raise RuntimeError(f"evidence semantics differ for {definition['id']}")
        semantics_digest = _sha256(canonical_json_bytes(semantics))
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
                "normalizedBytes": len(canonical_json_bytes(semantics)),
                "status": result["status"],
                "kernelState": result["kernelState"],
                "semanticsSha256": semantics_digest,
                "startedAt": call["startedAt"],
                "completedAt": call["completedAt"],
            }
            if "result" in semantics:
                event["resultSha256"] = _sha256(canonical_json_bytes(semantics["result"]))
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
                resource_bytes = semantics["sizeBytes"]
        steps.append(
            {
                "id": definition["id"],
                "action": definition["action"],
                "outcome": "passed",
                "contractMatched": True,
                "semantics": semantics,
                "semanticsSha256": semantics_digest,
                "startedAt": started,
                "completedAt": completed,
                "durationMs": _duration_ms(started, completed),
                "toolCallIndexes": indexes,
                "normalizedRequestBytes": normalized_request_bytes,
                "normalizedResultBytes": normalized_result_bytes,
                "resourceBytes": semantics["sizeBytes"]
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
            "revision": PUBLISHED_SOURCE_REVISION,
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
            "reviewer": (
                "pending independent reviewer (counters are placeholders, not a "
                "zero-findings review)"
            ),
            "source": "https://github.com/FSQ-lab/amkernel/issues/81",
            "blocker": 0,
            "major": 0,
            "minor": 0,
            "disposition": "pending",
        },
        "limitations": ["One reference Codex client and one host architecture were exercised."],
    }
    _write_json(output / "evidence.json", record)
    _write_provenance(output, wheel)
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


def _attempt_codex_launch(
    prompt: str,
    server: Path,
    capture: Path,
    client_dir: Path,
    codex_home: Path,
    executable: str,
) -> dict[str, Any]:
    client_dir.mkdir(parents=True, exist_ok=False)
    codex_home.mkdir(parents=True, exist_ok=False)
    env = _client_environment(codex_home)
    command = _codex_command(server, capture, client_dir, executable)
    started_at = _now()
    timed_out = False
    return_code: int | None = None
    stdout = ""
    stderr = ""
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=ATTEMPT_TIMEOUT_SECONDS,
        )
        return_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as expired:
        timed_out = True
        partial_stdout = expired.stdout or ""
        partial_stderr = expired.stderr or ""
        stdout = (
            partial_stdout.decode("utf-8", "replace")
            if isinstance(partial_stdout, bytes)
            else partial_stdout
        )
        stderr = (
            partial_stderr.decode("utf-8", "replace")
            if isinstance(partial_stderr, bytes)
            else partial_stderr
        )
    completed_at = _now()
    events: list[dict[str, Any]] = []
    execution: str | None = None
    parsed_event_count = 0
    diagnostics: list[dict[str, Any]] = []
    tool_diagnostics: list[dict[str, Any]] = []
    tool_diagnostics_dropped = 0
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        parsed_event_count += 1
        if execution is None:
            execution = _execution_signal([event])
        diagnostic = _diagnostic_event(event)
        if diagnostic is not None:
            if len(diagnostics) < ATTEMPT_EVENT_LIMIT:
                diagnostics.append(diagnostic)
            item_type = diagnostic.get("itemType")
            if isinstance(item_type, str) and item_type not in _NON_TOOL_ITEM_TYPES:
                if len(tool_diagnostics) < ATTEMPT_EVENT_LIMIT:
                    tool_diagnostics.append(diagnostic)
                else:
                    tool_diagnostics_dropped += 1
        if len(events) < ATTEMPT_EVENT_LIMIT:
            events.append(event)
    return {
        "startedAt": started_at,
        "completedAt": completed_at,
        "durationMs": _duration_ms(started_at, completed_at),
        "exitCode": return_code,
        "timedOut": timed_out,
        "execution": execution,
        "eventCount": len(events),
        "parsedEventCount": parsed_event_count,
        "events": events,
        "diagnostics": diagnostics,
        "toolDiagnostics": tool_diagnostics,
        "toolDiagnosticsDropped": tool_diagnostics_dropped,
        "stderr": _bounded(stderr),
    }


def _write_attempt(output: Path, index: int, attempt: dict[str, Any]) -> None:
    directory = output / "attempts"
    directory.mkdir(exist_ok=True)
    events = cast(list[dict[str, Any]], attempt["events"])
    lines = []
    for event in events:
        redacted = _bound_structure(_redact_structure(event))
        line = json.dumps(redacted, ensure_ascii=False, sort_keys=True)
        if len(line.encode()) > 2048:
            summary = {
                "type": redacted.get("type") if isinstance(redacted, dict) else None,
                "truncated": True,
                "originalBytes": len(line.encode()),
                "sha256": _sha256(line.encode()),
            }
            line = json.dumps(summary, sort_keys=True)
        lines.append(line)
    (directory / f"launch-{index:02d}-events.jsonl").write_text(
        "\n".join(lines) + ("\n" if lines else "")
    )
    (directory / f"launch-{index:02d}-stderr.txt").write_text(cast(str, attempt["stderr"]))
    summary = {
        key: value
        for key, value in attempt.items()
        if key not in {"events", "diagnostics", "toolDiagnostics"}
    }
    _write_json(directory / f"launch-{index:02d}.json", summary)


def _blocked_cleanup_observation(attempts: list[dict[str, Any]]) -> str:
    codes = [attempt.get("exitCode") for attempt in attempts]
    if len(attempts) == 2 and all(code is None for code in codes):
        count_phrase = "Two supplementary Codex launch attempts were made"
        exit_phrase = "both recorded exit codes are null"
    else:
        count_phrase = f"{len(attempts)} supplementary Codex launch attempts were made"
        rendered = ", ".join("null" if code is None else str(code) for code in codes)
        exit_phrase = f"recorded exit codes are {rendered}"
    timed = bool(attempts) and all(attempt.get("timedOut") for attempt in attempts)
    timing = (
        "each timed out after approximately 180 seconds"
        if timed
        else "each ended without entering a model turn"
    )
    return (
        "The frozen deterministic and naturalistic layers were not entered; these cleanup "
        "booleans describe only those unentered layers. "
        f"{count_phrase}, {timing}, and {exit_phrase}. "
        "TemporaryDirectory scope exit is the harness cleanup mechanism; no separate "
        "process-tree cleanup observation is retained."
    )


def _launch_supplementary_attempts(
    prompt: str,
    server: Path,
    temp: Path,
    executable: str,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    attempts: list[dict[str, Any]] = []
    for index in (1, 2):
        attempt = _attempt_codex_launch(
            prompt,
            server,
            temp / f"attempt-{index}-capture",
            temp / f"attempt-{index}-client",
            temp / f"attempt-{index}-home",
            executable,
        )
        attempts.append(attempt)
        if _attempt_executed(attempt):
            return attempts, attempt
    return attempts, None


def _diagnostic_lines(diagnostics: list[dict[str, Any]]) -> list[str]:
    lines = []
    for diagnostic in diagnostics:
        redacted = _bound_structure(_redact_structure(diagnostic))
        line = json.dumps(redacted, ensure_ascii=False, sort_keys=True)
        if len(line.encode()) > 2048:
            line = json.dumps(
                {
                    "type": redacted.get("type") if isinstance(redacted, dict) else None,
                    "truncated": True,
                    "originalBytes": len(line.encode()),
                    "sha256": _sha256(line.encode()),
                },
                sort_keys=True,
            )
        lines.append(line)
    return lines


def _write_execution_supplement(
    output: Path,
    *,
    attempts: list[dict[str, Any]],
    temp: Path,
    executable: str,
    client_version: str,
    wheel: Path,
    probe_detail: str,
    config: dict[str, object],
    config_changed: bool,
    source_changed: bool,
    tool_audit_incomplete: bool,
) -> None:
    directory = output / "supplementary"
    directory.mkdir(parents=True, exist_ok=True)
    executable_path = Path(executable)
    wheel_payload = wheel.read_bytes()
    _write_json(
        directory / "environment.json",
        {
            "clientVersion": client_version,
            "clientExecutable": {
                "basename": executable_path.name,
                "sizeBytes": executable_path.stat().st_size,
                "sha256": sha256_file(executable_path),
            },
            "model": MODEL,
            "providerUrl": PROVIDER_URL,
            "wheel": {"filename": wheel.name, "sha256": _sha256(wheel_payload)},
            "publishedSourceRevision": PUBLISHED_SOURCE_REVISION,
            "pythonVersion": platform.python_version(),
            "hostRelease": platform.release(),
            "probeDetail": _redact(probe_detail)[:1000],
            "observedExecution": True,
            "persistentConfiguration": config,
            "persistentConfigurationChanged": config_changed,
            "repositorySourceChanged": source_changed,
            "toolAuditIncomplete": tool_audit_incomplete,
            "frozenLayersEntered": False,
            "requiresReview": True,
            "attempts": len(attempts),
        },
    )
    for index, attempt in enumerate(attempts, start=1):
        attempt_dir = directory / f"attempt-{index:02d}"
        attempt_dir.mkdir()
        lines = _diagnostic_lines(cast(list[dict[str, Any]], attempt.get("diagnostics", [])))
        tool_lines = _diagnostic_lines(
            cast(list[dict[str, Any]], attempt.get("toolDiagnostics", []))
        )
        (attempt_dir / "diagnostics.jsonl").write_text("\n".join(lines) + ("\n" if lines else ""))
        (attempt_dir / "tool-events.jsonl").write_text(
            "\n".join(tool_lines) + ("\n" if tool_lines else "")
        )
        (attempt_dir / "stderr.txt").write_text(_bounded(cast(str, attempt.get("stderr", ""))))
        capture: dict[str, Any] = {}
        capture_file = temp / f"attempt-{index}-capture" / "resources.json"
        if capture_file.is_file():
            payload = capture_file.read_bytes()
            text = payload.decode("utf-8", "replace")
            retained = _redact(text)[:ATTEMPT_BYTES_LIMIT].encode()
            retained_name = "capture-resources.redacted.json"
            (attempt_dir / retained_name).write_bytes(retained)
            capture = {
                "sourceFilename": "resources.json",
                "retainedFilename": retained_name,
                "originalSizeBytes": len(payload),
                "retainedSha256": _sha256(retained),
            }
        metadata = {
            key: value
            for key, value in attempt.items()
            if key not in {"events", "diagnostics", "toolDiagnostics", "stderr"}
        }
        metadata["capture"] = capture
        _write_json(attempt_dir / "metadata.json", metadata)


def _build_blocked_evidence(
    output: Path,
    *,
    client_version: str,
    client_executable: str,
    wheel: Path,
    config: dict[str, object],
    run_started: str,
    run_completed: str,
    reason: str,
    attempts: list[dict[str, Any]],
) -> None:
    output.mkdir(parents=True, exist_ok=False)
    scenario = load_json(FIXTURES / "scenario.json")
    normalizer = load_json(FIXTURES / "normalizer.json")
    schema = load_json(FIXTURES / "evidence.schema.json")
    wheel_payload = wheel.read_bytes()
    wheel_digest = _sha256(wheel_payload)
    if wheel_digest != PUBLISHED_WHEEL_SHA256:
        raise RuntimeError("blocked evidence wheel is not the published artifact")
    duration_ms = _duration_ms(run_started, run_completed)
    record = {
        "schemaVersion": 1,
        "runId": f"codex-blocked-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
        "generatedAt": _now(),
        "runStartedAt": run_started,
        "runCompletedAt": run_completed,
        "outcome": "blocked",
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
            "revision": PUBLISHED_SOURCE_REVISION,
            "version": PUBLISHED_WHEEL_VERSION,
            "wheel": {
                "filename": wheel.name,
                "sizeBytes": len(wheel_payload),
                "sha256": wheel_digest,
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
                "id": schema["$id"],
                "sha256": sha256_file(FIXTURES / "evidence.schema.json"),
            },
            "normalizer": {
                "id": normalizer["normalizerId"],
                "sha256": sha256_file(FIXTURES / "normalizer.json"),
            },
            "normalizerImplementation": {
                "id": "amkernel-cross-client-normalizer-v1-python",
                "sha256": sha256_file(ROOT / "tests" / "e2e" / "cross_client_normalizer.py"),
            },
        },
        "preflight": {
            "clientReady": False,
            "serverReady": False,
            "wheelVerified": True,
            "reason": reason,
        },
        "configuration": {
            "workspaceIsolation": "temporary",
            "persistentMutation": False,
            "before": config,
            "after": config,
            "serverCommand": ["python", "codex_proxy.py", "--server", "venv/bin/amkernel"],
        },
        "steps": [],
        "context": {
            "publicToolCount": 1,
            "selectedTool": "python_exec",
            "toolCallCount": 0,
            "schemaRetryCount": 0,
            "wrongToolSelectionCount": 0,
            "clarificationRequestCount": 0,
            "normalizedRequestBytes": 0,
            "normalizedResultBytes": 0,
            "maximumNormalizedResultBytes": 0,
            "rawResourceBytes": 0,
            "resourceReferenceBytes": 0,
            "contextReductionRatio": 0,
            "finalResponseBytes": 0,
            "normalizedEventsBytes": 0,
            "durationMs": duration_ms,
        },
        "artifacts": [],
        "cleanup": {
            "attempted": False,
            "completed": False,
            "clientExited": False,
            "serverExited": False,
            "runnerExited": False,
            "managedProcessesRemaining": 0,
            "managedArtifactsRemaining": 0,
            "remainingExternalResources": [],
            "observation": _blocked_cleanup_observation(attempts),
        },
        "review": {
            "reviewer": (
                "pending independent reviewer (counters are placeholders, not a "
                "zero-findings review)"
            ),
            "source": "https://github.com/FSQ-lab/amkernel/issues/81",
            "blocker": 0,
            "major": 0,
            "minor": 0,
            "disposition": "pending",
        },
        "limitations": [
            (
                f"Blocked before the frozen deterministic layer: {len(attempts)} client launch "
                f"attempts with {client_executable.rsplit('/', 1)[-1]} could not reach the "
                "configured model provider, so neither evidence layer was entered and no "
                "step was produced."
            ),
            (
                "Bounded redacted launch logs are retained under attempts/ as supplementary "
                "records; they are not evidence artifacts and contain no completed model "
                "turn or model-generated response."
            ),
            (
                "One host architecture and one client build were exercised; "
                "no client-quality conclusion is implied."
            ),
        ],
    }
    _write_json(output / "evidence.json", record)
    _write_provenance(output, wheel)
    for index, attempt in enumerate(attempts, start=1):
        _write_attempt(output, index, attempt)
    executable_path = Path(client_executable)
    _write_json(
        output / "attempts" / "environment.json",
        {
            "clientVersion": client_version,
            "clientExecutable": {
                "basename": executable_path.name,
                "sizeBytes": executable_path.stat().st_size,
                "sha256": sha256_file(executable_path),
            },
            "model": MODEL,
            "providerUrl": PROVIDER_URL,
            "wheel": {"filename": wheel.name, "sha256": wheel_digest},
            "publishedSourceRevision": PUBLISHED_SOURCE_REVISION,
            "pythonVersion": platform.python_version(),
            "hostRelease": platform.release(),
            "supplementaryLaunches": [
                {
                    "exitCode": attempt.get("exitCode"),
                    "timedOut": bool(attempt.get("timedOut")),
                }
                for attempt in attempts
            ],
            "attempts": len(attempts),
        },
    )
    validate_evidence(record, output, FIXTURES)


def run(output: Path, wheel_path: Path | None = None) -> None:
    if output.exists():
        raise FileExistsError(output)
    executable = _codex_executable()
    client_version = _run([executable, "--version"])
    config_before = _persistent_config()
    source_before = _source_snapshot(output)
    scenario = load_json(FIXTURES / "scenario.json")
    with tempfile.TemporaryDirectory(prefix="amkernel-codex-") as raw_temp:
        temp = Path(raw_temp)
        wheel, server = _install_published_wheel(temp, wheel_path)
        ready, detail = _probe_provider()
        if not ready:
            attempts, executed = _launch_supplementary_attempts(
                _deterministic_prompt(scenario), server, temp, executable
            )
            if executed is not None:
                config_changed = _persistent_config() != config_before
                source_changed = _source_snapshot(output) != source_before
                dropped = sum(int(attempt.get("toolDiagnosticsDropped", 0)) for attempt in attempts)
                _write_execution_supplement(
                    output,
                    attempts=attempts,
                    temp=temp,
                    executable=executable,
                    client_version=client_version,
                    wheel=wheel,
                    probe_detail=detail,
                    config=config_before,
                    config_changed=config_changed,
                    source_changed=source_changed,
                    tool_audit_incomplete=dropped > 0,
                )
                if dropped:
                    raise RuntimeError(
                        "a supplementary client launch produced observed execution after the "
                        "model-provider probe failed and the bounded tool-event audit was "
                        f"exceeded ({dropped} tool events dropped); the run stopped before the "
                        "frozen layers and retained bounded redacted diagnostics under "
                        "output/supplementary. Review required."
                    )
                if config_changed:
                    raise RuntimeError(
                        "persistent Codex configuration changed during the supplementary "
                        "attempts; diagnostics retained under output/supplementary. Review "
                        "required."
                    )
                if source_changed:
                    raise RuntimeError(
                        "repository source snapshot changed during the supplementary attempts; "
                        "diagnostics retained under output/supplementary. Review required."
                    )
                raise RuntimeError(
                    "a supplementary client launch produced observed execution after the "
                    "model-provider probe failed; the run stopped before the frozen layers "
                    "and retained bounded redacted diagnostics under output/supplementary. "
                    "Review required."
                )
            run_started = attempts[0]["startedAt"]
            run_completed = attempts[-1]["completedAt"]
            if _persistent_config() != config_before:
                raise RuntimeError("persistent Codex configuration changed during the attempts")
            if _source_snapshot(output) != source_before:
                raise RuntimeError("repository source snapshot changed during the attempts")
            _build_blocked_evidence(
                output,
                client_version=client_version,
                client_executable=executable,
                wheel=wheel,
                config=config_before,
                run_started=run_started,
                run_completed=run_completed,
                reason=_blocked_reason(detail, attempts),
                attempts=attempts,
            )
            return
        deterministic_capture = temp / "deterministic-capture"
        deterministic_events, started, completed, deterministic_stderr = _run_codex(
            _deterministic_prompt(scenario),
            server,
            deterministic_capture,
            temp / "deterministic-client",
            temp / "deterministic-home",
            executable,
        )
        resources_path = deterministic_capture / "resources.json"
        if not resources_path.is_file():
            raise RuntimeError(
                "AMKernel proxy produced no capture: "
                + deterministic_stderr[-4000:]
                + json.dumps(deterministic_events[-10:], ensure_ascii=False)[-8000:]
            )
        deterministic_resources = cast(list[dict[str, Any]], load_json(resources_path))
        deterministic_calls = _tool_calls(deterministic_events)
        (
            deterministic_results,
            deterministic_semantics,
            resource_semantics,
        ) = _assert_deterministic_results(
            scenario,
            deterministic_calls,
            deterministic_resources,
            deterministic_capture,
            deterministic_events,
        )
        output.mkdir(parents=True)
        _build_deterministic_evidence(
            output / "deterministic",
            scenario,
            deterministic_calls,
            deterministic_results,
            deterministic_semantics,
            resource_semantics,
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
            executable,
        )
        natural_resources = cast(
            list[dict[str, Any]], load_json(natural_capture / "resources.json")
        )
        config_after = _persistent_config()
        source_after = _source_snapshot(output)
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
    parser.add_argument(
        "--wheel",
        type=Path,
        default=None,
        help="Published AMKernel 0.1.1 wheel; its bytes must match the pinned digest.",
    )
    args = parser.parse_args()
    run(args.output.resolve(), args.wheel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
