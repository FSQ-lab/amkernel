"""Validate cross-OS process-matrix evidence and build a portable hash-linked index.

The validator is deliberately independent of the harness: it re-reads the frozen
matrix and the source files, recomputes every content hash, and refuses records
whose claimed observations, identities, or cleanup are incomplete.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
MATRIX_PATH = "tests/fixtures/cross_client/process-matrix.json"
HARNESS_PATH = "tests/e2e/cross_os_process_matrix.py"
CONTRACT_PATHS = (
    "docs/decisions/0003-stage-1-execution-contract.md",
    "docs/decisions/0004-stage-1-runner-protocol.md",
    "docs/decisions/0005-stage-1-runtime-lifecycle.md",
    "docs/decisions/0006-stage-2-output-and-artifact-contract.md",
)
PRIVATE_PATTERNS = (
    re.compile(r"/Users/"),
    re.compile(r"/home/"),
    re.compile(r"[A-Za-z]:\\Users\\"),
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"(?i)(authorization|bearer)\s*[:=]\s*\S+"),
    re.compile(r"(?i)(password|secret|token)\s*[:=]\s*[^\s,}\"]+"),
)
TOKEN_RE = re.compile(r"[0-9a-f]{8,64}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
ALLOWED_SERVER_STATES = {"ready", "running", "exited", "unknown"}
ALLOWED_KERNEL_STATES = {"alive", "dead", "unknown"}
ALLOWED_STATUSES = {"completed", "timed_out", "failed", "kernel_killed"}
TOKEN_KEYS = {
    "runnerGroupToken",
    "previousRunnerToken",
    "replacementRunnerToken",
    "runnerToken",
    "continuationRunnerToken",
}
SHA256_KEYS = {
    "stdoutArtifactSha256",
    "tamperedPartSha256",
}
BOOL_KEYS = {
    "processGroupExistsAfterEscalation",
    "processGroupExistsAfterDeath",
}
INT_KEYS = {
    "observedManagedProcesses",
    "storeRoots",
    "storeRootsBeforeShutdown",
    "stdoutArtifactSize",
    "stdoutManifestPartCount",
    "manifestVerifiedBytes",
    "multipartBytes",
    "manifestPartCount",
    "tamperedPartIndex",
    "storeCeilingBytes",
    "fillerBytesPerExecution",
    "fillerExecutions",
}
STORE_KEYS = {"artifactRoots", "artifactFiles", "managedBytes", "artifactRootRemoved"}
TERMINATION_GRACE_SECONDS = 1.5
ROW_TRANSITIONS = {
    "installed-startup": ["after-mcp-initialize"],
    "normal-shutdown": ["before-shutdown", "client-closed"],
    "destructive-reset": ["before-reset", "after-reset"],
    "timeout-survives": ["after-timeout"],
    "timeout-escalates": ["after-escalation"],
    "runner-channel-death": ["after-runner-death"],
    "output-limit-drain": ["after-output-limit"],
    "artifact-integrity-expiry": ["after-expiry"],
    "cancellation-cleanup": ["active-execution", "client-closed-during-active-execution"],
}
ROW_PROCESS_PHASES = {
    "installed-startup": ["after-identity"],
    "normal-shutdown": ["after-identity"],
    "destructive-reset": ["after-identity", "after-reset"],
    "timeout-survives": ["after-identity", "after-continuation"],
    "timeout-escalates": ["after-identity", "after-escalation"],
    "runner-channel-death": ["after-identity", "after-runner-death"],
    "output-limit-drain": ["after-identity", "after-output-limit"],
    "artifact-integrity-expiry": ["after-identity", "after-expiry"],
    "cancellation-cleanup": ["active-execution"],
}
ROW_RESOURCES = {
    "installed-startup": {"observedManagedProcesses", "storeRoots"},
    "normal-shutdown": {"runnerGroupToken", "storeRootsBeforeShutdown", "shutdownElapsedSeconds"},
    "destructive-reset": {"previousRunnerToken", "replacementRunnerToken"},
    "timeout-survives": {"runnerToken", "continuationRunnerToken"},
    "timeout-escalates": {"runnerToken", "processGroupExistsAfterEscalation"},
    "runner-channel-death": {"runnerToken", "processGroupExistsAfterDeath"},
    "output-limit-drain": {
        "stdoutArtifactSize",
        "stdoutArtifactSha256",
        "stdoutManifestPartCount",
        "manifestVerifiedBytes",
        "store",
    },
    "artifact-integrity-expiry": {
        "multipartBytes",
        "manifestPartCount",
        "tamperedPartIndex",
        "tamperedPartSha256",
        "storeAfterEviction",
        "storeCeilingBytes",
        "fillerBytesPerExecution",
        "fillerExecutions",
    },
    "cancellation-cleanup": {"activeExecutionAborted", "runnerGroupToken"},
}
RECORD_KEYS = {
    "schemaVersion",
    "recordKind",
    "recordId",
    "executionContext",
    "dispatch",
    "sources",
    "matrix",
    "environment",
    "cells",
    "limitations",
    "review",
    "createdAt",
    "cellsSha256",
    "contentSha256",
}
ENVIRONMENT_KEYS = {
    "os",
    "python",
    "wheel",
    "entryPoint",
    "runner",
    "matrixPlatform",
    "declaredPlatform",
    "platformDeclarationMatches",
}
MATRIX_HEADER_KEYS = {
    "id",
    "platforms",
    "pythonVersions",
    "rowIds",
    "requiredEvidence",
    "unsupportedPlatforms",
}
ROW_TRANSITION_STATES = {
    "installed-startup": {"after-mcp-initialize": ("ready", "alive")},
    "normal-shutdown": {
        "before-shutdown": ("ready", "alive"),
        "client-closed": ("exited", "dead"),
    },
    "destructive-reset": {
        "before-reset": ("ready", "alive"),
        "after-reset": ("ready", "alive"),
    },
    "timeout-survives": {"after-timeout": ("ready", "alive")},
    "timeout-escalates": {"after-escalation": ("ready", "dead")},
    "runner-channel-death": {"after-runner-death": ("ready", "dead")},
    "output-limit-drain": {"after-output-limit": ("ready", "alive")},
    "artifact-integrity-expiry": {"after-expiry": ("ready", "alive")},
    "cancellation-cleanup": {
        "active-execution": ("ready", "alive"),
        "client-closed-during-active-execution": ("exited", "dead"),
    },
}
ROW_TRANSITION_PROCESS_PHASE = {
    "installed-startup": {"after-mcp-initialize": "after-identity"},
    "normal-shutdown": {"before-shutdown": "after-identity"},
    "destructive-reset": {"before-reset": "after-identity", "after-reset": "after-reset"},
    "timeout-survives": {"after-timeout": "after-continuation"},
    "timeout-escalates": {"after-escalation": "after-escalation"},
    "runner-channel-death": {"after-runner-death": "after-runner-death"},
    "output-limit-drain": {"after-output-limit": "after-output-limit"},
    "artifact-integrity-expiry": {"after-expiry": "after-expiry"},
    "cancellation-cleanup": {"active-execution": "active-execution"},
}
WHEEL_SOURCE_KEYS = {
    "filename",
    "sha256",
    "sizeBytes",
    "packageFileCount",
    "packageSha256",
    "sourceRevision",
    "sourceRootKind",
}

CELL_KEYS = {
    "id",
    "operation",
    "expected",
    "expectedSha256",
    "observed",
    "checks",
    "outcome",
    "errorType",
    "stateTransition",
    "processObservations",
    "resourceObservations",
    "cleanup",
    "durationMs",
    "limitations",
    "cellSha256",
}
CHECK_KEYS = {"name", "expected", "observed", "passed"}
CLEANUP_KEYS = {
    "attempted",
    "completed",
    "serverExited",
    "runnerExited",
    "processGroupRemoved",
    "managedProcessesRemaining",
    "managedArtifactsRemaining",
    "artifactRootRemoved",
    "forcedCleanup",
}


class EvidenceError(Exception):
    """A structural or source-linkage defect in an evidence record."""


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


def package_tree_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        hashes[str(path.relative_to(root))] = sha256_path(path)
    return hashes


def wheel_package_hashes(wheel: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    try:
        with zipfile.ZipFile(wheel) as archive:
            for name in sorted(archive.namelist()):
                if not name.startswith("amkernel/") or name.endswith("/"):
                    continue
                hashes[name[len("amkernel/") :]] = hashlib.sha256(archive.read(name)).hexdigest()
    except zipfile.BadZipFile as error:
        raise EvidenceError(f"wheel is not a valid zip archive: {wheel.name}") from error
    return hashes


def package_identity(hashes: dict[str, str]) -> dict[str, Any]:
    body = "\n".join(f"{name}\0{digest}" for name, digest in sorted(hashes.items()))
    return {
        "packageFileCount": len(hashes),
        "packageSha256": hashlib.sha256(body.encode()).hexdigest(),
    }


def require(condition: object, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def require_exact_keys(value: object, keys: set[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvidenceError(f"{context} must be a mapping")
    actual = set(value)
    require(actual == keys, f"{context} keys are {sorted(actual)}, expected {sorted(keys)}")
    return value


def require_int(value: Any, context: str, *, minimum: int = 0) -> None:
    require(
        isinstance(value, int) and not isinstance(value, bool) and value >= minimum,
        f"{context} is not an integer >= {minimum}",
    )


def require_bool(value: Any, context: str) -> None:
    require(isinstance(value, bool), f"{context} is not a boolean")


def require_iso_time(value: Any, context: str) -> None:
    require(isinstance(value, str) and value.endswith("Z"), f"{context} is not a UTC timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(parsed.tzinfo is not None, f"{context} lacks a timezone")


def load_matrix(path: Path) -> dict[str, Any]:
    matrix = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(matrix, dict):
        raise EvidenceError("matrix must be a mapping")
    require(isinstance(matrix.get("rows"), list) and matrix["rows"], "matrix rows are missing")
    require(matrix["matrixId"], "matrix id is missing")
    return matrix


def source_hashes(source_root: Path) -> dict[str, Any]:
    return {
        "matrix": {"path": MATRIX_PATH, "sha256": sha256_path(source_root / MATRIX_PATH)},
        "harness": {"path": HARNESS_PATH, "sha256": sha256_path(source_root / HARNESS_PATH)},
        "contracts": [
            {"path": path, "sha256": sha256_path(source_root / path)} for path in CONTRACT_PATHS
        ],
        "lock": {"path": "uv.lock", "sha256": sha256_path(source_root / "uv.lock")},
    }


def wheel_source_hashes(wheel_source_root: Path) -> dict[str, Any]:
    return package_identity(package_tree_hashes(wheel_source_root / "src" / "amkernel"))


def check_privacy(record: dict[str, Any]) -> None:
    text = json.dumps(record, ensure_ascii=False)
    for pattern in PRIVATE_PATTERNS:
        match = pattern.search(text)
        require(
            match is None,
            f"evidence contains a private path or credential-shaped value: {pattern.pattern}",
        )


def check_sources(record: dict[str, Any], source_root: Path, wheel_source_root: Path) -> None:
    expected = source_hashes(source_root)
    expected_wheel = wheel_source_hashes(wheel_source_root)
    sources = require_exact_keys(
        record.get("sources"), {"matrix", "harness", "contracts", "lock", "wheel"}, "sources"
    )
    require(sources["matrix"]["path"] == MATRIX_PATH, "matrix source path is not frozen")
    require(
        sources["matrix"]["sha256"] == expected["matrix"]["sha256"],
        "matrix hash does not match the checkout",
    )
    require(sources["harness"]["path"] == HARNESS_PATH, "harness path is not frozen")
    require(
        sources["harness"]["sha256"] == expected["harness"]["sha256"],
        "harness hash does not match the checkout",
    )
    require(sources["lock"]["path"] == "uv.lock", "lock path is not frozen")
    require(
        sources["lock"]["sha256"] == expected["lock"]["sha256"],
        "lock hash does not match the checkout",
    )
    contracts = sources.get("contracts")
    if not isinstance(contracts, list) or len(contracts) != len(CONTRACT_PATHS):
        raise EvidenceError("contract sources are incomplete")
    for actual, expected_contract in zip(contracts, expected["contracts"], strict=True):
        require(actual == expected_contract, "contract hash does not match the checkout")
    wheel = require_exact_keys(sources.get("wheel"), WHEEL_SOURCE_KEYS, "sources.wheel")
    require(
        isinstance(wheel.get("filename"), str) and wheel["filename"], "wheel filename is missing"
    )
    require(SHA256_RE.fullmatch(str(wheel.get("sha256"))) is not None, "wheel hash is malformed")
    require(
        isinstance(wheel.get("sizeBytes"), int) and wheel["sizeBytes"] > 0, "wheel size is missing"
    )
    require(
        wheel.get("packageFileCount") == expected_wheel["packageFileCount"],
        "wheel package file count does not match the pinned wheel source",
    )
    require(
        wheel.get("packageSha256") == expected_wheel["packageSha256"],
        "wheel package aggregate does not match the pinned wheel source",
    )
    require(
        isinstance(wheel.get("sourceRevision"), str) and wheel["sourceRevision"],
        "wheel source revision is missing",
    )
    require(
        wheel.get("sourceRootKind") in {"current-checkout", "pinned-release-source"},
        "wheel source root kind is invalid",
    )


def check_environment_wheel_identity(record: dict[str, Any]) -> None:
    source_wheel = record["sources"]["wheel"]
    environment_wheel = record["environment"]["wheel"]
    require(isinstance(environment_wheel, dict), "environment wheel identity is missing")
    for key in ("filename", "sha256", "sizeBytes"):
        require(
            environment_wheel.get(key) == source_wheel.get(key),
            f"environment wheel {key} disagrees with sources.wheel",
        )


def check_expected_wheel(
    record: dict[str, Any], expected_sha256: str | None, expected_revision: str | None
) -> None:
    wheel = record["sources"]["wheel"]
    if expected_sha256 is not None:
        require(
            wheel["sha256"] == expected_sha256,
            "wheel hash does not match the trusted expected wheel",
        )
    if expected_revision is not None:
        require(
            wheel["sourceRevision"] == expected_revision,
            "wheel source revision does not match the trusted expected revision",
        )


def check_wheel_file(record: dict[str, Any], wheel_path: Path) -> None:
    wheel = record["sources"]["wheel"]
    require(wheel_path.is_file(), "supplied wheel is missing")
    require(wheel_path.stat().st_size == wheel["sizeBytes"], "wheel size does not match evidence")
    require(sha256_path(wheel_path) == wheel["sha256"], "wheel hash does not match evidence")
    package = package_identity(wheel_package_hashes(wheel_path))
    require(
        wheel["packageFileCount"] == package["packageFileCount"],
        "wheel package file count disagrees",
    )
    require(wheel["packageSha256"] == package["packageSha256"], "wheel package aggregate disagrees")
    environment_wheel = record["environment"]["wheel"]
    require(
        environment_wheel["filename"] == wheel_path.name, "environment wheel filename disagrees"
    )
    require(environment_wheel["sha256"] == wheel["sha256"], "environment wheel hash disagrees")
    require(
        environment_wheel["sizeBytes"] == wheel["sizeBytes"], "environment wheel size disagrees"
    )


def check_environment(record: dict[str, Any], matrix: dict[str, Any]) -> None:
    environment = require_exact_keys(record.get("environment"), ENVIRONMENT_KEYS, "environment")
    os_identity = environment.get("os")
    if not isinstance(os_identity, dict):
        raise EvidenceError("operating-system identity is missing")
    require(
        os_identity.get("system") in {"Linux", "Darwin"}, "unsupported observed operating system"
    )
    expected_platform = {"Linux": "ubuntu-latest", "Darwin": "macos-latest"}[os_identity["system"]]
    require(
        environment["matrixPlatform"] == expected_platform, "matrix platform does not match the OS"
    )
    require(
        environment["declaredPlatform"] == expected_platform, "declared platform is inconsistent"
    )
    require(
        environment["platformDeclarationMatches"] is True,
        "platform declaration mismatch was observed",
    )
    require(
        expected_platform in matrix["platforms"], "observed platform is not in the frozen matrix"
    )
    python_identity = environment.get("python")
    if not isinstance(python_identity, dict):
        raise EvidenceError("python identity is missing")
    require(
        python_identity.get("implementation") == "CPython", "python implementation is not CPython"
    )
    require(
        python_identity.get("majorMinor") in matrix["pythonVersions"],
        "python minor is not in the matrix",
    )
    require(
        str(python_identity.get("version", "")).startswith(
            str(python_identity["majorMinor"]) + "."
        ),
        "python version does not match its major/minor identity",
    )
    require(
        python_identity.get("isVenvLauncher") is True,
        "harness interpreter is not the isolated venv launcher",
    )
    wheel = environment["wheel"]
    require(
        wheel["version"] == wheel["installedVersion"],
        "wheel and installed distribution versions differ",
    )
    require(
        wheel["entryPointVersionOutput"] == f"amkernel {wheel['version']}",
        "installed entry point version output is inconsistent",
    )
    require(environment["entryPoint"]["present"] is True, "installed entry point is absent")
    require(
        environment["entryPoint"]["executable"] is True, "installed entry point is not executable"
    )


def check_hosted_dispatch(record: dict[str, Any], require_hosted: bool) -> None:
    context = record.get("executionContext")
    require(context in {"hosted", "local"}, "execution context is missing")
    if require_hosted:
        require(context == "hosted", "record is not from a hosted workflow")
        dispatch = record.get("dispatch")
        if not isinstance(dispatch, dict):
            raise EvidenceError("hosted dispatch identity is missing")
        require(
            re.fullmatch(r"\d+", str(dispatch.get("runId"))) is not None, "hosted run id is missing"
        )
        require(
            re.fullmatch(r"\d+", str(dispatch.get("runAttempt"))) is not None,
            "hosted run attempt is missing",
        )
        require(
            re.fullmatch(r"[0-9a-f]{40}", str(dispatch.get("sha"))) is not None,
            "hosted commit identity is missing",
        )
        require(
            isinstance(dispatch.get("job"), str) and dispatch["job"],
            "hosted job identity is missing",
        )
        require(
            isinstance(dispatch.get("workflow"), str) and dispatch["workflow"],
            "hosted workflow identity is missing",
        )
        require(
            isinstance(dispatch.get("workflowRef"), str) and dispatch["workflowRef"],
            "hosted workflow ref is missing",
        )
        require(
            isinstance(dispatch.get("repository"), str) and dispatch["repository"],
            "hosted repository identity is missing",
        )


def check_expected_invocation(record: dict[str, Any], expected: dict[str, Any] | None) -> None:
    if expected is None:
        return
    dispatch = record.get("dispatch")
    if not isinstance(dispatch, dict):
        raise EvidenceError("record dispatch is missing")
    mapping = {
        "repository": "repository",
        "workflow": "workflow",
        "workflowRef": "workflowRef",
        "runId": "runId",
        "runAttempt": "runAttempt",
        "sha": "sha",
    }
    for expected_key, dispatch_key in mapping.items():
        value = expected.get(expected_key)
        require(isinstance(value, str) and value, f"expected invocation {expected_key} is missing")
        require(
            str(dispatch.get(dispatch_key)) == value,
            f"record dispatch {dispatch_key} does not match the combined invocation",
        )


def check_matrix_header(record: dict[str, Any], matrix: dict[str, Any]) -> None:
    header = require_exact_keys(record.get("matrix"), MATRIX_HEADER_KEYS, "matrix metadata")
    require(header["id"] == matrix["matrixId"], "matrix id is inconsistent")
    require(header["platforms"] == matrix["platforms"], "matrix platforms are inconsistent")
    require(
        header["pythonVersions"] == matrix["pythonVersions"],
        "matrix python versions are inconsistent",
    )
    require(
        header["rowIds"] == [row["id"] for row in matrix["rows"]], "matrix row ids are inconsistent"
    )
    require(
        header["requiredEvidence"] == matrix["requiredEvidence"],
        "required evidence list is inconsistent",
    )
    require(
        header["unsupportedPlatforms"] == matrix["unsupportedPlatforms"],
        "unsupported platform list is inconsistent",
    )
    required = record.get("review")
    if not isinstance(required, dict) or required.get("required") is not True:
        raise EvidenceError("review requirement is missing")
    require(
        required.get("disposition") == "pending-independent-lifecycle-review",
        "review disposition must not be self-attested",
    )


def check_store(value: Any, context: str) -> None:
    require_exact_keys(value, STORE_KEYS, context)
    for key in ("artifactRoots", "artifactFiles", "managedBytes"):
        require_int(value[key], f"{context}.{key}")
    require_bool(value["artifactRootRemoved"], f"{context}.artifactRootRemoved")


def check_cleanup(cell: dict[str, Any], require_complete: bool) -> None:
    cleanup = cell.get("cleanup")
    if not isinstance(cleanup, dict):
        raise EvidenceError(f"{cell['id']}: cleanup outcome is missing")
    require_exact_keys(cleanup, CLEANUP_KEYS, f"{cell['id']}: cleanup")
    for key in (
        "attempted",
        "completed",
        "serverExited",
        "runnerExited",
        "processGroupRemoved",
        "artifactRootRemoved",
        "forcedCleanup",
    ):
        require_bool(cleanup[key], f"{cell['id']}: cleanup.{key}")
    require_int(
        cleanup["managedProcessesRemaining"], f"{cell['id']}: cleanup.managedProcessesRemaining"
    )
    require_int(
        cleanup["managedArtifactsRemaining"], f"{cell['id']}: cleanup.managedArtifactsRemaining"
    )
    computed_complete = (
        cleanup["serverExited"]
        and cleanup["runnerExited"]
        and cleanup["processGroupRemoved"]
        and cleanup["managedProcessesRemaining"] == 0
        and cleanup["artifactRootRemoved"]
        and cleanup["managedArtifactsRemaining"] == 0
        and not cleanup["forcedCleanup"]
    )
    require(
        cleanup["completed"] == computed_complete,
        f"{cell['id']}: cleanup completion is contradictory",
    )
    if require_complete:
        require(cleanup["attempted"] is True, f"{cell['id']}: cleanup was not attempted")
        for key in (
            "completed",
            "serverExited",
            "runnerExited",
            "processGroupRemoved",
            "artifactRootRemoved",
        ):
            require(cleanup.get(key) is True, f"{cell['id']}: cleanup field {key} is not true")
        require(
            cleanup.get("managedProcessesRemaining") == 0, f"{cell['id']}: managed processes remain"
        )
        require(
            cleanup.get("managedArtifactsRemaining") == 0, f"{cell['id']}: managed artifacts remain"
        )
        require(
            cleanup.get("forcedCleanup") is False, f"{cell['id']}: cleanup required forced teardown"
        )


def check_transitions(cell: dict[str, Any], row_id: str, passed: bool) -> None:
    transitions = cell["stateTransition"]
    require(isinstance(transitions, list), f"{row_id}: state transitions are missing")
    if not transitions:
        require(not passed, f"{row_id}: passed cell has no state transitions")
        return
    required_phase = ROW_TRANSITIONS[row_id]
    observed_phases = [transition.get("phase") for transition in transitions]
    if passed:
        require(
            observed_phases == required_phase,
            f"{row_id}: transition phases are {observed_phases}, expected {required_phase}",
        )
    else:
        require(
            all(phase in required_phase or phase == "row-aborted" for phase in observed_phases),
            f"{row_id}: unknown transition phase",
        )
    allowed_keys = {"at", "phase", "serverState", "kernelState", "executionCount", "status"}
    for transition in transitions:
        require(isinstance(transition, dict), f"{row_id}: transition is not a mapping")
        require(set(transition) <= allowed_keys, f"{row_id}: transition has unknown keys")
        require(
            {"at", "phase", "serverState", "kernelState", "executionCount"} <= set(transition),
            f"{row_id}: transition is incomplete",
        )
        require_iso_time(transition["at"], f"{row_id}: transition.at")
        require(
            isinstance(transition["phase"], str) and transition["phase"],
            f"{row_id}: transition.phase is invalid",
        )
        require(
            transition["serverState"] in ALLOWED_SERVER_STATES,
            f"{row_id}: transition.serverState is invalid",
        )
        require(
            transition["kernelState"] in ALLOWED_KERNEL_STATES,
            f"{row_id}: transition.kernelState is invalid",
        )
        if transition["executionCount"] is not None:
            require_int(
                transition["executionCount"], f"{row_id}: transition.executionCount", minimum=0
            )
        if "status" in transition:
            require(
                transition["status"] in ALLOWED_STATUSES, f"{row_id}: transition.status is invalid"
            )
    if passed:
        expected_states = ROW_TRANSITION_STATES[row_id]
        expected_status = (
            "completed" if row_id == "artifact-integrity-expiry" else cell["observed"].get("status")
        )
        for transition in transitions:
            expected_server, expected_kernel = expected_states[transition["phase"]]
            require(
                transition["serverState"] == expected_server,
                f"{row_id}: {transition['phase']} serverState is "
                f"{transition['serverState']!r}, expected {expected_server!r}",
            )
            require(
                transition["kernelState"] == expected_kernel,
                f"{row_id}: {transition['phase']} kernelState is "
                f"{transition['kernelState']!r}, expected {expected_kernel!r}",
            )
            require(
                transition.get("status") == expected_status,
                f"{row_id}: {transition['phase']} status disagrees with observed",
            )
            if (row_id, transition["phase"]) in {
                ("normal-shutdown", "client-closed"),
                ("cancellation-cleanup", "client-closed-during-active-execution"),
            }:
                require(
                    transition["executionCount"] == 1,
                    f"{row_id}: {transition['phase']} executionCount "
                    "must be the exact observed count 1",
                )
        last = transitions[-1]
        if "serverState" in cell["observed"]:
            require(
                last["serverState"] == cell["observed"]["serverState"],
                f"{row_id}: final serverState disagrees with observed",
            )
        if "kernelState" in cell["observed"]:
            require(
                last["kernelState"] == cell["observed"]["kernelState"],
                f"{row_id}: final kernelState disagrees with observed",
            )


def check_process_observations(cell: dict[str, Any], row_id: str, passed: bool) -> None:
    observations = cell["processObservations"]
    require(isinstance(observations, list), f"{row_id}: process observations are missing")
    if not observations:
        require(not passed, f"{row_id}: passed cell has no process observations")
        return
    required_phases = ROW_PROCESS_PHASES[row_id]
    phases = [observation.get("phase") for observation in observations]
    if passed:
        require(
            phases == required_phases,
            f"{row_id}: process phases are {phases}, expected {required_phases}",
        )
    snapshot_keys = {
        "at",
        "phase",
        "managedProcessCount",
        "serverDescendantCount",
        "processGroup",
        "processes",
    }
    group_keys = {"token", "exists"}
    process_keys = {"role", "token", "alive"}
    seen_roles: set[str] = set()
    for observation in observations:
        require_exact_keys(observation, snapshot_keys, f"{row_id}: process snapshot")
        require_iso_time(observation["at"], f"{row_id}: process snapshot.at")
        require(
            isinstance(observation["phase"], str) and observation["phase"],
            f"{row_id}: process snapshot.phase is invalid",
        )
        require_int(observation["managedProcessCount"], f"{row_id}: managedProcessCount")
        require_int(observation["serverDescendantCount"], f"{row_id}: serverDescendantCount")
        require_exact_keys(observation["processGroup"], group_keys, f"{row_id}: processGroup")
        require(
            isinstance(observation["processGroup"]["token"], str)
            and TOKEN_RE.fullmatch(observation["processGroup"]["token"]),
            f"{row_id}: processGroup token is invalid",
        )
        require_bool(observation["processGroup"]["exists"], f"{row_id}: processGroup.exists")
        processes = observation["processes"]
        require(isinstance(processes, list) and processes, f"{row_id}: processes are missing")
        roles: set[str] = set()
        alive = 0
        server_alive = False
        for process in processes:
            require_exact_keys(process, process_keys, f"{row_id}: process")
            require(
                process["role"] in {"server", "runner", "child"},
                f"{row_id}: process role is invalid",
            )
            require(process["role"] not in roles, f"{row_id}: duplicate process role")
            roles.add(process["role"])
            require(
                isinstance(process["token"], str) and TOKEN_RE.fullmatch(process["token"]),
                f"{row_id}: process token is invalid",
            )
            require_bool(process["alive"], f"{row_id}: process.alive")
            if process["alive"]:
                alive += 1
            if process["role"] == "server" and process["alive"]:
                server_alive = True
        require(
            observation["managedProcessCount"] == alive,
            f"{row_id}: managedProcessCount disagrees with live roles",
        )
        expected_descendants = (alive - 1) if server_alive else 0
        require(
            observation["serverDescendantCount"] == expected_descendants,
            f"{row_id}: serverDescendantCount disagrees with live roles",
        )
        seen_roles.update(roles)
    if passed:
        require(
            {"server", "runner"} <= seen_roles,
            f"{row_id}: server and runner were not both observed alive",
        )


def check_resources(cell: dict[str, Any], row_id: str, observations: list[dict[str, Any]]) -> None:
    resources = cell["resourceObservations"]
    if not resources:
        require(cell["outcome"] != "passed", f"{row_id}: passed cell has no resource observations")
        return
    require_exact_keys(resources, ROW_RESOURCES[row_id], f"{row_id}: resourceObservations")
    for key in ("storeRoots", "storeRootsBeforeShutdown"):
        if key in resources:
            require_int(resources[key], f"{row_id}: {key}", minimum=1)
    if "observedManagedProcesses" in resources:
        require_int(resources["observedManagedProcesses"], f"{row_id}: observedManagedProcesses")
    if "shutdownElapsedSeconds" in resources:
        value = resources["shutdownElapsedSeconds"]
        require(
            isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0,
            f"{row_id}: shutdownElapsedSeconds is invalid",
        )
        require(
            value < TERMINATION_GRACE_SECONDS,
            f"{row_id}: SDK termination window was required before the server exited",
        )
    for key in TOKEN_KEYS:
        if key in resources:
            require(
                isinstance(resources[key], str) and TOKEN_RE.fullmatch(resources[key]),
                f"{row_id}: {key} is not a token",
            )
    for key in SHA256_KEYS:
        if key in resources:
            require(
                isinstance(resources[key], str) and SHA256_RE.fullmatch(resources[key]),
                f"{row_id}: {key} is not a SHA-256 digest",
            )
    for key in BOOL_KEYS:
        if key in resources:
            require_bool(resources[key], f"{row_id}: {key}")
    for key in INT_KEYS:
        if key in resources:
            minimum = 0 if key in {"tamperedPartIndex"} else 1
            require_int(resources[key], f"{row_id}: {key}", minimum=minimum)
    if "store" in resources:
        check_store(resources["store"], f"{row_id}: store")
    if "storeAfterEviction" in resources:
        check_store(resources["storeAfterEviction"], f"{row_id}: storeAfterEviction")
    if "activeExecutionAborted" in resources:
        require(
            isinstance(resources["activeExecutionAborted"], str)
            and resources["activeExecutionAborted"],
            f"{row_id}: activeExecutionAborted is missing",
        )
        require(
            resources["activeExecutionAborted"] != "not_finished",
            f"{row_id}: active execution did not abort",
        )
    group_tokens = {observation["processGroup"]["token"] for observation in observations}
    process_tokens = {
        process["token"] for observation in observations for process in observation["processes"]
    }
    if "runnerGroupToken" in resources:
        require(
            resources["runnerGroupToken"] in group_tokens,
            f"{row_id}: runnerGroupToken was not observed",
        )
    if row_id == "destructive-reset":
        require(
            resources["previousRunnerToken"] != resources["replacementRunnerToken"],
            f"{row_id}: reset did not replace the runner",
        )
        require(
            resources["previousRunnerToken"] in process_tokens,
            f"{row_id}: previous runner was not observed",
        )
        require(
            resources["replacementRunnerToken"] in process_tokens,
            f"{row_id}: replacement runner was not observed",
        )
        final_runner = next(
            process for process in observations[-1]["processes"] if process["role"] == "runner"
        )
        require(
            final_runner["token"] == resources["replacementRunnerToken"],
            f"{row_id}: replacement runner token disagrees with the final snapshot",
        )
    if row_id == "timeout-survives":
        require(
            resources["runnerToken"] == resources["continuationRunnerToken"],
            f"{row_id}: continuation did not use the same runner",
        )
        require(
            resources["runnerToken"] in process_tokens, f"{row_id}: runner token was not observed"
        )
    if row_id in {"timeout-escalates", "runner-channel-death"}:
        final = observations[-1]
        key = (
            "processGroupExistsAfterEscalation"
            if row_id == "timeout-escalates"
            else "processGroupExistsAfterDeath"
        )
        require(
            resources[key] == final["processGroup"]["exists"],
            f"{row_id}: process-group result disagrees with the final snapshot",
        )
        require(
            resources["runnerToken"] in process_tokens, f"{row_id}: runner token was not observed"
        )
        runner = next(process for process in final["processes"] if process["role"] == "runner")
        require(runner["alive"] is False, f"{row_id}: final runner is still alive")
    if row_id == "output-limit-drain":
        require(
            resources["manifestVerifiedBytes"] == resources["stdoutArtifactSize"],
            f"{row_id}: manifest bytes disagree with artifact size",
        )
        require(
            resources["store"]["managedBytes"] >= resources["stdoutArtifactSize"],
            f"{row_id}: store does not contain the artifact bytes",
        )
        require(
            resources["store"]["artifactRoots"] >= 1,
            f"{row_id}: artifact store root was not observed",
        )
    if row_id == "artifact-integrity-expiry":
        require(
            resources["tamperedPartIndex"] < resources["manifestPartCount"],
            f"{row_id}: tampered part index is outside the manifest",
        )
        require(
            resources["storeAfterEviction"]["managedBytes"] <= resources["storeCeilingBytes"],
            f"{row_id}: managed bytes exceed the ceiling",
        )
        require(
            resources["storeAfterEviction"]["artifactRoots"] >= 1,
            f"{row_id}: artifact store root was not observed",
        )
    if row_id == "installed-startup":
        require(
            resources["observedManagedProcesses"] == observations[0]["managedProcessCount"],
            f"{row_id}: managed process count disagrees with the snapshot",
        )
    if row_id == "normal-shutdown":
        check = next((item for item in cell["checks"] if item["name"] == "unforcedShutdown"), None)
        require(
            check is not None and check["passed"] is True and check["observed"] is True,
            f"{row_id}: unforced shutdown was not established",
        )
        require(
            cell["stateTransition"][-1]["serverState"] == cell["observed"]["serverState"],
            f"{row_id}: final server state disagrees with the transition",
        )
        require(
            cell["stateTransition"][-1]["kernelState"] == cell["observed"]["kernelState"],
            f"{row_id}: final kernel state disagrees with the transition",
        )
        require(
            cell["cleanup"]["serverExited"] is (cell["observed"]["serverState"] == "exited"),
            f"{row_id}: cleanup does not support server exit",
        )
        require(
            cell["cleanup"]["runnerExited"] is (cell["observed"]["kernelState"] == "dead"),
            f"{row_id}: cleanup does not support runner death",
        )
    if row_id == "cancellation-cleanup":
        require(
            cell["stateTransition"][-1]["serverState"] == cell["observed"]["serverState"],
            f"{row_id}: final server state disagrees with the transition",
        )
        require(
            cell["stateTransition"][-1]["kernelState"] == cell["observed"]["kernelState"],
            f"{row_id}: final kernel state disagrees with the transition",
        )
        require(
            cell["cleanup"]["serverExited"] is (cell["observed"]["serverState"] == "exited"),
            f"{row_id}: cleanup does not support server exit",
        )
        require(
            cell["cleanup"]["runnerExited"] is (cell["observed"]["kernelState"] == "dead"),
            f"{row_id}: cleanup does not support runner death",
        )
        require(
            any(
                process["role"] == "child" and process["alive"]
                for observation in observations
                for process in observation["processes"]
            ),
            f"{row_id}: active descendant was not observed",
        )


def check_transition_process_agreement(cell: dict[str, Any], row_id: str) -> None:
    if cell["outcome"] != "passed":
        return
    transitions = cell["stateTransition"]
    phase_map = ROW_TRANSITION_PROCESS_PHASE[row_id]
    observations = {
        observation["phase"]: observation for observation in cell["processObservations"]
    }
    for transition in transitions:
        process_phase = phase_map.get(transition["phase"])
        if process_phase is None:
            continue
        require(
            process_phase in observations,
            f"{row_id}: {transition['phase']} has no matching process observation",
        )
        observation = observations[process_phase]
        processes = {process["role"]: process["alive"] for process in observation["processes"]}
        if transition["serverState"] in {"ready", "running"}:
            require(
                processes.get("server") is True,
                f"{row_id}: {transition['phase']} claims a live server without process proof",
            )
        elif transition["serverState"] == "exited":
            require(
                processes.get("server") is False,
                f"{row_id}: {transition['phase']} claims an exited server without process proof",
            )
        if transition["kernelState"] == "alive":
            require(
                processes.get("runner") is True,
                f"{row_id}: {transition['phase']} claims a live runner without process proof",
            )
        elif transition["kernelState"] == "dead":
            require(
                processes.get("runner") is False,
                f"{row_id}: {transition['phase']} claims a dead runner without process proof",
            )


def validate_cell(cell: dict[str, Any], row: dict[str, Any]) -> list[str]:
    row_id = row["id"]
    require(isinstance(cell, dict), "cell is not a mapping")
    require_exact_keys(cell, CELL_KEYS, f"{row_id}: cell")
    require(cell.get("id") == row_id, "cell id does not match the matrix row")
    require(
        cell.get("operation") == row["operation"], f"{row_id}: operation does not match the matrix"
    )
    require(cell.get("expected") == row["expected"], f"{row_id}: expected values were altered")
    require(
        cell.get("expectedSha256") == sha256_text(canonical_json_bytes(row["expected"]).decode()),
        f"{row_id}: expected-value hash does not match the matrix",
    )
    require(isinstance(cell.get("observed"), dict), f"{row_id}: observed mapping is missing")
    require(
        set(cell["observed"]) == set(row["expected"]),
        f"{row_id}: observed keys do not match the matrix",
    )
    require(
        isinstance(cell.get("stateTransition"), list), f"{row_id}: state transitions are missing"
    )
    require(
        isinstance(cell.get("processObservations"), list),
        f"{row_id}: process observations are missing",
    )
    require(
        isinstance(cell.get("resourceObservations"), dict),
        f"{row_id}: resource observations are missing",
    )
    require(
        isinstance(cell.get("checks"), list) and cell["checks"], f"{row_id}: checks are missing"
    )
    require_int(cell.get("durationMs"), f"{row_id}: duration")
    require(
        isinstance(cell.get("limitations"), list)
        and all(isinstance(item, str) for item in cell["limitations"]),
        f"{row_id}: limitations are invalid",
    )
    require(cell.get("outcome") in {"passed", "failed"}, f"{row_id}: outcome is invalid")
    require(
        cell.get("errorType") is None or isinstance(cell.get("errorType"), str),
        f"{row_id}: errorType is invalid",
    )
    passed = cell["outcome"] == "passed"
    if passed:
        require(cell.get("errorType") is None, f"{row_id}: passed cell retained an error")
        for key, expected in row["expected"].items():
            require(
                cell["observed"].get(key) == expected,
                f"{row_id}: passed cell observed {key}={cell['observed'].get(key)!r}, "
                f"expected {expected!r}",
            )
    else:
        require(
            cell.get("errorType") is not None
            or any(check.get("passed") is not True for check in cell["checks"]),
            f"{row_id}: failed cell has no failure reason",
        )
    check_cleanup(cell, require_complete=passed)
    check_transitions(cell, row_id, passed)
    check_process_observations(cell, row_id, passed)
    check_transition_process_agreement(cell, row_id)
    if passed:
        check_resources(cell, row_id, cell["processObservations"])
    check_checks(cell, row, passed)
    return (
        []
        if passed
        else [f"{row_id}: outcome is {cell['outcome']!r} (errorType={cell['errorType']!r})"]
    )


def check_checks(cell: dict[str, Any], row: dict[str, Any], passed: bool) -> None:
    row_id = row["id"]
    recorded: dict[str, dict[str, Any]] = {}
    for check in cell["checks"]:
        require_exact_keys(check, CHECK_KEYS, f"{row_id}: check")
        require(
            isinstance(check["name"], str) and check["name"], f"{row_id}: check name is invalid"
        )
        require(check["name"] not in recorded, f"{row_id}: duplicate check {check['name']}")
        require_bool(check["passed"], f"{row_id}: check {check['name']}.passed is invalid")
        require(
            check["passed"] == (check["expected"] == check["observed"]),
            f"{row_id}: check {check['name']} is contradictory",
        )
        recorded[check["name"]] = check
    for key in row["expected"]:
        require(key in recorded, f"{row_id}: expected key {key} has no recorded check")
        require(
            recorded[key]["expected"] == row["expected"][key],
            f"{row_id}: check {key} expected value was altered",
        )
        if passed:
            require(recorded[key]["passed"] is True, f"{row_id}: expected check {key} did not pass")
    computed_passed = (
        cell["errorType"] is None
        and all(check["passed"] for check in cell["checks"])
        and len(cell["observed"]) >= len(row["expected"])
    )
    require(passed == computed_passed, f"{row_id}: outcome contradicts its checks or error state")


def validate_record(
    record: dict[str, Any],
    matrix: dict[str, Any],
    source_root: Path,
    *,
    require_hosted: bool,
    wheel_source_root: Path | None = None,
    wheel_path: Path | None = None,
    expected_invocation: dict[str, Any] | None = None,
    expected_wheel_sha256: str | None = None,
    expected_wheel_source_revision: str | None = None,
) -> list[str]:
    require_exact_keys(record, RECORD_KEYS, "record")
    require(record.get("schemaVersion") == SCHEMA_VERSION, "schema version is unsupported")
    require(
        record.get("recordKind") == "amkernel-cross-os-process-matrix", "record kind is unsupported"
    )
    require(isinstance(record.get("recordId"), str) and record["recordId"], "record id is missing")
    require(
        isinstance(record.get("createdAt"), str) and record["createdAt"].endswith("Z"),
        "creation time is missing",
    )
    check_hosted_dispatch(record, require_hosted)
    if require_hosted:
        require(
            expected_invocation is not None,
            "hosted validation requires the exact expected invocation",
        )
        require(
            expected_wheel_sha256 is not None, "hosted validation requires the expected wheel hash"
        )
        require(
            expected_wheel_source_revision is not None,
            "hosted validation requires the expected wheel source revision",
        )
    check_expected_invocation(record, expected_invocation)
    check_sources(record, source_root, wheel_source_root or source_root)
    check_expected_wheel(record, expected_wheel_sha256, expected_wheel_source_revision)
    check_environment(record, matrix)
    check_environment_wheel_identity(record)
    check_matrix_header(record, matrix)
    if wheel_path is not None:
        check_wheel_file(record, wheel_path)
    cells = record.get("cells")
    if not isinstance(cells, list):
        raise EvidenceError("cells are missing")
    require(
        [cell.get("id") for cell in cells] == [row["id"] for row in matrix["rows"]],
        "cell order or membership does not match the frozen matrix",
    )
    problems: list[str] = []
    for cell, row in zip(cells, matrix["rows"], strict=True):
        problems.extend(validate_cell(cell, row))
    for cell in cells:
        body = {key: value for key, value in cell.items() if key != "cellSha256"}
        require(
            cell.get("cellSha256") == sha256_text(canonical_json_bytes(body).decode()),
            f"{cell['id']}: cell hash does not recompute",
        )
    expected_cells = sha256_text(
        canonical_json_bytes([cell["cellSha256"] for cell in cells]).decode()
    )
    require(record.get("cellsSha256") == expected_cells, "aggregate cell hash does not recompute")
    body = {key: value for key, value in record.items() if key != "contentSha256"}
    require(
        record.get("contentSha256") == sha256_text(canonical_json_bytes(body).decode()),
        "record content hash does not recompute",
    )
    check_privacy(record)
    return problems


def evidence_files(directory: Path) -> list[Path]:
    return sorted(directory.rglob("process-evidence-*.json"))


def combine(
    records: list[tuple[Path, dict[str, Any]]],
    matrix: dict[str, Any],
    source_root: Path,
    expected_invocation: dict[str, Any],
    *,
    wheel_source_root: Path,
    expected_wheel_sha256: str,
    expected_wheel_source_revision: str,
) -> dict[str, Any]:
    require(records, "no evidence records were supplied")
    expected_sources = source_hashes(source_root)
    environments: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    failures: list[str] = []
    wheel_identities: set[tuple[Any, ...]] = set()
    for path, record in records:
        record_failures = validate_record(
            record,
            matrix,
            source_root,
            require_hosted=True,
            wheel_source_root=wheel_source_root,
            wheel_path=None,
            expected_invocation=expected_invocation,
            expected_wheel_sha256=expected_wheel_sha256,
            expected_wheel_source_revision=expected_wheel_source_revision,
        )
        failures.extend(record_failures)
        environment = record["environment"]
        key = (environment["matrixPlatform"], environment["python"]["majorMinor"])
        require(key not in seen, f"duplicate evidence environment: {key}")
        seen.add(key)
        sources = record["sources"]
        for name in ("matrix", "harness", "lock"):
            require(
                sources[name]["sha256"] == expected_sources[name]["sha256"],
                f"{path.name}: {name} source differs from the combined checkout",
            )
        require(
            sources["contracts"] == expected_sources["contracts"],
            f"{path.name}: contract sources differ from the combined checkout",
        )
        wheel = sources["wheel"]
        wheel_identities.add(
            (
                wheel["filename"],
                wheel["sha256"],
                wheel["sizeBytes"],
                wheel["packageFileCount"],
                wheel["packageSha256"],
                wheel["sourceRevision"],
                wheel["sourceRootKind"],
            )
        )
        cells = [
            {
                "id": cell["id"],
                "outcome": cell["outcome"],
                "cellSha256": cell["cellSha256"],
                "checksPassed": sum(1 for check in cell["checks"] if check["passed"]),
                "checksTotal": len(cell["checks"]),
            }
            for cell in record["cells"]
        ]
        if any(cell["outcome"] != "passed" for cell in record["cells"]):
            failures.append(f"{path.name}: at least one matrix cell failed")
        environments.append(
            {
                "environmentId": f"{key[0]}-cpython-{key[1]}",
                "matrixPlatform": key[0],
                "pythonMajorMinor": key[1],
                "os": environment["os"],
                "python": environment["python"],
                "runner": environment["runner"],
                "wheel": environment["wheel"],
                "evidenceFile": path.name,
                "evidenceSha256": sha256_path(path),
                "recordContentSha256": record["contentSha256"],
                "cells": cells,
            }
        )
    require(len(wheel_identities) == 1, "evidence environments used different wheel identities")
    dispatch_shas = {record["dispatch"]["sha"] for _path, record in records}
    require(len(dispatch_shas) == 1, "evidence environments came from different commits")
    required = {
        (str(platform), str(version))
        for platform in matrix["platforms"]
        for version in matrix["pythonVersions"]
    }
    missing = sorted(required - seen)
    require(not missing, f"required environment coverage is missing: {missing}")
    require(
        not (seen - required), f"unexpected environments were supplied: {sorted(seen - required)}"
    )
    environments.sort(
        key=lambda item: (
            matrix["platforms"].index(item["matrixPlatform"]),
            matrix["pythonVersions"].index(item["pythonMajorMinor"]),
        )
    )
    passed_cells = sum(
        1
        for environment in environments
        for cell in environment["cells"]
        if cell["outcome"] == "passed"
    )
    total_cells = sum(len(environment["cells"]) for environment in environments)
    wheel = next(iter(wheel_identities))
    index: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "indexKind": "amkernel-cross-os-process-matrix-index",
        "matrix": {
            "id": matrix["matrixId"],
            "sha256": expected_sources["matrix"]["sha256"],
            "platforms": matrix["platforms"],
            "pythonVersions": matrix["pythonVersions"],
            "rowIds": [row["id"] for row in matrix["rows"]],
            "unsupportedPlatforms": matrix["unsupportedPlatforms"],
        },
        "invocation": expected_invocation,
        "sources": {
            "harnessSha256": expected_sources["harness"]["sha256"],
            "contracts": expected_sources["contracts"],
            "lockSha256": expected_sources["lock"]["sha256"],
            "sourceRoot": "checkout",
        },
        "wheel": {
            "filename": wheel[0],
            "sha256": wheel[1],
            "sizeBytes": wheel[2],
            "packageFileCount": wheel[3],
            "packageSha256": wheel[4],
            "sourceRevision": wheel[5],
            "sourceRootKind": wheel[6],
        },
        "environments": environments,
        "totals": {
            "environments": len(environments),
            "cells": total_cells,
            "passedCells": passed_cells,
            "failedCells": total_cells - passed_cells,
        },
        "outcome": "observed" if not failures else "failed",
        "failures": failures,
        "limitations": [
            "The index covers only the frozen POSIX process matrix; "
            "Windows, Android, and iOS are not claimed.",
            "The index links retained per-environment evidence and does not replace "
            "independent lifecycle review.",
            "Review disposition remains pending until the parent records its independent review.",
        ],
        "review": {
            "required": True,
            "disposition": "pending-independent-lifecycle-review",
        },
        "createdAt": max(record["createdAt"] for _path, record in records),
    }
    index["indexSha256"] = sha256_text(canonical_json_bytes(index).decode())
    return index


def expected_invocation_from_args(args: argparse.Namespace) -> dict[str, Any]:
    values = {
        "repository": args.expected_repository,
        "workflow": args.expected_workflow,
        "workflowRef": args.expected_workflow_ref,
        "runId": args.expected_run_id,
        "runAttempt": args.expected_run_attempt,
        "sha": args.expected_sha,
    }
    require(
        all(isinstance(value, str) and value for value in values.values()),
        "every expected invocation value is required",
    )
    return values


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate one hosted evidence record")
    validate.add_argument("--evidence", required=True)
    validate.add_argument("--matrix", required=True)
    validate.add_argument("--source-root", required=True)
    validate.add_argument("--wheel-source-root")
    validate.add_argument("--wheel")
    validate.add_argument("--require-hosted", action="store_true")
    validate.add_argument("--expected-wheel-sha256")
    validate.add_argument("--expected-wheel-source-revision")
    validate.add_argument("--expected-repository")
    validate.add_argument("--expected-workflow")
    validate.add_argument("--expected-workflow-ref")
    validate.add_argument("--expected-run-id")
    validate.add_argument("--expected-run-attempt")
    validate.add_argument("--expected-sha")
    validate.add_argument("--summary")

    combined = subparsers.add_parser("combine", help="combine hosted records into one index")
    combined.add_argument("--evidence-dir", required=True)
    combined.add_argument("--matrix", required=True)
    combined.add_argument("--source-root", required=True)
    combined.add_argument("--wheel-source-root", required=True)
    combined.add_argument("--expected-wheel-sha256", required=True)
    combined.add_argument("--expected-wheel-source-revision", required=True)
    combined.add_argument("--output", required=True)
    combined.add_argument("--expected-repository", required=True)
    combined.add_argument("--expected-workflow", required=True)
    combined.add_argument("--expected-workflow-ref", required=True)
    combined.add_argument("--expected-run-id", required=True)
    combined.add_argument("--expected-run-attempt", required=True)
    combined.add_argument("--expected-sha", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    matrix = load_matrix(Path(args.matrix))
    source_root = Path(args.source_root).resolve()
    if args.command == "validate":
        evidence_path = Path(args.evidence)
        record = json.loads(evidence_path.read_text(encoding="utf-8"))
        expected_invocation = None
        invocation_args = (
            args.expected_repository,
            args.expected_workflow,
            args.expected_workflow_ref,
            args.expected_run_id,
            args.expected_run_attempt,
            args.expected_sha,
        )
        if args.require_hosted or any(value is not None for value in invocation_args):
            expected_invocation = expected_invocation_from_args(args)
        wheel_source_root = (
            Path(args.wheel_source_root).resolve() if args.wheel_source_root else source_root
        )
        problems = validate_record(
            record,
            matrix,
            source_root,
            require_hosted=args.require_hosted,
            wheel_source_root=wheel_source_root,
            wheel_path=Path(args.wheel) if args.wheel else None,
            expected_invocation=expected_invocation,
            expected_wheel_sha256=args.expected_wheel_sha256,
            expected_wheel_source_revision=args.expected_wheel_source_revision,
        )
        summary = {
            "evidence": evidence_path.name,
            "evidenceSha256": sha256_path(evidence_path),
            "contentSha256": record["contentSha256"],
            "cells": len(record["cells"]),
            "passed": sum(1 for cell in record["cells"] if cell["outcome"] == "passed"),
            "failed": sum(1 for cell in record["cells"] if cell["outcome"] != "passed"),
            "problems": problems,
        }
        if args.summary:
            Path(args.summary).write_text(
                json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0 if not problems else 1
    records = [
        (path, json.loads(path.read_text(encoding="utf-8")))
        for path in evidence_files(Path(args.evidence_dir))
    ]
    expected_invocation = expected_invocation_from_args(args)
    index = combine(
        records,
        matrix,
        source_root,
        expected_invocation,
        wheel_source_root=Path(args.wheel_source_root).resolve(),
        expected_wheel_sha256=args.expected_wheel_sha256,
        expected_wheel_source_revision=args.expected_wheel_source_revision,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {key: index[key] for key in ("outcome", "totals", "review", "indexSha256")}, indent=2
        )
    )
    return 0 if index["outcome"] == "observed" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except EvidenceError as error:
        print(f"evidence validation failed: {error}", file=sys.stderr)
        raise SystemExit(2) from error
