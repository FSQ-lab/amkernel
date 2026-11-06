from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ProfileName = Literal[
    "ready",
    "missing-driver",
    "driver-mismatch",
    "node-mismatch",
    "npm-mismatch",
    "appium-mismatch",
    "runtime-mismatch",
    "xcode-missing",
    "privacy-pending",
]

_DRIVER_VERSION = "4.5.1"
_APPIUM_VERSION = "3.1.1"
_NODE_VERSION = "22.12.0"
_NPM_VERSION = "10.9.0"
_CLIENT_VERSION = "5.2.5"
_SELENIUM_VERSION = "4.52.0"
_PYTHON_VERSION = "3.13.9"
_XCODE_VERSION = "16.4"
_APPIUM_HOME = "/Users/test/.appium"
_XCODE_PATH = "/Applications/Xcode.app/Contents/Developer"


def _version_tuple(version: str | None) -> tuple[int, int, int] | None:
    if version is None:
        return None
    parts = version.removeprefix("v").split(".")
    if not 1 <= len(parts) <= 3 or any(not part.isdigit() for part in parts):
        return None
    numbers = [int(part) for part in parts]
    numbers.extend([0] * (3 - len(numbers)))
    return numbers[0], numbers[1], numbers[2]


def _node_compatible(version: str | None) -> bool:
    parsed = _version_tuple(version)
    if parsed is None:
        return False
    return (
        (20, 19, 0) <= parsed < (21, 0, 0)
        or (22, 12, 0) <= parsed < (23, 0, 0)
        or parsed >= (24, 0, 0)
    )


def _npm_compatible(version: str | None) -> bool:
    parsed = _version_tuple(version)
    return parsed is not None and parsed >= (10, 0, 0)


def _appium_compatible(version: str | None) -> bool:
    if version is None:
        return False
    release, separator, prerelease = version.removeprefix("v").partition("-")
    parsed = _version_tuple(release)
    if parsed is None or not (3, 0, 0) <= parsed < (4, 0, 0):
        return False
    if not separator:
        return True
    parts = prerelease.split(".")
    return (
        parsed == (3, 0, 0)
        and len(parts) == 2
        and parts[0] == "rc"
        and parts[1].isdigit()
        and int(parts[1]) >= 2
    )


def _driver_compatible(version: str | None) -> bool:
    return _version_tuple(version) == _version_tuple(_DRIVER_VERSION)


def _runtime_compatible(python: str | None, client: str | None, selenium: str | None) -> bool:
    python_version = _version_tuple(python)
    client_version = _version_tuple(client)
    selenium_version = _version_tuple(selenium)
    return (
        python_version is not None
        and python_version >= (3, 9, 0)
        and client_version == _version_tuple(_CLIENT_VERSION)
        and selenium_version is not None
        and (4, 26, 0) <= selenium_version < (5, 0, 0)
    )


@dataclass(frozen=True)
class Change:
    component: str
    version: str
    source: str
    location: str
    effect: str
    rollback: str
    requires_user_action: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "version": self.version,
            "source": self.source,
            "location": self.location,
            "effect": self.effect,
            "rollback": self.rollback,
            "requiresUserAction": self.requires_user_action,
        }


@dataclass
class Grant:
    identifier: str
    changes: tuple[Change, ...]
    consumed: bool = False


class SyntheticMacSetupHost:
    """Deterministic host model; it executes no real installer, TCC command, app, or session."""

    def __init__(self, profile: ProfileName) -> None:
        self.profile = profile
        self.python = "3.14.0" if profile == "runtime-mismatch" else _PYTHON_VERSION
        self.runtime_client = _CLIENT_VERSION
        self.selenium = "5.0.0" if profile == "runtime-mismatch" else _SELENIUM_VERSION
        self.node = "20.18.9" if profile == "node-mismatch" else _NODE_VERSION
        self.npm = "9.9.4" if profile == "npm-mismatch" else _NPM_VERSION
        self.appium = "2.19.0" if profile == "appium-mismatch" else _APPIUM_VERSION
        if profile == "missing-driver":
            self.driver = None
        elif profile == "driver-mismatch":
            self.driver = "3.1.0"
        else:
            self.driver = _DRIVER_VERSION
        self.xcode = None if profile == "xcode-missing" else _XCODE_VERSION
        self.xcode_path = None if profile == "xcode-missing" else _XCODE_PATH
        self.xcode_tools_ready = profile != "xcode-missing"
        self.accessibility: bool | None = False if profile == "privacy-pending" else None
        self.automation: bool | None = None
        self.screen_recording: bool | None = None
        self.target = {
            "path": "/Applications/TextEdit.app",
            "bundleId": "com.apple.TextEdit",
            "launched": False,
        }
        self.server_started = False
        self.sessions_created = 0
        self._grant_sequence = 0
        self._grants: dict[str, Grant] = {}
        self.journal: list[dict[str, Any]] = []

    def _record(self, action: str, **detail: Any) -> None:
        self.journal.append({"sequence": len(self.journal) + 1, "action": action, **detail})

    def _prerequisites_ready(self) -> bool:
        return (
            _runtime_compatible(self.python, self.runtime_client, self.selenium)
            and _node_compatible(self.node)
            and _npm_compatible(self.npm)
            and _appium_compatible(self.appium)
            and _driver_compatible(self.driver)
            and self.xcode is not None
            and self.xcode_tools_ready
        )

    def inspect(self) -> dict[str, Any]:
        result = self.snapshot()
        self._record("inspect", profile=self.profile)
        return result

    def proposed_changes(self) -> tuple[Change, ...]:
        changes: list[Change] = []
        if not _runtime_compatible(self.python, self.runtime_client, self.selenium):
            changes.append(
                Change(
                    component="runtime-client",
                    version=(
                        f"CPython {_PYTHON_VERSION} / Appium-Python-Client {_CLIENT_VERSION} / "
                        f"Selenium {_SELENIUM_VERSION}"
                    ),
                    source="existing uv-managed AMKernel tool specification and indexes",
                    location="/Users/test/.local/share/uv/tools/amkernel",
                    effect="recreates the shared Runtime while preserving AMKernel and all extras",
                    rollback="restore the recorded Runtime Python and dependency specifications",
                )
            )
        if not _node_compatible(self.node) or not _npm_compatible(self.npm):
            changes.append(
                Change(
                    component="node-npm",
                    version=f"Node {_NODE_VERSION} / npm {_NPM_VERSION}",
                    source="existing nvm backend",
                    location="/Users/test/.nvm/versions/node/v22.12.0",
                    effect="changes Node/npm for the approved Appium command only",
                    rollback=f"restore task selection to Node {self.node} / npm {self.npm}",
                )
            )
        if not _appium_compatible(self.appium):
            changes.append(
                Change(
                    component="appium",
                    version=_APPIUM_VERSION,
                    source="npm registry through existing user npm prefix",
                    location="/Users/test/.nvm/versions/node/v22.12.0/lib/node_modules/appium",
                    effect="changes the shared global Appium used by the selected backend",
                    rollback=f"reinstall Appium {self.appium}",
                )
            )
        if not _driver_compatible(self.driver):
            changes.append(
                Change(
                    component="mac2-driver",
                    version=_DRIVER_VERSION,
                    source="npm registry through Appium extension CLI",
                    location=f"{_APPIUM_HOME}/node_modules/appium-mac2-driver",
                    effect="installs Mac2 only in the selected shared Appium home",
                    rollback=f"APPIUM_HOME={_APPIUM_HOME} appium driver uninstall mac2",
                )
            )
        if self.xcode is None:
            changes.append(
                Change(
                    component="xcode",
                    version=_XCODE_VERSION,
                    source="Apple App Store or Apple Developer downloads",
                    location="/Applications/Xcode.app",
                    effect=(
                        "downloads Xcode; acceptance, first launch and authentication are native"
                    ),
                    rollback="remove only the newly installed Xcode after preserving user projects",
                    requires_user_action=True,
                )
            )
        if self.accessibility is False:
            changes.append(
                Change(
                    component="accessibility",
                    version="observed Xcode Helper identity",
                    source="macOS System Settings",
                    location="Privacy & Security > Accessibility",
                    effect="allows the observed helper identity to control this Mac",
                    rollback="the user can disable the same observed helper entry",
                    requires_user_action=True,
                )
            )
        self._record("propose", changes=[change.as_dict() for change in changes])
        return tuple(changes)

    @staticmethod
    def server_smoke_change() -> Change:
        return Change(
            component="server-smoke",
            version="task-owned bounded run",
            source="verified setup-mac2 helper",
            location="127.0.0.1 task-selected port",
            effect="starts Appium without creating a session and then stops it",
            rollback="stop the task-owned Appium process",
        )

    def approve(self, changes: tuple[Change, ...]) -> str:
        self._grant_sequence += 1
        identifier = f"grant-{self._grant_sequence}"
        self._grants[identifier] = Grant(identifier, changes)
        self._record("approve", grantId=identifier, changes=[item.as_dict() for item in changes])
        return identifier

    def _grant_for(self, grant_id: str, changes: tuple[Change, ...]) -> Grant:
        grant = self._grants.get(grant_id)
        if grant is None:
            self._record("apply-rejected", reason="unknown-grant", grantId=grant_id)
            raise PermissionError("unknown approval grant")
        if grant.consumed:
            self._record("apply-rejected", reason="consumed-grant", grantId=grant_id)
            raise PermissionError("approval grant already consumed")
        if grant.changes != changes:
            self._record("apply-rejected", reason="scope-drift", grantId=grant_id)
            raise PermissionError("approved change set does not match requested change set")
        return grant

    def apply(self, grant_id: str, changes: tuple[Change, ...]) -> dict[str, Any]:
        grant = self._grant_for(grant_id, changes)
        if any(change.requires_user_action for change in changes):
            self._record("apply-rejected", reason="native-user-action-required", grantId=grant_id)
            raise PermissionError("native user action cannot be executed by the Agent")
        grant.consumed = True
        for change in changes:
            if change.component == "runtime-client":
                self.python = _PYTHON_VERSION
                self.runtime_client = _CLIENT_VERSION
                self.selenium = _SELENIUM_VERSION
            elif change.component == "node-npm":
                self.node = _NODE_VERSION
                self.npm = _NPM_VERSION
            elif change.component == "appium":
                self.appium = _APPIUM_VERSION
            elif change.component == "mac2-driver":
                self.driver = _DRIVER_VERSION
            else:
                self._record("apply-rejected", reason="unsupported-component")
                raise ValueError(f"unsupported component: {change.component}")
            self._record("install", component=change.component, version=change.version)
        return self.snapshot()

    def user_completed_native_action(
        self, action: str, grant_id: str, change: Change
    ) -> dict[str, Any]:
        expected = {
            "install-xcode": "xcode",
            "grant-accessibility": "accessibility",
            "grant-automation": "automation",
            "grant-screen-recording": "screen-recording",
        }
        component = expected.get(action)
        if component is None:
            raise ValueError(f"unknown native action: {action}")
        grant = self._grant_for(grant_id, (change,))
        if not change.requires_user_action or change.component != component:
            self._record("native-action-rejected", actionName=action, grantId=grant_id)
            raise PermissionError("native action does not match the disclosed approval")
        grant.consumed = True
        if action == "install-xcode":
            self.xcode = _XCODE_VERSION
            self.xcode_path = _XCODE_PATH
            self.xcode_tools_ready = True
        elif action == "grant-accessibility":
            self.accessibility = True
        elif action == "grant-automation":
            self.automation = True
        else:
            self.screen_recording = True
        self._record(
            "native-user-action",
            actionName=action,
            component=component,
            grantId=grant_id,
        )
        return self.snapshot()

    def environment_check(self) -> dict[str, Any]:
        result = {"summary": {"requiredOk": self._prerequisites_ready()}}
        self._record("environment-check", result=result)
        return result

    def doctor(self) -> dict[str, Any]:
        required: list[str] = []
        warnings: list[str] = []
        if not _runtime_compatible(self.python, self.runtime_client, self.selenium):
            required.append("Runtime Python, Client, or Selenium requirements are incompatible")
        if not _node_compatible(self.node):
            required.append("Node does not satisfy the selected Mac2 engine")
        if not _npm_compatible(self.npm):
            required.append("npm does not satisfy the selected Mac2 engine")
        if not _appium_compatible(self.appium):
            required.append("Appium does not satisfy the selected Mac2 peer requirement")
        if not _driver_compatible(self.driver):
            required.append("Mac2 is missing or incompatible in the selected Appium home")
        if self.xcode is None or not self.xcode_tools_ready:
            required.append("Selected Xcode tools are unavailable")
        if self.accessibility is not True:
            warnings.append("Accessibility for the actual Xcode Helper identity is unverified")
        result = {"requiredOk": not required, "required": required, "warnings": warnings}
        self._record("doctor", result=result)
        return result

    def run_server_smoke(self, grant_id: str, change: Change) -> dict[str, Any]:
        grant = self._grant_for(grant_id, (change,))
        if change != self.server_smoke_change():
            self._record("apply-rejected", reason="invalid-server-smoke", grantId=grant_id)
            raise PermissionError("server smoke does not match the verified bounded plan")
        grant.consumed = True
        self.server_started = True
        self._record("server-start", approved=True, owner="task")
        status = {"ready": self._prerequisites_ready(), "drivers": ["mac2"]}
        self._record("server-status", result=status)
        result = {"success": status["ready"], "driver": "mac2"}
        self._record("server-smoke-result", result=result)
        self.server_started = False
        self._record("server-stop", owner="task")
        return result

    def forbidden_mutation(self, kind: str) -> None:
        self._record("forbidden-mutation", kind=kind)
        raise PermissionError(f"forbidden macOS setup mutation: {kind}")

    def start_server(self, *, approved: bool, owner: str = "task") -> None:
        if not approved or owner != "task":
            self._record("server-start-rejected", approved=approved, owner=owner)
            raise PermissionError("server startup requires task ownership and approval")
        self.server_started = True
        self._record("server-start", approved=True, owner=owner)

    def stop_server(self) -> None:
        self.server_started = False
        self._record("server-stop", owner="task")

    def create_session(self) -> None:
        self.sessions_created += 1
        self.target["launched"] = True
        self._record("session-create")

    def snapshot(self) -> dict[str, Any]:
        required_ready = self._prerequisites_ready()
        return {
            "profile": self.profile,
            "runtime": {
                "python": self.python,
                "appiumPythonClient": self.runtime_client,
                "selenium": self.selenium,
            },
            "node": {
                "version": self.node,
                "npm": self.npm,
                "path": "/Users/test/.nvm/current/bin/node",
            },
            "appium": {
                "version": self.appium,
                "path": "/Users/test/.nvm/current/bin/appium",
                "home": _APPIUM_HOME,
            },
            "driver": {"name": "mac2", "version": self.driver},
            "xcode": {
                "version": self.xcode,
                "developerDir": self.xcode_path,
                "toolsReady": self.xcode_tools_ready,
            },
            "privacy": {
                "accessibility": self.accessibility,
                "automation": self.automation,
                "screenRecording": self.screen_recording,
            },
            "target": dict(self.target),
            "preparedReady": required_ready,
            "liveReady": required_ready and self.accessibility is True,
            "serverStarted": self.server_started,
            "sessionsCreated": self.sessions_created,
        }
