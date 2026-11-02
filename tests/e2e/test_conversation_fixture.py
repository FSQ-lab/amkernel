"""Protocol-edge regression tests for the synthetic conversation fixture.

These tests exercise only the local loopback W3C endpoints.  They do not run a
native client, a platform driver, or any real messaging service.
"""

from __future__ import annotations

import json
import sys
import unittest
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.e2e.conversation_fixture import ConversationAppium
from tests.e2e.skill_behavior import FixtureConfig

_ELEMENT_KEY = "element-6066-11e4-a52e-4f735466cecf"


class ConversationFixtureTests(unittest.TestCase):
    def _fixture(self, variant: str) -> ConversationAppium:
        fixture = ConversationAppium(FixtureConfig(variant))
        fixture.start()
        self.addCleanup(fixture.stop)
        return fixture

    @staticmethod
    def _call(
        fixture: ConversationAppium,
        method: str,
        path: str,
        body: object | None = None,
    ) -> tuple[int, Any]:
        data = None
        headers = {"Content-Type": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            fixture.endpoint + path, data=data, method=method, headers=headers
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def _session(self, fixture: ConversationAppium) -> str:
        status, payload = self._call(
            fixture,
            "POST",
            "/session",
            {
                "capabilities": {
                    "alwaysMatch": {
                        "platformName": "Android",
                        "appium:automationName": "UiAutomator2",
                    }
                }
            },
        )
        self.assertEqual(status, 200, payload)
        session_id = payload["value"]["sessionId"]
        assert isinstance(session_id, str)
        return session_id

    def _find(self, fixture: ConversationAppium, session: str, locator: str) -> str:
        status, payload = self._call(
            fixture,
            "POST",
            f"/session/{session}/element",
            {"using": "accessibility id", "value": locator},
        )
        self.assertEqual(status, 200, payload)
        element_id = payload["value"][_ELEMENT_KEY]
        assert isinstance(element_id, str)
        return element_id

    def _attribute(
        self, fixture: ConversationAppium, session: str, element: str, name: str
    ) -> Any:
        status, payload = self._call(
            fixture,
            "GET",
            f"/session/{session}/element/{element}/attribute/{name}",
        )
        self.assertEqual(status, 200, payload)
        return payload["value"]

    def _search(self, fixture: ConversationAppium, session: str) -> None:
        search = self._find(fixture, session, "conversation-search")
        status, payload = self._call(
            fixture,
            "POST",
            f"/session/{session}/element/{search}/value",
            {"text": "team"},
        )
        self.assertEqual(status, 200, payload)

    def test_search_truthful_ordering_and_identity_open(self) -> None:
        fixture = self._fixture("conversation-latest")
        session = self._session(fixture)
        initial = fixture.snapshot()["conversation"]
        self.assertEqual(initial["screen"], "search")
        self.assertEqual(initial["candidates"], [])
        self._search(fixture, session)
        conversation = fixture.snapshot()["conversation"]
        candidates = conversation["candidates"]
        self.assertEqual(len(candidates), 4)
        latest_id = conversation["latestConversationId"]
        latest = next(item for item in candidates if item["candidateId"] == latest_id)
        self.assertNotIn(latest["rowIndex"], {0, 2})
        self.assertNotEqual(latest["threadActivityAt"], latest["newestMessageAt"])
        for item in candidates:
            self.assertGreaterEqual(
                item["threadActivityAt"], item["newestMessageAt"]
            )
        self.assertEqual(conversation["uncertainReason"], None)
        row = self._find(
            fixture, session, f"conversation-row:{latest['candidateId']}"
        )
        self.assertEqual(
            self._attribute(fixture, session, row, "data-thread-id"), latest_id
        )
        self.assertIsNotNone(
            self._attribute(fixture, session, row, "data-activity-epoch-ms")
        )
        status, payload = self._call(
            fixture, "POST", f"/session/{session}/element/{row}/click"
        )
        self.assertEqual(status, 200, payload)
        opened = fixture.snapshot()["conversation"]["opened"]
        self.assertEqual(opened["candidateId"], latest_id)
        status, source = self._call(fixture, "GET", f"/session/{session}/source")
        self.assertEqual(status, 200)
        self.assertIn("conversation-title", source["value"])
        self.assertIn(latest["title"], source["value"])
        participants = self._find(
            fixture, session, "conversation-participants"
        )
        self.assertEqual(
            self._attribute(fixture, session, participants, "data-participants"),
            ", ".join(latest["participants"]),
        )
        message = self._find(fixture, session, "conversation-message-0")
        timestamp = self._attribute(fixture, session, message, "data-timestamp-iso")
        message_time = datetime.fromisoformat(timestamp)
        self.assertIsNotNone(message_time.tzinfo)
        self.assertLessEqual(
            message_time.timestamp(), latest["threadActivityAt"]
        )

    def test_refresh_invalidates_old_handles_and_reorders(self) -> None:
        fixture = self._fixture("conversation-latest")
        session = self._session(fixture)
        self._search(fixture, session)
        before = fixture.snapshot()["conversation"]
        latest_id = before["latestConversationId"]
        old_row = self._find(fixture, session, f"conversation-row:{latest_id}")
        refresh = self._find(fixture, session, "conversation-refresh")
        status, payload = self._call(
            fixture, "POST", f"/session/{session}/element/{refresh}/click"
        )
        self.assertEqual(status, 200, payload)
        after = fixture.snapshot()["conversation"]
        self.assertEqual(after["generation"], before["generation"] + 1)
        self.assertNotEqual(
            [item["candidateId"] for item in before["candidates"]],
            [item["candidateId"] for item in after["candidates"]],
        )
        status, payload = self._call(
            fixture, "POST", f"/session/{session}/element/{old_row}/click"
        )
        self.assertEqual(status, 404, payload)
        self.assertEqual(payload["value"]["error"], "stale element reference")
        new_row = self._find(fixture, session, f"conversation-row:{latest_id}")
        self.assertNotEqual(new_row, old_row)
        status, payload = self._call(
            fixture, "POST", f"/session/{session}/element/{new_row}/click"
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(
            fixture.snapshot()["conversation"]["opened"]["candidateId"], latest_id
        )

    def test_uncertain_variant_exposes_coarse_activity_only(self) -> None:
        fixture = self._fixture("conversation-uncertain")
        session = self._session(fixture)
        self._search(fixture, session)
        conversation = fixture.snapshot()["conversation"]
        self.assertEqual(conversation["uncertainReason"], "coarse-timestamps")
        self.assertTrue(conversation["searchComplete"])
        candidates = conversation["candidates"]
        self.assertEqual(len(candidates), 4)
        coarse = [
            item
            for item in candidates
            if item["threadActivity"] == candidates[0]["threadActivity"]
        ]
        self.assertGreaterEqual(len(coarse), 2)
        target = next(
            item
            for item in candidates
            if item["candidateId"] == conversation["latestConversationId"]
        )
        row = self._find(
            fixture, session, f"conversation-row:{target['candidateId']}"
        )
        self.assertIsNone(
            self._attribute(fixture, session, row, "data-activity-epoch-ms")
        )
        self.assertEqual(conversation["opened"], None)

    def test_execute_and_non_scroll_actions_fail_explicitly(self) -> None:
        fixture = self._fixture("conversation-latest")
        session = self._session(fixture)
        status, payload = self._call(
            fixture,
            "POST",
            f"/session/{session}/execute/sync",
            {"script": "amkernel:state", "args": []},
        )
        self.assertEqual(status, 501, payload)
        self.assertEqual(payload["value"]["error"], "unsupported operation")
        status, payload = self._call(
            fixture,
            "POST",
            f"/session/{session}/actions",
            {"actions": [{"type": "pointer", "id": "finger", "actions": []}]},
        )
        self.assertEqual(status, 501, payload)

    def test_malformed_send_keys_does_not_succeed(self) -> None:
        fixture = self._fixture("conversation-latest")
        session = self._session(fixture)
        search = self._find(fixture, session, "conversation-search")
        status, payload = self._call(
            fixture,
            "POST",
            f"/session/{session}/element/{search}/value",
            {"value": []},
        )
        self.assertEqual(status, 400, payload)
        self.assertEqual(fixture.snapshot()["conversation"]["candidates"], [])

    def test_empty_search_is_not_a_silent_listing(self) -> None:
        fixture = self._fixture("conversation-latest")
        session = self._session(fixture)
        search = self._find(fixture, session, "conversation-search")
        status, payload = self._call(
            fixture,
            "POST",
            f"/session/{session}/element/{search}/value",
            {"text": "   "},
        )
        self.assertEqual(status, 400, payload)
        self.assertEqual(fixture.snapshot()["conversation"]["candidates"], [])

    def test_context_and_missing_attributes_do_not_expose_open_identity(self) -> None:
        fixture = self._fixture("conversation-latest")
        session = self._session(fixture)
        self._search(fixture, session)
        latest_id = fixture.snapshot()["conversation"]["latestConversationId"]
        row = self._find(fixture, session, f"conversation-row:{latest_id}")
        status, _ = self._call(
            fixture, "POST", f"/session/{session}/element/{row}/click"
        )
        self.assertEqual(status, 200)
        context = self._find(fixture, session, "conversation-context")
        self.assertIsNotNone(self._attribute(fixture, session, context, "data-timezone"))
        self.assertIsNone(self._attribute(fixture, session, context, "missing"))
        title = self._find(fixture, session, "conversation-title")
        self.assertIsNone(self._attribute(fixture, session, title, "missing"))
        self.assertFalse(any(
            item["action"] == "verify-open"
            for item in fixture.snapshot()["conversation"]["actions"]
        ))
        status, source = self._call(fixture, "GET", f"/session/{session}/source")
        self.assertEqual(status, 200)
        import xml.etree.ElementTree as ET
        root = ET.fromstring(source["value"])
        opened_title = root.find(".//*[@name='conversation-title']")
        self.assertIsNotNone(opened_title)
        verified = [
            item for item in fixture.snapshot()["conversation"]["actions"]
            if item["action"] == "verify-open"
        ]
        self.assertEqual(verified[-1]["detail"]["candidateId"], latest_id)


if __name__ == "__main__":
    unittest.main()
