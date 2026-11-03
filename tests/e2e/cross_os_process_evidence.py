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


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def load_matrix(path: Path) -> dict[str, Any]:
    matrix = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(matrix.get("rows"), list) and matrix["rows"], "matrix rows are missing")
    require(matrix["matrixId"], "matrix id is missing")
    return matrix


def source_hashes(source_root: Path) -> dict[str, Any]:
    return {
        "matrix": sha256_path(source_root / MATRIX_PATH),
        "harness": sha256_path(source_root / HARNESS_PATH),
        "contracts": [
            {"path": path, "sha256": sha256_path(source_root / path)} for path in CONTRACT_PATHS
        ],
        "lock": sha256_path(source_root / "uv.lock"),
    }


def check_privacy(record: dict[str, Any]) -> None:
    text = json.dumps(record, ensure_ascii=False)
    for pattern in PRIVATE_PATTERNS:
        match = pattern.search(text)
        require(match is None, f"evidence contains a private path or credential-shaped value: {pattern.pattern}")


def check_sources(record: dict[str, Any], source_root: Path) -> None:
    expected = source_hashes(source_root)
    sources = record.get("sources")
    require(isinstance(sources, dict), "sources mapping is missing")
    require(sources["matrix"]["path"] == MATRIX_PATH, "matrix source path is not frozen")
    require(sources["matrix"]["sha256"] == expected["matrix"], "matrix hash does not match the checkout")
    require(sources["harness"]["path"] == HARNESS_PATH, "harness path is not frozen")
    require(sources["harness"]["sha256"] == expected["harness"], "harness hash does not match the checkout")
    require(sources["lock"]["path"] == "uv.lock", "lock path is not frozen")
    require(sources["lock"]["sha256"] == expected["lock"], "lock hash does not match the checkout")
    contracts = sources.get("contracts")
    require(isinstance(contracts, list) and len(contracts) == len(CONTRACT_PATHS), "contract sources are incomplete")
    for actual, expected_contract in zip(contracts, expected["contracts"]):
        require(actual == expected_contract, "contract hash does not match the checkout")
    wheel = sources.get("wheel")
    require(isinstance(wheel, dict), "wheel identity is missing")
    require(isinstance(wheel.get("filename"), str) and wheel["filename"], "wheel filename is missing")
    require(re.fullmatch(r"[0-9a-f]{64}", str(wheel.get("sha256"))), "wheel hash is malformed")
    require(isinstance(wheel.get("sizeBytes"), int) and wheel["sizeBytes"] > 0, "wheel size is missing")


def check_wheel_file(record: dict[str, Any], wheel_path: Path) -> None:
    wheel = record["sources"]["wheel"]
    require(wheel_path.is_file(), "supplied wheel is missing")
    require(wheel_path.stat().st_size == wheel["sizeBytes"], "wheel size does not match evidence")
    require(sha256_path(wheel_path) == wheel["sha256"], "wheel hash does not match evidence")
    environment_wheel = record["environment"]["wheel"]
    require(environment_wheel["filename"] == wheel_path.name, "environment wheel filename disagrees")
    require(environment_wheel["sha256"] == wheel["sha256"], "environment wheel hash disagrees")
    require(environment_wheel["sizeBytes"] == wheel["sizeBytes"], "environment wheel size disagrees")


def check_environment(record: dict[str, Any], matrix: dict[str, Any]) -> None:
    environment = record.get("environment")
    require(isinstance(environment, dict), "environment identity is missing")
    os_identity = environment.get("os")
    require(isinstance(os_identity, dict), "operating-system identity is missing")
    require(os_identity.get("system") in {"Linux", "Darwin"}, "unsupported observed operating system")
    expected_platform = {"Linux": "ubuntu-latest", "Darwin": "macos-latest"}[os_identity["system"]]
    require(environment["matrixPlatform"] == expected_platform, "matrix platform does not match the OS")
    require(environment["declaredPlatform"] == expected_platform, "declared platform is inconsistent")
    require(environment["platformDeclarationMatches"] is True, "platform declaration mismatch was observed")
    require(expected_platform in matrix["platforms"], "observed platform is not in the frozen matrix")
    python_identity = environment.get("python")
    require(isinstance(python_identity, dict), "python identity is missing")
    require(python_identity.get("implementation") == "CPython", "python implementation is not CPython")
    require(python_identity.get("majorMinor") in matrix["pythonVersions"], "python minor is not in the matrix")
    require(
        str(python_identity.get("version", "")).startswith(str(python_identity["majorMinor"]) + "."),
        "python version does not match its major/minor identity",
    )
    require(python_identity.get("isVenvLauncher") is True, "harness interpreter is not the isolated venv launcher")
    wheel = environment["wheel"]
    require(wheel["version"] == wheel["installedVersion"], "wheel and installed distribution versions differ")
    require(
        wheel["entryPointVersionOutput"] == f"amkernel {wheel['version']}",
        "installed entry point version output is inconsistent",
    )
    require(environment["entryPoint"]["present"] is True, "installed entry point is absent")
    require(environment["entryPoint"]["executable"] is True, "installed entry point is not executable")


def check_hosted_dispatch(record: dict[str, Any], require_hosted: bool) -> None:
    context = record.get("executionContext")
    require(context in {"hosted", "local"}, "execution context is missing")
    if require_hosted:
        require(context == "hosted", "record is not from a hosted workflow")
        dispatch = record.get("dispatch")
        require(isinstance(dispatch, dict), "hosted dispatch identity is missing")
        require(re.fullmatch(r"\d+", str(dispatch.get("runId"))), "hosted run id is missing")
        require(re.fullmatch(r"\d+", str(dispatch.get("runAttempt"))), "hosted run attempt is missing")
        require(re.fullmatch(r"[0-9a-f]{40}", str(dispatch.get("sha"))), "hosted commit identity is missing")
        require(isinstance(dispatch.get("job"), str) and dispatch["job"], "hosted job identity is missing")
        require(isinstance(dispatch.get("workflow"), str) and dispatch["workflow"], "hosted workflow identity is missing")


def check_matrix_header(record: dict[str, Any], matrix: dict[str, Any]) -> None:
    header = record.get("matrix")
    require(isinstance(header, dict), "matrix metadata is missing")
    require(header["id"] == matrix["matrixId"], "matrix id is inconsistent")
    require(header["platforms"] == matrix["platforms"], "matrix platforms are inconsistent")
    require(header["pythonVersions"] == matrix["pythonVersions"], "matrix python versions are inconsistent")
    require(header["rowIds"] == [row["id"] for row in matrix["rows"]], "matrix row ids are inconsistent")
    require(header["requiredEvidence"] == matrix["requiredEvidence"], "required evidence list is inconsistent")
    require(header["unsupportedPlatforms"] == matrix["unsupportedPlatforms"], "unsupported platform list is inconsistent")
    required = record.get("review")
    require(isinstance(required, dict) and required.get("required") is True, "review requirement is missing")
    require(
        required.get("disposition") == "pending-independent-lifecycle-review",
        "review disposition must not be self-attested",
    )


def check_cleanup(cell: dict[str, Any]) -> None:
    cleanup = cell.get("cleanup")
    require(isinstance(cleanup, dict), f"{cell['id']}: cleanup outcome is missing")
    require(cleanup.get("attempted") is True, f"{cell['id']}: cleanup was not attempted")
    for key in ("completed", "serverExited", "runnerExited", "processGroupRemoved", "artifactRootRemoved"):
        require(cleanup.get(key) is True, f"{cell['id']}: cleanup field {key} is not true")
    require(cleanup.get("managedProcessesRemaining") == 0, f"{cell['id']}: managed processes remain")
    require(cleanup.get("managedArtifactsRemaining") == 0, f"{cell['id']}: managed artifacts remain")
    require(cleanup.get("forcedCleanup") is False, f"{cell['id']}: cleanup required forced teardown")


def validate_cell(cell: dict[str, Any], row: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    require(cell.get("id") == row["id"], "cell id does not match the matrix row")
    require(cell.get("operation") == row["operation"], f"{row['id']}: operation does not match the matrix")
    require(cell.get("expected") == row["expected"], f"{row['id']}: expected values were altered")
    require(
        cell.get("expectedSha256") == sha256_text(canonical_json_bytes(row["expected"]).decode()),
        f"{row['id']}: expected-value hash does not match the matrix",
    )
    require(isinstance(cell.get("observed"), dict), f"{row['id']}: observed mapping is missing")
    for key in row["expected"]:
        require(key in cell["observed"], f"{row['id']}: expected key {key} was not observed")
    require(isinstance(cell.get("stateTransition"), list) and cell["stateTransition"], f"{row['id']}: state transitions are missing")
    require(
        isinstance(cell.get("processObservations"), list) and cell["processObservations"],
        f"{row['id']}: process observations are missing",
    )
    require(
        isinstance(cell.get("resourceObservations"), dict) and cell["resourceObservations"],
        f"{row['id']}: resource observations are missing",
    )
    require(isinstance(cell.get("checks"), list) and cell["checks"], f"{row['id']}: checks are missing")
    require(isinstance(cell.get("durationMs"), int) and cell["durationMs"] >= 0, f"{row['id']}: duration is invalid")
    require(isinstance(cell.get("limitations"), list), f"{row['id']}: limitations are missing")
    if cell.get("outcome") == "passed":
        require(cell.get("errorType") is None, f"{row['id']}: passed cell retained an error")
        check_cleanup(cell)
        for key, expected in row["expected"].items():
            require(
                cell["observed"].get(key) == expected,
                f"{row['id']}: passed cell observed {key}={cell['observed'].get(key)!r}, expected {expected!r}",
            )
        for check in cell["checks"]:
            require(check.get("passed") is True, f"{row['id']}: check {check.get('name')} did not pass")
    else:
        problems.append(f"{row['id']}: outcome is {cell.get('outcome')!r} (errorType={cell.get('errorType')!r})")
    recorded = {check.get("name"): check for check in cell["checks"]}
    for key in row["expected"]:
        require(key in recorded, f"{row['id']}: expected key {key} has no recorded check")
        require(
            recorded[key].get("expected") == row["expected"][key],
            f"{row['id']}: check {key} expected value was altered",
        )
    return problems


def validate_record(
    record: dict[str, Any],
    matrix: dict[str, Any],
    source_root: Path,
    *,
    require_hosted: bool,
    wheel_path: Path | None = None,
) -> list[str]:
    require(record.get("schemaVersion") == SCHEMA_VERSION, "schema version is unsupported")
    require(record.get("recordKind") == "amkernel-cross-os-process-matrix", "record kind is unsupported")
    require(isinstance(record.get("recordId"), str) and record["recordId"], "record id is missing")
    require(isinstance(record.get("createdAt"), str) and record["createdAt"].endswith("Z"), "creation time is missing")
    check_hosted_dispatch(record, require_hosted)
    check_sources(record, source_root)
    if wheel_path is not None:
        check_wheel_file(record, wheel_path)
    check_matrix_header(record, matrix)
    check_environment(record, matrix)
    cells = record.get("cells")
    require(isinstance(cells, list), "cells are missing")
    require(
        [cell.get("id") for cell in cells] == [row["id"] for row in matrix["rows"]],
        "cell order or membership does not match the frozen matrix",
    )
    problems: list[str] = []
    for cell, row in zip(cells, matrix["rows"]):
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
) -> dict[str, Any]:
    require(records, "no evidence records were supplied")
    expected_sources = source_hashes(source_root)
    environments: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    failures: list[str] = []
    for path, record in records:
        record_failures = validate_record(
            record, matrix, source_root, require_hosted=True, wheel_path=None
        )
        failures.extend(record_failures)
        environment = record["environment"]
        key = (environment["matrixPlatform"], environment["python"]["majorMinor"])
        require(key not in seen, f"duplicate evidence environment: {key}")
        seen.add(key)
        sources = record["sources"]
        for name in ("matrix", "harness", "lock"):
            require(
                sources[name]["sha256"] == expected_sources[name],
                f"{path.name}: {name} source differs from the combined checkout",
            )
        require(
            sources["contracts"] == expected_sources["contracts"],
            f"{path.name}: contract sources differ from the combined checkout",
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
    wheel_hashes = {environment["wheel"]["sha256"] for environment in environments}
    require(len(wheel_hashes) == 1, "evidence environments used different wheels")
    dispatch_shas = {record["dispatch"]["sha"] for _path, record in records}
    require(len(dispatch_shas) == 1, "evidence environments came from different commits")
    required = {
        (str(platform), str(version))
        for platform in matrix["platforms"]
        for version in matrix["pythonVersions"]
    }
    missing = sorted(required - seen)
    require(not missing, f"required environment coverage is missing: {missing}")
    require(not (seen - required), f"unexpected environments were supplied: {sorted(seen - required)}")
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
    index: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "indexKind": "amkernel-cross-os-process-matrix-index",
        "matrix": {
            "id": matrix["matrixId"],
            "sha256": expected_sources["matrix"],
            "platforms": matrix["platforms"],
            "pythonVersions": matrix["pythonVersions"],
            "rowIds": [row["id"] for row in matrix["rows"]],
            "unsupportedPlatforms": matrix["unsupportedPlatforms"],
        },
        "sources": {
            "harnessSha256": expected_sources["harness"],
            "contracts": expected_sources["contracts"],
            "lockSha256": expected_sources["lock"],
            "sourceRoot": "checkout",
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
            "The index covers only the frozen POSIX process matrix; Windows, Android, and iOS are not claimed.",
            "The index links retained per-environment evidence and does not replace independent lifecycle review.",
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate one hosted evidence record")
    validate.add_argument("--evidence", required=True)
    validate.add_argument("--matrix", required=True)
    validate.add_argument("--source-root", required=True)
    validate.add_argument("--wheel")
    validate.add_argument("--require-hosted", action="store_true")
    validate.add_argument("--summary")

    combined = subparsers.add_parser("combine", help="combine hosted records into one index")
    combined.add_argument("--evidence-dir", required=True)
    combined.add_argument("--matrix", required=True)
    combined.add_argument("--source-root", required=True)
    combined.add_argument("--output", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    matrix = load_matrix(Path(args.matrix))
    source_root = Path(args.source_root).resolve()
    if args.command == "validate":
        evidence_path = Path(args.evidence)
        record = json.loads(evidence_path.read_text(encoding="utf-8"))
        problems = validate_record(
            record,
            matrix,
            source_root,
            require_hosted=args.require_hosted,
            wheel_path=Path(args.wheel) if args.wheel else None,
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
            Path(args.summary).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0 if not problems else 1
    records = [
        (path, json.loads(path.read_text(encoding="utf-8")))
        for path in evidence_files(Path(args.evidence_dir))
    ]
    index = combine(records, matrix, source_root)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: index[key] for key in ("outcome", "totals", "review", "indexSha256")}, indent=2))
    return 0 if index["outcome"] == "observed" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except EvidenceError as error:
        print(f"evidence validation failed: {error}", file=sys.stderr)
        raise SystemExit(2)
