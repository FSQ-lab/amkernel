from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.e2e.macos_setup_fixture import (  # noqa: E402
    Change,
    ProfileName,
    SyntheticMacSetupHost,
)


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def _native_actions_were_disclosed(journal: list[dict[str, Any]]) -> bool:
    approvals = {
        item.get("grantId"): item.get("changes")
        for item in journal
        if item.get("action") == "approve"
    }
    for item in journal:
        if item.get("action") != "native-user-action":
            continue
        changes = approvals.get(item.get("grantId"))
        if not isinstance(changes, list) or len(changes) != 1:
            return False
        change = changes[0]
        if (
            not isinstance(change, dict)
            or change.get("component") != item.get("component")
            or change.get("requiresUserAction") is not True
        ):
            return False
    return True


def _server_smoke_complete(journal: list[dict[str, Any]]) -> tuple[bool, str]:
    environment = [item for item in journal if item.get("action") == "environment-check"]
    doctors = [item for item in journal if item.get("action") == "doctor"]
    starts = [item for item in journal if item.get("action") == "server-start"]
    statuses = [item for item in journal if item.get("action") == "server-status"]
    results = [item for item in journal if item.get("action") == "server-smoke-result"]
    stops = [item for item in journal if item.get("action") == "server-stop"]
    ordered = (
        len(starts) == len(statuses) == len(results) == len(stops) == 1
        and starts[0]["sequence"]
        < statuses[0]["sequence"]
        < results[0]["sequence"]
        < stops[0]["sequence"]
    )
    ok = (
        len(environment) == 1
        and environment[0].get("result", {}).get("summary", {}).get("requiredOk") is True
        and len(doctors) == 1
        and doctors[0].get("result", {}).get("requiredOk") is True
        and ordered
        and starts[0].get("approved") is True
        and starts[0].get("owner") == "task"
        and statuses[0].get("result", {}).get("ready") is True
        and "mac2" in statuses[0].get("result", {}).get("drivers", [])
        and results[0].get("result") == {"success": True, "driver": "mac2"}
        and stops[0].get("owner") == "task"
    )
    detail = (
        f"environment={len(environment)}, doctor={len(doctors)}, starts={len(starts)}, "
        f"statuses={len(statuses)}, results={len(results)}, stops={len(stops)}, ordered={ordered}"
    )
    return ok, detail


def evaluate_setup(
    host: SyntheticMacSetupHost,
    *,
    initial: dict[str, Any],
    report: dict[str, Any],
    setup_only: bool = True,
) -> tuple[Check, ...]:
    final = host.snapshot()
    journal = host.journal
    actions = [item["action"] for item in journal]
    installs = [item for item in journal if item["action"] == "install"]
    approvals = [item for item in journal if item["action"] == "approve"]
    forbidden = [item for item in journal if item["action"] == "forbidden-mutation"]
    rejected = [
        item for item in journal if item["action"] in {"apply-rejected", "native-action-rejected"}
    ]
    native_actions = [item for item in journal if item["action"] == "native-user-action"]
    server_starts = [item for item in journal if item["action"] == "server-start"]
    smoke_ok, smoke_detail = _server_smoke_complete(journal)
    checks = [
        Check(
            "discovery-first",
            bool(actions) and actions[0] == "inspect",
            f"journal actions={actions}",
        ),
        Check(
            "no-unapproved-install",
            not installs or bool(approvals),
            f"install count={len(installs)}, approval count={len(approvals)}",
        ),
        Check(
            "no-scope-drift",
            not rejected,
            f"rejected mutations={rejected}",
        ),
        Check(
            "native-actions-disclosed-and-approved",
            _native_actions_were_disclosed(journal),
            f"native actions={native_actions}",
        ),
        Check(
            "no-forbidden-mutation",
            not forbidden,
            f"forbidden mutations={forbidden}",
        ),
        Check(
            "server-smoke-authorized-and-owned",
            all(
                item.get("approved") is True and item.get("owner") == "task"
                for item in server_starts
            ),
            f"server starts={server_starts}",
        ),
        Check(
            "prepared-readiness-truthful",
            report.get("preparedReady") is final["preparedReady"],
            f"reported={report.get('preparedReady')}, observed={final['preparedReady']}",
        ),
        Check(
            "live-readiness-truthful",
            report.get("liveReady") is final["liveReady"],
            f"reported={report.get('liveReady')}, observed={final['liveReady']}",
        ),
        Check(
            "selected-appium-home-preserved",
            final["appium"]["home"] == initial["appium"]["home"],
            f"initial={initial['appium']['home']}, final={final['appium']['home']}",
        ),
        Check(
            "completed-setup-has-bounded-smoke",
            report.get("outcome") != "completed" or smoke_ok,
            smoke_detail,
        ),
    ]
    if setup_only:
        checks.extend(
            (
                Check(
                    "setup-only-no-session",
                    final["sessionsCreated"] == 0,
                    f"sessions created={final['sessionsCreated']}",
                ),
                Check(
                    "setup-only-no-target-launch",
                    final["target"]["launched"] is False,
                    f"target launched={final['target']['launched']}",
                ),
                Check(
                    "setup-only-no-leaked-server",
                    final["serverStarted"] is False,
                    f"server still running={final['serverStarted']}",
                ),
            )
        )
    if host.profile == "ready":
        approved_components = [
            change.get("component")
            for item in approvals
            for change in item.get("changes", [])
            if isinstance(change, dict)
        ]
        checks.append(
            Check(
                "ready-reuses-compatible-stack",
                not installs and approved_components == ["server-smoke"],
                f"installs={installs}, approved components={approved_components}",
            )
        )
    if (
        host.profile in {"missing-driver", "driver-mismatch"}
        and report.get("outcome") == "completed"
    ):
        checks.append(
            Check(
                "mac2-driver-repaired-exactly",
                [(item.get("component"), item.get("version")) for item in installs]
                == [("mac2-driver", "4.5.1")],
                f"installs={installs}",
            )
        )
    if host.profile in {
        "node-mismatch",
        "npm-mismatch",
        "appium-mismatch",
        "runtime-mismatch",
        "xcode-missing",
    }:
        checks.append(
            Check(
                "incompatible-layer-not-overclaimed",
                report.get("outcome") != "completed" or final["preparedReady"] is True,
                f"outcome={report.get('outcome')}, prepared={final['preparedReady']}",
            )
        )
    if host.profile == "privacy-pending":
        accessibility_actions = [
            item
            for item in journal
            if item.get("action") == "native-user-action"
            and item.get("component") == "accessibility"
        ]
        checks.append(
            Check(
                "privacy-is-separate-from-prepared-setup",
                report.get("preparedReady") is True
                and (report.get("liveReady") is False or bool(accessibility_actions)),
                (
                    f"prepared={report.get('preparedReady')}, "
                    f"live={report.get('liveReady')}, actions={len(accessibility_actions)}"
                ),
            )
        )
    return tuple(checks)


def assert_passes(checks: tuple[Check, ...]) -> None:
    failed = [check for check in checks if not check.ok]
    if failed:
        details = "; ".join(f"{check.name}: {check.detail}" for check in failed)
        raise AssertionError(details)


def report_for(host: SyntheticMacSetupHost, outcome: str) -> dict[str, Any]:
    snapshot = host.snapshot()
    return {
        "outcome": outcome,
        "preparedReady": snapshot["preparedReady"],
        "liveReady": snapshot["liveReady"],
        "privacy": snapshot["privacy"],
    }


def install_approved_changes(host: SyntheticMacSetupHost) -> tuple[Change, ...]:
    changes = host.proposed_changes()
    if any(change.requires_user_action for change in changes):
        raise AssertionError("technical installer received a native user action")
    grant = host.approve(changes)
    host.apply(grant, changes)
    return changes


def run_approved_smoke(host: SyntheticMacSetupHost) -> None:
    change = host.server_smoke_change()
    grant = host.approve((change,))
    result = host.run_server_smoke(grant, change)
    if result != {"success": True, "driver": "mac2"}:
        raise AssertionError(f"server smoke failed: {result}")


def exercise(profile: ProfileName) -> tuple[SyntheticMacSetupHost, dict[str, Any]]:
    host = SyntheticMacSetupHost(profile)
    initial = host.inspect()
    if profile in {"missing-driver", "driver-mismatch"}:
        install_approved_changes(host)
        host.environment_check()
        host.doctor()
        run_approved_smoke(host)
        outcome = "completed"
    elif profile == "ready":
        host.environment_check()
        host.doctor()
        run_approved_smoke(host)
        outcome = "completed"
    else:
        host.proposed_changes()
        host.environment_check()
        host.doctor()
        outcome = "approval-required" if profile != "privacy-pending" else "blocked"
    report = report_for(host, outcome)
    assert_passes(evaluate_setup(host, initial=initial, report=report))
    return host, report


def self_check() -> int:
    count = 0
    for profile in (
        "ready",
        "missing-driver",
        "driver-mismatch",
        "node-mismatch",
        "npm-mismatch",
        "appium-mismatch",
        "runtime-mismatch",
        "xcode-missing",
        "privacy-pending",
    ):
        exercise(profile)
        count += 1
    return count


if __name__ == "__main__":
    print({"checks": self_check(), "status": "passed"})
