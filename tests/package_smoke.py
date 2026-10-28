"""Install the built wheel into a clean environment and run its real entry point."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from amkernel import __version__


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
    """Build-independent smoke check for the wheel already in dist/."""
    root = Path(__file__).resolve().parents[1]
    wheels = sorted((root / "dist").glob("amkernel-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"expected exactly one AMKernel wheel, found {len(wheels)}")

    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv is required for the package smoke test")

    with tempfile.TemporaryDirectory(prefix="amkernel-smoke-") as temporary_directory:
        environment = Path(temporary_directory)
        run([uv, "venv", str(environment), "--python", sys.executable], cwd=root)

        scripts = environment / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        entry_point = scripts / ("amkernel.exe" if os.name == "nt" else "amkernel")

        run([uv, "pip", "install", "--python", str(python), str(wheels[0])], cwd=root)
        completed = run([str(entry_point), "--version"], cwd=root, capture_output=True)

    expected = f"amkernel {__version__}"
    if completed.stdout.strip() != expected or completed.stderr:
        raise RuntimeError(
            f"unexpected installed entry-point result: stdout={completed.stdout!r}, "
            f"stderr={completed.stderr!r}"
        )

    print(expected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
