"""Synthetic, host-isolated conversation app for Agent behavior tests.

This fixture is a deliberately narrow W3C/Appium-shaped HTTP server.  It models a
small messaging app: a search-first conversation list, opaque conversation
identities, a thread-level last-activity time (which may include non-message
events and is never earlier than the newest nested message), relative display
timestamps in a fixed locale/timezone, and a live list whose element handles go
stale when it refreshes or scrolls.

Nothing here talks to Gmail, a platform driver, or a real device.  Message
bodies, credentials, addresses, and full mail content are never modeled.  The
only observation surface for tests is the WebDriver response plus this module's
own request-driven journal, never the Agent's prose.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import quoteattr

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.e2e.skill_behavior import MAX_JOURNAL, FixtureConfig, SyntheticAppium, _safe_text

LOCALE = "en-US"
TIMEZONE = "America/Los_Angeles"
REFERENCE_CLOCK = "2026-11-03T00:20:00-08:00"
REFERENCE_EPOCH_MS = int(datetime.fromisoformat(REFERENCE_CLOCK).timestamp() * 1000)
ACTIVITY_SEMANTICS = "thread-last-activity-including-non-message-events"
MESSAGE_ACTIVITY_SEMANTICS = "newest-nested-message"

_VARIANTS = frozenset({"conversation-latest", "conversation-uncertain"})
_VARIANT_ALIASES = {"latest": "conversation-latest", "uncertain": "conversation-uncertain"}

_ELEMENT_KEY = "element-6066-11e4-a52e-4f735466cecf"
_ACTIVITY_PRECISION = {
    "conversation-latest": "second",
    "conversation-uncertain": "minute",
}


@dataclass(frozen=True, slots=True)
class _Message:
    id: str
    sender: str
    at: datetime


@dataclass(frozen=True, slots=True)
class _Thread:
    id: str
    title: str
    participants: tuple[str, ...]
    activity: datetime
    messages: tuple[_Message, ...]

    @property
    def newest(self) -> _Message:
        return self.messages[-1]


def _at(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def _display(moment: datetime, reference: datetime) -> str:
    """A fixed en-US relative label; relative-day boundaries use the reference date."""
    days = (moment.date() - reference.date()).days
    clock = moment.strftime("%I:%M %p").lstrip("0")
    if days == 0:
        return f"Today {clock}"
    if days == -1:
        return f"Yesterday {clock}"
    return f"{moment.strftime('%b')} {moment.day} {clock}"


def _threads(variant: str) -> tuple[_Thread, ...]:
    uncertain = variant == "conversation-uncertain"
    design = _Thread(
        id="conv-7f3a",
        title="Design team",
        participants=("Maya Chen", "Owen Brooks"),
        activity=_at("2026-11-03T00:05:10-08:00" if uncertain else "2026-11-03T00:00:00-08:00"),
        messages=(
            _Message("msg-design-1", "Maya Chen", _at("2026-11-02T23:00:00-08:00")),
            _Message("msg-design-2", "Owen Brooks", _at("2026-11-02T23:30:00-08:00")),
            _Message("msg-design-3", "Maya Chen", _at("2026-11-02T23:59:00-08:00")),
        ),
    )
    platform = _Thread(
        id="conv-19c2",
        title="Platform team",
        participants=("Riley Park", "Sam Ortega"),
        activity=_at("2026-11-02T23:55:00-08:00"),
        messages=(
            _Message("msg-platform-1", "Riley Park", _at("2026-11-02T23:10:00-08:00")),
            _Message("msg-platform-2", "Sam Ortega", _at("2026-11-02T23:30:00-08:00")),
            _Message("msg-platform-3", "Riley Park", _at("2026-11-02T23:50:00-08:00")),
        ),
    )
    research = _Thread(
        id="conv-52d8",
        title="Research team",
        participants=("Avery Lin", "Jordan Bell"),
        activity=_at("2026-11-03T00:05:40-08:00" if uncertain else "2026-11-03T00:05:00-08:00"),
        messages=(
            _Message("msg-research-1", "Avery Lin", _at("2026-11-02T22:15:00-08:00")),
            _Message("msg-research-2", "Jordan Bell", _at("2026-11-02T23:20:00-08:00")),
            _Message("msg-research-3", "Avery Lin", _at("2026-11-02T23:55:00-08:00")),
        ),
    )
    launch = _Thread(
        id="conv-a04b",
        title="Launch team",
        participants=("Casey Quinn", "Dana Whitfield"),
        activity=_at("2026-11-01T12:00:00-08:00"),
        messages=(
            _Message("msg-launch-1", "Casey Quinn", _at("2026-11-01T11:00:00-08:00")),
            _Message("msg-launch-2", "Dana Whitfield", _at("2026-11-01T11:30:00-08:00")),
            _Message("msg-launch-3", "Casey Quinn", _at("2026-11-01T12:00:00-08:00")),
        ),
    )
    return (design, platform, research, launch)


def _bounded_detail(value: object) -> object:
    if isinstance(value, str):
        return value[:240]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, (list, tuple)):
        return [_bounded_detail(item) for item in list(value)[:12]]
    if isinstance(value, Mapping):
        return {str(key)[:80]: _bounded_detail(item) for key, item in list(value.items())[:24]}
    return str(value)[:240]


def _error(status: int, error: str, message: str = "") -> tuple[int, dict[str, object]]:
    value: dict[str, object] = {"error": error}
    if message:
        value.update({"message": message, "stacktrace": ""})
    return status, {"value": value}


def _contains_scroll(payload: object) -> bool:
    if not isinstance(payload, Mapping):
        return False
    sequences = payload.get("actions")
    if not isinstance(sequences, list):
        return False
    for sequence in sequences:
        if not isinstance(sequence, Mapping):
            continue
        actions = sequence.get("actions")
        if not isinstance(actions, list):
            continue
        pointer_down = False
        pointer_move = False
        for action in actions:
            if not isinstance(action, Mapping):
                continue
            if action.get("type") == "scroll":
                return True
            try:
                delta = int(action.get("deltaY") or 0)
            except (TypeError, ValueError):
                delta = 0
            if delta:
                return True
            if action.get("type") == "pointerDown":
                pointer_down = True
            elif action.get("type") == "pointerMove":
                pointer_move = True
        if pointer_down and pointer_move:
            return True
    return False


def _attributes(mapping: Mapping[str, object]) -> str:
    return " ".join(
        f"{key}={quoteattr(str(value))}" for key, value in mapping.items() if value is not None
    )


class ConversationAppium(SyntheticAppium):
    """A narrow synthetic conversation app added to the base fixture journal."""

    LOCALE = LOCALE
    TIMEZONE = TIMEZONE
    REFERENCE_CLOCK = REFERENCE_CLOCK
    REFERENCE_EPOCH_MS = REFERENCE_EPOCH_MS

    def __init__(
        self,
        config: FixtureConfig,
        *,
        kill_runner: Any = None,
    ) -> None:
        variant = _VARIANT_ALIASES.get(str(config.variant), str(config.variant))
        if variant not in _VARIANTS:
            raise ValueError(
                "conversation fixture variant must be conversation-latest or conversation-uncertain"
            )
        super().__init__(config, kill_runner=kill_runner)
        self.variant = variant
        self.reference = datetime.fromisoformat(REFERENCE_CLOCK)
        self.threads = _threads(variant)
        for thread in self.threads:
            if thread.activity < thread.newest.at:
                raise ValueError(
                    "conversation fixture thread activity must not precede its "
                    "newest nested message"
                )
        self.threads_by_id = {thread.id: thread for thread in self.threads}
        self.screen = "search"
        self.query = ""
        self.generation = 0
        self.candidates: list[str] = []
        self.matched_ids: list[str] = []
        self.has_more = False
        self.search_complete = False
        self.search_count = 0
        self.refresh_count = 0
        self.scroll_count = 0
        self.opened: dict[str, Any] | None = None
        self.open_attempts = 0
        self.find_count = 0
        self.stale_click_rejections = 0
        self.invalid_clicks = 0
        self.actions: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Conversation state and journal helpers

    def _log(self, action: str, status: int, detail: Mapping[str, object]) -> None:
        entry = {
            "action": action,
            "at": time.time(),
            "status": int(status),
            "detail": _bounded_detail(dict(detail)),
        }
        with self.lock:
            if len(self.actions) < MAX_JOURNAL:
                self.actions.append(entry)

    def _detail_join(self, values: list[str]) -> str:
        return ",".join(values)

    def _thread(self, thread_id: str | None) -> _Thread | None:
        if thread_id is None:
            return None
        return self.threads_by_id.get(thread_id)

    def _activity_iso(self, thread: _Thread) -> str:
        if self.variant == "conversation-uncertain":
            return thread.activity.replace(second=0, microsecond=0).isoformat(timespec="seconds")
        return _iso(thread.activity)

    def _activity_display(self, thread: _Thread) -> str:
        return _display(thread.activity, self.reference)

    def _newest_display(self, thread: _Thread) -> str:
        return _display(thread.newest.at, self.reference)

    def _thread_attributes(self, thread: _Thread) -> dict[str, object]:
        attributes: dict[str, object] = {
            "data-thread-id": thread.id,
            "data-title": thread.title,
            "data-participants": ", ".join(thread.participants),
            "data-activity-iso": self._activity_iso(thread),
            "data-activity-display": self._activity_display(thread),
            "data-activity-precision": _ACTIVITY_PRECISION[self.variant],
            "data-activity-semantics": ACTIVITY_SEMANTICS,
            "data-message-activity-semantics": MESSAGE_ACTIVITY_SEMANTICS,
            "data-last-message-iso": _iso(thread.newest.at),
            "data-last-message-display": self._newest_display(thread),
            "data-generation": str(self.generation),
        }
        if self.variant == "conversation-latest":
            attributes["data-activity-epoch-ms"] = str(round(thread.activity.timestamp() * 1000))
        return attributes

    def _latest_thread(self) -> _Thread:
        return max(self.threads, key=lambda thread: thread.activity)

    def _context_attributes(self) -> dict[str, object]:
        return {
            "data-locale": LOCALE,
            "data-timezone": TIMEZONE,
            "data-reference-clock-iso": REFERENCE_CLOCK,
            "data-reference-epoch-ms": str(REFERENCE_EPOCH_MS),
            "data-screen": self.screen,
            "data-generation": str(self.generation),
            "data-query": self.query,
            "data-matched-count": str(len(self.matched_ids)),
            "data-returned-count": str(len(self.candidates)),
            "data-has-more": "true" if self.has_more else "false",
            "data-result-complete": "true" if self.search_complete else "false",
            "data-activity-precision": _ACTIVITY_PRECISION[self.variant],
            "data-activity-semantics": ACTIVITY_SEMANTICS,
            "data-message-activity-semantics": MESSAGE_ACTIVITY_SEMANTICS,
        }

    def _invalidate_elements(self) -> None:
        with self.lock:
            for element in self.elements.values():
                element["stale"] = True

    def _mark_stale(self, element_id: str) -> None:
        with self.lock:
            element = self.elements.get(element_id)
            if element is not None:
                element["stale"] = True

    def _search_matches(self, thread: _Thread, query: str) -> bool:
        if not query:
            return True
        needle = query.casefold()
        # Synthetic app search metadata: every conversation is also discoverable
        # by the app's generic conversation keywords. These are not target hints.
        haystack = (
            thread.title,
            *thread.participants,
            "conversation",
            "conversations",
            "messages",
            "chat",
            "inbox",
            "team",
        )
        return any(needle in value.casefold() for value in haystack)

    def _ordered_matches(self, query: str) -> list[_Thread]:
        matches = [thread for thread in self.threads if self._search_matches(thread, query)]
        return sorted(matches, key=lambda thread: thread.newest.at, reverse=True)

    # ------------------------------------------------------------------
    # W3C element lookup

    def _resolve_target(self, value: str) -> tuple[str, str | None, int | None] | None:
        if value == "conversation-search" and self.screen in {"search", "results"}:
            return "search", None, None
        if value == "conversation-refresh" and self.screen == "results":
            return "refresh", None, None
        if value == "conversation-back" and self.screen == "conversation":
            return "back", None, None
        if value == "conversation-context":
            return "context", None, None
        if value == "conversation-title" and self.screen == "conversation" and self.opened:
            return "title", str(self.opened["candidateId"]), None
        if value == "conversation-participants" and self.screen == "conversation" and self.opened:
            return "participants", str(self.opened["candidateId"]), None
        if value.startswith("conversation-row:"):
            thread_id = value.split(":", 1)[1]
            if self.screen == "results" and thread_id in self.candidates:
                return "row", thread_id, None
            return None
        if value.startswith("conversation-message-") and self.opened:
            suffix = value[len("conversation-message-") :]
            try:
                index = int(suffix)
            except ValueError:
                return None
            thread = self._thread(str(self.opened["candidateId"]))
            if thread is not None and 0 <= index < len(thread.messages):
                return "message", thread.id, index
        return None

    def _attempted_target(self, value: str) -> tuple[str | None, str | None]:
        if value.startswith("conversation-row:"):
            return "conversation", value.split(":", 1)[1]
        if value.startswith("conversation-message-"):
            candidate = self.opened.get("candidateId") if self.opened else None
            return "message", candidate
        if value == "conversation-search":
            return "search-input", None
        if value == "conversation-title" and self.opened:
            return "conversation", str(self.opened["candidateId"])
        if value == "conversation-participants" and self.opened:
            return "conversation", str(self.opened["candidateId"])
        return None, None

    def _target_kind(self, kind: str) -> str:
        if kind == "row":
            return "conversation"
        if kind == "title":
            return "conversation"
        if kind == "participants":
            return "conversation"
        if kind == "message":
            return "message"
        if kind == "search":
            return "search-input"
        return "conversation"

    def _element_name(self, kind: str, thread_id: str | None, message_index: int | None) -> str:
        if kind == "row":
            return f"conversation-row:{thread_id}"
        if kind == "title":
            return "conversation-title"
        if kind == "participants":
            return "conversation-participants"
        if kind == "message":
            return f"conversation-message-{message_index}"
        if kind == "search":
            return "conversation-search"
        if kind == "refresh":
            return "conversation-refresh"
        if kind == "back":
            return "conversation-back"
        return "conversation-context"

    def _element_label(self, kind: str, thread_id: str | None, message_index: int | None) -> str:
        thread = self._thread(thread_id)
        if kind in {"row", "title"} and thread is not None:
            return thread.title
        if kind == "participants" and thread is not None:
            return "Participants: " + ", ".join(thread.participants)
        if kind == "message" and thread is not None and message_index is not None:
            message = thread.messages[message_index]
            return f"{message.sender} {_display(message.at, self.reference)}"
        if kind == "search":
            return "Search conversations"
        if kind == "refresh":
            return "Refresh conversations"
        if kind == "back":
            return "Back"
        return "Conversation context"

    def _find(self, session_id: str, payload: object) -> tuple[int, dict[str, object]]:
        path = f"/session/{session_id}/element"
        session = self._session(session_id, "find", "POST", path)
        if session is None:
            self._log(
                "find",
                404,
                {
                    "elementId": None,
                    "generation": self.generation,
                    "targetKind": None,
                    "candidateId": None,
                    "error": "invalid session id",
                },
            )
            return _error(404, "invalid session id", "expired")
        using = ""
        value = ""
        if isinstance(payload, Mapping):
            using = _safe_text(payload.get("using", ""), 80)
            value = _safe_text(payload.get("value", ""), 240)
        if using not in {"accessibility id", "id"}:
            self._record(
                "find",
                "POST",
                path,
                400,
                detail={
                    "using": using,
                    "value": value,
                    "error": "invalid selector",
                    "sessionId": session_id,
                },
            )
            self._log(
                "find",
                400,
                {
                    "using": using,
                    "value": value,
                    "elementId": None,
                    "generation": self.generation,
                    "targetKind": None,
                    "candidateId": None,
                    "error": "invalid selector",
                },
            )
            return _error(
                400,
                "invalid selector",
                "synthetic conversation fixture accepts only accessibility id locators",
            )
        resolved = self._resolve_target(value)
        if resolved is None:
            target_kind, candidate_id = self._attempted_target(value)
            self._record(
                "find",
                "POST",
                path,
                404,
                detail={
                    "using": using,
                    "value": value,
                    "error": "no such element",
                    "sessionId": session_id,
                },
            )
            self._log(
                "find",
                404,
                {
                    "using": using,
                    "value": value,
                    "elementId": None,
                    "generation": self.generation,
                    "targetKind": target_kind,
                    "candidateId": candidate_id,
                    "error": "no such element",
                },
            )
            return _error(404, "no such element", "synthetic element is not visible")
        kind, thread_id, message_index = resolved
        with self.lock:
            self.find_count += 1
            self.element_counter += 1
            element_id = f"conversation-element-{self.element_counter}"
            label = self._element_label(kind, thread_id, message_index)
            self.elements[element_id] = {
                "id": element_id,
                "sessionId": session_id,
                "kind": kind,
                "threadId": thread_id,
                "messageIndex": message_index,
                "generation": self.generation,
                "label": label,
                "stale": False,
                "clicked": False,
                "enabled": kind in {"search", "refresh", "back", "row"},
            }
        target_kind = self._target_kind(kind)
        self._record(
            "find",
            "POST",
            path,
            200,
            detail={
                "using": using,
                "value": value,
                "elementId": element_id,
                "targetKind": target_kind,
                "threadId": thread_id,
                "generation": self.generation,
                "sessionId": session_id,
            },
        )
        if kind in {"row", "title", "participants", "message", "search"}:
            thread = self._thread(thread_id)
            self._log(
                "find",
                200,
                {
                    "using": using,
                    "value": value,
                    "elementId": element_id,
                    "generation": self.generation,
                    "targetKind": target_kind,
                    "candidateId": thread_id,
                    "threadId": thread_id,
                    "title": thread.title if thread else None,
                },
            )
        return 200, {"value": {_ELEMENT_KEY: element_id}}

    # ------------------------------------------------------------------
    # W3C element reads and writes

    def _element_attributes(self, element: Mapping[str, Any]) -> dict[str, object]:
        kind = str(element.get("kind", ""))
        thread = self._thread(element.get("threadId"))
        if kind == "context":
            return self._context_attributes()
        if kind == "search":
            return {
                "data-search-role": "conversation-search",
                "data-query": self.query,
                "data-generation": str(self.generation),
            }
        if kind == "refresh":
            return {"data-action": "refresh", "data-generation": str(self.generation)}
        if kind == "back":
            return {"data-action": "back"}
        if kind in {"row", "title"} and thread is not None:
            return self._thread_attributes(thread)
        if kind == "participants" and thread is not None:
            return {
                "data-participants": ", ".join(thread.participants),
                "data-thread-id": thread.id,
                "data-generation": str(self.generation),
            }
        if kind == "message" and thread is not None:
            index = int(element.get("messageIndex") or 0)
            message = thread.messages[index]
            return {
                "data-message-id": message.id,
                "data-sender": message.sender,
                "data-timestamp-iso": _iso(message.at),
                "data-timestamp-display": _display(message.at, self.reference),
                "data-generation": str(self.generation),
            }
        return {}

    def _element_read(
        self, session_id: str, element_id: str, *, attribute: str | None = None
    ) -> tuple[int, dict[str, object]]:
        action = "text" if attribute is None else "attribute"
        suffix = "text" if attribute is None else f"attribute/{attribute}"
        path = f"/session/{session_id}/element/{element_id}/{suffix}"
        session = self._session(session_id, action, "GET", path)
        if session is None:
            return _error(404, "invalid session id", "expired")
        with self.lock:
            element = self.elements.get(element_id)
            copied = dict(element) if isinstance(element, Mapping) else None
        if copied is None or copied.get("sessionId") != session_id:
            self._record(
                action,
                "GET",
                path,
                404,
                detail={"elementId": element_id, "error": "no such element"},
            )
            return _error(404, "no such element", "unknown synthetic element")
        kind = str(copied.get("kind", ""))
        thread_id = copied.get("threadId")
        invalid_state = False
        if copied.get("stale"):
            invalid_state = True
        elif kind == "row":
            invalid_state = (
                self.screen != "results"
                or copied.get("generation") != self.generation
                or thread_id not in self.candidates
            )
        elif kind == "participants":
            invalid_state = (
                self.screen != "conversation"
                or self.opened is None
                or self.opened.get("candidateId") != thread_id
            )
        elif kind == "title":
            invalid_state = (
                self.screen != "conversation"
                or self.opened is None
                or self.opened.get("candidateId") != thread_id
            )
        elif kind == "message":
            invalid_state = (
                self.screen != "conversation"
                or self.opened is None
                or self.opened.get("candidateId") != thread_id
            )
        elif kind == "search":
            invalid_state = self.screen == "conversation"
        elif kind == "refresh":
            invalid_state = self.screen != "results"
        elif kind == "back":
            invalid_state = self.screen != "conversation"
        if invalid_state:
            self._mark_stale(element_id)
            self._record(
                action,
                "GET",
                path,
                404,
                detail={
                    "elementId": element_id,
                    "kind": kind,
                    "error": "stale element reference",
                },
            )
            return _error(
                404,
                "stale element reference",
                "synthetic element belongs to an earlier list or view",
            )
        attributes = self._element_attributes(copied)
        if attribute is None:
            value: object = copied.get("label")
        elif attribute == "name":
            value = self._element_name(kind, thread_id, copied.get("messageIndex"))
        elif attribute in {"label", "text", "content-desc"}:
            value = copied.get("label")
        elif attribute == "value" and kind == "search":
            value = self.query
        else:
            value = attributes.get(attribute)
        target_kind = (
            "row"
            if kind == "row"
            else "title"
            if kind == "title"
            else "conversation"
            if kind == "participants"
            else "message"
            if kind == "message"
            else "search-input"
            if kind == "search"
            else "context"
            if kind == "context"
            else "control"
        )
        self._record(
            action,
            "GET",
            path,
            200,
            detail={
                "elementId": element_id,
                "attribute": attribute or "text",
                "value": value,
                "targetKind": target_kind,
                "threadId": thread_id,
                "generation": self.generation,
            },
        )
        self._log(
            "attribute",
            200,
            {
                "elementId": element_id,
                "attribute": attribute or "text",
                "value": "" if value is None else str(value),
                "targetKind": target_kind,
                "threadId": thread_id,
                "candidateId": thread_id,
                "generation": self.generation,
            },
        )
        self._log_observe(copied, attribute, value)
        return 200, {"value": value}

    def _log_observe(
        self, element: Mapping[str, Any], attribute: str | None, value: object
    ) -> None:
        if value is None:
            return
        kind = str(element.get("kind", ""))
        thread_id = element.get("threadId")
        candidate = str(thread_id) if thread_id else None
        observe_kind: str | None = None
        if kind == "row":
            if attribute in {"data-last-message-iso", "data-last-message-display"}:
                observe_kind = "message-activity"
            elif attribute == "data-activity-precision":
                observe_kind = "activity-precision"
            elif attribute in {
                "data-activity-iso",
                "data-activity-display",
                "data-activity-epoch-ms",
            }:
                observe_kind = "thread-activity"
            elif attribute in {
                "data-thread-id",
                "data-title",
                "data-participants",
                None,
            }:
                observe_kind = "identity"
        elif kind in {"title", "participants"}:
            if attribute in {"data-last-message-iso", "data-last-message-display"}:
                observe_kind = "message-activity"
            elif attribute == "data-activity-precision":
                observe_kind = "activity-precision"
            elif attribute in {
                "data-activity-iso",
                "data-activity-display",
                "data-activity-epoch-ms",
            }:
                observe_kind = "thread-activity"
            else:
                observe_kind = "identity"
        elif kind == "message":
            observe_kind = "message-activity"
        elif kind == "context":
            if attribute in {
                "data-locale",
                "data-timezone",
                "data-reference-clock-iso",
                "data-reference-epoch-ms",
                "data-generation",
            }:
                observe_kind = "timestamp-context"
        if observe_kind is None:
            return
        self._log(
            "observe",
            200,
            {
                "candidateId": candidate,
                "kind": observe_kind,
                "attribute": attribute,
                "value": "" if value is None else str(value),
            },
        )

    def _log_verify_open(self) -> None:
        if self.screen != "conversation" or self.opened is None:
            return
        self._log(
            "verify-open",
            200,
            {
                "candidateId": self.opened["candidateId"],
                "title": self.opened["title"],
                "participants": list(self.opened["participants"]),
            },
        )

    def _click(self, session_id: str, element_id: str) -> tuple[int, dict[str, object]]:
        path = f"/session/{session_id}/element/{element_id}/click"
        session = self._session(session_id, "click", "POST", path)
        if session is None:
            self._log(
                "open",
                404,
                {
                    "elementId": element_id,
                    "generation": self.generation,
                    "candidateId": None,
                    "error": "invalid session id",
                },
            )
            return _error(404, "invalid session id", "expired")
        with self.lock:
            element = self.elements.get(element_id)
            copied = dict(element) if isinstance(element, Mapping) else None
        if copied is None or copied.get("sessionId") != session_id:
            with self.lock:
                self.invalid_clicks += 1
            self._record(
                "click",
                "POST",
                path,
                404,
                detail={"elementId": element_id, "error": "no such element"},
            )
            self._log(
                "open",
                404,
                {
                    "elementId": element_id,
                    "generation": self.generation,
                    "candidateId": None,
                    "error": "no such element",
                },
            )
            return _error(404, "no such element", "unknown synthetic element")
        kind = str(copied.get("kind", ""))
        thread_id = copied.get("threadId")
        thread = self._thread(thread_id)
        stale = bool(copied.get("stale"))
        if kind == "row":
            stale = stale or (
                self.screen != "results"
                or copied.get("generation") != self.generation
                or thread_id not in self.candidates
            )
        elif kind == "refresh":
            stale = stale or self.screen != "results"
        elif kind == "back":
            stale = stale or self.screen != "conversation"
        elif kind == "search":
            stale = stale or self.screen == "conversation"
        elif kind in {"title", "participants"} or kind == "message":
            stale = stale or self.screen != "conversation"
        if stale:
            self._mark_stale(element_id)
            with self.lock:
                self.stale_click_rejections += 1
                self.open_attempts += 1 if kind == "row" else 0
            action_name = (
                "open" if kind == "row" else kind if kind in {"refresh", "back"} else "click"
            )
            detail: dict[str, object] = {
                "elementId": element_id,
                "targetKind": self._target_kind(kind),
                "threadId": thread_id,
                "candidateId": thread_id,
                "title": thread.title if thread else None,
                "generation": self.generation,
                "error": "stale element reference",
            }
            if action_name == "open" and thread is not None:
                detail["participants"] = list(thread.participants)
            self._record(
                "click",
                "POST",
                path,
                404,
                detail={
                    "elementId": element_id,
                    "label": copied.get("label", ""),
                    "error": "stale element reference",
                },
            )
            self._log(action_name, 404, detail)
            return _error(
                404,
                "stale element reference",
                "synthetic element became stale after a list or view change",
            )
        if kind == "row":
            if thread is None:
                self._log(
                    "open",
                    404,
                    {
                        "elementId": element_id,
                        "generation": self.generation,
                        "candidateId": thread_id,
                        "error": "no such element",
                    },
                )
                return _error(404, "no such element")
            with self.lock:
                self.open_attempts += 1
                self.opened = {
                    "candidateId": thread.id,
                    "title": thread.title,
                    "participants": list(thread.participants),
                    "threadActivity": self._activity_iso(thread),
                    "threadActivityAt": thread.activity.timestamp(),
                    "newestMessage": _iso(thread.newest.at),
                    "newestMessageAt": thread.newest.at.timestamp(),
                    "openedFromGeneration": self.generation,
                    "elementId": element_id,
                    "clickCount": 1,
                }
                copied["clicked"] = True
                self.screen = "conversation"
            self._invalidate_elements()
            detail = {
                "elementId": element_id,
                "generation": self.generation,
                "candidateId": thread.id,
                "title": thread.title,
                "participants": list(thread.participants),
            }
            self._record(
                "click",
                "POST",
                path,
                200,
                detail={
                    "elementId": element_id,
                    "label": thread.title,
                    "threadId": thread.id,
                    "error": "",
                },
            )
            self._log("open", 200, detail)
            return 200, {"value": None}
        if kind == "refresh":
            previous = self.generation
            with self.lock:
                self.refresh_count += 1
                self.generation += 1
                if len(self.candidates) > 1:
                    # Rotate the visible order without leaving the
                    # highest-activity identity in a fixed first/third slot.
                    shift = 2 if len(self.candidates) >= 4 else 1
                    self.candidates = [
                        *self.candidates[-shift:],
                        *self.candidates[:-shift],
                    ]
            self._invalidate_elements()
            detail = {
                "elementId": element_id,
                "generation": self.generation,
                "previousGeneration": previous,
                "candidateIds": list(self.candidates),
                "rowOrder": [
                    f"{index}:{thread_id}" for index, thread_id in enumerate(self.candidates)
                ],
                "reordered": len(self.candidates) > 1,
            }
            self._record(
                "refresh",
                "POST",
                path,
                200,
                detail={
                    "elementId": element_id,
                    "generation": self.generation,
                    "previousGeneration": previous,
                    "candidateIds": self._detail_join(self.candidates),
                },
            )
            self._log("refresh", 200, detail)
            return 200, {"value": None}
        if kind == "back":
            previous = self.generation
            with self.lock:
                self.generation += 1
                self.screen = "results"
                self.opened = None
            self._invalidate_elements()
            detail = {
                "elementId": element_id,
                "generation": self.generation,
                "previousGeneration": previous,
                "candidateIds": list(self.candidates),
            }
            self._record(
                "back",
                "POST",
                path,
                200,
                detail={
                    "elementId": element_id,
                    "generation": self.generation,
                    "candidateIds": self._detail_join(self.candidates),
                },
            )
            self._log("back", 200, detail)
            return 200, {"value": None}
        if kind == "search":
            self._record(
                "click",
                "POST",
                path,
                200,
                detail={"elementId": element_id, "targetKind": "search-input"},
            )
            self._log(
                "click",
                200,
                {
                    "elementId": element_id,
                    "targetKind": "search-input",
                    "generation": self.generation,
                },
            )
            return 200, {"value": None}
        with self.lock:
            self.invalid_clicks += 1
        self._record(
            "click",
            "POST",
            path,
            400,
            detail={"elementId": element_id, "kind": kind, "error": "element not interactable"},
        )
        self._log(
            "click",
            400,
            {
                "elementId": element_id,
                "targetKind": self._target_kind(kind),
                "threadId": thread_id,
                "generation": self.generation,
                "error": "element not interactable",
            },
        )
        return _error(400, "element not interactable", "synthetic element is not actionable")

    def _send_keys(
        self, session_id: str, element_id: str, payload: object, path: str
    ) -> tuple[int, dict[str, object]]:
        session = self._session(session_id, "search", "POST", path)
        if session is None:
            return _error(404, "invalid session id", "expired")
        text = ""
        if not isinstance(payload, Mapping):
            self._record(
                "search",
                "POST",
                path,
                400,
                detail={"elementId": element_id, "error": "invalid argument"},
            )
            self._log(
                "search",
                400,
                {
                    "elementId": element_id,
                    "query": "",
                    "candidateIds": [],
                    "complete": False,
                    "error": "invalid argument",
                    "generation": self.generation,
                },
            )
            return _error(
                400,
                "invalid argument",
                "send-keys payload must be a JSON object",
            )
        if isinstance(payload, Mapping):
            raw_text = payload.get("text")
            raw_value = payload.get("value")
            if isinstance(raw_text, str):
                text = raw_text
            elif (
                isinstance(raw_value, list)
                and raw_value
                and all(isinstance(item, str) for item in raw_value)
            ):
                text = "".join(raw_value)
            else:
                self._record(
                    "search",
                    "POST",
                    path,
                    400,
                    detail={"elementId": element_id, "error": "invalid argument"},
                )
                self._log(
                    "search",
                    400,
                    {
                        "elementId": element_id,
                        "query": "",
                        "candidateIds": [],
                        "complete": False,
                        "error": "invalid argument",
                        "generation": self.generation,
                    },
                )
                return _error(
                    400,
                    "invalid argument",
                    "send-keys payload must contain text or a list value",
                )
        with self.lock:
            element = self.elements.get(element_id)
            copied = dict(element) if isinstance(element, Mapping) else None
        if copied is None or copied.get("sessionId") != session_id:
            self._record(
                "search",
                "POST",
                path,
                404,
                detail={"elementId": element_id, "error": "no such element"},
            )
            self._log(
                "search",
                404,
                {
                    "elementId": element_id,
                    "query": "",
                    "candidateIds": [],
                    "complete": False,
                    "error": "no such element",
                    "generation": self.generation,
                },
            )
            return _error(404, "no such element", "unknown synthetic element")
        if copied.get("stale") or copied.get("kind") != "search" or self.screen == "conversation":
            self._mark_stale(element_id)
            self._record(
                "search",
                "POST",
                path,
                404,
                detail={"elementId": element_id, "error": "stale element reference"},
            )
            self._log(
                "search",
                404,
                {
                    "elementId": element_id,
                    "query": "",
                    "candidateIds": [],
                    "complete": False,
                    "error": "stale element reference",
                    "generation": self.generation,
                },
            )
            return _error(
                404,
                "stale element reference",
                "search field belongs to an earlier view",
            )
        query = text.strip()
        if not query:
            self._record(
                "search",
                "POST",
                path,
                400,
                detail={"elementId": element_id, "error": "invalid argument"},
            )
            self._log(
                "search",
                400,
                {
                    "elementId": element_id,
                    "query": "",
                    "candidateIds": [],
                    "complete": False,
                    "error": "empty search query",
                    "generation": self.generation,
                },
            )
            return _error(
                400,
                "invalid argument",
                "synthetic conversation search requires non-empty text",
            )
        matches = self._ordered_matches(query)
        with self.lock:
            self.query = query
            self.matched_ids = [thread.id for thread in matches]
            self.candidates = [thread.id for thread in matches]
            self.has_more = False
            self.search_complete = True
            self.screen = "results"
            self.generation += 1
            self.search_count += 1
        self._invalidate_elements()
        detail = {
            "query": query,
            "generation": self.generation,
            "returnedCount": len(self.candidates),
            "matchedCount": len(self.matched_ids),
            "complete": True,
            "candidateIds": list(self.candidates),
        }
        self._record(
            "search",
            "POST",
            path,
            200,
            detail={
                "query": query,
                "generation": self.generation,
                "returnedCount": len(self.candidates),
                "matchedCount": len(self.matched_ids),
                "complete": True,
                "candidateIds": self._detail_join(self.candidates),
            },
        )
        self._log("search", 200, detail)
        return 200, {"value": None}

    def _clear(self, session_id: str, element_id: str, path: str) -> tuple[int, dict[str, object]]:
        session = self._session(session_id, "search-clear", "POST", path)
        if session is None:
            return _error(404, "invalid session id", "expired")
        with self.lock:
            element = self.elements.get(element_id)
            copied = dict(element) if isinstance(element, Mapping) else None
        if (
            copied is None
            or copied.get("sessionId") != session_id
            or copied.get("stale")
            or copied.get("kind") != "search"
        ):
            self._record(
                "search-clear",
                "POST",
                path,
                404,
                detail={"elementId": element_id, "error": "no such element"},
            )
            return _error(404, "no such element", "unknown or stale search element")
        with self.lock:
            self.query = ""
            self.matched_ids = []
            self.candidates = []
            self.has_more = False
            self.search_complete = False
            self.screen = "search"
            self.generation += 1
        self._invalidate_elements()
        detail = {
            "query": "",
            "generation": self.generation,
            "returnedCount": 0,
            "matchedCount": 0,
            "complete": False,
            "candidateIds": [],
            "cleared": True,
        }
        self._record(
            "search-clear",
            "POST",
            path,
            200,
            detail={"generation": self.generation, "query": "", "cleared": True},
        )
        self._log("search-clear", 200, detail)
        return 200, {"value": None}

    # ------------------------------------------------------------------
    # W3C actions (standard scroll only)

    def _execute(self, session_id: str, payload: object) -> tuple[int, dict[str, object]]:
        path = f"/session/{session_id}/execute/sync"
        session = self._session(session_id, "execute", "POST", path)
        if session is None:
            return _error(404, "invalid session id", "expired")
        script = ""
        if isinstance(payload, Mapping):
            script = _safe_text(payload.get("script", ""), 240)
        self._record(
            "unsupported-execute",
            "POST",
            path,
            501,
            detail={"script": script, "error": "unsupported operation"},
            kind="unsupported-script",
        )
        self._log(
            "execute",
            501,
            {"script": script, "error": "unsupported operation"},
        )
        return _error(
            501,
            "unsupported operation",
            "synthetic conversation fixture does not implement execute scripts",
        )

    def _actions(
        self, session_id: str, payload: object, path: str
    ) -> tuple[int, dict[str, object]]:
        session = self._session(session_id, "actions", "POST", path)
        if session is None:
            return _error(404, "invalid session id", "expired")
        if not _contains_scroll(payload):
            self._record(
                "unsupported-actions",
                "POST",
                path,
                501,
                detail={"error": "unsupported operation"},
                kind="unsupported-script",
            )
            self._log(
                "scroll",
                501,
                {
                    "generation": self.generation,
                    "error": "unsupported operation",
                },
            )
            return _error(
                501,
                "unsupported operation",
                "synthetic conversation fixture supports only scroll actions",
            )
        if self.screen != "results":
            self._log(
                "scroll",
                400,
                {
                    "generation": self.generation,
                    "error": "invalid element state",
                },
            )
            return _error(
                400,
                "invalid element state",
                "scroll requires the conversation search results",
            )
        previous = self.generation
        with self.lock:
            self.scroll_count += 1
            self.generation += 1
            if len(self.candidates) > 1:
                shift = 2 if len(self.candidates) >= 4 else 1
                self.candidates = [
                    *self.candidates[shift:],
                    *self.candidates[:shift],
                ]
        self._invalidate_elements()
        detail = {
            "generation": self.generation,
            "previousGeneration": previous,
            "candidateIds": list(self.candidates),
            "rowOrder": [f"{index}:{thread_id}" for index, thread_id in enumerate(self.candidates)],
            "reordered": len(self.candidates) > 1,
        }
        self._record(
            "scroll",
            "POST",
            path,
            200,
            detail={
                "generation": self.generation,
                "previousGeneration": previous,
                "candidateIds": self._detail_join(self.candidates),
            },
        )
        self._log("scroll", 200, detail)
        return 200, {"value": None}

    def _delete_actions(self, session_id: str, path: str) -> tuple[int, dict[str, object]]:
        session = self._session(session_id, "release-actions", "DELETE", path)
        if session is None:
            return _error(404, "invalid session id", "expired")
        self._record(
            "release-actions",
            "DELETE",
            path,
            200,
            detail={"sessionId": session_id},
        )
        return 200, {"value": None}

    # ------------------------------------------------------------------
    # Page source

    def _source(
        self, session_id: str, path: str, method: str = "GET"
    ) -> tuple[int, dict[str, object]]:
        session = self._session(session_id, "source", method, path)
        if session is None:
            return _error(404, "invalid session id", "expired")
        with self.lock:
            xml = self._source_xml()
            screen = self.screen
            query = self.query
            generation = self.generation
            candidate_ids = list(self.candidates)
            has_more = self.has_more
            row_order = [f"{index}:{thread_id}" for index, thread_id in enumerate(candidate_ids)]
        self._record(
            "source",
            method,
            path,
            200,
            detail={
                "screen": screen,
                "query": query,
                "generation": generation,
                "candidateIds": ",".join(candidate_ids),
                "rowOrder": ",".join(row_order),
                "hasMore": has_more,
            },
        )
        self._log(
            "source",
            200,
            {
                "screen": screen,
                "query": query,
                "generation": generation,
                "candidateIds": candidate_ids,
                "rowOrder": row_order,
                "hasMore": has_more,
            },
        )
        self._log_source_observations()
        return 200, {"value": xml}

    def _source_xml(self) -> str:
        root = {
            "name": "ConversationFixture",
            "data-app": "conversation-fixture",
            "data-locale": LOCALE,
            "data-timezone": TIMEZONE,
            "data-reference-clock": REFERENCE_CLOCK,
            "data-reference-epoch-ms": str(REFERENCE_EPOCH_MS),
            "data-screen": self.screen,
            "data-generation": str(self.generation),
            "data-query": self.query,
            "data-matched-count": str(len(self.matched_ids)),
            "data-returned-count": str(len(self.candidates)),
            "data-has-more": "true" if self.has_more else "false",
            "data-result-complete": "true" if self.search_complete else "false",
            "data-activity-precision": _ACTIVITY_PRECISION[self.variant],
            "data-activity-semantics": ACTIVITY_SEMANTICS,
            "data-message-activity-semantics": MESSAGE_ACTIVITY_SEMANTICS,
        }
        parts = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f"<hierarchy><XCUIElementTypeApplication {_attributes(root)}>",
        ]
        if self.screen == "conversation" and self.opened is not None:
            thread = self._thread(str(self.opened["candidateId"]))
            if thread is not None:
                parts.append(
                    '<XCUIElementTypeButton name="conversation-back" '
                    'label="Back" accessible="true"/>'
                )
                parts.append(
                    f'<XCUIElementTypeStaticText name="conversation-title" '
                    f"label={quoteattr(thread.title)} "
                    f"{_attributes(self._thread_attributes(thread))}/>"
                )
                parts.append(
                    f'<XCUIElementTypeStaticText name="conversation-participants" '
                    f"label={quoteattr('Participants: ' + ', '.join(thread.participants))}/>"
                )
                parts.append('<XCUIElementTypeOther name="conversation-messages">')
                for index, message in enumerate(thread.messages):
                    attrs = {
                        "name": f"conversation-message-{index}",
                        "label": f"{message.sender} {_display(message.at, self.reference)}",
                        "data-message-id": message.id,
                        "data-sender": message.sender,
                        "data-timestamp-iso": _iso(message.at),
                        "data-timestamp-display": _display(message.at, self.reference),
                        "data-generation": str(self.generation),
                    }
                    parts.append(f"<XCUIElementTypeCell {_attributes(attrs)}/>")
                parts.append("</XCUIElementTypeOther>")
        else:
            search_attrs = {
                "name": "conversation-search",
                "label": "Search conversations",
                "value": self.query,
                "data-search-role": "conversation-search",
                "data-generation": str(self.generation),
            }
            parts.append(f"<XCUIElementTypeSearchField {_attributes(search_attrs)}/>")
            if self.screen == "search":
                parts.append(
                    '<XCUIElementTypeStaticText name="search-hint" '
                    'label="Search conversations by title, participant, or keyword"/>'
                )
            else:
                list_attrs = {
                    "name": "conversation-list",
                    "data-generation": str(self.generation),
                    "data-matched-count": str(len(self.matched_ids)),
                    "data-returned-count": str(len(self.candidates)),
                    "data-has-more": "true" if self.has_more else "false",
                }
                parts.append(f"<XCUIElementTypeOther {_attributes(list_attrs)}>")
                if not self.candidates:
                    parts.append(
                        '<XCUIElementTypeStaticText name="no-results" '
                        'label="No conversations match this search"/>'
                    )
                for thread_id in self.candidates:
                    thread = self._thread(thread_id)
                    if thread is None:
                        continue
                    row_attrs = self._thread_attributes(thread)
                    row_attrs.update(
                        {"name": f"conversation-row:{thread.id}", "label": thread.title}
                    )
                    parts.append(f"<XCUIElementTypeCell {_attributes(row_attrs)}>")
                    parts.append(
                        f'<XCUIElementTypeStaticText name="thread-activity" '
                        f"label={quoteattr('Last activity: ' + self._activity_display(thread))}/>"
                    )
                    parts.append(
                        f'<XCUIElementTypeStaticText name="newest-message" '
                        f"label={quoteattr('Newest message: ' + self._newest_display(thread))}/>"
                    )
                    parts.append("</XCUIElementTypeCell>")
                if self.has_more:
                    parts.append(
                        '<XCUIElementTypeStaticText name="more-results" '
                        'label="More results are not available in this view"/>'
                    )
                parts.append("</XCUIElementTypeOther>")
                parts.append(
                    '<XCUIElementTypeButton name="conversation-refresh" '
                    'label="Refresh conversations" accessible="true"/>'
                )
        parts.append("</XCUIElementTypeApplication></hierarchy>")
        return "".join(parts)

    def _log_source_observations(self) -> None:
        with self.lock:
            screen = self.screen
            candidates = list(self.candidates)
            opened = dict(self.opened) if self.opened is not None else None
        if screen == "results":
            self._log(
                "observe",
                200,
                {
                    "candidateId": None,
                    "kind": "timestamp-context",
                    "value": f"clock={REFERENCE_CLOCK};locale={LOCALE};timezone={TIMEZONE}",
                },
            )
            for thread_id in candidates:
                thread = self._thread(thread_id)
                if thread is None:
                    continue
                self._log(
                    "observe",
                    200,
                    {
                        "candidateId": thread.id,
                        "kind": "thread-activity",
                        "value": self._activity_iso(thread),
                    },
                )
                self._log(
                    "observe",
                    200,
                    {
                        "candidateId": thread.id,
                        "kind": "message-activity",
                        "value": _iso(thread.newest.at),
                    },
                )
        elif screen == "conversation" and opened is not None:
            thread = self._thread(opened.get("candidateId"))
            if thread is not None:
                self._log(
                    "observe",
                    200,
                    {
                        "candidateId": thread.id,
                        "kind": "thread-activity",
                        "value": self._activity_iso(thread),
                    },
                )
            self._log(
                "observe",
                200,
                {
                    "candidateId": opened.get("candidateId"),
                    "kind": "identity",
                    "value": f"{opened.get('title')}|{', '.join(opened.get('participants', []))}",
                },
            )
            self._log_verify_open()

    # ------------------------------------------------------------------
    # Test observation

    def snapshot(self) -> dict[str, Any]:
        base = super().snapshot()
        with self.lock:
            candidates = []
            for index, thread_id in enumerate(self.candidates):
                thread = self._thread(thread_id)
                if thread is None:
                    continue
                candidates.append(
                    {
                        "candidateId": thread.id,
                        "title": thread.title,
                        "participants": list(thread.participants),
                        "rowIndex": index,
                        "threadActivity": self._activity_iso(thread),
                        "threadActivityAt": thread.activity.timestamp(),
                        "newestMessage": _iso(thread.newest.at),
                        "newestMessageAt": thread.newest.at.timestamp(),
                        "threadActivityDisplay": self._activity_display(thread),
                        "newestMessageDisplay": self._newest_display(thread),
                        "activityPrecision": _ACTIVITY_PRECISION[self.variant],
                    }
                )
            opened = (
                {
                    "candidateId": self.opened["candidateId"],
                    "title": self.opened["title"],
                    "participants": list(self.opened["participants"]),
                }
                if self.opened is not None
                else None
            )
            base["conversation"] = {
                "variant": self.variant,
                "locale": LOCALE,
                "timezone": TIMEZONE,
                "referenceClock": REFERENCE_CLOCK,
                "referenceEpochMs": REFERENCE_EPOCH_MS,
                "generation": self.generation,
                "latestConversationId": self._latest_thread().id,
                "activitySemantics": ACTIVITY_SEMANTICS,
                "messageActivitySemantics": MESSAGE_ACTIVITY_SEMANTICS,
                "searchComplete": self.search_complete,
                "uncertainReason": (
                    "coarse-timestamps" if self.variant == "conversation-uncertain" else None
                ),
                "candidates": candidates,
                "opened": opened,
                "actions": [
                    {
                        "action": entry["action"],
                        "at": entry["at"],
                        "status": entry["status"],
                        "detail": _bounded_detail(entry["detail"]),
                    }
                    for entry in self.actions
                ],
                "screen": self.screen,
                "query": self.query,
                "matchedCount": len(self.matched_ids),
                "returnedCount": len(self.candidates),
                "hasMore": self.has_more,
                "searchCount": self.search_count,
                "refreshCount": self.refresh_count,
                "scrollCount": self.scroll_count,
                "openAttempts": self.open_attempts,
                "findCount": self.find_count,
                "staleClickRejections": self.stale_click_rejections,
                "invalidClicks": self.invalid_clicks,
            }
        return base

    # ------------------------------------------------------------------
    # HTTP routing additions

    def _handler(self) -> type[Any]:
        base = super()._handler()
        fixture = self

        class Handler(base):  # type: ignore[misc, valid-type]
            def do_POST(self) -> None:
                parts = self._parts()
                if len(parts) >= 3 and parts[0] == "session":
                    session_id = parts[1]
                    if len(parts) == 5 and parts[2] == "element" and parts[4] in {"value", "clear"}:
                        try:
                            body = self._body()
                        except (ValueError, json.JSONDecodeError):
                            fixture._record("bad-request", "POST", self.path, 400, kind="unknown")
                            self._send(400, {"value": {"error": "invalid argument"}})
                            return
                        if parts[4] == "value":
                            self._send(*fixture._send_keys(session_id, parts[3], body, self.path))
                        else:
                            self._send(*fixture._clear(session_id, parts[3], self.path))
                        return
                    if parts[2:] == ["actions"]:
                        try:
                            body = self._body()
                        except (ValueError, json.JSONDecodeError):
                            fixture._record("bad-request", "POST", self.path, 400, kind="unknown")
                            self._send(400, {"value": {"error": "invalid argument"}})
                            return
                        self._send(*fixture._actions(session_id, body, self.path))
                        return
                super().do_POST()

            def do_DELETE(self) -> None:
                parts = self._parts()
                if len(parts) == 3 and parts[0] == "session" and parts[2] == "actions":
                    self._send(*fixture._delete_actions(parts[1], self.path))
                    return
                super().do_DELETE()

        return Handler


__all__ = [
    "LOCALE",
    "REFERENCE_CLOCK",
    "REFERENCE_EPOCH_MS",
    "TIMEZONE",
    "ConversationAppium",
]
