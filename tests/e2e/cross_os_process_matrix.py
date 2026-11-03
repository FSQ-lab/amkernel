"""Execute the frozen cross-OS process matrix against one installed AMKernel wheel.

This harness intentionally observes the public MCP surface plus same-user process
identity.  It never imports ``amkernel`` from the source tree at runtime: the
entry point, Python interpreter, and wheel identity are supplied by the caller
and are the objects whose lifecycle is observed.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import secrets
import shutil
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, cast

from mcp.client import Client
from mcp.client.stdio import StdioServerParameters
from mcp.shared.exceptions import MCPError

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.e2e.installed_stdio import (  # noqa: E402
    pid_exists,
    process_metrics,
    read_resource,
    structured_rich,
    verify_manifest,
    wait_pid_gone,
)

SCHEMA_VERSION = 1
ROW_TIMEOUT_SECONDS = 360.0
CLEANUP_TIMEOUT_SECONDS = 15.0
STORE_ROOT_PREFIX = "amkernel-"
HOSTED = os.environ.get("GITHUB_ACTIONS") == "true"

IDENTITY_CODE = (
    "import os\n"
    "{'runner': os.getpid(), 'server': os.getppid(), 'group': os.getpgrp()}\n"
)

STUBBORN_CHILD_CODE = """import os, signal, subprocess, sys, time

def ignore(signum, frame):
    pass

for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
    signal.signal(signum, ignore)

child = subprocess.Popen(
    [sys.executable, "-c",
     "import signal,time\\n"
     "def ignore(signum, frame): pass\\n"
     "signal.signal(signal.SIGINT, ignore)\\n"
     "signal.signal(signal.SIGTERM, ignore)\\n"
     "while True: time.sleep(0.2)"]
)
with open("active-identity.json", "w", encoding="utf-8") as handle:
    import json
    handle.write(json.dumps({
        "server": os.getppid(),
        "runner": os.getpid(),
        "group": os.getpgrp(),
        "child": child.pid,
        "childGroup": os.getpgid(child.pid),
    }))
while True:
    time.sleep(0.2)
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_protocol_constant(source_root: Path, name: str) -> int:
    text = (source_root / "src" / "amkernel" / "protocol.py").read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(name)}: Final = ([\d_]+)$", text, flags=re.MULTILINE)
    if match is None:
        raise RuntimeError(f"source constant {name} is missing")
    return int(match.group(1).replace("_", ""))


def store_roots(tmpdir: Path) -> list[Path]:
    if not tmpdir.exists():
        return []
    return sorted(path for path in tmpdir.iterdir() if path.name.startswith(STORE_ROOT_PREFIX))


def measure_store(tmpdir: Path) -> dict[str, int | bool]:
    total = 0
    files = 0
    roots = store_roots(tmpdir)
    for root in roots:
        for directory, _dirnames, filenames in os.walk(root, followlinks=False):
            for filename in filenames:
                path = Path(directory) / filename
                try:
                    stat = path.lstat()
                except FileNotFoundError:
                    continue
                if path.is_symlink():
                    continue
                total += stat.st_size
                files += 1
    return {
        "artifactRoots": len(roots),
        "artifactFiles": files,
        "managedBytes": total,
        "artifactRootRemoved": not roots,
    }


def group_exists(group: int) -> bool:
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class ManagedProcesses:
    """Tokenized process observations for one matrix row."""

    def __init__(self, tmpdir: Path, salt: str) -> None:
        self.tmpdir = tmpdir
        self.salt = salt
        self.server: int | None = None
        self.runner: int | None = None
        self.group: int | None = None
        self.extra: list[tuple[str, int]] = []

    def token(self, kind: str, value: int) -> str:
        return hashlib.sha256(f"{self.salt}:{kind}:{value}".encode()).hexdigest()[:16]

    def register(self, identity: dict[str, Any], *, runner_key: str = "runner") -> None:
        runner = identity.get(runner_key)
        server = identity.get("server")
        group = identity.get("group")
        if isinstance(runner, int):
            self.runner = runner
        if isinstance(server, int):
            self.server = server
        if isinstance(group, int):
            self.group = group
        self.group = self.runner if self.group is None else self.group
        child = identity.get("child")
        if isinstance(child, int):
            self.extra.append(("child", child))

    def _record(self, role: str, pid: int | None) -> dict[str, Any]:
        if pid is None:
            return {"role": role, "token": None, "alive": False}
        return {"role": role, "token": self.token("pid", pid), "alive": pid_exists(pid)}

    def snapshot(self, phase: str) -> dict[str, Any]:
        records = [self._record("server", self.server), self._record("runner", self.runner)]
        records.extend(self._record(role, pid) for role, pid in self.extra)
        managed = sum(1 for record in records if record["alive"])
        descendant_count = 0
        if self.server is not None and pid_exists(self.server):
            try:
                descendant_count = process_metrics(self.server)["childProcessCount"]
            except (OSError, subprocess.SubprocessError, ValueError):
                descendant_count = -1
        return {
            "phase": phase,
            "at": utc_now(),
            "processes": records,
            "processGroup": {
                "token": None if self.group is None else self.token("group", self.group),
                "exists": self.group is not None and group_exists(self.group),
            },
            "managedProcessCount": managed,
            "serverDescendantCount": descendant_count,
        }

    async def finalize(self) -> dict[str, Any]:
        known = [pid for pid in (self.server, self.runner) if pid is not None]
        known.extend(pid for _role, pid in self.extra)
        deadline = time.monotonic() + CLEANUP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if all(not pid_exists(pid) for pid in known) and (
                self.group is None or not group_exists(self.group)
            ):
                break
            await asyncio.sleep(0.05)
        forced = False
        if any(pid_exists(pid) for pid in known) or (
            self.group is not None and group_exists(self.group)
        ):
            forced = True
            if self.group is not None:
                try:
                    os.killpg(self.group, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            for pid in known:
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            await asyncio.sleep(0.2)
            for pid in known:
                await wait_pid_gone(pid, timeout=2.0)
        server_exited = self.server is not None and not pid_exists(self.server)
        runner_exited = self.runner is not None and not pid_exists(self.runner)
        group_removed = self.group is not None and not group_exists(self.group)
        remaining = sum(1 for pid in known if pid_exists(pid))
        if self.group is not None and group_exists(self.group):
            remaining += 1
        store = measure_store(self.tmpdir)
        completed = (
            self.server is not None
            and self.runner is not None
            and server_exited
            and runner_exited
            and group_removed
            and remaining == 0
            and bool(store["artifactRootRemoved"])
            and not forced
        )
        return {
            "attempted": True,
            "completed": completed,
            "serverExited": server_exited,
            "runnerExited": runner_exited,
            "processGroupRemoved": group_removed,
            "managedProcessesRemaining": remaining,
            "managedArtifactsRemaining": int(store["artifactFiles"]),
            "artifactRootRemoved": bool(store["artifactRootRemoved"]),
            "forcedCleanup": forced,
        }


@dataclass
class RowCell:
    row: dict[str, Any]
    observed: dict[str, Any] = field(default_factory=dict)
    transitions: list[dict[str, Any]] = field(default_factory=list)
    process_observations: list[dict[str, Any]] = field(default_factory=list)
    resource_observations: dict[str, Any] = field(default_factory=dict)
    evidence_checks: list[dict[str, Any]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    error_type: str | None = None
    cleanup: dict[str, Any] = field(default_factory=dict)
    started: float = field(default_factory=time.monotonic)

    def transition(self, phase: str, **fields: Any) -> None:
        self.transitions.append({"phase": phase, "at": utc_now(), **fields})

    def observe_processes(self, managed: ManagedProcesses, phase: str) -> None:
        snapshot = managed.snapshot(phase)
        self.process_observations.append(snapshot)
        return None

    def evidence_check(self, name: str, expected: Any, observed: Any, passed: bool | None = None) -> None:
        if passed is None:
            passed = observed == expected
        self.evidence_checks.append(
            {"name": name, "expected": expected, "observed": observed, "passed": bool(passed)}
        )

    def result(self, matrix_row: dict[str, Any]) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        for key, expected in matrix_row["expected"].items():
            observed = self.observed.get(key)
            checks.append(
                {
                    "name": key,
                    "expected": expected,
                    "observed": observed,
                    "passed": observed == expected,
                }
            )
        checks.extend(self.evidence_checks)
        passed = (
            self.error_type is None
            and all(check["passed"] for check in checks)
            and len(self.observed) >= len(matrix_row["expected"])
        )
        cell = {
            "id": matrix_row["id"],
            "operation": matrix_row["operation"],
            "expected": matrix_row["expected"],
            "expectedSha256": sha256_text(canonical_json_bytes(matrix_row["expected"]).decode()),
            "observed": self.observed,
            "checks": checks,
            "outcome": "passed" if passed else "failed",
            "errorType": self.error_type,
            "stateTransition": self.transitions,
            "processObservations": self.process_observations,
            "resourceObservations": self.resource_observations,
            "cleanup": self.cleanup,
            "durationMs": int((time.monotonic() - self.started) * 1000),
            "limitations": self.limitations,
        }
        cell["cellSha256"] = sha256_text(canonical_json_bytes(cell).decode())
        return cell


@dataclass
class RowContext:
    entry_point: Path
    python: Path
    workspace: Path
    tmpdir: Path
    managed: ManagedProcesses
    parameters: StdioServerParameters
    constants: dict[str, int]


def make_context(
    *,
    row_id: str,
    entry_point: Path,
    python: Path,
    base_workspace: Path,
    salt: str,
    constants: dict[str, int],
) -> RowContext:
    row_root = base_workspace / row_id
    if row_root.exists():
        shutil.rmtree(row_root)
    workspace = row_root / "workspace"
    tmpdir = row_root / "tmp"
    workspace.mkdir(parents=True)
    tmpdir.mkdir(parents=True)
    parameters = StdioServerParameters(
        command=str(entry_point),
        cwd=str(workspace),
        env={"TMPDIR": str(tmpdir), "PYTHONUNBUFFERED": "1"},
    )
    return RowContext(
        entry_point=entry_point,
        python=python,
        workspace=workspace,
        tmpdir=tmpdir,
        managed=ManagedProcesses(tmpdir, salt),
        parameters=parameters,
        constants=constants,
    )


async def call_exec(
    client: Client,
    code: str,
    *,
    timeout: float | None = None,
    reset: bool = False,
) -> dict[str, Any]:
    arguments: dict[str, Any] = {"code": code}
    if timeout is not None:
        arguments["timeout"] = timeout
    if reset:
        arguments["reset"] = True
    value, _content = structured_rich(await client.call_tool("python_exec", arguments))
    return value


def register_identity(cell: RowCell, ctx: RowContext, value: dict[str, Any]) -> dict[str, Any]:
    identity = value.get("result")
    if not isinstance(identity, dict):
        raise AssertionError("identity execution returned a non-mapping result")
    ctx.managed.register(identity)
    cell.observe_processes(ctx.managed, "after-identity")
    return identity


async def wait_for_path(path: Path, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            return
        await asyncio.sleep(0.02)
    raise TimeoutError("active execution did not publish its identity")


def output_flood_bytes(constants: dict[str, int]) -> int:
    return constants["MAX_STREAM_BYTES"]


def filler_execution_bytes(constants: dict[str, int]) -> int:
    chunk = constants["MAX_ARTIFACT_CHUNK_BYTES"]
    return constants["MAX_ARTIFACT_BYTES"] - chunk


def safe_error_type(error: BaseException) -> str:
    return type(error).__name__


async def row_installed_startup(ctx: RowContext, cell: RowCell) -> None:
    async with Client(ctx.parameters, read_timeout_seconds=120.0) as client:
        tools = await client.list_tools()
        cell.evidence_check("toolCount", 1, len(tools.tools))
        value = await call_exec(client, IDENTITY_CODE)
        identity = register_identity(cell, ctx, value)
        cell.transition(
            "after-mcp-initialize",
            serverState="ready",
            kernelState=value["kernelState"],
            executionCount=value["executionCount"],
        )
        snapshot = cell.process_observations[-1]
        cell.observed = {
            "serverState": "ready" if len(tools.tools) == 1 else "unknown",
            "kernelState": value["kernelState"],
            "managedProcesses": snapshot["managedProcessCount"],
        }
        cell.resource_observations = {
            "storeRoots": len(store_roots(ctx.tmpdir)),
            "observedManagedProcesses": snapshot["managedProcessCount"],
        }
        cell.evidence_check(
            "runnerGroupMatchesRunner",
            ctx.managed.token("group", cast(int, identity["group"])),
            snapshot["processGroup"]["token"],
        )
        cell.evidence_check("executionCount", 1, value["executionCount"])
    ctx.managed.register({"server": ctx.managed.server, "runner": ctx.managed.runner, "group": ctx.managed.group})


async def row_normal_shutdown(ctx: RowContext, cell: RowCell) -> None:
    async with Client(ctx.parameters, read_timeout_seconds=120.0) as client:
        value = await call_exec(
            client,
            "import os\n{'value': 1, 'runner': os.getpid(), 'server': os.getppid(), 'group': os.getpgrp()}",
        )
        identity = register_identity(cell, ctx, value)
        cell.transition(
            "before-shutdown",
            serverState="ready",
            kernelState=value["kernelState"],
            executionCount=value["executionCount"],
        )
        cell.evidence_check("completedExecutionCount", 1, value["executionCount"])
        cell.evidence_check("completedResultValue", 1, cast(dict[str, Any], value["result"])["value"])
        cell.resource_observations = {
            "storeRootsBeforeShutdown": len(store_roots(ctx.tmpdir)),
            "runnerGroupToken": ctx.managed.token("group", cast(int, identity["group"])),
        }
    cell.transition(
        "client-closed",
        serverState="exited"
        if ctx.managed.server is not None and not pid_exists(ctx.managed.server)
        else "running",
        kernelState="dead"
        if ctx.managed.runner is not None and not pid_exists(ctx.managed.runner)
        else "alive",
    )


async def row_destructive_reset(ctx: RowContext, cell: RowCell) -> None:
    async with Client(ctx.parameters, read_timeout_seconds=120.0) as client:
        first = await call_exec(client, "marker = 'present'\n" + IDENTITY_CODE)
        previous = register_identity(cell, ctx, first)
        previous_runner = cast(int, previous["runner"])
        cell.transition(
            "before-reset",
            serverState="ready",
            kernelState=first["kernelState"],
            executionCount=first["executionCount"],
        )
        reset = await call_exec(
            client,
            (
                "import os\n"
                "{'runner': os.getpid(), 'server': os.getppid(), 'group': os.getpgrp(), "
                "'markerPresent': 'marker' in globals()}\n"
            ),
            reset=True,
        )
        replacement = cast(dict[str, Any], reset["result"])
        ctx.managed.runner = cast(int, replacement["runner"])
        ctx.managed.server = cast(int, replacement["server"])
        ctx.managed.group = cast(int, replacement["group"])
        await wait_pid_gone(previous_runner, timeout=5.0)
        cell.observe_processes(ctx.managed, "after-reset")
        cell.transition(
            "after-reset",
            serverState="ready",
            kernelState=reset["kernelState"],
            executionCount=reset["executionCount"],
        )
        cell.observed = {
            "runnerReplaced": replacement["runner"] != previous_runner,
            "priorNamespaceAbsent": replacement["markerPresent"] is False,
            "serverState": "ready",
            "kernelState": reset["kernelState"],
        }
        cell.evidence_check("resetExecutionCount", 1, reset["executionCount"])
        cell.evidence_check("previousRunnerGone", False, pid_exists(previous_runner))
        cell.resource_observations = {
            "previousRunnerToken": ctx.managed.token("pid", previous_runner),
            "replacementRunnerToken": ctx.managed.token("pid", cast(int, replacement["runner"])),
        }


async def row_timeout_survives(ctx: RowContext, cell: RowCell) -> None:
    async with Client(ctx.parameters, read_timeout_seconds=120.0) as client:
        first = await call_exec(client, IDENTITY_CODE)
        identity = register_identity(cell, ctx, first)
        runner_pid = cast(int, identity["runner"])
        timed_out = await call_exec(client, "import time\ntime.sleep(30)", timeout=0.05)
        cell.transition(
            "after-timeout",
            status=timed_out["status"],
            serverState="ready",
            kernelState=timed_out["kernelState"],
            executionCount=timed_out["executionCount"],
        )
        continuation = await call_exec(
            client, "import os\n{'runner': os.getpid(), 'value': 42}"
        )
        continued = cast(dict[str, Any], continuation["result"])
        cell.observe_processes(ctx.managed, "after-continuation")
        cell.observed = {
            "status": timed_out["status"],
            "kernelState": timed_out["kernelState"],
            "continuationVerified": continued == {"runner": runner_pid, "value": 42},
        }
        cell.evidence_check("timeoutErrorType", "TimeoutError", timed_out["error"]["type"])
        cell.evidence_check("continuationExecutionCount", 3, continuation["executionCount"])
        cell.evidence_check(
            "sameRunnerPid", True, pid_exists(runner_pid) and continued["runner"] == runner_pid
        )
        cell.resource_observations = {
            "runnerToken": ctx.managed.token("pid", runner_pid),
            "continuationRunnerToken": ctx.managed.token("pid", cast(int, continued["runner"])),
        }


async def row_timeout_escalates(ctx: RowContext, cell: RowCell) -> None:
    async with Client(ctx.parameters, read_timeout_seconds=120.0) as client:
        first = await call_exec(client, IDENTITY_CODE)
        identity = register_identity(cell, ctx, first)
        runner_pid = cast(int, identity["runner"])
        escalated = await call_exec(
            client,
            (
                "import signal, time\n"
                "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                "while True:\n"
                "    time.sleep(0.2)\n"
            ),
            timeout=0.1,
        )
        await wait_pid_gone(runner_pid, timeout=8.0)
        server_ready = bool((await client.list_tools()).tools)
        unavailable = await call_exec(client, "6 * 7")
        cell.observe_processes(ctx.managed, "after-escalation")
        cell.transition(
            "after-escalation",
            status=escalated["status"],
            serverState="ready" if server_ready else "unknown",
            kernelState=escalated["kernelState"],
            executionCount=escalated["executionCount"],
        )
        cell.observed = {
            "status": escalated["status"],
            "kernelState": escalated["kernelState"],
            "runnerReplacedImplicitly": pid_exists(runner_pid)
            or unavailable["kernelState"] != "dead",
        }
        cell.evidence_check(
            "escalationErrorType", "KernelKilled", escalated.get("error", {}).get("type")
        )
        cell.evidence_check("unavailableStatus", "kernel_killed", unavailable["status"])
        cell.evidence_check(
            "unavailableErrorType", "KernelUnavailable", unavailable.get("error", {}).get("type")
        )
        cell.evidence_check("serverRemainedReady", True, server_ready)
        cell.evidence_check(
            "executionCountUnchanged",
            escalated["executionCount"],
            unavailable["executionCount"],
        )
        cell.resource_observations = {
            "runnerToken": ctx.managed.token("pid", runner_pid),
            "processGroupExistsAfterEscalation": group_exists(cast(int, ctx.managed.group)),
        }


async def row_runner_channel_death(ctx: RowContext, cell: RowCell) -> None:
    async with Client(ctx.parameters, read_timeout_seconds=120.0) as client:
        first = await call_exec(client, IDENTITY_CODE)
        identity = register_identity(cell, ctx, first)
        runner_pid = cast(int, identity["runner"])
        killed = await call_exec(
            client,
            "import os, signal\nos.kill(os.getpid(), signal.SIGKILL)",
        )
        await wait_pid_gone(runner_pid, timeout=8.0)
        server_ready = bool((await client.list_tools()).tools)
        unavailable = await call_exec(client, "6 * 7")
        cell.observe_processes(ctx.managed, "after-runner-death")
        cell.transition(
            "after-runner-death",
            status=killed["status"],
            serverState="ready" if server_ready else "unknown",
            kernelState=killed["kernelState"],
            executionCount=killed["executionCount"],
        )
        cell.observed = {
            "status": killed["status"],
            "kernelState": killed["kernelState"],
            "serverState": "ready" if server_ready else "unknown",
            "runnerReplacedImplicitly": pid_exists(runner_pid),
        }
        cell.evidence_check(
            "runnerDeathErrorType", "KernelExited", killed.get("error", {}).get("type")
        )
        cell.evidence_check("unavailableStatus", "kernel_killed", unavailable["status"])
        cell.evidence_check(
            "unavailableErrorType", "KernelUnavailable", unavailable.get("error", {}).get("type")
        )
        cell.evidence_check(
            "executionCountUnchanged",
            killed["executionCount"],
            unavailable["executionCount"],
        )
        cell.resource_observations = {
            "runnerToken": ctx.managed.token("pid", runner_pid),
            "processGroupExistsAfterDeath": group_exists(cast(int, ctx.managed.group)),
        }


async def row_output_limit_drain(ctx: RowContext, cell: RowCell) -> None:
    async with Client(ctx.parameters, read_timeout_seconds=180.0) as client:
        first = await call_exec(client, IDENTITY_CODE)
        identity = register_identity(cell, ctx, first)
        runner_pid = cast(int, identity["runner"])
        output_limit = output_flood_bytes(ctx.constants)
        tail_bytes = 5
        limited = await call_exec(
            client,
            (
                "import os\n"
                "chunk = b'x' * 65536\n"
                "for _ in range(4096): os.write(1, chunk)\n"
                f"os.write(1, b'tail\\n')\n"
            ),
            timeout=30.0,
        )
        record = cast(dict[str, Any], limited["output"]["stdoutArtifact"])
        part_bytes = ctx.constants["ARTIFACT_RESOURCE_PART_BYTES"]
        expected_parts = output_limit // part_bytes
        manifest_bytes = await verify_manifest(client, record, expected_parts=expected_parts)
        manifest_mime, manifest_raw = await read_resource(client, cast(str, record["uri"]))
        cell.evidence_check(
            "stdoutManifestMime",
            "application/vnd.amkernel.artifact-manifest+json",
            manifest_mime,
        )
        observed_parts = len(json.loads(manifest_raw)["parts"])
        cell.transition(
            "after-output-limit",
            status=limited["status"],
            serverState="ready",
            kernelState=limited["kernelState"],
            executionCount=limited["executionCount"],
        )
        continuation = await call_exec(
            client, "import os\n{'runner': os.getpid(), 'value': 42}"
        )
        continued = cast(dict[str, Any], continuation["result"])
        cell.observe_processes(ctx.managed, "after-output-limit")
        cell.observed = {
            "status": limited["status"],
            "kernelState": limited["kernelState"],
            "errorType": limited["error"]["type"],
            "drainCompleted": (
                limited["output"]["totalBytes"] == output_limit + tail_bytes
                and limited["output"]["discardedBytes"] == tail_bytes
                and manifest_bytes == output_limit
                and record == limited["artifacts"][0]
            ),
            "continuationVerified": continued == {"runner": runner_pid, "value": 42},
        }
        cell.evidence_check("outputLimitBytes", output_limit, limited["output"]["limitBytes"])
        cell.evidence_check("totalOutputBytes", output_limit + tail_bytes, limited["output"]["totalBytes"])
        cell.evidence_check("discardedTailBytes", tail_bytes, limited["output"]["discardedBytes"])
        cell.evidence_check("stdoutArtifactParts", expected_parts, observed_parts)
        cell.evidence_check("continuationExecutionCount", 3, continuation["executionCount"])
        cell.resource_observations = {
            "stdoutArtifactSize": record["size"],
            "stdoutArtifactSha256": record["sha256"],
            "stdoutManifestPartCount": observed_parts,
            "manifestVerifiedBytes": manifest_bytes,
            "store": measure_store(ctx.tmpdir),
        }


async def row_artifact_integrity_expiry(ctx: RowContext, cell: RowCell) -> None:
    async with Client(ctx.parameters, read_timeout_seconds=180.0) as client:
        first = await call_exec(client, IDENTITY_CODE)
        register_identity(cell, ctx, first)
        part_bytes = ctx.constants["ARTIFACT_RESOURCE_PART_BYTES"]
        source_size = part_bytes + 1
        created = await call_exec(
            client,
            f"artifact('large.bin', b'm' * {source_size})\n'created'",
        )
        record = cast(dict[str, Any], created["artifacts"][0])
        cell.evidence_check("multipartRepresentation", "manifest", record["representation"])
        verified = await verify_manifest(client, record, expected_parts=2)
        cell.evidence_check("initialManifestBytes", source_size, verified)
        manifest_mime, manifest_bytes = await read_resource(client, cast(str, record["uri"]))
        cell.evidence_check(
            "manifestMime", "application/vnd.amkernel.artifact-manifest+json", manifest_mime
        )
        manifest = json.loads(manifest_bytes)
        tampered_part = manifest["parts"][0]
        artifact_id = cast(str, record["uri"]).rsplit("/", 1)[-1]
        tampered = await call_exec(
            client,
            (
                "import glob, os, tempfile\n"
                "matches = glob.glob(os.path.join(tempfile.gettempdir(), 'amkernel-*', "
                f"'bundle-*', 'artifact-{artifact_id}', 'part-0'))\n"
                "if len(matches) == 1:\n"
                "    os.chmod(matches[0], 0o600)\n"
                "    with open(matches[0], 'r+b') as resource:\n"
                "        resource.write(b'X')\n"
                "len(matches)"
            ),
        )
        cell.evidence_check("tamperMatchCount", 1, tampered["result"])
        tampered_read = "rejected"
        try:
            await client.read_resource(cast(str, tampered_part["uri"]))
        except MCPError as error:
            cell.evidence_check("tamperError", "resource integrity failure", error.message)
        else:
            tampered_read = "readable"
            cell.evidence_check("tamperError", "resource integrity failure", "resource remained readable")
        filler_bytes = filler_execution_bytes(ctx.constants)
        quota = ctx.constants["ARTIFACT_STORE_QUOTA_BYTES"]
        reservation = ctx.constants["EXECUTION_BUNDLE_RESERVATION_BYTES"]
        filler_count = max(
            1,
            -(-(quota - reservation - source_size) // filler_bytes) + 1,
        )
        for _ in range(filler_count):
            filler = await call_exec(
                client,
                (
                    "import os\n"
                    "chunk = b'e' * 65536\n"
                    f"for _ in range({filler_bytes // 65536}): os.write(1, chunk)"
                ),
                timeout=30.0,
            )
            if filler["status"] != "completed" or filler["output"]["totalBytes"] != filler_bytes:
                raise AssertionError("quota pressure filler did not complete as expected")
        expired_read = "still_available"
        try:
            await client.read_resource(cast(str, record["uri"]))
        except MCPError as error:
            cell.evidence_check("expiryError", "resource not found", error.message)
            expired_read = "not_found" if error.message == "resource not found" else error.message
        else:
            cell.evidence_check("expiryError", "resource not found", "resource remained available")
        store = measure_store(ctx.tmpdir)
        within = int(store["managedBytes"]) <= quota
        cell.observed = {
            "initialRead": "verified",
            "tamperedRead": tampered_read,
            "expiredRead": expired_read,
            "remainingManagedBytesWithinCeiling": within,
        }
        cell.evidence_check("managedBytesCeiling", True, within)
        cell.transition(
            "after-expiry",
            status=created["status"],
            serverState="ready",
            kernelState="alive",
            executionCount=1,
        )
        cell.observe_processes(ctx.managed, "after-expiry")
        cell.resource_observations = {
            "multipartBytes": source_size,
            "manifestPartCount": len(manifest["parts"]),
            "tamperedPartIndex": 0,
            "tamperedPartSha256": tampered_part["sha256"],
            "storeAfterEviction": store,
            "storeCeilingBytes": quota,
            "fillerBytesPerExecution": filler_bytes,
            "fillerExecutions": filler_count,
        }


async def row_cancellation_cleanup(ctx: RowContext, cell: RowCell) -> None:
    parameters = ctx.parameters
    client_manager = Client(parameters, read_timeout_seconds=180.0)
    client = await client_manager.__aenter__()
    active: asyncio.Task[Any] | None = None
    aborted = "unknown"
    try:
        tools = await client.list_tools()
        cell.evidence_check("toolCountDuringActiveRun", 1, len(tools.tools))
        identity_path = ctx.workspace / "active-identity.json"
        active = asyncio.create_task(
            client.call_tool(
                "python_exec",
                {"code": STUBBORN_CHILD_CODE, "timeout": 3600.0},
            )
        )
        await wait_for_path(identity_path, timeout=15.0)
        identity = cast(dict[str, Any], json.loads(identity_path.read_text(encoding="utf-8")))
        ctx.managed.register(identity)
        child_pid = cast(int, identity.get("child"))
        cell.observe_processes(ctx.managed, "active-execution")
        cell.transition(
            "active-execution",
            serverState="ready",
            kernelState="alive",
            executionCount=1,
        )
        cell.evidence_check("activeRunnerAlive", True, pid_exists(cast(int, identity["runner"])))
        cell.evidence_check("activeChildAlive", True, pid_exists(child_pid))
    finally:
        try:
            await client_manager.__aexit__(None, None, None)
        finally:
            if active is not None:
                aborted = "not_finished" if active.done() and not active.cancelled() else "cancelled"
                active.cancel()
                try:
                    await active
                except BaseException as error:
                    aborted = safe_error_type(error)
    cell.transition(
        "client-closed-during-active-execution",
        serverState="exited"
        if ctx.managed.server is not None and not pid_exists(ctx.managed.server)
        else "running",
        kernelState="dead"
        if ctx.managed.runner is not None and not pid_exists(ctx.managed.runner)
        else "alive",
    )
    cell.evidence_check("activeExecutionAborted", True, aborted != "not_finished")
    cell.resource_observations = {
        "activeExecutionAborted": aborted,
        "runnerGroupToken": None if ctx.managed.group is None else ctx.managed.token("group", ctx.managed.group),
    }


Handler = Callable[[RowContext, RowCell], Awaitable[None]]

HANDLERS: dict[str, Handler] = {
    "installed-startup": row_installed_startup,
    "normal-shutdown": row_normal_shutdown,
    "destructive-reset": row_destructive_reset,
    "timeout-survives": row_timeout_survives,
    "timeout-escalates": row_timeout_escalates,
    "runner-channel-death": row_runner_channel_death,
    "output-limit-drain": row_output_limit_drain,
    "artifact-integrity-expiry": row_artifact_integrity_expiry,
    "cancellation-cleanup": row_cancellation_cleanup,
}


def finalize_observed_from_cleanup(cell: RowCell) -> None:
    if cell.row["id"] == "normal-shutdown":
        cell.observed["serverState"] = "exited" if cell.cleanup.get("serverExited") else "unknown"
        cell.observed["kernelState"] = "dead" if cell.cleanup.get("runnerExited") else "unknown"
        cell.observed["managedProcessesRemaining"] = cell.cleanup.get("managedProcessesRemaining")
    elif cell.row["id"] == "cancellation-cleanup":
        cell.observed["serverState"] = "exited" if cell.cleanup.get("serverExited") else "unknown"
        cell.observed["kernelState"] = "dead" if cell.cleanup.get("runnerExited") else "unknown"
        cell.observed["managedProcessesRemaining"] = cell.cleanup.get("managedProcessesRemaining")
        cell.observed["managedArtifactsRemaining"] = cell.cleanup.get("managedArtifactsRemaining")


async def execute_row(
    matrix_row: dict[str, Any],
    *,
    entry_point: Path,
    python: Path,
    base_workspace: Path,
    salt: str,
    constants: dict[str, int],
) -> dict[str, Any]:
    ctx = make_context(
        row_id=matrix_row["id"],
        entry_point=entry_point,
        python=python,
        base_workspace=base_workspace,
        salt=salt,
        constants=constants,
    )
    cell = RowCell(row=matrix_row)
    handler = HANDLERS[matrix_row["id"]]
    try:
        async with asyncio.timeout(ROW_TIMEOUT_SECONDS):
            await handler(ctx, cell)
    except BaseException as error:
        cell.error_type = safe_error_type(error)
        if os.environ.get("AMKERNEL_ROW_DEBUG"):
            import traceback

            traceback.print_exception(error)
        cell.limitations.append(
            "The row aborted before completing all observations; only emitted observations are retained."
        )
    cell.cleanup = await ctx.managed.finalize()
    finalize_observed_from_cleanup(cell)
    cleanup_completed = bool(cell.cleanup.get("completed"))
    cell.evidence_check("cleanupCompleted", True, cleanup_completed)
    if not cleanup_completed:
        cell.limitations.append(
            "Managed cleanup did not complete within the lifecycle envelope; forced teardown was only harness cleanup."
        )
    if not cell.transitions:
        cell.transition(
            "row-aborted",
            serverState="unknown",
            kernelState="unknown",
            executionCount=None,
        )
    return cell.result(matrix_row)


def discover_wheel_version(wheel: Path) -> str:
    match = re.fullmatch(r"amkernel-([^-]+)-py3-none-any\.whl", wheel.name)
    if match is None:
        raise RuntimeError(f"unexpected wheel filename: {wheel.name}")
    return match.group(1)


def build_sources(source_root: Path, matrix_path: Path, wheel: Path, harness: Path) -> dict[str, Any]:
    contracts = [
        "docs/decisions/0003-stage-1-execution-contract.md",
        "docs/decisions/0004-stage-1-runner-protocol.md",
        "docs/decisions/0005-stage-1-runtime-lifecycle.md",
        "docs/decisions/0006-stage-2-output-and-artifact-contract.md",
    ]
    return {
        "matrix": {
            "path": "tests/fixtures/cross_client/process-matrix.json",
            "sha256": sha256_path(matrix_path),
        },
        "harness": {
            "path": "tests/e2e/cross_os_process_matrix.py",
            "sha256": sha256_path(harness),
        },
        "contracts": [
            {"path": path, "sha256": sha256_path(source_root / path)} for path in contracts
        ],
        "lock": {"path": "uv.lock", "sha256": sha256_path(source_root / "uv.lock")},
        "wheel": {
            "filename": wheel.name,
            "sha256": sha256_path(wheel),
            "sizeBytes": wheel.stat().st_size,
        },
    }


def build_environment(entry_point: Path, python: Path, wheel: Path, declared_platform: str) -> dict[str, Any]:
    system = platform.system()
    derived = {"Linux": "ubuntu-latest", "Darwin": "macos-latest"}.get(system, system.lower())
    version_output = subprocess.run(
        [str(entry_point), "--version"], check=True, capture_output=True, text=True
    )
    installed_version = importlib.metadata.version("amkernel")
    return {
        "os": {
            "system": system,
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "platform": platform.platform(),
        },
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "majorMinor": f"{sys.version_info.major}.{sys.version_info.minor}",
            "isVenvLauncher": python.is_symlink() and os.path.samefile(python, sys.executable),
        },
        "wheel": {
            "filename": wheel.name,
            "sha256": sha256_path(wheel),
            "sizeBytes": wheel.stat().st_size,
            "version": discover_wheel_version(wheel),
            "installedVersion": installed_version,
            "entryPointVersionOutput": version_output.stdout.strip(),
        },
        "entryPoint": {
            "name": entry_point.name,
            "present": entry_point.is_file(),
            "executable": os.access(entry_point, os.X_OK),
        },
        "runner": {
            "os": os.environ.get("RUNNER_OS"),
            "arch": os.environ.get("RUNNER_ARCH"),
            "image": os.environ.get("ImageOS") or os.environ.get("RUNNER_IMAGE"),
        },
        "matrixPlatform": derived,
        "declaredPlatform": declared_platform,
        "platformDeclarationMatches": derived == declared_platform,
    }


def build_dispatch() -> dict[str, Any] | None:
    if not HOSTED:
        return None
    return {
        "repository": os.environ.get("GITHUB_REPOSITORY"),
        "workflow": os.environ.get("GITHUB_WORKFLOW"),
        "workflowRef": os.environ.get("GITHUB_WORKFLOW_REF"),
        "job": os.environ.get("GITHUB_JOB"),
        "runId": os.environ.get("GITHUB_RUN_ID"),
        "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "sha": os.environ.get("GITHUB_SHA"),
        "ref": os.environ.get("GITHUB_REF"),
    }


def build_record(
    *,
    matrix: dict[str, Any],
    matrix_path: Path,
    source_root: Path,
    wheel: Path,
    harness: Path,
    entry_point: Path,
    python: Path,
    declared_platform: str,
    cells: list[dict[str, Any]],
    run_id: str,
) -> dict[str, Any]:
    environment = build_environment(entry_point, python, wheel, declared_platform)
    record: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "recordKind": "amkernel-cross-os-process-matrix",
        "recordId": run_id,
        "executionContext": "hosted" if HOSTED else "local",
        "dispatch": build_dispatch(),
        "sources": build_sources(source_root, matrix_path, wheel, harness),
        "matrix": {
            "id": matrix["matrixId"],
            "platforms": matrix["platforms"],
            "pythonVersions": matrix["pythonVersions"],
            "rowIds": [row["id"] for row in matrix["rows"]],
            "requiredEvidence": matrix["requiredEvidence"],
            "unsupportedPlatforms": matrix["unsupportedPlatforms"],
        },
        "environment": environment,
        "cells": cells,
        "limitations": [
            "Only the frozen matrix rows were observed; this record makes no Windows, Android, or iOS claim.",
            "Process identity is represented by per-run opaque tokens; raw PIDs, paths, hostnames, and private content are not retained.",
            "Cleanup covers only the AMKernel-managed server, runner process group, and artifact root; external host resources are not claimed.",
            "Independent lifecycle review is required and is not self-attested by this record.",
        ],
        "review": {
            "required": True,
            "disposition": "pending-independent-lifecycle-review",
        },
        "createdAt": utc_now(),
    }
    if not environment["platformDeclarationMatches"]:
        record["limitations"].append(
            "The declared CI platform label did not match the derived operating-system identity."
        )
    record["cellsSha256"] = sha256_text(
        canonical_json_bytes([cell["cellSha256"] for cell in cells]).decode()
    )
    record["contentSha256"] = sha256_text(canonical_json_bytes(record).decode())
    return record


async def run(args: argparse.Namespace) -> int:
    source_root = Path(args.source_root).resolve()
    matrix_path = Path(args.matrix).resolve()
    wheel = Path(args.wheel).resolve()
    harness = Path(__file__).resolve()
    entry_point = Path(args.entry_point)
    python = Path(args.python)
    base_workspace = Path(args.workspace).resolve()
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    constants = {
        "MAX_STREAM_BYTES": read_protocol_constant(source_root, "MAX_STREAM_BYTES"),
        "MAX_ARTIFACT_BYTES": read_protocol_constant(source_root, "MAX_ARTIFACT_BYTES"),
        "MAX_ARTIFACT_CHUNK_BYTES": read_protocol_constant(source_root, "MAX_ARTIFACT_CHUNK_BYTES"),
        "ARTIFACT_RESOURCE_PART_BYTES": read_protocol_constant(
            source_root, "ARTIFACT_RESOURCE_PART_BYTES"
        ),
        "ARTIFACT_STORE_QUOTA_BYTES": read_protocol_constant(
            source_root, "ARTIFACT_STORE_QUOTA_BYTES"
        ),
        "EXECUTION_BUNDLE_RESERVATION_BYTES": read_protocol_constant(
            source_root, "EXECUTION_BUNDLE_RESERVATION_BYTES"
        ),
    }
    salt = secrets.token_hex(16)
    cells: list[dict[str, Any]] = []
    for row in matrix["rows"]:
        print(f"::group::process-row {row['id']}", flush=True)
        cell = await execute_row(
            row,
            entry_point=entry_point,
            python=python,
            base_workspace=base_workspace,
            salt=salt,
            constants=constants,
        )
        cells.append(cell)
        print(f"{row['id']}: {cell['outcome']}", flush=True)
        for check in cell["checks"]:
            if not check["passed"]:
                print(
                    f"  check failed: {check['name']} expected={check['expected']!r} "
                    f"observed={check['observed']!r}",
                    flush=True,
                )
        if cell["errorType"]:
            print(f"  row error: {cell['errorType']}", flush=True)
        print("::endgroup::", flush=True)
    record = build_record(
        matrix=matrix,
        matrix_path=matrix_path,
        source_root=source_root,
        wheel=wheel,
        harness=harness,
        entry_point=entry_point,
        python=python,
        declared_platform=args.platform,
        cells=cells,
        run_id=f"{matrix['matrixId']}-{uuid.uuid4().hex}",
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    passed = sum(cell["outcome"] == "passed" for cell in cells)
    print(f"cells={len(cells)} passed={passed} failed={len(cells) - passed}")
    return 0 if passed == len(cells) else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entry-point", required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--matrix", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--wheel", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(run(parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
