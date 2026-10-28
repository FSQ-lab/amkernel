"""Package and console-entry behavior."""

import shutil
import subprocess
import sys
from importlib.metadata import version

import amkernel


def test_package_version_matches_distribution_metadata() -> None:
    assert amkernel.__version__ == version("amkernel")


def test_module_version_entry_point() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "amkernel", "--version"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout.strip() == f"amkernel {amkernel.__version__}"
    assert completed.stderr == ""


def test_console_script_version_entry_point() -> None:
    executable = shutil.which("amkernel")
    assert executable is not None

    completed = subprocess.run(
        [executable, "--version"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout.strip() == f"amkernel {amkernel.__version__}"
    assert completed.stderr == ""
