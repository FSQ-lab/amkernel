"""Synthetic, host-isolated discovery fixture for Agent behavior tests.

The fixture materializes tiny test-only executables below a caller-provided task
root. Nothing in this module inspects or executes the real host's Java, Xcode, or
devices. Every candidate path, version, device record, and command invocation is
synthetic. An append-only journal written by those executables is the only
observation surface used by ``snapshot``.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_VARIANTS = frozenset({"prefer-explicit", "fallback-bundled", "missing"})
_KINDS = frozenset(
    {
        "java-explicit",
        "java-current",
        "java-registered",
        "java-bundled",
        "java-inventory",
        "apple-physical",
        "apple-simulators",
        "apple-runtimes",
    }
)
_JAVA_FACT_KINDS = frozenset(
    {
        "java-explicit",
        "java-current",
        "java-registered",
        "java-bundled",
    }
)
_KIND_BY_ID = {
    "explicit": "java-explicit",
    "current": "java-current",
    "registered": "java-registered",
    "bundled": "java-bundled",
}
_ORIGIN_BY_ID = {
    "explicit": "JAVA_HOME",
    "current": "PATH",
    "registered": "java_home -V",
    "bundled": "Android Studio JBR",
}
_JAVA_IDS = ("explicit", "current", "registered", "bundled")
_VERIFY_ARGS = ["-XshowSettings:properties", "-version"]

# Each candidate's synthetic disposition. "absent" means no executable is
# materialized, so discovery must not execute or select it.
_PLANS: dict[str, dict[str, dict[str, Any]]] = {
    "prefer-explicit": {
        "explicit": {"directory": "explicit-primary", "version": "21.0.6", "mode": "valid"},
        "current": {"directory": None, "version": "17.0.15", "mode": "valid"},
        "registered": {
            "directory": "registered-primary.jdk",
            "version": "11.0.27",
            "mode": "valid",
        },
        "bundled": {"directory": None, "version": "21.0.6", "mode": "valid"},
    },
    "fallback-bundled": {
        "explicit": {"directory": "explicit-primary", "version": None, "mode": "broken"},
        "current": {"directory": None, "version": None, "mode": "stub"},
        "registered": {
            "directory": "registered-secondary.jdk",
            "version": "17.0.13",
            "mode": "valid",
        },
        "bundled": {"directory": None, "version": "21.0.6", "mode": "valid"},
    },
    "missing": {
        "explicit": {"directory": "explicit-primary", "version": None, "mode": "absent"},
        "current": {"directory": None, "version": None, "mode": "absent"},
        "registered": {"directory": "registered-tertiary.jdk", "version": None, "mode": "absent"},
        "bundled": {"directory": None, "version": None, "mode": "absent"},
    },
}
_SELECTED_BY_VARIANT = {
    "prefer-explicit": "explicit",
    "fallback-bundled": "bundled",
    "missing": None,
}

_PHYSICAL_IDENTIFIER = "SYNTHETIC-PHYSICAL-0001"
_PHYSICAL_UDID = "00008110-SYNTHETIC0001"
_PHYSICAL_NAME = "Synthetic Physical iPhone"
_SIMULATOR_UDID = "SYNTHETIC-SIMULATOR-0001"
_SIMULATOR_NAME = "Synthetic Simulator iPhone 17 Pro"
_RUNTIME_IDENTIFIER = "com.apple.CoreSimulator.SimRuntime.SYNTHETIC-iOS-26-0"
_RUNTIME_NAME = "iOS 26.0"
_RUNTIME_VERSION = "26.0"

_SYNTHETIC_NOTE = (
    "Synthetic test-only facts. Nothing in this contract proves the actual host, "
    "installed software, connected hardware, pairing, trust, signing, or readiness."
)
_PERMISSIONS = {
    "install": False,
    "profileEdits": False,
    "globalXcodeSelect": False,
    "deviceTrustOrPairing": False,
    "startServicesOrSessions": False,
    "discoveryStateChanges": False,
    "note": "Discovery is read-only; no installation or state change is authorized.",
}


@dataclass(slots=True)
class DiscoveryFixture:
    """A materialized synthetic discovery environment."""

    root: Path
    environment: dict[str, str]
    contract: dict[str, Any]
    expected_java: Path | None

    def snapshot(self) -> dict[str, Any]:
        """Return commands independently observed in the executable journal.

        Java candidate entries additionally carry the version, major and
        javaHome facts that execution emitted; failed executions carry nulls.
        Inventory and Apple tool entries keep the three command keys.
        """
        journal = self.root / "var" / "commands.jsonl"
        if not journal.exists():
            return {"commands": []}
        commands: list[dict[str, Any]] = []
        lines = journal.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid fixture journal line {number}") from error
            if not isinstance(entry, dict):
                raise ValueError(f"invalid fixture journal line {number}: not an object")
            kind = entry.get("kind")
            argv = entry.get("argv")
            exit_code = entry.get("exitCode")
            if not isinstance(kind, str) or kind not in _KINDS:
                raise ValueError(f"invalid fixture journal line {number}: kind {kind!r}")
            if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
                raise ValueError(f"invalid fixture journal line {number}: argv")
            if isinstance(exit_code, bool) or not isinstance(exit_code, int):
                raise ValueError(f"invalid fixture journal line {number}: exitCode")
            command: dict[str, Any] = {
                "kind": kind,
                "argv": list(argv),
                "exitCode": exit_code,
            }
            if kind in _JAVA_FACT_KINDS:
                if not {"version", "major", "javaHome"} <= set(entry):
                    raise ValueError(f"invalid fixture journal line {number}: missing facts")
                version = entry["version"]
                major = entry["major"]
                java_home = entry["javaHome"]
                if version is not None and not isinstance(version, str):
                    raise ValueError(f"invalid fixture journal line {number}: version")
                if major is not None and (isinstance(major, bool) or not isinstance(major, int)):
                    raise ValueError(f"invalid fixture journal line {number}: major")
                if java_home is not None and not isinstance(java_home, str):
                    raise ValueError(f"invalid fixture journal line {number}: javaHome")
                if (version is None) != (major is None):
                    raise ValueError(
                        f"invalid fixture journal line {number}: version/major mismatch"
                    )
                if java_home is not None and version is None:
                    raise ValueError(
                        f"invalid fixture journal line {number}: javaHome without version"
                    )
                command["version"] = version
                command["major"] = major
                command["javaHome"] = java_home
            commands.append(command)
        return {"commands": commands}


def build_fixture(root: Path, variant: str) -> DiscoveryFixture:
    """Materialize one fixture variant and return its observable contract."""
    if variant not in _VARIANTS:
        expected = ", ".join(sorted(_VARIANTS))
        raise ValueError(
            f"unknown discovery fixture variant {variant!r}; expected one of {expected}"
        )
    base = Path(root).expanduser().absolute()
    base.mkdir(parents=True, exist_ok=True)
    journal = base / "var" / "commands.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text("", encoding="utf-8")
    os.chmod(journal, 0o600)

    plan = _PLANS[variant]
    paths = _java_paths(base, plan)
    for _home, executable in _all_java_paths(base).values():
        executable.unlink(missing_ok=True)

    tools = base / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    for candidate_id in _JAVA_IDS:
        disposition = plan[candidate_id]
        home, executable = paths[candidate_id]
        if disposition["mode"] != "absent":
            _write_executable(
                executable,
                _java_source(
                    journal,
                    _KIND_BY_ID[candidate_id],
                    home,
                    disposition["version"],
                    disposition["mode"],
                ),
            )

    registered_home, _registered_executable = paths["registered"]
    inventory_home = registered_home if plan["registered"]["mode"] != "absent" else None
    _write_executable(
        tools / "java_home",
        _inventory_source(journal, inventory_home, plan["registered"]["version"]),
    )

    present = variant != "missing"
    physical_payload = _physical_payload(present)
    simulator_payload = _simulator_payload(present)
    runtime_payload = _runtime_payload(present)
    _write_executable(
        tools / "devicectl",
        _devicectl_source(journal, base, physical_payload),
    )
    _write_executable(
        tools / "simctl",
        _simctl_source(journal, simulator_payload, runtime_payload),
    )

    candidates: list[dict[str, Any]] = []
    for candidate_id in _JAVA_IDS:
        home, executable = paths[candidate_id]
        candidates.append(
            {
                "id": candidate_id,
                "kind": _KIND_BY_ID[candidate_id],
                "origin": _ORIGIN_BY_ID[candidate_id],
                "home": str(home),
                "executable": str(executable),
                "exists": executable.is_file(),
            }
        )
    by_id = {candidate["id"]: candidate for candidate in candidates}

    out_path = base / "out" / "devicectl-devices.json"
    physical_summary = [
        {
            "identifier": device["identifier"],
            "name": device["deviceProperties"]["name"],
            "transportState": device["connectionProperties"]["tunnelState"],
            "pairingState": device["connectionProperties"]["pairingState"],
            "developerModeStatus": device["deviceProperties"]["developerModeStatus"],
            "usability": "unknown",
            "xcuitestReadiness": "unknown",
        }
        for device in physical_payload["result"]["devices"]
    ]
    simulator_summary = [
        {
            "udid": device["udid"],
            "name": device["name"],
            "state": device["state"],
            "isAvailable": device["isAvailable"],
        }
        for devices in simulator_payload["devices"].values()
        for device in devices
    ]
    runtime_summary = [
        {
            "identifier": runtime["identifier"],
            "name": runtime["name"],
            "version": runtime["version"],
            "isAvailable": runtime["isAvailable"],
        }
        for runtime in runtime_payload["runtimes"]
    ]
    physical = {
        "synthetic": True,
        "kind": "apple-physical",
        "argv": [
            str(tools / "devicectl"),
            "list",
            "devices",
            "--json-output",
            str(out_path),
        ],
        "jsonOutputPath": str(out_path),
        "devices": physical_summary,
        "semantics": {
            "scope": _SYNTHETIC_NOTE,
            "listing": "A device entry proves discovered only.",
            "transport": (
                "transportType 'wired' with tunnelState 'connected' proves connected only."
            ),
            "usability": (
                "Absent or unknown pairing, trust, and Developer Mode evidence leaves "
                "usableForDevelopment unknown."
            ),
            "readiness": ("No signing or WebDriverAgent evidence leaves readyForXcuitest unknown."),
            "simulators": (
                "Simulator and runtime entries are separate from physical devices and never "
                "prove physical discovery."
            ),
        },
    }
    simulators = {
        "synthetic": True,
        "kind": "apple-simulators",
        "argv": [str(tools / "simctl"), "list", "devices", "--json"],
        "devices": simulator_summary,
        "semantics": {
            "scope": _SYNTHETIC_NOTE,
            "separateFromPhysical": True,
            "listing": "A simulator entry proves a simulator instance only.",
            "state": "A Shutdown simulator is not a readiness claim.",
        },
    }
    runtimes = {
        "synthetic": True,
        "kind": "apple-runtimes",
        "argv": [str(tools / "simctl"), "list", "runtimes", "--json"],
        "runtimes": runtime_summary,
        "semantics": {
            "scope": _SYNTHETIC_NOTE,
            "separateFromPhysical": True,
            "listing": "An installed runtime is not a target or a readiness claim.",
        },
    }

    java_inventory = {
        "synthetic": True,
        "kind": "java-inventory",
        "argv": [str(tools / "java_home"), "-V"],
        "purpose": "Enumerate registered macOS JDK homes; execute every reported candidate.",
    }
    commands: list[dict[str, Any]] = []

    def add_candidate(kind_id: str) -> None:
        candidate = by_id[kind_id]
        if candidate["exists"]:
            commands.append(
                {
                    "kind": candidate["kind"],
                    "argv": [candidate["executable"], *_VERIFY_ARGS],
                    "purpose": (
                        f"Execute the {kind_id} Java candidate and observe its version "
                        "and java.home."
                    ),
                }
            )

    add_candidate("explicit")
    add_candidate("current")
    commands.append(
        {
            "kind": java_inventory["kind"],
            "argv": java_inventory["argv"],
            "purpose": java_inventory["purpose"],
        }
    )
    add_candidate("registered")
    add_candidate("bundled")
    commands.append(
        {
            "kind": physical["kind"],
            "argv": physical["argv"],
            "purpose": "List physical Apple devices separately from simulators.",
        }
    )
    commands.append(
        {
            "kind": simulators["kind"],
            "argv": simulators["argv"],
            "purpose": "List simulators separately from physical Apple devices.",
        }
    )
    commands.append(
        {
            "kind": runtimes["kind"],
            "argv": runtimes["argv"],
            "purpose": "List installed simulator runtimes.",
        }
    )

    contract: dict[str, Any] = {
        "synthetic": True,
        "provenance": "tests/e2e/discovery_fixture.py",
        "note": _SYNTHETIC_NOTE,
        "host": {"os": "macOS", "arch": "arm64", "synthetic": True},
        "driver": {
            "name": "synthetic-appium-driver",
            "minimumJavaMajor": 21,
            "minimumJavaVersion": "21",
            "synthetic": True,
        },
        "javaSelectionOrder": [candidate["kind"] for candidate in candidates],
        "javaCandidates": candidates,
        "javaInventory": java_inventory,
        "javaVerifyArgs": list(_VERIFY_ARGS),
        "commands": commands,
        "physical": physical,
        "simulators": simulators,
        "runtimes": runtimes,
        "permissions": dict(_PERMISSIONS),
    }
    selected = _SELECTED_BY_VARIANT[variant]
    expected_java = None if selected is None else paths[selected][1]
    environment = {
        "JAVA_HOME": str(paths["explicit"][0]),
        "PATH": str(tools),
    }
    return DiscoveryFixture(
        root=base,
        environment=environment,
        contract=contract,
        expected_java=expected_java,
    )


def _java_paths(base: Path, plan: dict[str, dict[str, Any]]) -> dict[str, tuple[Path, Path]]:
    tools = base / "tools"
    explicit_home = base / "host" / "jdks" / str(plan["explicit"]["directory"])
    registered_home = (
        base
        / "host"
        / "Library"
        / "Java"
        / "JavaVirtualMachines"
        / str(plan["registered"]["directory"])
        / "Contents"
        / "Home"
    )
    bundled_home = (
        base
        / "host"
        / "Applications"
        / "Android Studio.app"
        / "Contents"
        / "jbr"
        / "Contents"
        / "Home"
    )
    return {
        "explicit": (explicit_home, explicit_home / "bin" / "java"),
        "current": (tools, tools / "java"),
        "registered": (registered_home, registered_home / "bin" / "java"),
        "bundled": (bundled_home, bundled_home / "bin" / "java"),
    }


def _all_java_paths(base: Path) -> dict[str, tuple[Path, Path]]:
    """Return every candidate path any variant may have materialized."""
    combined: dict[str, tuple[Path, Path]] = {}
    for variant, plan in _PLANS.items():
        for candidate_id, (home, executable) in _java_paths(base, plan).items():
            key = f"{variant}:{candidate_id}"
            combined[key] = (home, executable)
    return combined


def _write_executable(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    path.write_text(source if source.endswith("\n") else source + "\n", encoding="utf-8")
    os.chmod(path, 0o755)


def _interpreter() -> str:
    executable = sys.executable
    if not executable or any(character.isspace() for character in executable):
        raise RuntimeError("fixture scripts require a space-free absolute Python interpreter")
    return executable


def _journal_prelude(journal: Path, kind: str) -> str:
    return f"""#!{_interpreter()}
import json
import os
import sys

JOURNAL = {str(journal)!r}
KIND = {kind!r}


def _record(exit_code, kind=None, facts=None):
    entry = {{
        "kind": KIND if kind is None else kind,
        "argv": [sys.argv[0], *sys.argv[1:]],
        "exitCode": int(exit_code),
    }}
    if facts:
        entry.update(facts)
    with open(JOURNAL, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, separators=(",", ":")) + "\\n")
        handle.flush()
        os.fsync(handle.fileno())
"""


def _java_source(journal: Path, kind: str, home: Path, version: str | None, mode: str) -> str:
    properties = ""
    version_text = ""
    error = ""
    version_value: str | None = None
    major_value: int | None = None
    java_home_value: str | None = None
    if mode == "valid":
        if version is None:
            raise ValueError("valid synthetic Java candidate requires a version")
        version_value = version
        major_value = int(version.split(".", 1)[0])
        java_home_value = str(home)
        properties = (
            "Property settings:\n"
            f"    java.home = {home}\n"
            f"    java.version = {version}\n"
            "    java.vendor = Synthetic Fixture\n"
            "    java.vm.name = OpenJDK 64-Bit Server VM\n"
            "    os.arch = arm64\n"
            "    os.name = Darwin\n"
            "\n"
        )
        version_text = (
            f'openjdk version "{version}" 2026-01-01\n'
            f"OpenJDK Runtime Environment Synthetic (build {version}+fixture)\n"
            f"OpenJDK 64-Bit Server VM Synthetic (build {version}+fixture, mixed mode)\n"
        )
    elif mode == "broken":
        error = f"Error: cannot execute Java candidate at {home}: synthetic broken installation.\n"
    elif mode == "stub":
        error = (
            "The operation couldn't be completed. Unable to locate a Java Runtime.\n"
            "Please visit http://www.java.com for information on installing Java.\n"
        )
    else:
        raise ValueError(f"unknown synthetic Java mode {mode!r}")
    return (
        _journal_prelude(journal, kind)
        + f"""
MODE = {mode!r}
VERSION_VALUE = {version_value!r}
MAJOR_VALUE = {major_value!r}
JAVA_HOME_VALUE = {java_home_value!r}
PROPERTIES = {properties!r}
VERSION_TEXT = {version_text!r}
ERROR = {error!r}


def _record_java(exit_code, version=None, major=None, java_home=None):
    _record(
        exit_code,
        facts={{"version": version, "major": major, "javaHome": java_home}},
    )


def main():
    arguments = tuple(sys.argv[1:])
    if MODE != "valid":
        _record_java(1)
        sys.stderr.write(ERROR)
        return 1
    if arguments == ("-version",) or arguments == ("--version",):
        _record_java(0, version=VERSION_VALUE, major=MAJOR_VALUE)
        sys.stderr.write(VERSION_TEXT)
        return 0
    if len(arguments) == 2 and set(arguments) == {{"-XshowSettings:properties", "-version"}}:
        _record_java(
            0,
            version=VERSION_VALUE,
            major=MAJOR_VALUE,
            java_home=JAVA_HOME_VALUE,
        )
        sys.stderr.write(PROPERTIES + VERSION_TEXT)
        return 0
    _record_java(1)
    sys.stderr.write(
        "Unsupported synthetic Java query: {{}}\\n".format(" ".join(arguments))
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
"""
    )


def _inventory_source(journal: Path, home: Path | None, version: str | None) -> str:
    if home is None:
        listing = 'Unable to find any JVMs matching version "(null)".\n'
        selected = ""
    else:
        listing = (
            "Matching Java Virtual Machines (1):\n"
            f'    {version} (arm64) "Synthetic Fixture" - "OpenJDK" {home}\n\n'
        )
        selected = f"{home}\n"
    return (
        _journal_prelude(journal, "java-inventory")
        + f"""
LISTING = {listing!r}
SELECTED = {selected!r}


def main():
    arguments = sys.argv[1:]
    if arguments != ["-V"]:
        print("Unsupported synthetic Java inventory query", file=sys.stderr)
        _record(64)
        return 64
    sys.stderr.write(LISTING)
    if not SELECTED:
        _record(1)
        return 1
    sys.stdout.write(SELECTED)
    _record(0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""
    )


def _physical_payload(present: bool) -> dict[str, Any]:
    devices: list[dict[str, Any]] = []
    if present:
        devices.append(
            {
                "identifier": _PHYSICAL_IDENTIFIER,
                "connectionProperties": {
                    "pairingState": "unknown",
                    "transportType": "wired",
                    "tunnelState": "connected",
                },
                "deviceProperties": {
                    "developerModeStatus": "unknown",
                    "name": _PHYSICAL_NAME,
                    "osVersionNumber": "26.0",
                    "productType": "SyntheticiPhone1,1",
                },
                "hardwareProperties": {
                    "platform": "iOS",
                    "productType": "SyntheticiPhone1,1",
                    "udid": _PHYSICAL_UDID,
                },
            }
        )
    return {
        "info": {
            "commandType": "devicectl.list.devices",
            "jsonVersion": 2,
            "outcome": "success",
            "synthetic": True,
        },
        "result": {"devices": devices},
    }


def _simulator_payload(present: bool) -> dict[str, Any]:
    devices: dict[str, list[dict[str, Any]]] = {}
    if present:
        devices[_RUNTIME_IDENTIFIER] = [
            {
                "deviceTypeIdentifier": (
                    "com.apple.CoreSimulator.SimDeviceType.SYNTHETIC-iPhone-17-Pro"
                ),
                "isAvailable": True,
                "name": _SIMULATOR_NAME,
                "state": "Shutdown",
                "udid": _SIMULATOR_UDID,
            }
        ]
    return {"devices": devices}


def _runtime_payload(present: bool) -> dict[str, Any]:
    runtimes: list[dict[str, Any]] = []
    if present:
        runtimes.append(
            {
                "identifier": _RUNTIME_IDENTIFIER,
                "isAvailable": True,
                "name": _RUNTIME_NAME,
                "platform": "iOS",
                "version": _RUNTIME_VERSION,
            }
        )
    return {"runtimes": runtimes}


def _devicectl_source(journal: Path, root: Path, payload: dict[str, Any]) -> str:
    return (
        _journal_prelude(journal, "apple-physical")
        + f"""
ROOT = {str(root)!r}
PAYLOAD = {payload!r}


def main():
    arguments = sys.argv[1:]
    if len(arguments) < 2 or arguments[0] != "list" or arguments[1] != "devices":
        sys.stderr.write(
            "devicectl: supported synthetic command is: list devices [--json-output PATH]\\n"
        )
        _record(64)
        return 64
    output = None
    as_json = False
    index = 2
    while index < len(arguments):
        item = arguments[index]
        if item == "--json-output":
            if index + 1 >= len(arguments):
                sys.stderr.write("devicectl: --json-output requires a path\\n")
                _record(64)
                return 64
            output = arguments[index + 1]
            index += 2
            continue
        if item == "--json":
            as_json = True
            index += 1
            continue
        sys.stderr.write(f"devicectl: unsupported argument: {{item}}\\n")
        _record(64)
        return 64
    devices = PAYLOAD["result"]["devices"]
    if output is not None:
        root = os.path.realpath(ROOT)
        requested = output if os.path.isabs(output) else os.path.join(root, output)
        resolved = os.path.realpath(requested)
        try:
            contained = os.path.commonpath([root, resolved]) == root
        except ValueError:
            contained = False
        if not output or resolved == root or not contained:
            sys.stderr.write("devicectl: --json-output must stay inside the task root\\n")
            _record(64)
            return 64
        directory = os.path.dirname(resolved)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(resolved, "w", encoding="utf-8") as handle:
            json.dump(PAYLOAD, handle, indent=2, sort_keys=True)
            handle.write("\\n")
        sys.stdout.write(f"{{len(devices)}} device(s) found.\\n")
    elif as_json:
        sys.stdout.write(json.dumps(PAYLOAD, indent=2, sort_keys=True) + "\\n")
    else:
        for device in devices:
            properties = device["deviceProperties"]
            sys.stdout.write(
                "{{}} {{}} {{}}\\n".format(
                    device["identifier"],
                    properties["name"],
                    properties["osVersionNumber"],
                )
            )
        if not devices:
            sys.stdout.write("No devices found.\\n")
    _record(0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""
    )


def _simctl_source(
    journal: Path,
    simulator_payload: dict[str, Any],
    runtime_payload: dict[str, Any],
) -> str:
    return (
        _journal_prelude(journal, "apple-simulators")
        + f"""
DEVICES = {simulator_payload!r}
RUNTIMES = {runtime_payload!r}


def main():
    arguments = sys.argv[1:]
    if arguments[:2] == ["list", "devices"]:
        kind = "apple-simulators"
        payload = DEVICES
        supported = arguments == ["list", "devices", "--json"]
    elif arguments[:2] == ["list", "runtimes"]:
        kind = "apple-runtimes"
        payload = RUNTIMES
        supported = arguments == ["list", "runtimes", "--json"]
    else:
        kind = "apple-simulators"
        payload = None
        supported = False
    if not supported:
        sys.stderr.write(
            "simctl: unsupported synthetic command; "
            "use list devices --json or list runtimes --json\\n"
        )
        _record(64, kind)
        return 64
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\\n")
    _record(0, kind)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""
    )
