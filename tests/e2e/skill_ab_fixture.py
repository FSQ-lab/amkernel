"""Loopback-only Appium transport for the paired Skill development experiment.

Six synthetic scenes, not an Appium driver or a sandbox. The Agent receives only
ordinary WebDriver observations; snapshots and business oracles stay test-side.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import unquote
from xml.etree import ElementTree as ET

ELEMENT = "element-6066-11e4-a52e-4f735466cecf"
PACKAGE = "com.amkernel.skillab"


class SceneError(Exception):
    def __init__(self, error: str, message: str) -> None:
        super().__init__(message)
        self.error = error


def node(
    key: str, text: str = "", kind: str = "android.widget.Button", **attrs: Any
) -> dict[str, Any]:
    return {
        "key": key,
        "text": text,
        "class": kind,
        "resource-id": f"{PACKAGE}:id/{key}",
        "content-desc": key,
        "enabled": True,
        "displayed": True,
        "clickable": kind.endswith(("Button", "EditText")),
        "focused": False,
        "checked": False,
        **attrs,
    }


def state_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class SceneServer:
    """One reset scene and finite mutation gate for one fresh Agent run."""

    def __init__(self, scene: Any) -> None:
        self.scene = scene
        self.journal: list[dict[str, Any]] = []
        self.active = False
        self.created = 0
        self.deleted = 0
        self.actions = 0
        self.rejected = 0
        self.handles: dict[str, str] = {}
        self.next_handle = 1
        self.lock = threading.RLock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *args: Any) -> None:
                pass

            def handle_request(self) -> None:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 <= length <= 128_000:
                        raise ValueError("request too large")
                    body = json.loads(self.rfile.read(length)) if length else {}
                    if not isinstance(body, dict):
                        raise ValueError("JSON object required")
                    status, payload = owner.request(self.command, unquote(self.path), body)
                except (ValueError, json.JSONDecodeError) as error:
                    status, payload = (
                        400,
                        {"value": {"error": "invalid argument", "message": str(error)}},
                    )
                encoded = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            do_GET = handle_request
            do_POST = handle_request
            do_DELETE = handle_request

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_port}"

    def __enter__(self) -> SceneServer:
        self.thread.start()
        return self

    def __exit__(self, *_args: Any) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)

    def _nodes(self) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = self.scene.nodes()
        keys = [item["key"] for item in nodes]
        if len(set(keys)) != len(keys):
            raise ValueError("scene exposes duplicate element keys")
        return nodes

    def _xml(self, nodes: list[dict[str, Any]]) -> ET.Element:
        root = ET.Element("hierarchy", {"rotation": "0"})
        elements: dict[str, ET.Element] = {}
        for index, item in enumerate(nodes):
            attrs = {
                key: str(value).lower() if isinstance(value, bool) else str(value)
                for key, value in item.items()
                if key not in {"key", "parent"}
            }
            attrs.setdefault("bounds", f"[0,{index * 48}][400,{index * 48 + 48}]")
            attrs.setdefault("package", PACKAGE)
            element = ET.Element(str(item["class"]), attrs)
            elements[item["key"]] = element
        for item in nodes:
            parent_key = item.get("parent")
            parent = root if parent_key is None else elements.get(parent_key, root)
            parent.append(elements[item["key"]])
        return root

    def _scope(self, nodes: list[dict[str, Any]], parent: str | None) -> list[dict[str, Any]]:
        if parent is None:
            return nodes
        keys = {parent}
        selected = []
        for _ in range(len(nodes)):
            previous = len(keys)
            for item in nodes:
                if item.get("parent") in keys:
                    keys.add(item["key"])
            if len(keys) == previous:
                break
        for item in nodes:
            if item["key"] in keys and item["key"] != parent:
                selected.append(item)
        return selected

    def _find(self, body: dict[str, Any], parent: str | None) -> list[dict[str, str]]:
        nodes = self._scope(self._nodes(), parent)
        strategy, value = body.get("using"), str(body.get("value", ""))
        matches: list[dict[str, Any]]
        if strategy == "id":
            matches = [n for n in nodes if value in {n["key"], n["resource-id"]}]
        elif strategy == "accessibility id":
            matches = [n for n in nodes if n["content-desc"] == value]
        elif strategy == "class name":
            matches = [n for n in nodes if n["class"] == value]
        elif strategy == "xpath":
            root = self._xml(nodes)
            query = "." + value if value.startswith("//") else value
            try:
                selected = root.findall(query)
            except (SyntaxError, KeyError) as error:
                raise SceneError(
                    "invalid selector", "Supported XPath: class and attribute equality"
                ) from error
            ids = {e.attrib.get("resource-id") for e in selected}
            matches = [n for n in nodes if n["resource-id"] in ids]
        elif strategy == "-android uiautomator":
            predicate = (
                r'\.(text|textContains|description|resourceId|className)\("((?:[^"\\]|\\.)*)"\)'
            )
            expression = rf"\s*new\s+UiSelector\(\)(?:{predicate})+\s*;?\s*"
            if re.fullmatch(expression, value) is None:
                raise SceneError("invalid selector", "Unsupported UiSelector expression")
            filters = re.findall(predicate, value)
            matches = nodes
            for operation, raw in filters:
                try:
                    expected = json.loads('"' + raw + '"')
                except json.JSONDecodeError as error:
                    raise SceneError("invalid selector", "Malformed UiSelector string") from error
                attr = {
                    "text": "text",
                    "textContains": "text",
                    "description": "content-desc",
                    "resourceId": "resource-id",
                    "className": "class",
                }[operation]
                matches = [
                    n
                    for n in matches
                    if (
                        expected in str(n[attr])
                        if operation == "textContains"
                        else n[attr] == expected
                    )
                ]
        else:
            raise SceneError(
                "invalid selector",
                "Supported: id, accessibility id, class name, simple XPath, UiSelector",
            )
        result = []
        for item in matches:
            handle = f"element-{self.next_handle}"
            self.next_handle += 1
            self.handles[handle] = item["key"]
            result.append({ELEMENT: handle})
        return result

    def _element(self, handle: str) -> dict[str, Any]:
        key = self.handles.get(handle)
        for item in self._nodes():
            if item["key"] == key:
                return item
        raise SceneError(
            "stale element reference", "Element is no longer on the current page; reacquire"
        )

    def _act(self, action: str, key: str = "", value: str = "") -> None:
        if self.actions >= self.scene.budget:
            self.rejected += 1
            raise SceneError(
                "invalid element state",
                "Synthetic action budget exhausted; no further mutation admitted",
            )
        self.actions += 1
        try:
            self.scene.act(action, key, value)
        finally:
            visible = {item["key"] for item in self._nodes()}
            self.handles = {
                handle: item_key for handle, item_key in self.handles.items() if item_key in visible
            }

    def request(self, method: str, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        with self.lock:
            before = state_digest(self.scene.snapshot())
            event: dict[str, Any] = {
                "seq": len(self.journal) + 1,
                "method": method,
                "path": path,
                "action": "read",
                "key": "",
                "value": "",
                "beforeSha256": before,
            }
            try:
                value = self._dispatch(method, path, body, event)
                status, payload = 200, {"value": value}
            except SceneError as error:
                status = {
                    "no such element": 404,
                    "invalid session id": 404,
                    "stale element reference": 404,
                    "unknown command": 404,
                }.get(error.error, 400)
                payload = {"value": {"error": error.error, "message": str(error), "stacktrace": ""}}
                event["error"] = error.error
            after = self.scene.snapshot()
            event.update(status=status, afterSha256=state_digest(after))
            if event["action"] in {"click", "clear", "type", "scroll", "back"}:
                event["stateAfter"] = copy.deepcopy(after)
            self.journal.append(event)
            return status, payload

    def _dispatch(self, method: str, path: str, body: dict[str, Any], event: dict[str, Any]) -> Any:
        if method == "GET" and path == "/status":
            return {"ready": True, "message": "Synthetic development fixture only"}
        if method == "GET" and path == "/sessions":
            return [{"id": "owned-session", "capabilities": {}}] if self.active else []
        if method == "POST" and path == "/session":
            if self.created:
                raise SceneError(
                    "session not created",
                    "One owned session per task; replacement does not reset action budget",
                )
            self.created += 1
            self.active = True
            return {
                "sessionId": "owned-session",
                "capabilities": {
                    "platformName": "Android",
                    "appium:automationName": "UiAutomator2",
                    "appium:appPackage": PACKAGE,
                },
            }
        prefix = "/session/owned-session"
        if not self.active or not path.startswith(prefix):
            raise SceneError("invalid session id", "No active owned session")
        route = path[len(prefix) :]
        if method == "DELETE" and not route:
            self.deleted += 1
            self.active = False
            event["action"] = "quit"
            return None
        if method == "GET" and route in {
            "/appium/device/current_package",
            "/appium/device/current_activity",
            "/context",
            "/contexts",
            "/window/rect",
            "/window/current/size",
        }:
            return {
                "/appium/device/current_package": PACKAGE,
                "/appium/device/current_activity": ".MainActivity",
                "/context": "NATIVE_APP",
                "/contexts": ["NATIVE_APP"],
                "/window/rect": {"x": 0, "y": 0, "width": 400, "height": 800},
                "/window/current/size": {"width": 400, "height": 800},
            }[route]
        if method == "POST" and route == "/timeouts":
            return None
        if method == "GET" and route == "/source":
            nodes = self._nodes()
            event.update(
                action="source",
                visibleKeys=[n["key"] for n in nodes],
                observedNodes=copy.deepcopy(nodes),
            )
            return ET.tostring(self._xml(nodes), encoding="unicode")
        parts = route.strip("/").split("/")
        parent = None
        if len(parts) >= 3 and parts[0] == "element" and parts[2] in {"element", "elements"}:
            parent = self._element(parts[1])["key"]
            parts = parts[2:]
        if method == "POST" and parts in [["element"], ["elements"]]:
            matches = self._find(body, parent)
            event.update(
                action="find", visibleKeys=[self.handles[next(iter(e.values()))] for e in matches]
            )
            if parts[0] == "elements":
                return matches
            if not matches:
                raise SceneError("no such element", "No element matches on the current page")
            return matches[0]
        if len(parts) >= 3 and parts[0] == "element":
            item = self._element(parts[1])
            event["key"] = item["key"]
            operation = parts[2]
            if method == "GET":
                if operation == "text":
                    event["observedNodes"] = [{"key": item["key"], "text": item["text"]}]
                event["visibleKeys"] = [item["key"]]
                if operation in {"text", "enabled", "displayed", "selected", "name", "rect"}:
                    return {
                        "text": item["text"],
                        "enabled": item["enabled"],
                        "displayed": item["displayed"],
                        "selected": item.get("selected", item["checked"]),
                        "name": item["class"],
                        "rect": {"x": 0, "y": 0, "width": 400, "height": 48},
                    }[operation]
                if operation == "attribute" and len(parts) == 4:
                    name = {
                        "contentDescription": "content-desc",
                        "resourceId": "resource-id",
                        "className": "class",
                    }.get(parts[3], parts[3])
                    result = item.get(name)
                    if name == "text":
                        event["observedNodes"] = [{"key": item["key"], "text": result}]
                    return str(result).lower() if isinstance(result, bool) else result
            if method == "POST" and operation in {"click", "clear", "value"}:
                action = "type" if operation == "value" else operation
                text = body.get("text", "".join(body.get("value", []))) if action == "type" else ""
                event.update(action=action, value=text)
                self._act(action, item["key"], text)
                return None
        if method == "POST" and route == "/back":
            event["action"] = "back"
            self._act("back")
            return None
        if method == "POST" and route == "/execute/sync":
            script, args = body.get("script"), body.get("args", [])
            event.update(
                action="execute",
                script=(
                    script
                    if isinstance(script, str)
                    and re.fullmatch(r"mobile: [A-Za-z][A-Za-z0-9]{0,63}", script)
                    else "<unrecognized-script>"
                ),
            )
            if script in {"mobile: getCurrentPackage", "mobile: getCurrentActivity"}:
                event["action"] = "read"
                return PACKAGE if script == "mobile: getCurrentPackage" else ".MainActivity"
            if script in {"mobile: scrollGesture", "mobile: swipeGesture"}:
                options = args[0] if args and isinstance(args[0], dict) else {}
                event.update(action="scroll", value=str(options.get("direction", "down")))
                self._act("scroll", value=str(options.get("direction", "down")))
                return self.scene.snapshot().get("canScrollMore", False)
        raise SceneError(
            "unknown command", "This synthetic endpoint does not implement that WebDriver command"
        )

    def evidence(self) -> dict[str, Any]:
        with self.lock:
            return {
                "state": copy.deepcopy(self.scene.snapshot()),
                "journal": copy.deepcopy(self.journal),
                "actions": self.actions,
                "budget": self.scene.budget,
                "rejected": self.rejected,
                "sessionsCreated": self.created,
                "sessionsDeleted": self.deleted,
                "activeSession": self.active,
            }

    def contract(self) -> dict[str, Any]:
        return {
            "scope": "synthetic-development-only",
            "endpoint": self.url,
            "platformName": "Android",
            "automationName": "UiAutomator2",
            "appPackage": PACKAGE,
            "actionBudget": self.scene.budget,
            "supported": {
                "reads": [
                    "status",
                    "sessions",
                    "page_source",
                    "current_package / mobile: getCurrentPackage",
                    "current_activity / mobile: getCurrentActivity",
                    "current_context",
                    "contexts",
                    "window_size",
                    "element text/enabled/displayed/selected/attributes",
                ],
                "locators": [
                    "id",
                    "accessibility id",
                    "class name",
                    "XPath class/attribute equality",
                    "Android UiSelector text/textContains/description/resourceId/className",
                ],
                "mutations": [
                    "element.click()",
                    "element.clear()",
                    "element.send_keys(text)",
                    "driver.back()",
                    "mobile: scrollGesture",
                    "mobile: swipeGesture",
                ],
            },
            "semantics": (
                "Each admitted click, clear, text input, back or scroll consumes one action "
                "even on failure. Reads and owned-session quit do not. At exhaustion only "
                "reads and quit remain. Fields expose native focused, enabled and displayed "
                "attributes. XML text preserves whitespace. UI state and persisted saved "
                "objects are distinct. No direct filesystem, private fixture state, shell, "
                "dependencies, other endpoints or real devices may be used. No screenshot "
                "is needed for these fully accessible tasks."
            ),
        }
