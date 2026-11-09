"""Behavioral boundaries for the experiment's actual loopback mutation gate."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from tests.e2e.skill_ab_fixture import ELEMENT, SceneServer
from tests.e2e.skill_ab_forms import ExactFileScene, FocusSubmitScene


def _request(
    server: SceneServer, method: str, path: str, body: dict[str, Any] | None = None
) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    request = Request(
        server.url + path, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        response = urlopen(request, timeout=3)
    except HTTPError as error:
        response = error
    with response:
        return response.status, json.load(response)["value"]


def _session(server: SceneServer) -> str:
    status, payload = _request(
        server, "POST", "/session", {"capabilities": {"alwaysMatch": {"platformName": "Android"}}}
    )
    assert status == 200
    session_id: str = payload["sessionId"]
    return "/session/" + session_id


def _find(server: SceneServer, prefix: str, key: str) -> str:
    status, value = _request(
        server, "POST", prefix + "/element", {"using": "accessibility id", "value": key}
    )
    assert status == 200
    handle: str = value[ELEMENT]
    return handle


def test_failed_admitted_input_uses_budget_without_changing_wrong_field() -> None:
    scene = FocusSubmitScene()
    scene.budget = 1
    initial = scene.snapshot()
    with SceneServer(scene) as server:
        prefix = _session(server)
        handle = _find(server, prefix, "backup-phone")
        status, error = _request(
            server, "POST", f"{prefix}/element/{handle}/value", {"text": "555-0134"}
        )
        assert status == 400
        assert error["error"] == "invalid element state"
        assert scene.snapshot()["fields"] == initial["fields"]
        status, error = _request(server, "POST", f"{prefix}/element/{handle}/click", {})
        assert status == 400
        assert server.actions == 1
        assert server.rejected == 1
        # Exhaustion neither kills the session nor prevents truthful cleanup.
        assert _request(server, "GET", prefix + "/source")[0] == 200
        assert _request(server, "DELETE", prefix)[0] == 200
        assert not server.active
        assert server.deleted == 1
        assert scene.snapshot()["saved"] is None


def test_old_handle_becomes_stale_after_submit_and_reads_are_pure() -> None:
    scene = FocusSubmitScene()
    with SceneServer(scene) as server:
        prefix = _session(server)
        handle = _find(server, prefix, "backup-phone")
        before = scene.snapshot()
        for _ in range(3):
            assert _request(server, "GET", prefix + "/source")[0] == 200
        assert scene.snapshot() == before
        assert server.actions == 0
        for suffix, body in [("click", {}), ("clear", {}), ("value", {"text": "555-0134"})]:
            assert _request(server, "POST", f"{prefix}/element/{handle}/{suffix}", body)[0] == 200
        save = _find(server, prefix, "save-profile")
        assert _request(server, "POST", f"{prefix}/element/{save}/click", {})[0] == 200
        status, error = _request(server, "GET", f"{prefix}/element/{handle}/text")
        assert status == 404
        assert error["error"] == "stale element reference"
        assert scene.snapshot()["saved"]["backup-phone"] == "555-0134"
        assert server.actions == 4
        assert _request(server, "DELETE", prefix)[0] == 200


def test_unsupported_selector_clause_never_selects_a_different_target() -> None:
    with SceneServer(FocusSubmitScene()) as server:
        prefix = _session(server)
        for suffix in (".instance(1)", ".enabled(true)"):
            status, error = _request(
                server,
                "POST",
                prefix + "/element",
                {
                    "using": "-android uiautomator",
                    "value": 'new UiSelector().className("android.widget.Button")' + suffix,
                },
            )
            assert status == 400
            assert error["error"] == "invalid selector"
        assert server.actions == 0
        assert server.scene.snapshot()["saved"] is None
        assert _request(server, "DELETE", prefix)[0] == 200


def test_detached_editor_handle_stays_stale_after_same_key_reappears() -> None:
    with SceneServer(ExactFileScene()) as server:
        prefix = _session(server)

        def act(key: str, operation: str = "click", text: str = "") -> str:
            handle = _find(server, prefix, key)
            body = {"text": text} if operation == "value" else {}
            assert (
                _request(server, "POST", f"{prefix}/element/{handle}/{operation}", body)[0] == 200
            )
            return handle

        act("new-file")
        act("file-name", "value", "roundtrip")
        act("create-file")
        old = act("file-body", "value", "persisted body")
        act("save-file")
        act("file-roundtrip.txt")
        status, error = _request(server, "GET", f"{prefix}/element/{old}/text")
        assert status == 404
        assert error["error"] == "stale element reference"
        fresh = _find(server, prefix, "file-body")
        assert _request(server, "GET", f"{prefix}/element/{fresh}/text") == (200, "persisted body")
        assert _request(server, "DELETE", prefix)[0] == 200


def test_native_identity_queries_are_read_only_at_exhaustion_and_require_live_session() -> None:
    scene = FocusSubmitScene()
    scene.budget = 0
    before = scene.snapshot()
    with SceneServer(scene) as server:
        prefix = _session(server)
        queries = (
            ("mobile: getCurrentPackage", "/appium/device/current_package"),
            ("mobile: getCurrentActivity", "/appium/device/current_activity"),
        )
        for script, legacy_route in queries:
            expected = _request(server, "GET", prefix + legacy_route)
            assert (
                _request(server, "POST", prefix + "/execute/sync", {"script": script, "args": []})
                == expected
            )
        assert scene.snapshot() == before
        assert server.actions == server.rejected == 0
        assert _request(server, "DELETE", prefix)[0] == 200
        for script, _ in queries:
            status, error = _request(
                server, "POST", prefix + "/execute/sync", {"script": script, "args": []}
            )
            assert status == 404
            assert error["error"] == "invalid session id"


def test_unknown_scripts_remain_rejected_and_journal_omits_code_and_arguments() -> None:
    with SceneServer(FocusSubmitScene()) as server:
        prefix = _session(server)
        before = server.scene.snapshot()
        for script, recorded in (
            ("mobile: shell", "mobile: shell"),
            ("return 'private-script-body'", "<unrecognized-script>"),
        ):
            status, error = _request(
                server,
                "POST",
                prefix + "/execute/sync",
                {"script": script, "args": [{"command": "private-argument"}]},
            )
            assert status == 404
            assert error["error"] == "unknown command"
            event = server.journal[-1]
            assert event["action"] == "execute"
            assert event["script"] == recorded
        assert "private-" not in json.dumps(server.journal)
        assert server.scene.snapshot() == before
        assert server.actions == server.rejected == 0
        assert _request(server, "DELETE", prefix)[0] == 200
