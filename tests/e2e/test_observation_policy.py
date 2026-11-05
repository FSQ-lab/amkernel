from __future__ import annotations

import base64
import hashlib
import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any
from xml.etree import ElementTree

import pytest
from PIL import Image

from tests.e2e import skill_behavior
from tests.e2e.test_skill_behavior_evaluator import (
    _action,
    _checks,
    _final,
    _python_call,
    _run,
)

_BASE = datetime(2026, 1, 1, tzinfo=UTC)
_PRE_SHA = "a" * 64
_POST_SHA = "b" * 64

_VISUAL_CASES = [
    ("android-visual-fallback", "android-visual", "android", "uiautomator2"),
    ("ios-visual-fallback", "ios-visual", "ios", "xcuitest"),
    ("mac2-visual-fallback", "mac2-visual", "mac", "mac2"),
]
_VISUAL_BY_SCENARIO = {item[0]: item for item in _VISUAL_CASES}
_SHORT_SCENARIOS = ("android-short-flow", "ios-short-flow", "mac2-calculator")


def _at(offset: float) -> float:
    return (_BASE + timedelta(seconds=offset)).timestamp()


def _iso(offset: float) -> str:
    return (_BASE + timedelta(seconds=offset)).isoformat()


def _real_python_call(start: float, end: float) -> dict[str, Any]:
    return _python_call(started=_iso(start), completed=_iso(end))


def _failed(checks: dict[str, dict[str, Any]]) -> set[str]:
    return {check_id for check_id, item in checks.items() if not item["ok"]}


# ---------------------------------------------------------------------------
# Evaluator-only fixtures: the existing control-first flows stay screenshot-free.


def _short_flow_actions(scenario: str, *, screenshot: bool) -> list[dict[str, Any]]:
    session_id = "fixture-session-1"
    if scenario == "android-short-flow":
        caps = {"platformName": "Android", "appium:automationName": "UiAutomator2"}
    elif scenario == "ios-short-flow":
        caps = {"platformName": "iOS", "appium:automationName": "XCUITest"}
    else:
        caps = {"platformName": "mac", "appium:automationName": "mac2"}
    actions = [
        _action(
            "create-session",
            at=_at(1),
            detail={"sessionId": session_id, "caps": json.dumps(caps, sort_keys=True)},
        ),
    ]
    if scenario == "mac2-calculator":
        actions.append(
            _action("read-state", at=_at(2), detail={"state": {"toggle": False, "beta": False}})
        )
        if screenshot:
            actions.append(_action("screenshot", at=_at(2.5), detail={"sessionId": session_id}))
        actions.extend(
            [
                _action("click", at=_at(3), detail={"sessionId": session_id, "label": "Toggle"}),
                _action(
                    "read-state",
                    at=_at(3.5),
                    detail={"state": {"toggle": True, "beta": False}},
                ),
            ]
        )
    else:
        actions.extend(
            [
                _action("find", at=_at(2), detail={"sessionId": session_id, "label": "Toggle"}),
            ]
        )
        if screenshot:
            actions.append(_action("screenshot", at=_at(2.5), detail={"sessionId": session_id}))
        actions.extend(
            [
                _action("click", at=_at(3), detail={"sessionId": session_id, "label": "Toggle"}),
                _action(
                    "source",
                    at=_at(4),
                    detail={"sessionId": session_id, "state": {"toggle": True, "beta": False}},
                ),
            ]
        )
    actions.append(_action("delete-session", at=_at(5), detail={"sessionId": session_id}))
    return actions


def _short_flow_run(scenario: str, *, screenshot: bool) -> dict[str, Any]:
    run = _run(
        scenario,
        variant=scenario,
        actions=_short_flow_actions(scenario, screenshot=screenshot),
        final=_final(
            taskOutcome="completed",
            cleanup={"ownedSession": "completed", "server": "preserved"},
        ),
        calls=[_real_python_call(0, 6)],
        sessions=[{"id": "fixture-session-1", "preexisting": False, "active": False}],
        state={"toggle": True, "beta": False},
    )
    run["fixture"]["screenshotCalls"] = int(screenshot)
    return run


@pytest.mark.parametrize("scenario", _SHORT_SCENARIOS)
def test_existing_flows_reject_unnecessary_screenshot_but_pass_without_it(
    scenario: str,
) -> None:
    clean = _checks(_short_flow_run(scenario, screenshot=False))
    assert not _failed(clean), f"control-only flow regressed: {sorted(_failed(clean))}"
    assert clean["observation-no-unnecessary-screenshot"]["ok"] is True

    polluted = _checks(_short_flow_run(scenario, screenshot=True))
    assert polluted["observation-no-unnecessary-screenshot"]["ok"] is False
    assert _failed(polluted) == {"observation-no-unnecessary-screenshot"}


# ---------------------------------------------------------------------------
# Visual fixture behavior: real bitmap, hidden geometry, strict platform routing.


@contextmanager
def _running_fixture(variant: str) -> Iterator[skill_behavior.SyntheticAppium]:
    fixture = skill_behavior.SyntheticAppium(skill_behavior.FixtureConfig(variant))
    fixture.start()
    try:
        yield fixture
    finally:
        fixture.stop()


def _request(
    fixture: skill_behavior.SyntheticAppium,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        f"{fixture.endpoint}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def _create_session(
    fixture: skill_behavior.SyntheticAppium, platform: str, automation: str
) -> tuple[int, dict[str, Any]]:
    return _request(
        fixture,
        "POST",
        "/session",
        {
            "capabilities": {
                "alwaysMatch": {
                    "platformName": platform,
                    "appium:automationName": automation,
                }
            }
        },
    )


def _pointer_payload(x: int, y: int) -> dict[str, Any]:
    return {
        "actions": [
            {
                "type": "pointer",
                "id": "finger",
                "parameters": {"pointerType": "touch"},
                "actions": [
                    {"type": "pointerMove", "x": x, "y": y, "origin": "viewport"},
                    {"type": "pointerDown", "button": 0},
                    {"type": "pointerUp", "button": 0},
                ],
            }
        ]
    }


def _journal(fixture: skill_behavior.SyntheticAppium, action: str) -> list[dict[str, Any]]:
    return [item for item in fixture.snapshot()["journal"] if item.get("action") == action]


def _screenshot_bytes(fixture: skill_behavior.SyntheticAppium, session_id: str) -> bytes:
    status, body = _request(fixture, "GET", f"/session/{session_id}/screenshot")
    assert status == 200
    return base64.b64decode(body["value"], validate=True)


def _image(raw: bytes) -> Image.Image:
    image = Image.open(BytesIO(raw))
    image.load()
    return image.convert("RGB")


def _pixels(raw: bytes) -> dict[str, Any]:
    image = Image.open(BytesIO(raw))
    image.load()
    rgba = image.convert("RGBA")
    return {
        "width": rgba.width,
        "height": rgba.height,
        "mode": "RGBA",
        "sha256": hashlib.sha256(rgba.tobytes()).hexdigest(),
    }


def _reencode_png(raw: bytes) -> bytes:
    image = Image.open(BytesIO(raw))
    image.load()
    output = BytesIO()
    image.save(output, format="PNG", compress_level=1)
    return output.getvalue()


def _resize_png(raw: bytes, size: tuple[int, int]) -> bytes:
    image = Image.open(BytesIO(raw))
    image.load()
    output = BytesIO()
    image.resize(size, Image.Resampling.NEAREST).save(output, format="PNG")
    return output.getvalue()


def _change_pixel_png(raw: bytes) -> bytes:
    image = Image.open(BytesIO(raw))
    image.load()
    changed = image.convert("RGB")
    original = changed.getpixel((0, 0))
    changed.putpixel((0, 0), (0, 0, 0) if original != (0, 0, 0) else (255, 255, 255))
    output = BytesIO()
    changed.save(output, format="PNG")
    return output.getvalue()


@pytest.mark.parametrize("scenario,variant,platform,automation", _VISUAL_CASES)
def test_visual_fixture_enforces_platform_and_withholds_target_from_semantics(
    scenario: str, variant: str, platform: str, automation: str
) -> None:
    del scenario
    wrong_platform, wrong_automation = (
        ("ios", "xcuitest") if platform != "ios" else ("android", "uiautomator2")
    )
    with _running_fixture(variant) as fixture:
        rejected, _ = _create_session(fixture, wrong_platform, wrong_automation)
        assert rejected == 500

        accepted, created = _create_session(fixture, platform, automation)
        assert accepted == 200
        session_id = created["value"]["sessionId"]

        status, rect = _request(fixture, "GET", f"/session/{session_id}/window/rect")
        assert status == 200
        assert rect["value"] == {
            "x": 0,
            "y": 0,
            "width": skill_behavior.VISUAL_SCREEN_WIDTH,
            "height": skill_behavior.VISUAL_SCREEN_HEIGHT,
        }

        status, source = _request(fixture, "GET", f"/session/{session_id}/source")
        assert status == 200
        xml = source["value"]
        root = ElementTree.fromstring(xml)
        application = root.find(".//*[@bundleId='com.amkernel.fixture']")
        assert application is not None
        assert application.get("name") == "AMKernelFixture"
        lowered = xml.lower()
        for leaked in (
            "toggle",
            "circle",
            str(skill_behavior.VISUAL_TARGET_CENTER[0]),
            str(skill_behavior.VISUAL_TARGET_CENTER[1]),
            "204,51,51",
            "47,158,68",
        ):
            assert leaked not in lowered

        status, _ = _request(
            fixture,
            "POST",
            f"/session/{session_id}/element",
            {"using": "accessibility id", "value": "Toggle"},
        )
        assert status == 404

        status, state = _request(
            fixture,
            "POST",
            f"/session/{session_id}/execute/sync",
            {"script": "amkernel:state", "args": []},
        )
        assert status == 200
        assert state["value"] == {"screen": "display-settings"}


def test_visual_screenshot_is_real_png_and_changes_with_state() -> None:
    center = skill_behavior.VISUAL_TARGET_CENTER
    with _running_fixture("android-visual") as fixture:
        accepted, created = _create_session(fixture, "android", "uiautomator2")
        assert accepted == 200
        session_id = created["value"]["sessionId"]

        before_raw = _screenshot_bytes(fixture, session_id)
        before = _image(before_raw)
        assert before_raw.startswith(b"\x89PNG\r\n\x1a\n")
        assert before.size == (
            skill_behavior.VISUAL_SCREEN_WIDTH,
            skill_behavior.VISUAL_SCREEN_HEIGHT,
        )
        assert before.size != (1, 1)
        status, rect = _request(fixture, "GET", f"/session/{session_id}/window/rect")
        assert status == 200
        assert before.size == (rect["value"]["width"], rect["value"]["height"])
        before_pixel = before.getpixel(center)
        assert before_pixel != before.getpixel((0, 0))
        before_journal = _journal(fixture, "screenshot")[-1]["detail"]
        assert before_journal["sessionId"] == session_id
        assert before_journal["sha256"] == hashlib.sha256(before_raw).hexdigest()
        assert before_journal["pixels"] == _pixels(before_raw)
        assert before_journal["state"] == {"toggle": False}
        assert (
            before_journal["width"],
            before_journal["height"],
        ) == before.size

        status, _ = _request(
            fixture,
            "POST",
            f"/session/{session_id}/actions",
            _pointer_payload(*center),
        )
        assert status == 200

        after_raw = _screenshot_bytes(fixture, session_id)
        after = _image(after_raw)
        assert after.size == before.size
        assert after_raw != before_raw
        assert after.getpixel(center) != before_pixel
        after_journal = _journal(fixture, "screenshot")[-1]["detail"]
        assert after_journal["sessionId"] == session_id
        assert after_journal["sha256"] == hashlib.sha256(after_raw).hexdigest()
        assert after_journal["pixels"] == _pixels(after_raw)
        assert after_journal["state"] == {"toggle": True}


@pytest.mark.parametrize("scenario,variant,platform,automation", _VISUAL_CASES)
def test_visual_pointer_hit_changes_state_and_miss_does_not(
    scenario: str, variant: str, platform: str, automation: str
) -> None:
    del scenario
    center = skill_behavior.VISUAL_TARGET_CENTER
    with _running_fixture(variant) as fixture:
        accepted, created = _create_session(fixture, platform, automation)
        assert accepted == 200
        session_id = created["value"]["sessionId"]

        status, _ = _request(
            fixture,
            "POST",
            f"/session/{session_id}/actions",
            _pointer_payload(0, 0),
        )
        assert status == 200
        missed = fixture.snapshot()
        assert missed["state"]["toggle"] is False
        missed_click = _journal(fixture, "coordinate-click")[-1]["detail"]
        assert missed_click["sessionId"] == session_id
        assert missed_click["hit"] is False

        status, _ = _request(
            fixture,
            "POST",
            f"/session/{session_id}/actions",
            _pointer_payload(*center),
        )
        assert status == 200
        hit = fixture.snapshot()
        assert hit["state"]["toggle"] is True
        clicks = _journal(fixture, "coordinate-click")
        assert len(clicks) == 2
        assert clicks[-1]["detail"]["sessionId"] == session_id
        assert clicks[-1]["detail"]["hit"] is True
        assert clicks[-1]["detail"]["state"]["toggle"] is True

        before = len(clicks)
        status, _ = _request(fixture, "POST", f"/session/{session_id}/actions", {"actions": []})
        assert status == 400
        assert len(_journal(fixture, "coordinate-click")) == before
        assert fixture.snapshot()["state"]["toggle"] is True

        status, _ = _request(fixture, "DELETE", f"/session/{session_id}/actions")
        assert status == 200
        assert _journal(fixture, "actions-release")
        assert len(_journal(fixture, "coordinate-click")) == before


def _raw_request(
    fixture: skill_behavior.SyntheticAppium, method: str, path: str, body: bytes
) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        f"{fixture.endpoint}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_visual_pointer_errors_never_change_state_or_record_a_click() -> None:
    with _running_fixture("android-visual") as fixture:
        accepted, created = _create_session(fixture, "android", "uiautomator2")
        assert accepted == 200
        session_id = created["value"]["sessionId"]
        path = f"/session/{session_id}/actions"

        malformed, _ = _raw_request(fixture, "POST", path, b'{"actions":')
        assert malformed == 400
        paused, _ = _request(
            fixture,
            "POST",
            path,
            {
                "actions": [
                    {
                        "type": "pointer",
                        "id": "finger",
                        "actions": [{"type": "pause", "duration": 1}],
                    }
                ]
            },
        )
        assert paused == 200
        invalid_pause, _ = _request(
            fixture,
            "POST",
            path,
            {
                "actions": [
                    {
                        "type": "pointer",
                        "id": "finger",
                        "actions": [{"type": "pause", "duration": -1}],
                    }
                ]
            },
        )
        assert invalid_pause == 400
        incomplete, _ = _request(
            fixture,
            "POST",
            path,
            {
                "actions": [
                    {
                        "type": "pointer",
                        "id": "finger",
                        "actions": [
                            {"type": "pointerMove", "x": 0, "y": 0, "origin": "viewport"},
                            {"type": "pointerDown", "button": 0},
                        ],
                    }
                ]
            },
        )
        assert incomplete == 400
        assert fixture.snapshot()["state"]["toggle"] is False
        assert not _journal(fixture, "coordinate-click")


def test_official_appium_client_pointer_round_trip_and_cleanup() -> None:
    webdriver = pytest.importorskip("appium.webdriver")
    options_module = pytest.importorskip("appium.options.android")

    center = skill_behavior.VISUAL_TARGET_CENTER
    with _running_fixture("android-visual") as fixture:
        options = options_module.UiAutomator2Options().load_capabilities(
            {"platformName": "android", "appium:automationName": "uiautomator2"}
        )
        driver = webdriver.Remote(command_executor=fixture.endpoint, options=options)
        try:
            assert driver.get_window_rect() == {
                "x": 0,
                "y": 0,
                "width": skill_behavior.VISUAL_SCREEN_WIDTH,
                "height": skill_behavior.VISUAL_SCREEN_HEIGHT,
            }
            before = _image(driver.get_screenshot_as_png())
            assert before.getpixel(center) != before.getpixel((0, 0))

            driver.tap([center])

            after = _image(driver.get_screenshot_as_png())
            assert after.getpixel(center) != before.getpixel(center)
        finally:
            driver.quit()

        snapshot = fixture.snapshot()
        assert snapshot["state"]["toggle"] is True
        hits = [
            item
            for item in _journal(fixture, "coordinate-click")
            if item.get("status") == 200 and item.get("detail", {}).get("hit") is True
        ]
        assert len(hits) == 1
        owns = [item for item in snapshot["sessions"] if not item.get("preexisting")]
        assert owns and all(item["active"] is False for item in owns)
        assert _journal(fixture, "delete-session")


# ---------------------------------------------------------------------------
# Visual evaluator: accept observed evidence, reject every unsupported shortcut.


def _visual_run(
    *,
    scenario: str = "android-visual-fallback",
    platform: str | None = None,
    automation: str | None = None,
    pre_shot: bool = True,
    post_shot: bool = True,
    hit: bool = True,
    intervening_click: bool = False,
    delete: bool = True,
    pre_image: bool = True,
    post_image: bool = True,
    same_call: bool = False,
) -> dict[str, Any]:
    _, _, default_platform, default_automation = _VISUAL_BY_SCENARIO[scenario]
    platform = default_platform if platform is None else platform
    automation = default_automation if automation is None else automation
    session_id = "fixture-session-1"
    caps = json.dumps(
        {"platformName": platform, "appium:automationName": automation}, sort_keys=True
    )
    actions = [
        _action(
            "create-session",
            at=_at(1),
            detail={"sessionId": session_id, "caps": caps},
        )
    ]
    if pre_shot:
        actions.append(
            _action(
                "screenshot",
                at=_at(2),
                detail={
                    "sessionId": session_id,
                    "state": {"toggle": False},
                    "width": skill_behavior.VISUAL_SCREEN_WIDTH,
                    "height": skill_behavior.VISUAL_SCREEN_HEIGHT,
                    "sha256": _PRE_SHA,
                },
            )
        )
    if intervening_click:
        actions.append(
            _action("click", at=_at(3), detail={"sessionId": session_id, "label": "Display"})
        )
    actions.append(
        _action(
            "coordinate-click",
            at=_at(4),
            detail={
                "sessionId": session_id,
                "hit": hit,
                "state": {"toggle": hit},
                "width": skill_behavior.VISUAL_SCREEN_WIDTH,
                "height": skill_behavior.VISUAL_SCREEN_HEIGHT,
            },
        )
    )
    if post_shot:
        actions.append(
            _action(
                "screenshot",
                at=_at(7),
                detail={
                    "sessionId": session_id,
                    "state": {"toggle": hit},
                    "width": skill_behavior.VISUAL_SCREEN_WIDTH,
                    "height": skill_behavior.VISUAL_SCREEN_HEIGHT,
                    "sha256": _POST_SHA,
                },
            )
        )
    if delete:
        actions.append(_action("delete-session", at=_at(8), detail={"sessionId": session_id}))

    if same_call:
        calls = [
            _real_python_call(0.5, 4.5),
            _real_python_call(5, 9),
        ]
        post_call = calls[1]
    else:
        calls = [
            _real_python_call(0.5, 2.5),
            _real_python_call(3, 5),
            _real_python_call(6, 9),
        ]
        post_call = calls[2]
    for call in calls:
        call["imageCount"] = 0
        call["imageSha256"] = []
    if pre_shot and pre_image:
        calls[0]["imageCount"] = 1
        calls[0]["imageSha256"] = [_PRE_SHA]
    if post_shot and post_image:
        post_call["imageCount"] = 1
        post_call["imageSha256"] = [_POST_SHA]

    run = _run(
        scenario,
        variant=_VISUAL_BY_SCENARIO[scenario][1],
        actions=actions,
        final=_final(
            taskOutcome="completed",
            cleanup={"ownedSession": "completed", "server": "preserved"},
        ),
        calls=calls,
        sessions=[
            {"id": session_id, "preexisting": False, "active": not delete},
        ],
        state={"toggle": hit, "beta": False},
    )
    run["fixture"]["screenshotCalls"] = int(pre_shot) + int(post_shot)
    return run


def _reencoded_visual_run(*, unrelated: str | None = None) -> dict[str, Any]:
    run = _visual_run()
    journal = run["fixture"]["journal"]
    shots = [item for item in journal if item.get("action") == "screenshot"]
    calls = [item for item in run["tool_calls"] if item.get("mcpToolName") == "python_exec"]
    assert len(shots) == 2 and len(calls) == 3
    canonical = [
        skill_behavior._visual_screenshot_png(False),
        skill_behavior._visual_screenshot_png(True),
    ]
    for shot, call, raw in zip((shots[0], shots[1]), (calls[0], calls[2]), canonical, strict=True):
        encoded = _reencode_png(raw)
        assert encoded != raw
        raw_pixels = _pixels(raw)
        encoded_pixels = _pixels(encoded)
        assert encoded_pixels == raw_pixels
        shot["detail"]["sha256"] = hashlib.sha256(raw).hexdigest()
        shot["detail"]["pixels"] = raw_pixels
        call["imageSha256"] = [hashlib.sha256(encoded).hexdigest()]
        call["imagePixels"] = [encoded_pixels]
        assert call["imageSha256"][0] != shot["detail"]["sha256"]
    if unrelated == "resized":
        unrelated_raw = _resize_png(canonical[0], (200, 150))
        unrelated_pixels = _pixels(unrelated_raw)
        assert unrelated_pixels["width"] == 200
    elif unrelated == "changed":
        unrelated_raw = _change_pixel_png(canonical[0])
        unrelated_pixels = _pixels(unrelated_raw)
        assert unrelated_pixels["width"] == 400
        assert unrelated_pixels != _pixels(canonical[0])
    elif unrelated is not None:
        raise ValueError(f"unknown unrelated image variant: {unrelated}")
    else:
        return run
    for call in (calls[0], calls[2]):
        call["imagePixels"] = [unrelated_pixels]
    return run


@pytest.mark.parametrize("scenario,variant,platform,automation", _VISUAL_CASES)
def test_visual_evaluator_accepts_displayed_pre_and_post_images(
    scenario: str, variant: str, platform: str, automation: str
) -> None:
    del variant, platform, automation
    checks = _checks(_visual_run(scenario=scenario))
    assert not _failed(checks), f"visual baseline failed: {sorted(_failed(checks))}"


def test_visual_evaluator_accepts_lossless_reencoded_same_pixel_images() -> None:
    checks = _checks(_reencoded_visual_run())
    assert not _failed(checks), (
        "same full-frame pixels with a different PNG encoding were rejected: "
        f"{sorted(_failed(checks))}"
    )


def test_visual_evaluator_rejects_resized_or_changed_unrelated_image() -> None:
    for variant in ("resized", "changed"):
        failures = _failed(_checks(_reencoded_visual_run(unrelated=variant)))
        assert "visual-current-screenshot-before-coordinate" in failures, variant
        assert "visual-observed-result" in failures, variant
        assert "visual-task-result" not in failures, variant


def test_visual_evaluator_rejects_download_only_and_missing_images() -> None:
    download_only = _checks(_visual_run(pre_image=False))
    assert "visual-current-screenshot-before-coordinate" in _failed(download_only)
    assert "visual-observed-result" not in _failed(download_only)

    post_download_only = _checks(_visual_run(post_image=False))
    assert "visual-current-screenshot-before-coordinate" not in _failed(post_download_only)
    assert "visual-observed-result" in _failed(post_download_only)
    assert "visual-task-result" not in _failed(post_download_only)

    missing = _checks(
        _visual_run(pre_shot=False, post_shot=False, pre_image=False, post_image=False)
    )
    failures = _failed(missing)
    assert "visual-current-screenshot-before-coordinate" in failures
    assert "visual-observed-result" in failures
    assert "visual-task-result" not in failures


def test_visual_evaluator_rejects_same_call_blind_spot_and_stale_pre_image() -> None:
    blind = _checks(_visual_run(same_call=True))
    assert "visual-current-screenshot-before-coordinate" in _failed(blind)
    assert "visual-observed-result" not in _failed(blind)

    stale = _checks(_visual_run(intervening_click=True))
    assert "visual-current-screenshot-before-coordinate" in _failed(stale)
    assert "visual-observed-result" not in _failed(stale)


def test_visual_evaluator_rejects_wrong_platform_coordinate_and_post_state() -> None:
    wrong_platform = _checks(_visual_run(platform="ios", automation="xcuitest"))
    assert "visual-correct-platform" in _failed(wrong_platform)
    assert "visual-current-screenshot-before-coordinate" not in _failed(wrong_platform)

    wrong_coordinate = _checks(_visual_run(hit=False))
    failures = _failed(wrong_coordinate)
    assert "visual-current-screenshot-before-coordinate" in failures
    assert "visual-observed-result" in failures
    assert "visual-task-result" in failures

    no_post = _checks(_visual_run(post_shot=False, post_image=False))
    assert "visual-observed-result" in _failed(no_post)
    assert "visual-current-screenshot-before-coordinate" not in _failed(no_post)
    assert "visual-task-result" not in _failed(no_post)


def test_visual_evaluator_rejects_cleanup_claims_without_observed_cleanup() -> None:
    checks = _checks(_visual_run(delete=False))
    failures = _failed(checks)
    assert "cleanup-owned-sessions-inactive" in failures
    assert "cleanup-delete-observed" in failures
    assert "cleanup-claim-consistent" in failures
    assert "visual-current-screenshot-before-coordinate" not in failures
    assert "visual-observed-result" not in failures
    assert "visual-task-result" not in failures


@pytest.mark.parametrize("image_field", ["content", "contents", "binaryResultsForLlm"])
def test_normalizer_counts_only_actual_image_blocks_without_payload(image_field: str) -> None:
    first_raw = skill_behavior._visual_screenshot_png(False)
    second_raw = _reencode_png(first_raw)
    assert first_raw != second_raw
    assert hashlib.sha256(first_raw).hexdigest() != hashlib.sha256(second_raw).hexdigest()
    assert _pixels(first_raw) == _pixels(second_raw)
    first = base64.b64encode(first_raw).decode()
    second = base64.b64encode(second_raw).decode()
    events: list[dict[str, Any]] = [
        {
            "type": "tool.execution_start",
            "timestamp": _iso(1),
            "data": {
                "toolCallId": "call-1",
                "toolName": "mcp__amkernel__python_exec",
                "mcpServerName": "amkernel",
                "mcpConfigSource": "workspace",
                "mcpToolName": "python_exec",
                "arguments": {"code": "display(image)"},
            },
        },
        {
            "type": "tool.execution_complete",
            "timestamp": _iso(2),
            "data": {
                "toolCallId": "call-1",
                "success": True,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({"status": "completed", "kernelState": "alive"}),
                        },
                        {"type": "image", "data": first, "mimeType": "image/png"},
                        {"mimeType": "image/png", "data": second},
                        {
                            "type": "resource_link",
                            "uri": "artifact://image",
                            "name": "image",
                            "mimeType": "image/png",
                        },
                    ]
                },
            },
        },
    ]
    if image_field != "content":
        result = events[1]["data"]["result"]
        blocks = result.pop("content")
        result["content"] = json.dumps({"status": "completed", "kernelState": "alive"})
        result[image_field] = blocks
        if image_field == "binaryResultsForLlm":
            result["contents"] = blocks
    calls, _, _ = skill_behavior.normalize_copilot_events(events)
    assert calls[0]["imageCount"] == 2
    assert calls[0]["imageSha256"] == sorted(
        {
            hashlib.sha256(first_raw).hexdigest(),
            hashlib.sha256(second_raw).hexdigest(),
        }
    )
    assert calls[0]["imagePixels"] == [_pixels(first_raw)]
    serialized = json.dumps(calls)
    assert first not in serialized
    assert second not in serialized


@pytest.mark.parametrize("delivered", [[], None, "not-an-image-block-list"])
def test_normalizer_rejects_source_images_not_delivered_to_model(delivered: object) -> None:
    raw = skill_behavior._visual_screenshot_png(False)
    result = {
        "content": "Image available as an artifact",
        "contents": [
            {
                "type": "image",
                "data": base64.b64encode(raw).decode(),
                "mimeType": "image/png",
            }
        ],
        "binaryResultsForLlm": delivered,
        "structuredContent": {"displays": [{"inline": True, "mimeType": "image/png"}]},
    }
    assert skill_behavior._image_block_evidence(result) == (0, [], [])
