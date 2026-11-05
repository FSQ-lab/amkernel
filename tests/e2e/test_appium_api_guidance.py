"""Execute public Client guidance against a synthetic endpoint, never a device.

The optional automation Client belongs to the experiment environment, not core.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from tests.e2e.skill_behavior import FixtureConfig, SyntheticAppium

REFERENCE = Path(__file__).parents[2] / "src/amkernel/skill/references/amkernel-appium.md"


@pytest.fixture
def native_session() -> Any:
    webdriver = pytest.importorskip("appium.webdriver")
    options_module = pytest.importorskip("appium.options.android")
    fixture = SyntheticAppium(FixtureConfig("android"))
    fixture.start()
    driver = webdriver.Remote(fixture.endpoint, options=options_module.UiAutomator2Options())
    try:
        yield driver, fixture
    finally:
        driver.quit()
        fixture.stop()


def _examples() -> list[str]:
    return re.findall(r"```python\n(.*?)```", REFERENCE.read_text(), re.DOTALL)


def test_native_locator_and_state_examples_execute(native_session: Any) -> None:
    driver, fixture = native_session
    namespace = {
        "driver": driver,
        "accessibility_id": "Toggle",
        "uiautomator_selector": 'new UiSelector().text("Toggle")',
    }
    examples = _examples()
    exec(examples[1], namespace)
    exec(examples[2], namespace)
    assert namespace["native_state"] == {
        "package": "com.amkernel.fixture",
        "activity": ".MainActivity",
    }
    finds = [item for item in fixture.journal if item["action"] == "find"]
    assert [item["detail"]["using"] for item in finds] == [
        "accessibility id",
        "-android uiautomator",
    ]
    assert fixture.unsupported_scripts == []
    assert fixture.unknown == []


@pytest.mark.parametrize("constant", ["ACCESSIBILITY_ID", "ANDROID_UIAUTOMATOR"])
def test_selenium_locator_patterns_fail_before_remote_action(
    native_session: Any, constant: str
) -> None:
    by = pytest.importorskip("selenium.webdriver.common.by").By
    driver, fixture = native_session
    with pytest.raises(AttributeError):
        exec(f"driver.find_element(By.{constant}, 'Toggle')", {"driver": driver, "By": by})
    assert not any(item["action"] == "find" for item in fixture.journal)


def test_native_title_pattern_is_rejected(native_session: Any) -> None:
    errors = pytest.importorskip("selenium.common.exceptions")
    driver, fixture = native_session
    with pytest.raises(errors.WebDriverException):
        exec("driver.title", {"driver": driver})
    assert fixture.unknown[-1]["path"].endswith("/title")


def test_stale_local_identity_does_not_pass_live_state_example(native_session: Any) -> None:
    errors = pytest.importorskip("selenium.common.exceptions")
    driver, fixture = native_session
    fixture.sessions[driver.session_id]["active"] = False
    assert driver.session_id
    with pytest.raises(errors.InvalidSessionIdException):
        exec(_examples()[2], {"driver": driver})
    # The fixture rejects DELETE for an expired session too; preserve normal teardown.
    fixture.sessions[driver.session_id]["active"] = True


def test_web_example_requires_available_context_before_title() -> None:
    class NativeOnly:
        contexts = ("NATIVE_APP",)

        @property
        def title(self) -> str:
            pytest.fail("Web API reached without a Web context")

    with pytest.raises(RuntimeError, match="not available"):
        exec(_examples()[3], {"driver": NativeOnly(), "web_context": "WEBVIEW_fixture"})


@pytest.mark.parametrize("web_context", ["WEBVIEW_fixture", "CHROMIUM"])
def test_web_example_selects_observed_context_before_title(web_context: str) -> None:
    class WebFixture:
        def __init__(self) -> None:
            self.contexts = ("NATIVE_APP", web_context)
            self.current_context = "NATIVE_APP"
            self.switch_to = self

        def context(self, selected: str) -> None:
            assert selected in self.contexts
            self.current_context = selected

        @property
        def title(self) -> str:
            assert self.current_context == web_context
            return "Fixture page"

    namespace = {"driver": WebFixture(), "web_context": web_context}
    exec(_examples()[3], namespace)
    assert namespace["web_title"] == "Fixture page"
