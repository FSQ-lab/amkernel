"""Install the built wheel into a clean environment and run its real entry point."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path


def run(
    command: list[str], *, cwd: Path, capture_output: bool = False
) -> subprocess.CompletedProcess[str]:
    """Run one required smoke-test command."""
    return subprocess.run(
        command,
        check=True,
        cwd=cwd,
        capture_output=capture_output,
        text=True,
    )


def main() -> int:
    """Install one wheel and prove its public entry point through a real client."""
    root = Path(__file__).resolve().parents[1]
    wheels = sorted((root / "dist").glob("amkernel-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"expected exactly one AMKernel wheel, found {len(wheels)}")

    wheel = wheels[0]
    wheel_sha256 = hashlib.sha256(wheel.read_bytes()).hexdigest()
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv is required for the package smoke test")

    expected_version = f"amkernel {version('amkernel')}"
    with tempfile.TemporaryDirectory(prefix="amkernel-smoke-") as temporary_directory:
        workspace = Path(temporary_directory) / "workspace"
        workspace.mkdir()
        environment = workspace / ".venv"
        run([uv, "venv", str(environment), "--python", sys.executable], cwd=root)

        scripts = environment / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        entry_point = scripts / ("amkernel.exe" if os.name == "nt" else "amkernel")

        run([uv, "pip", "install", "--python", str(python), str(wheel)], cwd=root)
        version_result = run([str(entry_point), "--version"], cwd=workspace, capture_output=True)
        if version_result.stdout.strip() != expected_version or version_result.stderr:
            raise RuntimeError(
                "unexpected installed entry-point result: "
                f"stdout={version_result.stdout!r}, stderr={version_result.stderr!r}"
            )

        scenario_command = [
            str(python),
            str(root / "tests" / "e2e" / "installed_stdio.py"),
            "--entry-point",
            str(entry_point),
            "--python",
            str(python),
            "--workspace",
            str(workspace),
        ]
        try:
            scenario_result = run(scenario_command, cwd=workspace, capture_output=True)
        except subprocess.CalledProcessError as error:
            raise RuntimeError(
                f"installed scenario failed: stdout={error.stdout!r}, stderr={error.stderr!r}"
            ) from error
        host_diagnostics = scenario_result.stderr.strip().splitlines()
        expected_diagnostics = [
            "KernelExited: response channel failed: Runner response channel closed"
        ]
        if host_diagnostics != expected_diagnostics:
            raise RuntimeError(
                f"unexpected installed scenario diagnostics: {scenario_result.stderr!r}"
            )
        scenario_evidence = json.loads(scenario_result.stdout)

    evidence = {
        "artifact": str(wheel.relative_to(root)),
        "artifactSha256": wheel_sha256,
        "buildPython": sys.version,
        "host": platform.platform(),
        "installedVersion": expected_version,
        "scenarioCommand": scenario_command,
        "scenario": scenario_evidence,
        "hostDiagnostics": host_diagnostics,
    }
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
