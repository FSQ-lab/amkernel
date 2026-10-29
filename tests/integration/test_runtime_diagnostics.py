from __future__ import annotations

from importlib import metadata
from pathlib import Path

import pytest

from amkernel.runtime import KernelRuntime

pytestmark = pytest.mark.anyio


def _write_metadata(root: Path, name: str, version: str | None) -> None:
    distribution = root / f"{name}.dist-info"
    distribution.mkdir()
    fields = ["Metadata-Version: 2.1", f"Name: {name}"]
    if version is not None:
        fields.append(f"Version: {version}")
    (distribution / "METADATA").write_text("\n".join(fields) + "\n")


async def test_requested_packages_preserve_order_and_closed_results(tmp_path: Path) -> None:
    exact_version = "x" * 1_024
    _write_metadata(tmp_path, "EmptyVersion", None)
    _write_metadata(tmp_path, "ControlVersion", "1\x00bad")
    _write_metadata(tmp_path, "ExactVersion", exact_version)
    _write_metadata(tmp_path, "OversizedVersion", "x" * 1_025)
    installed_version = metadata.version("amkernel")

    runtime = KernelRuntime(tmp_path)
    try:
        result = await runtime.execute(
            "import os, sys\nsys.path.insert(0, os.getcwd())\n42",
            packages=(
                "amkernel",
                "Definitely-Not-Installed-AMKernel",
                "EmptyVersion",
                "ControlVersion",
                "ExactVersion",
                "OversizedVersion",
            ),
        )
        assert result.status == "completed"
        assert result.result == 42
        assert result.runtime.implementation
        assert result.runtime.platform
        packages = result.runtime.packages
        assert [package.name for package in packages] == [
            "amkernel",
            "Definitely-Not-Installed-AMKernel",
            "EmptyVersion",
            "ControlVersion",
            "ExactVersion",
            "OversizedVersion",
        ]
        assert packages[0].version == installed_version
        assert packages[1].error == "not installed"
        assert packages[2].error == "invalid metadata"
        assert packages[3].error == "invalid metadata"
        assert packages[4].version == exact_version
        assert packages[5].error == "invalid metadata"
        assert all((package.version is None) != (package.error is None) for package in packages)

        unavailable = await runtime.execute(
            """
import importlib.metadata

def unavailable_distribution(name):
    raise RuntimeError("private metadata path must not be public")

importlib.metadata.distribution = unavailable_distribution
""",
            packages=("amkernel",),
        )
        assert unavailable.status == "completed"
        assert unavailable.runtime.packages[0].error == "metadata unavailable"

        empty = await runtime.execute("None")
        assert empty.status == "completed"
        assert empty.runtime.packages == ()
    finally:
        assert (await runtime.shutdown()).cleaned


async def test_package_diagnostics_survive_failed_cells(tmp_path: Path) -> None:
    runtime = KernelRuntime(tmp_path)
    try:
        result = await runtime.execute(
            'raise ValueError("cell failed")',
            packages=("amkernel", "Definitely-Not-Installed-AMKernel"),
        )
        assert result.status == "failed"
        assert result.error is not None
        assert [package.name for package in result.runtime.packages] == [
            "amkernel",
            "Definitely-Not-Installed-AMKernel",
        ]
        assert result.runtime.packages[0].version == metadata.version("amkernel")
        assert result.runtime.packages[1].error == "not installed"
    finally:
        assert (await runtime.shutdown()).cleaned


async def test_package_inspection_shares_deadline_and_retains_last_valid_diagnostics(
    tmp_path: Path,
) -> None:
    runtime = KernelRuntime(tmp_path)
    try:
        baseline = await runtime.execute("1", packages=("amkernel",))
        assert baseline.status == "completed"
        assert baseline.runtime.packages[0].version == metadata.version("amkernel")

        timed_out = await runtime.execute(
            """
import importlib.metadata
import time

def slow_distribution(name):
    time.sleep(10)

importlib.metadata.distribution = slow_distribution
""",
            timeout=0.1,
            packages=("amkernel",),
        )
        assert timed_out.status == "kernel_killed"
        assert timed_out.kernel_state == "dead"
        assert timed_out.runtime == baseline.runtime

        reset = await runtime.execute("2", reset=True)
        assert reset.status == "completed"
        assert reset.result == 2
        assert reset.kernel_state == "alive"
        assert reset.runtime.packages == ()
        assert reset.runtime.executable == baseline.runtime.executable
        assert reset.runtime.python_version == baseline.runtime.python_version
    finally:
        assert (await runtime.shutdown()).cleaned
